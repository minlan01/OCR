"""
Celery 应用配置
================
SaaS 优化要点：
- worker_concurrency=2: 4核8G 服务器限制同时执行2个任务，防止CPU/内存过载
- worker_prefetch_multiplier=1: 每次只取1个任务，避免积压
- task_acks_late=True: 任务执行完才确认，防止 worker 崩溃丢失任务
"""
from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from config.settings import settings
from config.logging import setup_logging


celery_app = Celery(
    "scanstruct",
    broker=settings.redis_broker_url_with_auth,
    backend=settings.redis_result_backend_with_auth,
    include=["worker.tasks", "worker.evidence_tasks"],
)

# visibility_timeout 必须 >= 所有 task 的 time_limit 最大值 + buffer，
# 否则长任务会被 Redis 重新派发给另一个 worker，导致同任务双跑。
# 显式取所有 task 超时最大值（含分片 task 的独立 time_limit），不依赖全局绑定。
_MAX_TASK_TIME_LIMIT = max(
    settings.celery_task_timeout_seconds,  # 全局默认（scan/analyze/export 用）
    360,   # process_ocr_batch
    210,   # finalize_material_ocr
    150,   # dispatch_material_ocr
    60,    # check_case_ocr_done
)

# Celery 配置（SaaS 优化版）
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=60,
    task_max_retries=3,
    # ── SaaS 并发控制 ──
    worker_concurrency=2,              # 4核8G: 同时只执行2个任务
    worker_prefetch_multiplier=1,      # 每次只拉取1个任务，避免积压
    worker_max_tasks_per_child=50,     # 每50个任务重启worker进程，防止内存泄漏
    worker_max_memory_per_child=600000, # 600MB per child（RapidOCR 模型占 ~150MB，留余量给 pixmap 尖峰）
    # ── 超时 ──
    result_expires=3600 * 24 * 7,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    task_soft_time_limit=max(60, settings.celery_task_timeout_seconds - 300),
    task_time_limit=settings.celery_task_timeout_seconds,
    # ── 分片 task 独立超时（不影响 scan/analyze/export 等全局 task） ──
    task_annotations={
        "process_ocr_batch": {
            "soft_time_limit": 300,   # 5 分钟，200 页 OCR 足够
            "time_limit": 360,
        },
        "finalize_material_ocr": {
            "soft_time_limit": 180,   # 3 分钟，含 10000 页 full_text 拼接
            "time_limit": 210,
        },
        "dispatch_material_ocr": {
            "soft_time_limit": 120,   # 2 分钟，含 PDF 下载
            "time_limit": 150,
        },
        "check_case_ocr_done": {
            "soft_time_limit": 30,
            "time_limit": 60,
        },
    },
    broker_transport_options={
        "max_connections": 10,
        "health_check_interval": 30,
        "visibility_timeout": _MAX_TASK_TIME_LIMIT + 600,
    },
    task_routes={
        "process_scan": {"queue": settings.celery_queue_name},
    },
    task_default_queue=settings.celery_queue_name,
    # ── 定时任务 ──
    beat_schedule={
        "cleanup-expired-tasks": {
            "task": "cleanup_expired_tasks",
            "schedule": 86400.0,  # 每24小时执行一次
        },
    },
)


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Worker 就绪时的回调"""
    setup_logging()
    from loguru import logger
    logger.info("ScanStruct Celery worker ready")

    # 预热 OCR 模型（异步加载）
    try:
        from services.ocr.engine import ocr_engine
        ocr_engine.load_model()
        logger.info("OCR model preloaded")
    except Exception as e:
        logger.warning(f"OCR model preload skipped: {e}")
