"""
Celery 应用配置
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

# Celery 配置
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
    worker_prefetch_multiplier=1,
    result_expires=3600 * 24 * 7,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    task_soft_time_limit=max(60, settings.celery_task_timeout_seconds - 300),
    task_time_limit=settings.celery_task_timeout_seconds,
    broker_transport_options={
        "max_connections": 10,
        "health_check_interval": 30,
    },
    task_routes={
        "process_scan": {"queue": settings.celery_queue_name},
    },
    task_default_queue=settings.celery_queue_name,
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
