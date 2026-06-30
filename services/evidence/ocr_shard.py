"""大 PDF 分片 OCR 编排核心（纯函数 + MinIO/DB 读写）

三段式架构（详见 docs/superpowers/specs/2026-06-29-large-pdf-shard-ocr-design.md）：
  dispatch_material_ocr  ──派发──>  process_ocr_batch × N  ──收口──>  finalize_material_ocr
                                                                      │
                                                                      └─> check_case_ocr_done

本模块只提供纯函数（可单测，不依赖 Celery runtime）。worker 层负责 DB session
管理与 task 装饰器，调本模块函数完成实际工作。

进度记录两层：
  - DB EvidenceStep.step_metadata（材料级总览，前端轮询用）
  - MinIO checkpoints/batch_NNNN.json（批次级幂等性，断点续传用）
"""
from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import settings


# ─── 常量 ───────────────────────────────────────────────────────────────────

STEP_NAME = "ocr_shard"

# Redis 信号量 key 前缀（复用 task_concurrency.py 的 Lua 模式）
_BATCH_SEMAPHORE_PREFIX = "scanstruct:ocr_batch_concurrent:"
_BATCH_SEMAPHORE_TTL = 600  # 10 分钟，覆盖单批最长执行 + retry 余量；finalize 终态时主动清理

# 批次状态
STATUS_SHARDING = "sharding"
STATUS_FINALIZING = "finalizing"
STATUS_COMPLETED = "completed"
STATUS_PARTIAL_FAILED = "partial_failed"

# 并发下载 page json 的线程数（用于 full_text 拼接）
_FULL_TEXT_CONCURRENCY = 10


# ─── 批次切分 ───────────────────────────────────────────────────────────────

def plan_batches(total_pages: int, batch_page_size: int | None = None) -> list[tuple[int, int, int]]:
    """切批：返回 [(batch_index, start_page, end_page), ...]，1-based 闭区间。

    10000 页 / 200 页每批 = 50 批。
    """
    if total_pages <= 0:
        return []
    size = batch_page_size or settings.ocr_batch_page_size
    size = max(1, size)
    batches: list[tuple[int, int, int]] = []
    idx = 0
    start = 1
    while start <= total_pages:
        end = min(start + size - 1, total_pages)
        batches.append((idx, start, end))
        idx += 1
        start = end + 1
    return batches


def should_shard(file_type: str | None, total_pages: int) -> bool:
    """判断是否应走分片路径。PDF 且页数超过阈值才分片。"""
    if file_type != "pdf":
        return False
    return total_pages > settings.ocr_shard_threshold_pages


# ─── MinIO 路径 ─────────────────────────────────────────────────────────────

def _ocr_prefix(case_id: str, material_id: str) -> str:
    from services.evidence.ocr_storage import make_ocr_prefix
    return make_ocr_prefix(case_id, material_id)


def _checkpoint_key(case_id: str, material_id: str, batch_index: int) -> str:
    return f"{_ocr_prefix(case_id, material_id)}/checkpoints/batch_{batch_index:04d}.json"


# ─── MinIO checkpoint 读写 ──────────────────────────────────────────────────

def _minio():
    from services.storage.minio_client import minio_client
    return minio_client


def load_checkpoint(case_id: str, material_id: str, batch_index: int) -> dict | None:
    """读 MinIO checkpoint，不存在返回 None。"""
    key = _checkpoint_key(case_id, material_id, batch_index)
    try:
        raw = _minio().download_bytes(settings.minio_bucket_result, key)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def write_checkpoint(
    case_id: str,
    material_id: str,
    batch_index: int,
    *,
    status: str,
    start: int,
    end: int,
    pages_written: list[int] | None = None,
    error: str | None = None,
    retries: int | None = None,
) -> None:
    """写 MinIO checkpoint（覆盖写，幂等）。"""
    payload: dict[str, Any] = {
        "batch_index": batch_index,
        "start": start,
        "end": end,
        "status": status,
        "pages_written": pages_written or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error is not None:
        payload["error"] = error
    if retries is not None:
        payload["retries"] = retries
    key = _checkpoint_key(case_id, material_id, batch_index)
    _minio().upload_bytes(
        settings.minio_bucket_result,
        key,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )


def append_checkpoint_page(
    case_id: str,
    material_id: str,
    batch_index: int,
    page_num: int,
) -> None:
    """追加单页到 checkpoint.pages_written（read-modify-write，批次内串行调用）。"""
    cp = load_checkpoint(case_id, material_id, batch_index) or {
        "batch_index": batch_index,
        "status": "processing",
        "pages_written": [],
    }
    pages = list(cp.get("pages_written") or [])
    if page_num not in pages:
        pages.append(page_num)
    cp["pages_written"] = pages
    cp["updated_at"] = datetime.now(timezone.utc).isoformat()
    key = _checkpoint_key(case_id, material_id, batch_index)
    _minio().upload_bytes(
        settings.minio_bucket_result,
        key,
        json.dumps(cp, ensure_ascii=False).encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )


# ─── DB 进度读写 ────────────────────────────────────────────────────────────

def _sync_engine():
    """同步 DB engine（worker 内复用，NullPool 避免连接泄漏）。"""
    from sqlalchemy import create_engine
    return create_engine(
        settings.database_url_sync,
        pool_size=1,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def load_progress(material_id: str) -> dict | None:
    """从 EvidenceStep.step_metadata 读 ocr_shard step 的进度。

    找不到 step 返回 None。返回的 dict 含 total_pages/batch_size/total_batches/
    completed_batches/failed_batches/pending_batches/status/cancelled/pdf_local_path。
    """
    from sqlalchemy import text
    eng = _sync_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT step_metadata FROM evidence_steps "
                    "WHERE case_id = (SELECT evidence_case_id FROM evidence_materials WHERE id = :mid) "
                    "AND step_name = :step ORDER BY started_at DESC LIMIT 1"
                ),
                {"mid": material_id, "step": STEP_NAME},
            ).fetchone()
    finally:
        eng.dispose()
    if not row:
        return None
    meta = row[0] or {}
    total = int(meta.get("total_batches") or 0)
    completed = list(meta.get("completed_batches") or [])
    failed = list(meta.get("failed_batches") or [])
    failed_idx = {b["index"] for b in failed if isinstance(b, dict)}
    pending = [i for i in range(total) if i not in completed and i not in failed_idx]
    return {
        "total_pages": int(meta.get("total_pages") or 0),
        "batch_size": int(meta.get("batch_size") or settings.ocr_batch_page_size),
        "total_batches": total,
        "completed_batches": completed,
        "failed_batches": failed,
        "pending_batches": pending,
        "status": meta.get("status", STATUS_SHARDING),
        "cancelled": bool(meta.get("cancelled", False)),
        "pdf_local_path": meta.get("pdf_local_path"),
        "selected_pages": meta.get("selected_pages"),
    }


# case_id 缓存：material_id -> case_id（进程内，避免高频查 DB）
_case_id_cache: dict[str, str] = {}
_case_id_cache_lock = __import__("threading").Lock()


def _get_case_id_for_material(material_id: str) -> str | None:
    # 优先读缓存
    with _case_id_cache_lock:
        cached = _case_id_cache.get(material_id)
    if cached:
        return cached
    from sqlalchemy import text
    eng = _sync_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT evidence_case_id FROM evidence_materials WHERE id = :mid"),
                {"mid": material_id},
            ).fetchone()
    finally:
        eng.dispose()
    result = str(row[0]) if row and row[0] else None
    if result:
        with _case_id_cache_lock:
            _case_id_cache[material_id] = result
    return result


def write_progress(material_id: str, **fields: Any) -> None:
    """upsert ocr_shard step 的 step_metadata 字段（整体覆盖写）。

    用于派发器初始化进度。批次完成用 mark_batch_completed（原子追加）。
    """
    from sqlalchemy import text
    case_id = _get_case_id_for_material(material_id)
    if not case_id:
        return
    eng = _sync_engine()
    try:
        with eng.begin() as conn:
            # 若已有 step 则更新，否则插入
            existing = conn.execute(
                text(
                    "SELECT id FROM evidence_steps "
                    "WHERE case_id = :cid AND step_name = :step "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"cid": case_id, "step": STEP_NAME},
            ).fetchone()
            if existing:
                conn.execute(
                    text(
                        "UPDATE evidence_steps SET step_metadata = :meta, status = :status "
                        "WHERE id = :sid"
                    ),
                    {
                        "meta": json.dumps(fields, ensure_ascii=False),
                        "status": fields.get("status", STATUS_SHARDING),
                        "sid": existing[0],
                    },
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO evidence_steps (case_id, step_name, status, progress, "
                        "step_metadata, started_at) "
                        "VALUES (:cid, :step, :status, 0, :meta, :now)"
                    ),
                    {
                        "cid": case_id,
                        "step": STEP_NAME,
                        "status": fields.get("status", STATUS_SHARDING),
                        "meta": json.dumps(fields, ensure_ascii=False),
                        "now": datetime.now(timezone.utc),
                    },
                )
    finally:
        eng.dispose()


def mark_batch_completed(material_id: str, batch_index: int) -> None:
    """原子追加 batch_index 到 completed_batches（spec §3.8 的 jsonb_set + ||）。

    用 WHERE NOT 防重复 append，PostgreSQL 行级锁串行化并发 UPDATE，不丢记录。
    """
    from sqlalchemy import text
    case_id = _get_case_id_for_material(material_id)
    if not case_id:
        return
    eng = _sync_engine()
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE evidence_steps
                    SET step_metadata = jsonb_set(
                        step_metadata,
                        '{completed_batches}',
                        COALESCE(
                            (step_metadata->'completed_batches') || to_jsonb(:idx),
                            to_jsonb(:idx)
                        )
                    )
                    WHERE case_id = :cid AND step_name = :step
                      AND NOT (
                        :idx = ANY(
                          SELECT jsonb_array_elements_text(
                            step_metadata->'completed_batches'
                          )::int
                        )
                      )
                    """
                ),
                {"cid": case_id, "step": STEP_NAME, "idx": batch_index},
            )
    finally:
        eng.dispose()


def mark_batch_failed(
    material_id: str,
    batch_index: int,
    error: str,
    retries: int,
) -> None:
    """原子更新 failed_batches 中该批次的失败记录。

    用 jsonb 原子操作（与 mark_batch_completed 同模式），避免 read-modify-write
    并发丢更新：先过滤掉同 index 旧记录，再追加新记录。
    """
    from sqlalchemy import text
    case_id = _get_case_id_for_material(material_id)
    if not case_id:
        return
    eng = _sync_engine()
    try:
        with eng.begin() as conn:
            # 原子：jsonb 删除同 index 旧记录 + 追加新记录
            new_record = json.dumps(
                {"index": batch_index, "error": error, "retries": retries},
                ensure_ascii=False,
            )
            conn.execute(
                text(
                    """
                    UPDATE evidence_steps
                    SET step_metadata = jsonb_set(
                        step_metadata,
                        '{failed_batches}',
                        COALESCE(
                            (
                                SELECT jsonb_agg(elem)
                                FROM jsonb_array_elements(
                                    step_metadata->'failed_batches'
                                ) AS elem
                                WHERE (elem->>'index')::int != :idx
                            ),
                            '[]'::jsonb
                        ) || :new_record::jsonb
                    )
                    WHERE case_id = :cid AND step_name = :step
                    """
                ),
                {
                    "cid": case_id,
                    "step": STEP_NAME,
                    "idx": batch_index,
                    "new_record": new_record,
                },
            )
    finally:
        eng.dispose()


def set_progress_status(material_id: str, status: str, **extra: Any) -> None:
    """更新 progress.status 字段，可附带其他字段更新。"""
    from sqlalchemy import text
    case_id = _get_case_id_for_material(material_id)
    if not case_id:
        return
    eng = _sync_engine()
    try:
        with eng.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, step_metadata FROM evidence_steps "
                    "WHERE case_id = :cid AND step_name = :step "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"cid": case_id, "step": STEP_NAME},
            ).fetchone()
            if not row:
                return
            meta = row[1] or {}
            meta["status"] = status
            meta.update(extra)
            conn.execute(
                text(
                    "UPDATE evidence_steps SET step_metadata = :meta, status = :status "
                    "WHERE id = :sid"
                ),
                {
                    "meta": json.dumps(meta, ensure_ascii=False),
                    "status": status,
                    "sid": row[0],
                },
            )
    finally:
        eng.dispose()


def is_material_cancelled(material_id: str) -> bool:
    """检查 DB step_metadata.cancelled 标记。"""
    prog = load_progress(material_id)
    return bool(prog and prog.get("cancelled"))


def set_cancelled(material_id: str) -> None:
    """协作式取消：打 cancelled=True 标记，批次/派发器/收口器开头检查。"""
    set_progress_status(material_id, STATUS_PARTIAL_FAILED, cancelled=True)


# ─── Redis 信号量（单材料批次并发限制） ─────────────────────────────────────

_LUA_ACQUIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
if current <= tonumber(ARGV[1]) then
    return current
else
    redis.call('DECR', KEYS[1])
    return 0
end
"""


def _redis():
    import redis as _redis
    return _redis.from_url(
        settings.redis_url_with_auth,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def acquire_batch_slot(material_id: str) -> bool:
    """尝试获取单材料批次并发许可。

    Returns:
        True  — 获得许可，可执行批次
        False — 已达 ocr_batch_max_concurrent_per_material 上限，应排队
    """
    limit = settings.ocr_batch_max_concurrent_per_material
    if limit <= 0:
        return True  # 0 = 不限
    try:
        r = _redis()
        key = f"{_BATCH_SEMAPHORE_PREFIX}{material_id}"
        result = r.eval(_LUA_ACQUIRE, 1, key, limit, _BATCH_SEMAPHORE_TTL)
        return int(result) > 0
    except Exception as e:
        logger.warning(f"[批次信号量] Redis 异常，降级放行: {e}")
        return True


def release_batch_slot(material_id: str) -> None:
    """释放批次许可。必须在 finally 块调用。

    与 clear_batch_semaphore 的关系：批次 task 正常完成/失败时 DECR 归还许可；
    finalize 到达终态时 DELETE 整个 key（兜底清理崩溃残留）。两者不冲突——
    正常路径 DECR 到 0，finalize DELETE；异常路径 DECR 未执行，finalize DELETE 兜底。
    """
    limit = settings.ocr_batch_max_concurrent_per_material
    if limit <= 0:
        return
    try:
        r = _redis()
        key = f"{_BATCH_SEMAPHORE_PREFIX}{material_id}"
        current = r.decr(key)
        if current < 0:
            r.set(key, 0)
    except Exception as e:
        logger.warning(f"[批次信号量] Redis 释放异常（忽略）: {e}")


def clear_batch_semaphore(material_id: str) -> None:
    """清理材料的批次信号量（finalize 终态时调用）。

    Bug 7 修复：worker 崩溃时 finally:release_batch_slot 未执行，信号量卡满。
    finalize 成功/失败时主动删除 key，避免残留计数阻塞后续重试。
    """
    limit = settings.ocr_batch_max_concurrent_per_material
    if limit <= 0:
        return
    try:
        r = _redis()
        key = f"{_BATCH_SEMAPHORE_PREFIX}{material_id}"
        r.delete(key)
        logger.debug(f"[批次信号量] 清理 {material_id} 信号量")
    except Exception as e:
        logger.warning(f"[批次信号量] 清理异常（忽略）: {e}")


# ─── full_text 拼接（收口器用） ─────────────────────────────────────────────

def assemble_full_text(
    case_id: str,
    material_id: str,
    total_pages: int,
) -> tuple[str, int]:
    """流式拼接 full_text.txt：并发下载 page json → 提取 text → 按页号顺序写临时文件。

    Returns:
        (tmp_path, full_text_len)。调用方负责上传后清理 tmp_path。
    """
    from services.evidence.ocr_storage import EvidenceOCRStore

    work_base = os.getenv("OCR_WORK_DIR") or None
    if work_base:
        Path(work_base).mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=work_base, suffix=".full_text.txt")
    os.close(fd)

    page_texts: dict[int, str] = {}

    def _fetch(page_num: int) -> tuple[int, str]:
        return page_num, EvidenceOCRStore.load_page_text(case_id, material_id, page_num)

    with ThreadPoolExecutor(max_workers=_FULL_TEXT_CONCURRENCY) as pool:
        futures = {
            pool.submit(_fetch, p): p
            for p in range(1, total_pages + 1)
        }
        for fut in as_completed(futures):
            try:
                page_num, text = fut.result()
                page_texts[page_num] = text
            except Exception as e:
                logger.warning(f"full_text 拼接下载页失败: {e}")

    total_len = 0
    with open(tmp_path, "w", encoding="utf-8") as f:
        for p in range(1, total_pages + 1):
            text = page_texts.get(p, "")
            if text:
                f.write(text)
                f.write("\n")
                total_len += len(text) + 1

    return tmp_path, total_len


# ─── 临时文件清理 ───────────────────────────────────────────────────────────

def cleanup_temp_files(*paths: str) -> None:
    """清理临时文件/目录（静默忽略错误）。"""
    import shutil
    for p in paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.unlink(p)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {p}: {e}")


# ─── 派发器/收口器/case 检查 纯函数 ─────────────────────────────────────────

def dispatch_plan(
    material_id: str,
    case_id: str,
    pdf_local_path: str,
    total_pages: int,
    selected_pages: list[int] | None = None,
) -> dict:
    """派发器纯函数：初始化进度 + 返回批次计划。

    幂等：若已有 status=sharding 的 step 直接 return 不重复派发。
    返回 {"batches": [(idx, start, end), ...], "skipped": bool, "reason": str}
    实际的 delay() 调用由 worker 层根据返回值执行。
    """
    # 幂等检查
    existing = load_progress(material_id)
    if existing and existing.get("status") == STATUS_SHARDING:
        # 续传：从 DB 读 total_pages（避免传入值与记录不一致），只派发 pending 批次
        batches_meta = existing
        total_batches = batches_meta["total_batches"]
        db_total_pages = batches_meta["total_pages"]
        completed = set(batches_meta["completed_batches"])
        # 重建批次计划，过滤已完成
        all_batches = plan_batches(db_total_pages, batches_meta["batch_size"])
        pending = [(i, s, e) for (i, s, e) in all_batches if i not in completed]
        return {
            "batches": pending,
            "skipped": False,
            "reason": "resume",
            "total_batches": total_batches,
        }

    batches = plan_batches(total_pages)
    progress_meta: dict[str, Any] = {
        "step_name": STEP_NAME,
        "total_pages": total_pages,
        "batch_size": settings.ocr_batch_page_size,
        "total_batches": len(batches),
        "completed_batches": [],
        "failed_batches": [],
        "pending_batches": [i for i, _, _ in batches],
        "status": STATUS_SHARDING,
        "cancelled": False,
        "pdf_local_path": pdf_local_path,
        "selected_pages": selected_pages or [],
    }
    write_progress(material_id, **progress_meta)
    return {
        "batches": batches,
        "skipped": False,
        "reason": "fresh",
        "total_batches": len(batches),
    }


def is_finalize_ready(material_id: str) -> dict:
    """收口器判断：返回是否全部完成 / 缺哪些批次 / 哪些不可救。

    Returns:
        {
            "ready": bool,                # 全部完成可拼接
            "missing": [idx, ...],        # 缺失批次（含 pending）
            "retryable": [idx, ...],      # 失败但 retries < max（可重派）
            "unrecoverable": [{...}],     # 失败且 retries >= max（不可救）
        }
    """
    prog = load_progress(material_id)
    if not prog:
        return {"ready": False, "missing": [], "retryable": [], "unrecoverable": []}

    total = prog["total_batches"]
    completed = set(prog["completed_batches"])
    max_retries = settings.ocr_batch_max_retries

    # 已 completed 的批次若曾在 failed_batches 留旧记录，忽略之（先失败后成功的场景）
    active_failed = [
        b for b in prog["failed_batches"]
        if isinstance(b, dict) and b.get("index") not in completed
    ]
    unrecoverable = [
        b for b in active_failed
        if int(b.get("retries", 0)) >= max_retries
    ]
    retryable = [
        b["index"] for b in active_failed
        if int(b.get("retries", 0)) < max_retries
    ]
    failed_idx = {b["index"] for b in active_failed}
    missing = [
        i for i in range(total)
        if i not in completed and i not in failed_idx
    ]

    ready = not missing and not retryable and not unrecoverable
    return {
        "ready": ready,
        "missing": missing,
        "retryable": retryable,
        "unrecoverable": unrecoverable,
    }


def finalize_assemble_and_manifest(
    material_id: str,
    case_id: str,
) -> dict:
    """收口器：拼接 full_text + 写 manifest + 标记 completed。

    前置：is_finalize_ready().ready == True。
    返回 summary（写入 material.ocr_result 用）。
    """
    from services.evidence.ocr_storage import EvidenceOCRStore, OCR_STORAGE_MINIO

    prog = load_progress(material_id)
    if not prog:
        raise RuntimeError(f"No ocr_shard progress for material {material_id}")

    total_pages = prog["total_pages"]
    tmp_path, full_text_len = assemble_full_text(case_id, material_id, total_pages)
    try:
        bucket = settings.minio_bucket_result
        prefix = _ocr_prefix(case_id, material_id)
        full_text_key = f"{prefix}/full_text.txt"

        # 预览：取前 ocr_text_db_preview_chars 字符
        preview = ""
        with open(tmp_path, "r", encoding="utf-8") as f:
            preview = f.read(settings.ocr_text_db_preview_chars)
        if full_text_len > settings.ocr_text_db_preview_chars:
            preview += f"\n…（共 {full_text_len:,} 字符，完整文本已存 MinIO）"

        summary: dict[str, Any] = {
            "storage": OCR_STORAGE_MINIO,
            "minio_bucket": bucket,
            "minio_prefix": prefix,
            "full_text_key": full_text_key,
            "source_type": "pdf_ocr_shard",
            "page_count": total_pages,
            "block_count": 0,  # 分片路径不汇总 block_count，按需读 pages/
            "full_text_length": full_text_len,
            "text_preview": preview[: settings.ocr_text_db_preview_chars],
            "shard": {
                "total_batches": prog["total_batches"],
                "batch_size": prog["batch_size"],
            },
        }

        EvidenceOCRStore._write_full_text_and_manifest(
            bucket=bucket,
            prefix=prefix,
            full_text_path=tmp_path,
            full_text_len=full_text_len,
            preview=preview,
            summary=summary,
            full_text_key=full_text_key,
        )

        set_progress_status(material_id, STATUS_COMPLETED)
        logger.info(
            f"Shard finalize done: {case_id}/{material_id} "
            f"({total_pages} pages, {full_text_len:,} chars)"
        )
        return summary
    finally:
        cleanup_temp_files(tmp_path)


def mark_material_failed(material_id: str, error: str, failed_batches: list) -> dict:
    """收口器判定不可救时，返回 summary（worker 层据此置 material.ocr_status=failed）。"""
    set_progress_status(material_id, STATUS_PARTIAL_FAILED)
    return {
        "storage": "inline",
        "source_type": "pdf_ocr_shard_failed",
        "error": error,
        "failed_batches": failed_batches,
        "page_count": 0,
        "full_text_length": 0,
    }


# ─── case 级检查 ────────────────────────────────────────────────────────────

def case_all_materials_terminal(case_id: str) -> bool:
    """检查 case 下所有 material 是否都到终态（completed/failed/not_applicable/skipped）。

    check_case_ocr_done task 用此判断是否推进到分类阶段。
    """
    from sqlalchemy import text
    eng = _sync_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM evidence_materials "
                    "WHERE evidence_case_id = :cid "
                    "AND ocr_status NOT IN ('completed', 'failed', 'not_applicable', 'skipped')"
                ),
                {"cid": case_id},
            ).fetchone()
    finally:
        eng.dispose()
    return int(row[0] if row else 0) == 0


def case_already_advanced(case_id: str) -> bool:
    """case 已进入 catalog_ready 及之后阶段，则不重复推进分类。"""
    from sqlalchemy import text
    eng = _sync_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT status FROM evidence_cases WHERE id = :cid"),
                {"cid": case_id},
            ).fetchone()
    finally:
        eng.dispose()
    if not row:
        return False
    status = row[0]
    return status in ("catalog_ready", "analyzing", "analysis_done", "exporting", "completed")
