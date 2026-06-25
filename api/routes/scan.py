"""
扫描任务 API 路由
POST   /api/v1/scans/upload            - 上传 PDF
GET    /api/v1/scans                   - 任务列表（分页+筛选+排序）
GET    /api/v1/scans/{task_id}         - 任务详情（含步骤+文件+预签名URL）
GET    /api/v1/scans/{task_id}/result  - 下载/查看结构化结果
GET    /api/v1/scans/{task_id}/download - 下载 Word 文档
POST   /api/v1/scans/{task_id}/retry   - 重试失败任务（自动派发Celery）
DELETE /api/v1/scans/{task_id}         - 删除任务（含MinIO清理+Celery撤销）
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.common import MessageResponse, PaginatedResponse
from api.schemas.scan import (
    BatchProcessRequest,
    BatchProcessResult,
    BatchUploadResult,
    ScanTaskDetail,
    ScanTaskSummary,
    ScanUploadResponse,
    TaskStepOut,
    ScanFileOut,
)
from api.rate_limit import limiter
from api.dependencies import get_tenant_filter
from services.exporter.docx_exporter import export_docx_bytes
from config.settings import settings
from db.models import ScanTask, TaskStep, ScanFile
from db.session import get_db
from services.storage.minio_client import minio_client

# Celery 相关：模块级导入以支持 patch/mock
try:
    from worker.tasks import process_scan  # noqa: F401
except ImportError:
    process_scan = None

try:
    from worker.celery_app import celery_app  # noqa: F401
except ImportError:
    celery_app = None

router = APIRouter(prefix="/scans")

# 允许的文件类型
ALLOWED_CONTENT_TYPES = {"application/pdf"}
ALLOWED_EXTENSIONS = set(settings.allowed_extensions)  # 冻结为集合加速查找

# 允许排序的字段白名单
ALLOWED_SORT_FIELDS = {
    "created_at", "updated_at", "completed_at", "started_at",
    "status", "filename",
    "page_count", "confidence_avg", "file_size",
}


def _compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


async def _mark_task_failed(
    db: AsyncSession,
    task: ScanTask,
    error_code: str,
    error_message: str,
) -> None:
    """标记任务为失败状态"""
    task.status = "failed"
    task.error_code = error_code
    task.error_message = error_message
    await db.flush()


def _dispatch_celery(task_id: uuid.UUID) -> str:
    """派发 Celery 任务，返回 celery_task_id

    Raises:
        RuntimeError: Celery 不可用或派发失败
    """
    if process_scan is None:
        raise RuntimeError("Celery task dispatcher not available")
    try:
        result = process_scan.delay(str(task_id))
        logger.info(f"Task {task_id} dispatched to Celery: celery_task_id={result.id}")
        return result.id
    except Exception as e:
        logger.error(f"Failed to dispatch Celery task for {task_id}: {type(e).__name__}")
        raise RuntimeError(f"Failed to dispatch: {type(e).__name__}") from e


async def _fetch_result_json(task: ScanTask, task_id: uuid.UUID) -> dict:
    """获取已完成任务的结构化结果 JSON

    Args:
        task: 扫描任务对象
        task_id: 任务 UUID（用于日志）

    Returns:
        解析后的 JSON dict

    Raises:
        HTTPException: 任务未完成 / 结果不存在 / 下载失败 / 数据损坏
    """
    if task.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task.status}",
        )
    if not task.result_path:
        raise HTTPException(status_code=404, detail="Result file not found for this task")
    try:
        data = await asyncio.to_thread(
            minio_client.download_bytes,
            bucket=settings.minio_bucket_result,
            object_key=task.result_path,
        )
    except Exception as e:
        logger.error(f"Failed to fetch result for task {task_id}: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to retrieve processing result")
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Result data corrupted for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Result data is corrupted, please retry")


async def _get_task_or_404(
    task_id: uuid.UUID, db: AsyncSession, tenant_id: uuid.UUID | None = None,
    *, for_update: bool = False,
) -> ScanTask:
    """获取任务或抛出 404（可选按 tenant_id 过滤；可选行锁）"""
    stmt = select(ScanTask).where(ScanTask.id == task_id)
    if tenant_id is not None:
        stmt = stmt.where(ScanTask.tenant_id == tenant_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


def _build_step_out(step: TaskStep) -> TaskStepOut:
    """构建步骤输出模型"""
    return TaskStepOut(
        id=step.id,
        step_name=step.step_name,
        status=step.status,
        duration_ms=step.duration_ms,
        retry_count=step.retry_count,
        error_message=step.error_message,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _build_file_out(file: ScanFile) -> ScanFileOut:
    """构建文件输出模型"""
    return ScanFileOut(
        id=file.id,
        file_type=file.file_type,
        page_no=file.page_no,
        bucket=file.bucket,
        object_key=file.object_key,
        size_bytes=file.size_bytes,
    )


def _build_detail(task: ScanTask) -> ScanTaskDetail:
    """从 ORM 对象构建任务详情（含步骤和文件）"""
    return ScanTaskDetail(
        task_id=task.id,
        filename=task.filename,
        scanner_id=task.scanner_id,
        source_type=task.source_type,
        status=task.status,
        priority=task.priority,
        file_size=task.file_size,
        file_md5=task.file_md5,
        page_count=task.page_count,
        confidence_avg=float(task.confidence_avg) if task.confidence_avg is not None else None,
        structure_score=float(task.structure_score) if task.structure_score is not None else None,
        table_count=task.table_count or 0,
        heading_count=task.heading_count or 0,
        paragraph_count=task.paragraph_count or 0,
        callback_url=task.callback_url,
        callback_status=task.callback_status,
        error_code=task.error_code,
        error_message=task.error_message,
        metadata=task.metadata_,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        steps=[_build_step_out(s) for s in (task.steps or [])],
        files=[_build_file_out(f) for f in (task.files or [])],
    )


# ═══════════════════════════════════════════════════════════
# SSRF 防护 — 共享校验函数（upload + batch-upload + process 复用）
# ═══════════════════════════════════════════════════════════
def _validate_callback_url(callback_url: str | None) -> None:
    """校验 callback_url 防止 SSRF 攻击。

    覆盖：IPv4 私网、IPv6 本地/ULA/link-local、DNS 本地域名、非 http(s) 协议。
    """
    if not callback_url:
        return
    from urllib.parse import urlparse

    parsed = urlparse(callback_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="callback_url must be http(s)")

    host = (parsed.hostname or "").lower().strip("[]")
    if not host:
        raise HTTPException(status_code=400, detail="callback_url missing hostname")

    # 本地域名直接拦截
    LOCAL_HOSTS = ("localhost", "0.0.0.0", "::", "::1")
    if host in LOCAL_HOSTS:
        raise HTTPException(status_code=400, detail="callback_url cannot point to loopback")

    # 尝试解析为 IP（含 IPv6 映射地址 ::ffff:127.0.0.1）
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status_code=400, detail="callback_url cannot point to private/reserved addresses")
    except ValueError:
        # 不是 IP 字面量 → 域名，拦截本地伪域名
        if host.endswith(".local") or host.endswith(".internal") or host.endswith(".localhost"):
            raise HTTPException(status_code=400, detail="callback_url cannot point to local domain")
        # 注意：DNS rebinding 无法在静态校验完全防御，
        # 需在发起 callback 请求时二次校验解析 IP（见 services/callback.py）


# ═══════════════════════════════════════════════════════════
# Celery 任务撤销 — 通过 inspect().active() 匹配 args 查找真实 task_id
# （process_scan.delay(uuid) 传的是参数，Celery 内部 task_id 是另一个值）
# ═══════════════════════════════════════════════════════════
def _revoke_scan_celery_task(celery_app, task_id) -> None:
    """撤销与指定 ScanTask UUID 关联的 Celery 任务。

    先用 inspect().active() 查找 args 含该 UUID 的 Celery 任务，
    再 revoke 真实的 Celery task_id（而非 ScanTask UUID）。
    """
    tid_str = str(task_id)
    try:
        # 1. 精确匹配：在活跃任务 args 中查找
        active = celery_app.control.inspect().get("active", {})
        for _worker, tasks in active.items():
            for t in tasks:
                args = t.get("args") or []
                if any(str(a) == tid_str for a in args):
                    celery_app.control.revoke(t["id"], terminate=True, signal="SIGTERM")
                    logger.info(f"Revoked Celery task {t['id']} for ScanTask {tid_str}")
                    return
        # 2. 没找到活跃任务 → 直接 revoke UUID（兼容 Celery 用 UUID 作 task_id 的旧路径）
        celery_app.control.revoke(tid_str, terminate=True, signal="SIGTERM")
        logger.debug(f"No active Celery task matched ScanTask {tid_str}, sent revoke anyway")
    except Exception as e:
        logger.debug(f"Celery revoke skipped for {tid_str}: {e}")


# ═══════════════════════════════════════════════════════════
# 内部上传逻辑（单文件，可被 upload / batch-upload 复用）
# ═══════════════════════════════════════════════════════════
async def _upload_single_file(
    db: AsyncSession,
    content: bytes,
    filename: str,
    scanner_id: str = "manual",
    callback_url: str | None = None,
    meta_dict: dict | None = None,
    tenant_id: uuid.UUID | None = None,
) -> ScanUploadResponse | dict:
    """上传单个文件，返回 ScanUploadResponse 或 {"skipped": ...} / {"failed": ...}"""

    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        return {"skipped": {"filename": filename, "reason": f"Invalid extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}}

    if len(content) == 0:
        return {"skipped": {"filename": filename, "reason": "Empty file"}}

    if len(content) > settings.max_upload_size:
        return {"skipped": {"filename": filename, "reason": f"File too large ({len(content) // (1024*1024)} MB). Max: {settings.max_upload_size // (1024*1024)} MB"}}

    # 文件魔数校验（防止扩展名伪装，与 evidence 模块一致）
    if filename.lower().endswith(".pdf") and not content[:5].startswith(b"%PDF"):
        return {"skipped": {"filename": filename, "reason": "File content does not match PDF format (magic number check failed)"}}

    file_md5 = _compute_md5(content)

    # MD5 去重：只匹配非 failed 的同租户任务（failed 文件允许重新上传）
    stmt = select(ScanTask).where(
        ScanTask.file_md5 == file_md5,
        ScanTask.status != "failed",
    )
    if tenant_id is not None:
        stmt = stmt.where(ScanTask.tenant_id == tenant_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(f"Duplicate file detected: {filename} (MD5={file_md5}), existing task={existing.id}")
        return ScanUploadResponse(
            task_id=existing.id,
            status=existing.status,
            filename=existing.filename,
            message="duplicate_file",
        )

    task_id = uuid.uuid4()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    object_key = f"raw/{today}/{task_id}_{quote(filename)}"

    # 先上传 MinIO，再写 DB — 失败时补偿删除已上传的对象
    try:
        await asyncio.to_thread(
            minio_client.upload_bytes,
            bucket=settings.minio_bucket_raw,
            object_key=object_key,
            data=content,
            content_type="application/pdf",
        )
    except Exception as e:
        logger.error(f"MinIO upload failed for task {task_id}: {type(e).__name__}")
        return {"failed": {"filename": filename, "reason": "MinIO upload failed"}}

    task = ScanTask(
        id=task_id,
        tenant_id=tenant_id,
        filename=filename,
        scanner_id=scanner_id,
        source_type="api_upload",
        status="received",
        file_size=len(content),
        file_md5=file_md5,
        callback_url=callback_url,
        original_path=object_key,
        metadata_=meta_dict or {},
    )
    db.add(task)

    scan_file = ScanFile(
        task_id=task_id,
        file_type="raw_pdf",
        bucket=settings.minio_bucket_raw,
        object_key=object_key,
        size_bytes=len(content),
    )
    db.add(scan_file)

    try:
        await db.flush()
    except Exception as e:
        # DB 失败 → 补偿删除已上传的 MinIO 对象
        logger.error(f"DB flush failed for task {task_id}: {e}")
        try:
            await asyncio.to_thread(
                minio_client.delete_object,
                bucket=settings.minio_bucket_raw,
                object_key=object_key,
            )
        except Exception:
            logger.error(f"Compensation delete failed for orphan {object_key}")
        raise

    # 更新租户存储用量
    if tenant_id is not None:
        from sqlalchemy import update as sa_update
        from db.models_auth import Tenant
        await db.execute(
            sa_update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(storage_used_mb=Tenant.storage_used_mb + (len(content) / (1024.0 * 1024.0)))
        )

    logger.info(f"Scan uploaded: task={task_id}, file={filename}, size={len(content)}")

    return ScanUploadResponse(
        task_id=task_id,
        status=task.status,
        filename=filename,
        message="uploaded_pending_process",
    )


# ═══════════════════════════════════════════════════════════
# POST /api/v1/scans/upload
# ═══════════════════════════════════════════════════════════
@router.post("/upload", response_model=ScanUploadResponse, status_code=202)
@limiter.limit("3/minute")
async def upload_scan(
    request: Request,
    file: UploadFile = File(...),
    scanner_id: Optional[str] = Form(default=None),
    callback_url: Optional[str] = Form(default=None),
    metadata_json: Optional[str] = Form(default=None, alias="metadata"),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """上传扫描件 PDF，创建处理任务"""

    filename = file.filename or "unknown.pdf"
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. Expected: application/pdf",
        )

    try:
        content = await file.read()
    except Exception:
        logger.error(f"Failed to read uploaded file (filename hidden for privacy)")
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {settings.max_upload_size // (1024*1024)} MB",
        )

    MAX_METADATA_SIZE = 64 * 1024
    meta_dict = {}
    if metadata_json:
        if len(metadata_json) > MAX_METADATA_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Metadata JSON too large (max {MAX_METADATA_SIZE // 1024} KB)",
            )
        try:
            meta_dict = json.loads(metadata_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON")

    _safe_scanner_id = scanner_id or "manual"
    if not re.match(r'^[a-zA-Z0-9_\-]{1,128}$', _safe_scanner_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid scanner_id: must be 1-128 alphanumeric characters, underscores, or hyphens",
        )

    # SSRF 防护：校验 callback_url（upload 和 batch-upload 共用）
    _validate_callback_url(callback_url)

    result = await _upload_single_file(
        db=db,
        content=content,
        filename=filename,
        scanner_id=_safe_scanner_id,
        callback_url=callback_url,
        meta_dict=meta_dict,
        tenant_id=tenant_id,
    )

    if isinstance(result, dict):
        if "failed" in result:
            raise HTTPException(status_code=500, detail=result["failed"]["reason"])
        if "skipped" in result:
            raise HTTPException(status_code=400, detail=result["skipped"]["reason"])

    return result


# ═══════════════════════════════════════════════════════════
# POST /api/v1/scans/batch-upload
# ═══════════════════════════════════════════════════════════
@router.post("/batch-upload", response_model=BatchUploadResult, status_code=202)
@limiter.limit("1/minute")
async def batch_upload(
    request: Request,
    files: list[UploadFile] = File(..., description="PDF 文件列表（最多 20 个）"),
    scanner_id: Optional[str] = Form(default=None),
    callback_url: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """批量上传扫描件 PDF，每个文件创建独立处理任务"""

    if len(files) > 20:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum 20 per request, got {len(files)}",
        )

    _safe_scanner_id = scanner_id or "manual"
    if not re.match(r'^[a-zA-Z0-9_\-]{1,128}$', _safe_scanner_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid scanner_id: must be 1-128 alphanumeric characters, underscores, or hyphens",
        )

    # SSRF 防护：batch-upload 也必须校验 callback_url（与 upload 共用）
    _validate_callback_url(callback_url)

    uploaded: list[ScanUploadResponse] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for file in files:
        filename = file.filename or "unknown.pdf"

        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            skipped.append({"filename": filename, "reason": f"Invalid extension"})
            continue

        try:
            content = await file.read()
        except Exception:
            failed.append({"filename": filename, "reason": "Failed to read file"})
            continue

        result = await _upload_single_file(
            db=db,
            content=content,
            filename=filename,
            scanner_id=_safe_scanner_id,
            callback_url=callback_url,
            tenant_id=tenant_id,
        )

        if isinstance(result, ScanUploadResponse):
            uploaded.append(result)
        elif isinstance(result, dict):
            if "skipped" in result:
                skipped.append(result["skipped"])
            elif "failed" in result:
                failed.append(result["failed"])

    logger.info(f"Batch upload: uploaded={len(uploaded)}, skipped={len(skipped)}, failed={len(failed)}")

    return BatchUploadResult(uploaded=uploaded, skipped=skipped, failed=failed)


# ═══════════════════════════════════════════════════════════
# POST /api/v1/scans/process
# ═══════════════════════════════════════════════════════════
@router.post("/process", response_model=BatchProcessResult, status_code=202)
@limiter.limit("10/minute")
async def batch_process(
    request: Request,
    body: BatchProcessRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """批量启动识别处理

    接收一组任务 ID，将 received 状态的任务改为 pending 并派发 Celery 处理。
    非 received 状态的任务将被跳过。
    """
    if process_scan is None:
        raise HTTPException(
            status_code=500,
            detail="Celery task dispatcher not available",
        )

    dispatched: list[uuid.UUID] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for task_id in body.task_ids:
        # SELECT FOR UPDATE 防止并发请求同时拿到同一任务
        stmt = select(ScanTask).where(ScanTask.id == task_id).with_for_update()
        if tenant_id is not None:
            stmt = stmt.where(ScanTask.tenant_id == tenant_id)
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            skipped.append({"task_id": str(task_id), "reason": "not_found"})
            continue

        if task.status != "received":
            skipped.append({
                "task_id": str(task_id),
                "reason": f"status_is_{task.status}_not_received",
            })
            continue

        task.status = "pending"
        await db.flush()

        try:
            _dispatch_celery(task_id)
            dispatched.append(task_id)
        except RuntimeError as e:
            await _mark_task_failed(db, task, "DISPATCH_ERROR", str(e))
            failed.append({"task_id": str(task_id), "reason": str(e)})

    logger.info(
        f"Batch process: dispatched={len(dispatched)}, "
        f"skipped={len(skipped)}, failed={len(failed)}"
    )

    return BatchProcessResult(dispatched=dispatched, skipped=skipped, failed=failed)


# ═══════════════════════════════════════════════════════════
# GET /api/v1/scans
# ═══════════════════════════════════════════════════════════
@router.get("", response_model=PaginatedResponse[ScanTaskSummary])
@limiter.limit("30/minute")
async def list_scans(
    request: Request,
    page: int = Query(default=1, ge=1, description="页码（从1开始）"),
    size: int = Query(default=20, ge=1, le=100, description="每页条数（1-100）"),
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    scanner_id: Optional[str] = Query(default=None, description="按扫描仪筛选"),
    sort_by: str = Query(
        default="created_at",
        description=f"排序字段: {', '.join(sorted(ALLOWED_SORT_FIELDS))}",
    ),
    sort_order: str = Query(
        default="desc",
        pattern="^(asc|desc)$",
        description="排序方向: asc / desc",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """查询扫描任务列表（分页+筛选+排序）

    支持按 status、scanner_id 筛选，支持多字段排序。
    """
    # 校验排序字段
    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by field. Allowed: {', '.join(sorted(ALLOWED_SORT_FIELDS))}",
        )

    # 构建筛选条件
    conditions = []
    if status:
        conditions.append(ScanTask.status == status)
    if scanner_id:
        conditions.append(ScanTask.scanner_id == scanner_id)
    if tenant_id is not None:
        conditions.append(ScanTask.tenant_id == tenant_id)

    # 总数
    count_stmt = select(func.count(ScanTask.id))
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar()

    # 排序方向
    sort_col = getattr(ScanTask, sort_by)
    order_func = desc if sort_order == "desc" else lambda col: col.asc()

    # 分页查询
    stmt = select(ScanTask).order_by(order_func(sort_col))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.offset((page - 1) * size).limit(size)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    items = [
        ScanTaskSummary(
            task_id=t.id,
            filename=t.filename,
            status=t.status,
            page_count=t.page_count,
            confidence_avg=float(t.confidence_avg) if t.confidence_avg is not None else None,
            created_at=t.created_at,
            completed_at=t.completed_at,
            error_code=t.error_code,
        )
        for t in tasks
    ]

    return PaginatedResponse(items=items, page=page, size=size, total=total)


# ═══════════════════════════════════════════════════════════
# GET /api/v1/scans/{task_id}
# ═══════════════════════════════════════════════════════════
@router.get("/{task_id}", response_model=ScanTaskDetail)
@limiter.limit("60/minute")
async def get_scan_detail(
    request: Request,
    task_id: uuid.UUID,
    include_presigned: bool = Query(
        default=False,
        description="是否生成预签名下载URL（有效期1小时）",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """查询任务详情（含处理步骤、文件产物、可选预签名URL）"""
    task = await _get_task_or_404(task_id, db, tenant_id)

    detail = _build_detail(task)

    # 可选：为文件生成预签名 URL
    if include_presigned:
        presigned_urls = {}
        for f_obj in (task.files or []):
            try:
                url = minio_client.get_presigned_url(
                    bucket=f_obj.bucket,
                    object_key=f_obj.object_key,
                    expires=3600,
                )
                presigned_urls[f"{f_obj.file_type}_{f_obj.id}"] = url
            except Exception as e:
                logger.warning(f"Presigned URL generation failed for file {f_obj.id}: {e}")
                presigned_urls[f"{f_obj.file_type}_{f_obj.id}"] = None

        # 将 presigned_urls 添加到 metadata 中返回
        detail.metadata["presigned_urls"] = presigned_urls

    return detail


# ═══════════════════════════════════════════════════════════
# GET /api/v1/scans/{task_id}/result
# ═══════════════════════════════════════════════════════════
@router.get("/{task_id}/result")
@limiter.limit("60/minute")
async def get_scan_result(
    request: Request,
    task_id: uuid.UUID,
    download: bool = Query(
        default=False,
        description="是否以文件附件形式下载（否则内联返回JSON）",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """获取任务的结构化 JSON 结果

    - `download=false`（默认）：内联返回 JSON，方便前端预览
    - `download=true`：以附件形式下载，文件名 = {task_id}_result.json

    任务必须处于 completed 状态且结果文件存在。
    """
    task = await _get_task_or_404(task_id, db, tenant_id)
    result_json = await _fetch_result_json(task, task_id)

    if download:
        # 文件下载模式
        safe_filename = f"{task_id}_result.json"
        return Response(
            content=json.dumps(result_json, ensure_ascii=False, indent=2).encode("utf-8"),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_filename)}",
            },
        )
    else:
        # 内联 JSON 模式
        return result_json


# ═══════════════════════════════════════════════════════════
# GET /api/v1/scans/{task_id}/download
# ═══════════════════════════════════════════════════════════
@router.get("/{task_id}/download")
@limiter.limit("30/minute")
async def download_scan_docx(
    request: Request,
    task_id: uuid.UUID,
    format: str = Query(
        default="docx",
        description="下载格式（目前支持 docx）",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """下载结构化结果为 Word 文档 (.docx)

    将扫描件的结构化 JSON 结果转换为格式化的 Word 文档并下载。
    任务必须处于 completed 状态且结果文件存在。

    - `format=docx`（默认）：返回 .docx 文件
    """
    if format not in ("docx",):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Supported: docx")

    task = await _get_task_or_404(task_id, db, tenant_id)
    result_json = await _fetch_result_json(task, task_id)

    # 生成 Word 文档
    try:
        docx_bytes = export_docx_bytes(result_json, filename=task.filename)
    except Exception as e:
        logger.error(f"Failed to generate docx for task {task_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate Word document",
        )

    # 安全文件名
    base_name = Path(task.filename).stem
    safe_filename = quote(f"{base_name}_结构化.docx")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


# ═══════════════════════════════════════════════════════════
# POST /api/v1/scans/{task_id}/retry
# ═══════════════════════════════════════════════════════════
@router.post("/{task_id}/retry", response_model=MessageResponse, status_code=202)
@limiter.limit("10/minute")
async def retry_scan(
    request: Request,
    task_id: uuid.UUID,
    force: bool = Query(
        default=False,
        description="是否强制重试（也允许重试已完成/处理中的任务）",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """重试扫描任务

    - 仅 failed 状态可重试（除非 force=true）
    - 重置状态为 pending 并清除错误信息
    - 清理上次运行的中间产物（工作目录 + MinIO 中间文件）
    - 自动派发 Celery 异步任务到队列

    返回 202 Accepted 表示任务已排队。
    """
    task = await _get_task_or_404(task_id, db, tenant_id, for_update=True)

    # 检查状态
    if not force and task.status != "failed":
        raise HTTPException(
            status_code=400,
            detail=f"Only failed tasks can be retried (force=true to override). "
            f"Current status: {task.status}",
        )
    if task.status not in ("failed", "completed", "pending", "received", "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry task with status: {task.status}",
        )

    # === 幂等保护：清理上次运行的中间产物 ===

    # 1. 清理工作目录中的中间文件（用 asyncio.to_thread 避免阻塞事件循环）
    work_dir = Path(settings.archive_dir) / "processing" / str(task_id)
    if work_dir.exists():
        try:
            import shutil
            import asyncio
            await asyncio.to_thread(shutil.rmtree, work_dir)
            logger.info(f"Retry: cleaned work directory for {task_id}")
        except Exception as e:
            logger.warning(f"Retry: failed to clean work directory for {task_id}: {e}")

    # 2. 清理 MinIO 中间产物（保留原始 PDF）
    try:
        def _cleanup_minio_intermediate():
            objects = minio_client.client.list_objects(
                settings.minio_bucket_result, prefix=str(task_id), recursive=True
            )
            for obj in objects:
                try:
                    minio_client.delete_object(settings.minio_bucket_result, obj.object_name)
                except Exception as e:
                    logger.warning(f"Retry: failed to delete MinIO object {obj.object_name}: {e}")
        await asyncio.to_thread(_cleanup_minio_intermediate)
        logger.debug(f"Retry: cleaned MinIO intermediate objects for {task_id}")
    except Exception as e:
        logger.warning(f"Retry: MinIO cleanup skipped for {task_id}: {e}")

    # 3. 撤销可能仍在运行的旧 Celery 任务
    if celery_app is not None:
        _revoke_scan_celery_task(celery_app, task_id)

    # === 重置任务状态 ===
    task.status = "pending"
    task.error_code = None
    task.error_message = None
    task.started_at = None
    task.completed_at = None

    # 重置统计字段
    task.confidence_avg = None
    task.structure_score = None
    task.page_count = None
    task.table_count = 0
    task.heading_count = 0
    task.paragraph_count = 0

    # 删除旧步骤（UniqueConstraint(task_id, step_name) 会阻止重试时创建同名步骤）
    from sqlalchemy import delete
    await db.execute(
        delete(TaskStep).where(TaskStep.task_id == task_id)
    )

    await db.flush()

    # === 派发 Celery 异步任务 ===
    try:
        _dispatch_celery(task_id)
    except RuntimeError as e:
        await _mark_task_failed(db, task, "RETRY_DISPATCH_ERROR", str(e))
        if "not available" in str(e):
            raise HTTPException(
                status_code=500,
                detail="Celery task dispatcher not available",
            )
        raise HTTPException(
            status_code=500,
            detail="Failed to dispatch retry task",
        )

    logger.info(f"Task {task_id} reset to pending for retry")

    return MessageResponse(message=f"Task {task_id} queued for retry")


# ═══════════════════════════════════════════════════════════
# DELETE /api/v1/scans/{task_id}
# ═══════════════════════════════════════════════════════════
@router.delete("/{task_id}", response_model=MessageResponse)
@limiter.limit("10/minute")
async def delete_scan(
    request: Request,
    task_id: uuid.UUID,
    keep_raw: bool = Query(
        default=False,
        description="是否保留原始 PDF 文件（仅清理中间产物）",
    ),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """删除任务及关联数据

    清理步骤：
    1. 撤销正在运行的 Celery 任务
    2. 清理 MinIO 对象（raw bucket 可选保留）
    3. 级联删除数据库记录（task_steps / scan_files 自动清理）

    参数:
    - `keep_raw=true`：保留原始 PDF，仅删除中间处理产物
    """
    task = await _get_task_or_404(task_id, db, tenant_id)

    logger.info(
        f"Deleting task {task_id}: filename={task.filename}, "
        f"status={task.status}, keep_raw={keep_raw}"
    )

    # === 1. 撤销 Celery 任务 ===
    if celery_app is not None:
        _revoke_scan_celery_task(celery_app, task_id)
    else:
        logger.debug(f"Celery not available, skip task revocation for {task_id}")

    # === 2. 清理 MinIO 对象 ===
    cleanup_errors = []
    try:
        if keep_raw:
            # 仅清理非 raw bucket
            buckets_to_clean = [
                b for b in settings.all_minio_buckets
                if b != settings.minio_bucket_raw
            ]
            def _cleanup_minio_keep_raw():
                for bucket in buckets_to_clean:
                    try:
                        objects = minio_client.client.list_objects(
                            bucket, prefix=str(task_id), recursive=True
                        )
                        for obj in objects:
                            try:
                                minio_client.delete_object(bucket, obj.object_name)
                            except Exception as e:
                                cleanup_errors.append(f"{bucket}/{obj.object_name}: {e}")
                        logger.debug(f"Cleaned bucket {bucket} for task {task_id}")
                    except Exception as e:
                        logger.warning(f"Error listing objects in {bucket}: {e}")
            await asyncio.to_thread(_cleanup_minio_keep_raw)
        else:
            await asyncio.to_thread(minio_client.delete_task_objects, str(task_id))
            logger.debug(f"Cleaned all objects for task {task_id}")
    except Exception as e:
        logger.warning(f"MinIO cleanup warning for task {task_id}: {e}")
        cleanup_errors.append(f"MinIO: {e}")

    # === 3. 删除数据库记录 ===
    # 扣减租户存储用量
    if task.tenant_id is not None and task.file_size:
        from sqlalchemy import update as sa_update
        from db.models_auth import Tenant
        await db.execute(
            sa_update(Tenant)
            .where(Tenant.id == task.tenant_id)
            .values(storage_used_mb=Tenant.storage_used_mb - (task.file_size / (1024.0 * 1024.0)))
        )

    # 级联删除自动处理 task_steps 和 scan_files
    await db.delete(task)
    await db.flush()

    log_msg = f"Task {task_id} deleted (keep_raw={keep_raw})"
    if cleanup_errors:
        log_msg += f" | cleanup warnings: {len(cleanup_errors)}"
    logger.info(log_msg)

    return MessageResponse(message=f"Task {task_id} deleted")
