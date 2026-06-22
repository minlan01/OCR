"""
证据模块 API 路由
Phase1: 上传 → OCR → 分类 → 清单
Phase2: 分析 → 导出
"""
from __future__ import annotations

import asyncio
import copy
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.evidence import (
    AnalysisResponse,
    CatalogResponse,
    CatalogGroupResponse,
    CompensationCalculateRequest,
    CompensationUpdateRequest,
    CreateEvidenceCaseRequest,
    EvidenceCaseListResponse,
    EvidenceCaseListSlimResponse,
    EvidenceCaseListItem,
    EvidenceCaseResponse,
    ExportBundleResponse,
    MaterialResponse,
    ProcessResponse,
    ProgressResponse,
    StepResponse,
    UpdateCatalogRequest,
    UpdateMaterialRequest,
    UpdateCaseRequest,
)
from api.schemas.common import MessageResponse
from api.rate_limit import limiter
from api.dependencies import get_tenant_filter
from config.settings import settings
from db.models_evidence import EvidenceCase, EvidenceMaterial, EvidenceStep
from db.session import get_db

try:
    from worker.evidence_tasks import (
        process_evidence_full,
        analyze_evidence,
        export_evidence_bundle,
    )
except ImportError:
    process_evidence_full = None
    analyze_evidence = None
    export_evidence_bundle = None

router = APIRouter(prefix="/evidence")

EVIDENCE_MINIO_BUCKET = "scan-result"


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _build_material_out(m: EvidenceMaterial) -> MaterialResponse:
    return MaterialResponse(
        id=str(m.id),
        original_filename=m.original_filename,
        file_type=m.file_type,
        minio_bucket=m.minio_bucket,
        minio_key=m.minio_key,
        file_size=m.file_size,
        auto_category=m.auto_category,
        manual_category=m.manual_category,
        effective_category=m.effective_category,
        category_confidence=m.category_confidence,
        ocr_status=m.ocr_status,
        ocr_text=m.ocr_text,
        ocr_result=m.ocr_result,
        page_count=m.page_count,
        extracted_data=m.extracted_data,
        manual_edit=m.manual_edit,
        catalog_index=m.catalog_index,
        catalog_title=m.catalog_title,
        catalog_description=m.catalog_description,
        proof_purpose=m.proof_purpose,
        fee_detail=m.fee_detail,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _build_step_out(s: EvidenceStep) -> StepResponse:
    return StepResponse(
        id=s.id,
        step_name=s.step_name,
        status=s.status,
        progress=s.progress,
        duration_ms=s.duration_ms,
        error_message=s.error_message,
        started_at=s.started_at,
        completed_at=s.completed_at,
    )


def _build_case_out(case: EvidenceCase) -> EvidenceCaseResponse:
    return EvidenceCaseResponse(
        id=str(case.id),
        case_name=case.case_name,
        case_type=case.case_type,
        is_minor=case.is_minor,
        status=case.status,
        plaintiff_info=case.plaintiff_info,
        defendant_info=case.defendant_info,
        catalog_data=case.catalog_data,
        catalog_pdf_path=case.catalog_pdf_path,
        analysis_result=case.analysis_result,
        validation_result=case.validation_result,
        missing_items=case.missing_items,
        export_bundle_path=case.export_bundle_path,
        export_files=case.export_files,
        lawyer_info=case.lawyer_info if isinstance(case.lawyer_info, list) else [],
        metadata=case.metadata_,
        materials=[_build_material_out(m) for m in (case.materials or [])],
        steps=[_build_step_out(s) for s in (case.steps or [])],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


async def _get_case_or_404(case_id: uuid.UUID, db: AsyncSession, tenant_id: uuid.UUID | None = None) -> EvidenceCase:
    stmt = select(EvidenceCase).where(EvidenceCase.id == case_id)
    if tenant_id is not None:
        stmt = stmt.where(EvidenceCase.tenant_id == tenant_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Evidence case not found: {case_id}")
    return case


async def _check_case_exists(case_id: uuid.UUID, db: AsyncSession, tenant_id: uuid.UUID | None = None) -> EvidenceCase:
    """轻量级检查案件是否存在，不加载 materials 和 steps"""
    from sqlalchemy.orm import noload
    stmt = (
        select(EvidenceCase)
        .options(noload(EvidenceCase.materials), noload(EvidenceCase.steps))
        .where(EvidenceCase.id == case_id)
    )
    if tenant_id is not None:
        stmt = stmt.where(EvidenceCase.tenant_id == tenant_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Evidence case not found: {case_id}")
    return case


def _cleanup_old_export(case: EvidenceCase, filename: str) -> None:
    """清理旧的导出文件（在重新生成同类型文件前调用）"""
    export_files = case.export_files or {}
    old_key = export_files.get(filename)
    if old_key:
        try:
            from services.storage.minio_client import minio_client
            minio_client.delete_object(EVIDENCE_MINIO_BUCKET, old_key)
        except Exception:
            pass


def _track_export(case: EvidenceCase, filename: str, minio_key: str) -> None:
    """追踪导出文件的 MinIO key（用于后续清理）"""
    if case.export_files is None:
        case.export_files = {}
    case.export_files[filename] = minio_key


def _cleanup_all_exports(case: EvidenceCase) -> None:
    """清理案件的所有已追踪导出文件（重新分析时调用）"""
    export_files = case.export_files or {}
    if not export_files:
        return
    try:
        from services.storage.minio_client import minio_client
        for filename, key in export_files.items():
            if key:
                try:
                    minio_client.delete_object(EVIDENCE_MINIO_BUCKET, key)
                except Exception:
                    pass
        case.export_files = {}
        logger.info(f"Cleaned up {len(export_files)} old export files for case {case.id}")
    except Exception as e:
        logger.warning(f"Failed to clean exports for case {case.id}: {e}")


def _detect_file_type(filename: str) -> str:
    """根据文件扩展名判断文件类型"""
    if not filename:
        return "other"
    fn = filename.lower()
    if fn.endswith(".pdf"):
        return "pdf"
    if fn.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")):
        return "image"
    if fn.endswith((".docx", ".doc")):
        return "docx"
    if fn.endswith((".xlsx", ".xls")):
        return "xlsx"
    if fn.endswith((".mp3", ".wav", ".m4a", ".amr", ".aac", ".flac", ".ogg")):
        return "audio"
    return "other"


# ─── Phase 1: 上传 → 清单 ───────────────────────────────────────────────────

@router.post("/cases", response_model=EvidenceCaseResponse, status_code=201)
@limiter.limit("10/minute")
async def create_case(
    request: Request,
    body: CreateEvidenceCaseRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """创建证据案件"""
    # ─── 租户配额检查 ───
    if tenant_id is not None:
        from db.models_auth import Tenant
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if tenant and tenant.status != "active":
            raise HTTPException(status_code=403, detail="租户已被暂停，无法创建案件")
        if tenant:
            count_stmt = select(func.count(EvidenceCase.id)).where(EvidenceCase.tenant_id == tenant_id)
            current_count = (await db.execute(count_stmt)).scalar()
            if current_count >= tenant.max_cases:
                raise HTTPException(
                    status_code=429,
                    detail=f"已达租户案件上限 ({tenant.max_cases})，请联系管理员升级套餐",
                )
    case = EvidenceCase(
        tenant_id=tenant_id,
        case_name=body.case_name,
        case_type=body.case_type,
        is_minor=body.is_minor,
        status="draft",
        plaintiff_info=body.plaintiff_info,
        defendant_info=body.defendant_info,
    )
    db.add(case)
    await db.flush()
    await db.refresh(case)
    logger.info(f"Evidence case created: {case.id} type={body.case_type} minor={body.is_minor} tenant={tenant_id}")
    return _build_case_out(case)


@router.get("/cases", response_model=EvidenceCaseListResponse)
@limiter.limit("30/minute")
async def list_cases(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """案件列表"""
    from sqlalchemy.orm import noload

    count_stmt = select(func.count(EvidenceCase.id))
    if tenant_id is not None:
        count_stmt = count_stmt.where(EvidenceCase.tenant_id == tenant_id)
    total = (await db.execute(count_stmt)).scalar()

    stmt = (
        select(EvidenceCase)
        .options(noload(EvidenceCase.materials), noload(EvidenceCase.steps))
        .order_by(desc(EvidenceCase.created_at))
        .offset((page - 1) * size)
        .limit(size)
    )
    if tenant_id is not None:
        stmt = stmt.where(EvidenceCase.tenant_id == tenant_id)
    result = await db.execute(stmt)
    cases = result.scalars().all()

    return EvidenceCaseListResponse(
        items=[_build_case_out(c) for c in cases],
        total=total,
    )


@router.get("/cases/{case_id}", response_model=EvidenceCaseResponse)
@limiter.limit("60/minute")
async def get_case(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """案件详情"""
    case = await _get_case_or_404(case_id, db, tenant_id)
    return _build_case_out(case)


@router.put("/cases/{case_id}", response_model=EvidenceCaseResponse)
@limiter.limit("30/minute")
async def update_case(
    request: Request,
    case_id: uuid.UUID,
    body: UpdateCaseRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """更新案件基本信息（名称/类型/是否未成年人/律师信息/被告联系电话）"""
    case = await _get_case_or_404(case_id, db, tenant_id)
    if body.case_name is not None:
        case.case_name = body.case_name
    if body.case_type is not None:
        case.case_type = body.case_type
    if body.is_minor is not None:
        case.is_minor = body.is_minor
    if body.lawyer_info is not None:
        # 最多2个律师
        case.lawyer_info = body.lawyer_info[:2]
    if body.defendant_phone is not None:
        def_info = case.defendant_info or {}
        def_info["phone"] = body.defendant_phone
        case.defendant_info = def_info
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(case)
    return _build_case_out(case)


@router.post("/cases/{case_id}/cancel", response_model=MessageResponse)
@limiter.limit("10/minute")
async def cancel_case(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """取消正在处理的案件：杀掉 Celery 任务 + 清理 OCR 进程 + 标记为 failed"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    ACTIVE_STATUSES = {"processing", "analyzing", "exporting"}
    if case.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"案件当前状态为 '{case.status}'，无法取消。只能取消正在处理的案件。",
        )

    # 1. 查找并撤销该案件关联的 Celery 任务
    cancelled_tasks = []
    try:
        from worker.celery_app import celery_app as _celery
        # 查找活跃任务
        active = _celery.control.inspect().get("active", {})
        task_names = [
            "process_evidence_full",
            "analyze_evidence",
            "export_evidence_bundle",
        ]
        for worker_name, tasks in active.items():
            for t in tasks:
                if (
                    t.get("name") in task_names
                    and t.get("args")
                    and len(t["args"]) > 0
                    and str(t["args"][0]) == str(case_id)
                ):
                    task_id = t["id"]
                    _celery.control.revoke(task_id, terminate=True, signal="SIGKILL")
                    cancelled_tasks.append(task_id)
                    logger.warning(f"Revoked Celery task {task_id} for case {case_id}")
    except Exception as e:
        logger.warning(f"Failed to revoke Celery tasks for case {case_id}: {e}")

    # 2. 清理 worker /tmp 下该案件的 OCR 临时文件（通过 Redis pub/sub 或直接标记）
    # Worker 进程被 SIGKILL 后会自动释放资源

    # 3. 更新案件状态为 failed
    case.status = "failed"
    await db.commit()

    logger.info(
        f"Cancelled case {case_id}: revoked {len(cancelled_tasks)} tasks, "
        f"tasks={cancelled_tasks}"
    )
    return MessageResponse(
        message=f"案件 '{case.case_name}' 已取消，{len(cancelled_tasks)} 个后台任务已终止"
    )


@router.delete("/cases/{case_id}", response_model=MessageResponse)
@limiter.limit("30/minute")
async def delete_case(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """删除案件及其所有材料、步骤（ORM级联删除）+ 清理MinIO存储

    processing/analyzing/exporting 状态的案件必须先调用 /cancel 取消后才能删除。
    """
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 状态保护：正在处理的案件不允许直接删除（会导致数据库锁竞争）
    ACTIVE_STATUSES = {"processing", "analyzing", "exporting"}
    if case.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"案件正在{ {'processing':'处理','analyzing':'分析','exporting':'导出'}.get(case.status, '处理') }中"
                   f"（状态: {case.status}），请先取消后再删除。"
                   f"可调用 POST /api/v1/evidence/cases/{case_id}/cancel 取消处理。",
        )

    # 清理 MinIO 中该案件的所有文件（上传素材 + 生成文档 + 导出包）
    try:
        from services.storage.minio_client import minio_client
        deleted_count = minio_client.delete_prefix(
            bucket=EVIDENCE_MINIO_BUCKET,
            prefix=f"evidence/{case_id}/",
        )
        logger.info(f"Cleaned up {deleted_count} MinIO objects for case {case_id}")
    except Exception as e:
        logger.warning(f"Failed to clean MinIO for case {case_id}: {e}")

    await db.delete(case)
    await db.commit()
    logger.info(f"Deleted evidence case {case_id}")
    return MessageResponse(message=f"案件 '{case.case_name}' 已删除")


@router.post("/cases/{case_id}/upload", response_model=list[MaterialResponse], status_code=201)
@limiter.limit("10/minute")
async def upload_materials(
    request: Request,
    case_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """批量上传证据材料（支持多文件，大文件流式上传）"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    if case.status in ("completed",):
        raise HTTPException(
            status_code=400,
            detail=f"案件已完成，无法继续上传。请创建新案件。",
        )

    if case.status == "draft":
        case.status = "uploading"

    MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB 以上走流式
    from services.storage.minio_client import minio_client

    # 查询当前案件已有的非终态素材文件名（用于去重）
    existing_stmt = select(EvidenceMaterial.original_filename).where(
        EvidenceMaterial.evidence_case_id == case_id,
        EvidenceMaterial.ocr_status.notin_(["failed"]),
    )
    existing_result = await db.execute(existing_stmt)
    existing_filenames = {name for name in existing_result.scalars().all() if name}

    # 检查同名文件
    duplicate_names = []
    for file in files:
        fname = file.filename or ""
        if fname in existing_filenames:
            duplicate_names.append(fname)
    if duplicate_names:
        raise HTTPException(
            status_code=409,
            detail=f"以下文件已存在（如需重新上传，请先删除旧文件）：{', '.join(duplicate_names)}",
        )

    uploaded = []
    uploaded_minio_keys: list[str] = []  # 跟踪已上传对象，失败时回滚清理
    try:
        for file in files:
            # 先检查 Content-Length 避免读取超大文件到内存
            if file.size and file.size > settings.max_upload_size:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件过大: {file.filename}（最大允许 {settings.max_upload_size // (1024*1024)} MB）",
                )

        file_type = _detect_file_type(file.filename or "")
        # 文件类型白名单校验（含音频）
        ALLOWED_TYPES = {"pdf", "image", "docx", "xlsx", "audio"}
        if file_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.filename}（仅支持 PDF/图片/Word/Excel/音频）",
            )

        # 扩展名校验（使用 settings.allowed_extensions）
        ext = Path(file.filename or "").suffix.lower()
        if ext not in settings.allowed_extensions and file_type not in ("image", "docx", "xlsx", "audio"):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件扩展名: {ext}（允许: {', '.join(settings.allowed_extensions)}）",
            )

        # 文件魔数校验（防止扩展名伪装攻击）
        magic_head = await file.read(8)
        await file.seek(0)
        MAGIC_NUMBERS = {
            "pdf": [b"%PDF"],
            "docx": [b"PK\x03\x04"],  # zip 格式
            "xlsx": [b"PK\x03\x04"],
            "image_jpg": [b"\xff\xd8\xff"],
            "image_png": [b"\x89PNG\r\n\x1a\n"],
            "image_gif": [b"GIF87a", b"GIF89a"],
            "image_bmp": [b"BM"],
            "image_webp": [b"RIFF"],
            "image_tiff": [b"II*\x00", b"MM\x00*"],
        }
        magic_ok = False
        if file_type == "pdf":
            magic_ok = any(magic_head.startswith(m) for m in MAGIC_NUMBERS["pdf"])
        elif file_type in ("docx", "xlsx"):
            magic_ok = any(magic_head.startswith(m) for m in MAGIC_NUMBERS["docx"])
        elif file_type == "image":
            for key in ("image_jpg", "image_png", "image_gif", "image_bmp", "image_webp", "image_tiff"):
                if any(magic_head.startswith(m) for m in MAGIC_NUMBERS[key]):
                    magic_ok = True
                    break
        elif file_type == "audio":
            # 音频格式多样，仅做扩展名校验
            magic_ok = True
        if not magic_ok:
            raise HTTPException(
                status_code=400,
                detail=f"文件内容与扩展名不符（可能被篡改）: {file.filename}",
            )

        original_filename = file.filename or "upload"
        minio_key = f"evidence/{case_id}/{uuid.uuid4()}_{quote(original_filename)}"
        content_type = file.content_type or "application/octet-stream"

        # 根据文件大小选择上传方式
        file_size_actual: int
        try:
            if file.size and file.size >= MULTIPART_THRESHOLD:
                # 大文件：流式上传（内存恒定 = 一个分片大小）
                # 先保存到临时文件，再 fput_object
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp_path = tmp.name
                    while True:
                        chunk = await file.read(50 * 1024 * 1024)  # 50MB chunks
                        if not chunk:
                            break
                        tmp.write(chunk)
                    file_size_actual = tmp.tell()

                if file_size_actual > settings.max_upload_size:
                    import os
                    os.unlink(tmp_path)
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大: {original_filename}（最大允许 {settings.max_upload_size // (1024*1024)} MB）",
                    )

                try:
                    minio_client.upload_file(
                        bucket=EVIDENCE_MINIO_BUCKET,
                        object_key=minio_key,
                        file_path=tmp_path,
                        content_type=content_type,
                    )
                finally:
                    import os
                    os.unlink(tmp_path)
            elif file_type == "audio":
                # 音频文件：读取到内存（通常不大），流式上传
                content = await file.read()
                file_size_actual = len(content)
                if file_size_actual > settings.max_upload_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大: {original_filename}（最大允许 {settings.max_upload_size // (1024*1024)} MB）",
                    )
                minio_client.upload_bytes(
                    bucket=EVIDENCE_MINIO_BUCKET,
                    object_key=minio_key,
                    data=content,
                    content_type=content_type,
                )
            else:
                # 小文件：原有方式
                content = await file.read()
                file_size_actual = len(content)
                if file_size_actual > settings.max_upload_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大: {original_filename}（最大允许 {settings.max_upload_size // (1024*1024)} MB）",
                    )
                minio_client.upload_bytes(
                    bucket=EVIDENCE_MINIO_BUCKET,
                    object_key=minio_key,
                    data=content,
                    content_type=content_type,
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"MinIO upload failed for evidence case {case_id}: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail="File storage failed")

        # 音频文件 OCR 状态标记为 not_applicable
        ocr_status = "not_applicable" if file_type == "audio" else "pending"

        material = EvidenceMaterial(
            evidence_case_id=case_id,
            original_filename=original_filename,
            file_type=file_type,
            minio_bucket=EVIDENCE_MINIO_BUCKET,
            minio_key=minio_key,
            file_size=file_size_actual,
            ocr_status=ocr_status,
        )
        db.add(material)
        await db.flush()
        await db.refresh(material)
        uploaded.append(material)
        uploaded_minio_keys.append(minio_key)  # 标记为已成功（供回滚清理）

    except Exception:
        # 批量上传中途失败：清理已上传的 MinIO 孤儿对象，避免存储泄漏
        for orphan_key in uploaded_minio_keys:
            try:
                minio_client.delete_object(
                    bucket=EVIDENCE_MINIO_BUCKET,
                    object_key=orphan_key,
                )
                logger.warning(f"Cleaned orphan MinIO object: {orphan_key}")
            except Exception as cleanup_err:
                logger.error(f"Failed to clean orphan {orphan_key}: {cleanup_err}")
        raise  # 重新抛出原异常

    logger.info(f"Uploaded {len(uploaded)} files to evidence case {case_id}")
    return [_build_material_out(m) for m in uploaded]


@router.post("/cases/{case_id}/process", response_model=ProcessResponse)
@limiter.limit("5/minute")
async def start_process(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """一键处理：OCR + 分类 + 排序 → 生成清单"""
    if process_evidence_full is None:
        raise HTTPException(status_code=500, detail="Celery task dispatcher not available")

    case = await _get_case_or_404(case_id, db, tenant_id)

    # 检查是否有未处理的素材（pending 或 failed 状态）
    pending_stmt = select(func.count()).select_from(EvidenceMaterial).where(
        EvidenceMaterial.evidence_case_id == case_id,
        EvidenceMaterial.ocr_status.in_(("pending", "failed")),
    )
    pending_result = await db.execute(pending_stmt)
    pending_count = pending_result.scalar() or 0

    # 如果没有未处理的素材，且案件已完成目录生成，跳过处理
    if pending_count == 0 and case.status in ("catalog_ready", "analyzing", "exporting", "completed"):
        if case.status == "catalog_ready":
            return ProcessResponse(
                case_id=str(case_id),
                message="所有素材已完成处理，无需重新处理",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Cannot process case with status: {case.status}",
        )

    logger.info(f"Processing case {case_id}: {pending_count} materials pending OCR")

    try:
        task = process_evidence_full.delay(str(case_id))
    except Exception as e:
        logger.error(f"Failed to dispatch evidence process task for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch process task")

    return ProcessResponse(
        case_id=str(case_id),
        message=f"Processing started: {pending_count} materials queued for OCR → classify → catalog",
        task_id=task.id,
    )


@router.get("/cases/{case_id}/progress", response_model=ProgressResponse)
@limiter.limit("60/minute")
async def get_progress(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """处理进度"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    steps = case.steps or []
    completed_steps = sum(1 for s in steps if s.status == "completed")
    total_steps = max(len(steps), 1)

    current_step = None
    for s in steps:
        if s.status == "processing":
            current_step = s.step_name
            break

    # 计算整体进度
    status_progress_map = {
        "draft": 0.0,
        "uploading": 5.0,
        "processing": 30.0,
        "catalog_ready": 60.0,
        "analyzing": 75.0,
        "analysis_done": 90.0,
        "exporting": 95.0,
        "completed": 100.0,
        "failed": 0.0,
    }
    progress_percent = status_progress_map.get(case.status, 0.0)

    # ── 排队位置计算 ──
    queue_position = None
    if case.status == "processing":
        # 正在处理中，排队位置=0
        queue_position = 0
    elif case.status in ("pending", "uploading"):
        # 等待处理时，查询 Celery 队列中的排位
        try:
            from services.utils.task_concurrency import get_concurrent_count
            current_running = get_concurrent_count()
            if current_running < 0:
                queue_position = None  # Redis 不可用，无法判断
            elif current_running >= 3:  # _MAX_CONCURRENT_CASES
                queue_position = current_running  # 粗略估计：前面有N个在跑
            else:
                queue_position = 0  # 空闲，马上就能处理
        except Exception:
            queue_position = None

    return ProgressResponse(
        case_id=str(case_id),
        status=case.status,
        current_step=current_step,
        total_steps=total_steps,
        completed_steps=completed_steps,
        progress_percent=progress_percent,
        queue_position=queue_position,
        steps=[_build_step_out(s) for s in steps],
    )


@router.get("/cases/{case_id}/catalog", response_model=CatalogResponse)
@limiter.limit("60/minute")
async def get_catalog(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """获取证据材料清单"""
    from services.evidence.classifier import CATEGORY_NAMES

    case = await _get_case_or_404(case_id, db, tenant_id)
    catalog_data = case.catalog_data or {}

    groups = []
    for group in catalog_data.get("groups", []):
        category = group.get("category", "")
        # 获取该分组的材料详情
        mat_ids = [item.get("material_id") for item in group.get("items", [])]
        group_materials = []
        for mat in (case.materials or []):
            if str(mat.id) in mat_ids:
                group_materials.append(_build_material_out(mat))

        groups.append(CatalogGroupResponse(
            category=category,
            category_name=group.get("category_name", CATEGORY_NAMES.get(category, category)),
            items=group_materials,
        ))

    # 赔偿计算总额（第二步结果，优先于 OCR 提取的费用）
    compensation_total = None
    comp_data = case.compensation_data or {}
    if comp_data and comp_data.get("items"):
        try:
            compensation_total = float(str(comp_data.get("total_amount", 0)))
        except (ValueError, TypeError):
            compensation_total = None

    return CatalogResponse(
        case_id=str(case_id),
        case_name=case.case_name,
        case_type=case.case_type,
        groups=groups,
        fee_summary=catalog_data.get("fee_summary", {}),
        total_amount=catalog_data.get("total_amount", 0.0),
        compensation_total=compensation_total,
    )


@router.put("/cases/{case_id}/catalog", response_model=MessageResponse)
@limiter.limit("10/minute")
async def update_catalog(
    request: Request,
    case_id: uuid.UUID,
    body: UpdateCatalogRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """编辑清单（改分类/调序/改描述）"""
    await _check_case_exists(case_id, db, tenant_id)

    for item_update in body.items:
        try:
            mat_uuid = uuid.UUID(item_update.material_id)
        except ValueError:
            continue

        stmt = select(EvidenceMaterial).where(
            EvidenceMaterial.id == mat_uuid,
            EvidenceMaterial.evidence_case_id == case_id,
        )
        result = await db.execute(stmt)
        material = result.scalar_one_or_none()
        if not material:
            continue

        if item_update.manual_category is not None:
            material.manual_category = item_update.manual_category
            material.effective_category = item_update.manual_category
        if item_update.catalog_title is not None:
            material.catalog_title = item_update.catalog_title
        if item_update.catalog_description is not None:
            material.catalog_description = item_update.catalog_description
        if item_update.proof_purpose is not None:
            material.proof_purpose = item_update.proof_purpose
        if item_update.sort_order is not None:
            material.catalog_index = item_update.sort_order

    await db.flush()
    return MessageResponse(message="Catalog updated")


@router.put("/cases/{case_id}/materials/{material_id}", response_model=MaterialResponse)
@limiter.limit("10/minute")
async def update_material(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    body: UpdateMaterialRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """编辑材料分类/信息"""
    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    if body.manual_category is not None:
        material.manual_category = body.manual_category
        material.effective_category = body.manual_category
    if body.catalog_title is not None:
        material.catalog_title = body.catalog_title
    if body.catalog_description is not None:
        material.catalog_description = body.catalog_description
    if body.proof_purpose is not None:
        material.proof_purpose = body.proof_purpose
    if body.manual_edit is not None:
        material.manual_edit = body.manual_edit

    await db.flush()
    await db.refresh(material)
    return _build_material_out(material)


@router.delete("/cases/{case_id}/materials/{material_id}", response_model=MessageResponse)
@limiter.limit("10/minute")
async def delete_material(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """删除材料（同时清理 MinIO 文件）

    案件正在 processing 时禁止删除材料（会导致锁竞争），
    请先取消案件处理后再删除。
    """
    case = await _check_case_exists(case_id, db, tenant_id=tenant_id)

    # 状态保护
    ACTIVE_STATUSES = {"processing", "analyzing", "exporting"}
    if case.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"案件正在处理中（状态: {case.status}），无法删除材料。请先取消处理。",
        )

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # 清理 MinIO 存储文件
    try:
        from services.storage.minio_client import minio_client
        bucket = material.minio_bucket or EVIDENCE_MINIO_BUCKET
        key = material.minio_key
        if key:
            minio_client.delete_object(bucket, key)
            logger.info(f"Deleted MinIO object {bucket}/{key} for material {material_id}")
    except Exception as e:
        logger.warning(f"Failed to delete MinIO object for material {material_id}: {e}")

    await db.delete(material)
    await db.flush()
    logger.info(f"Deleted material {material_id} from case {case_id}")
    return MessageResponse(message="Material deleted")


@router.post("/cases/{case_id}/materials/{material_id}/retry-ocr", response_model=MessageResponse)
@limiter.limit("5/minute")
async def retry_material_ocr(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """重试单个素材的 OCR 识别"""
    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # 重置 OCR 状态为 pending，以便重新处理
    material.ocr_status = "pending"
    material.ocr_text = None
    material.ocr_result = {}
    material.auto_category = None
    material.effective_category = None
    material.category_confidence = None
    material.extracted_data = {}
    await db.flush()

    # 触发异步处理任务
    from worker.evidence_tasks import process_single_material_ocr
    task = process_single_material_ocr.delay(str(material_id))

    logger.info(f"Retrying OCR for material {material_id} from case {case_id}, task_id={task.id}")
    return MessageResponse(message=f"OCR 重试已启动，任务ID: {task.id}")


# ─── 多页文档页面预览与选择 ──────────────────────────────────────────────────

@router.get("/cases/{case_id}/materials/{material_id}/pages/preview")
@limiter.limit("30/minute")
async def preview_material_pages(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """预览多页文档的全部页面（缩略图）

    返回每页的 base64 JPEG 缩略图、页码和尺寸，
    用于人工或自动定位目标页。
    支持 PDF 格式；图片格式返回单页；DOCX 暂不支持。
    """
    import base64

    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # 从 MinIO 获取文件
    try:
        from services.storage.minio_client import minio_client
        file_bytes = minio_client.download_bytes(
            material.minio_bucket or EVIDENCE_MINIO_BUCKET,
            material.minio_key,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    pages: list[dict] = []

    if material.file_type == "pdf":
        import fitz
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                zoom = 0.3  # 缩略图 30% 缩放
                mat = fitz.Matrix(zoom, zoom)

                for i in range(len(doc)):
                    page = doc[i]
                    pix = page.get_pixmap(matrix=mat)
                    thumb_bytes = pix.tobytes("jpeg", jpg_quality=50)
                    b64 = base64.b64encode(thumb_bytes).decode("ascii")

                    pages.append({
                        "page": i + 1,
                        "width": pix.width,
                        "height": pix.height,
                        "thumbnail_b64": b64,
                    })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF rendering failed: {e}")

    elif material.file_type in ("image", "jpg", "jpeg", "png"):
        from PIL import Image as PILImage
        try:
            img = PILImage.open(io.BytesIO(file_bytes))
            # 缩略图
            img.thumbnail((300, 400), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            pages.append({
                "page": 1,
                "width": img.width,
                "height": img.height,
                "thumbnail_b64": b64,
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image processing failed: {e}")

    elif material.file_type in ("docx", "doc"):
        # DOCX 暂不支持预览
        pages.append({
            "page": 1,
            "width": 0,
            "height": 0,
            "thumbnail_b64": "",
            "note": "DOCX preview not yet supported",
        })
    else:
        pages.append({
            "page": 1,
            "width": 0,
            "height": 0,
            "thumbnail_b64": "",
            "note": "Unsupported file type for preview",
        })

    return {
        "material_id": str(material_id),
        "file_type": material.file_type,
        "total_pages": len(pages),
        "selected_pages": material.selected_pages or [],
        "pages": pages,
    }


@router.post("/cases/{case_id}/materials/{material_id}/pages/select")
@limiter.limit("30/minute")
async def select_material_pages(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    selected_pages: list[int] = Body(default=[], embed=True),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """选择多页文档中需要处理的目标页

    - 传入页码列表（1-based），例如 [1, 3, 5]
    - 空列表 [] 表示处理全部页面
    - 选择后，后续 OCR 和分析只处理选中页面
    """
    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # 验证页码范围
    max_page = material.page_count or 1
    for p in selected_pages:
        if p < 1 or p > max_page:
            raise HTTPException(
                status_code=400,
                detail=f"Page {p} out of range (1-{max_page})",
            )

    material.selected_pages = selected_pages
    await db.flush()

    return {
        "material_id": str(material_id),
        "selected_pages": selected_pages,
        "message": f"选定 {len(selected_pages)}/{max_page} 页" if selected_pages
                   else f"已重置为处理全部 {max_page} 页",
    }


@router.get("/cases/{case_id}/materials/{material_id}/pages/{page_num}/extract")
@limiter.limit("30/minute")
async def extract_material_page(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    page_num: int,
    dpi: int = Query(default=150, ge=72, le=300),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """提取指定页为高清图像

    返回该页的 JPEG 图像，用于独立 OCR 或人工审阅。
    """
    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    # 从 MinIO 获取文件
    try:
        from services.storage.minio_client import minio_client
        file_bytes = minio_client.download_bytes(
            material.minio_bucket or EVIDENCE_MINIO_BUCKET,
            material.minio_key,
        )
        logger.debug(f"Downloaded {len(file_bytes)} bytes from MinIO for extraction")
    except Exception as e:
        logger.error(f"MinIO download failed for extract: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    if material.file_type == "pdf":
        import fitz
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                max_page = len(doc)
                if page_num < 1 or page_num > max_page:
                    raise HTTPException(status_code=400, detail=f"Page {page_num} out of range (1-{max_page})")

                zoom = dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                page = doc[page_num - 1]
                pix = page.get_pixmap(matrix=mat)
                jpeg_bytes = pix.tobytes("jpeg", jpg_quality=85)
                logger.info(f"Extracted page {page_num} from {material.original_filename}: {len(jpeg_bytes)} bytes, {pix.width}x{pix.height}")

                return Response(
                    content=jpeg_bytes,
                    media_type="image/jpeg",
                    headers={
                        "Content-Disposition": f'inline; filename="page_{page_num}.jpg"',
                        "X-Page-Width": str(pix.width),
                        "X-Page-Height": str(pix.height),
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF extraction failed: {e}")

    elif material.file_type in ("image", "jpg", "jpeg", "png"):
        # 单页图片：返回原图
        return Response(
            content=file_bytes,
            media_type=f"image/{material.file_type}" if material.file_type != "image" else "image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="{material.original_filename}"',
            },
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {material.file_type}")


# ─── PDF 导出 ─────────────────────────────────────────────────────────────────
@router.get("/cases/{case_id}/catalog/pdf")
@limiter.limit("30/minute")
async def download_catalog_pdf(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """下载证据目录 PDF（表格形式）"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    catalog_data = case.catalog_data or {}
    if not catalog_data.get("groups"):
        raise HTTPException(status_code=400, detail="证据目录尚未生成")

    try:
        import asyncio
        from services.evidence.pdf_generator import generate_catalog_table_pdf

        pdf_bytes = await asyncio.to_thread(
            generate_catalog_table_pdf,
            case.case_name,
            case.case_type,
            catalog_data,
        )

    except Exception as e:
        logger.error(f"Failed to generate catalog table PDF for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate catalog table PDF")

    safe_filename = quote(f"证据目录_{case.case_name}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.get("/cases/{case_id}/materials/pdf")
@limiter.limit("10/minute")
async def download_materials_pdf(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """下载证据材料 PDF（图片网格排版，嵌入原始素材）"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 清除旧的 PDF 缓存（格式升级后强制重新生成）
    if case.catalog_pdf_path:
        old_pdf_path = case.catalog_pdf_path
        try:
            from services.storage.minio_client import minio_client
            minio_client.client.remove_object(
                bucket_name=EVIDENCE_MINIO_BUCKET,
                object_name=old_pdf_path,
            )
        except Exception:
            pass
        case.catalog_pdf_path = None
        await db.commit()

    try:
        import asyncio
        from services.evidence.pdf_generator import generate_catalog_pdf_inline
        from services.storage.minio_client import minio_client

        catalog_data = case.catalog_data or {}

        # 从数据库获取该案件的所有素材文件信息
        materials_result = await db.execute(
            select(EvidenceMaterial).where(
                EvidenceMaterial.evidence_case_id == case_id
            ).order_by(EvidenceMaterial.created_at)
        )
        materials = materials_result.scalars().all()

        # 从 MinIO 下载每个素材的原始文件
        material_files: dict[str, tuple[str, str, bytes]] = {}
        ocr_texts: dict[str, str] = {}  # 素材OCR文本，用于反向选页
        for mat in materials:
            try:
                file_bytes = minio_client.download_bytes(
                    bucket=mat.minio_bucket or EVIDENCE_MINIO_BUCKET,
                    object_key=mat.minio_key,
                )
                material_files[str(mat.id)] = (
                    mat.original_filename or "unknown",
                    mat.file_type or "unknown",
                    file_bytes,
                )
                # 收集OCR文本（扫描件PDF无原生文本层时用于位置估算）
                if mat.ocr_text:
                    ocr_texts[str(mat.id)] = mat.ocr_text
            except Exception as e:
                logger.warning(f"Failed to download material {mat.id}: {e}")

        pdf_bytes = await asyncio.to_thread(
            generate_catalog_pdf_inline,
            str(case_id),
            case.case_name,
            case.case_type,
            catalog_data,
            material_files,
            case.analysis_result,  # 传递分析结果用于反向选页
            ocr_texts,  # 传递OCR文本用于扫描件PDF位置估算
        )

        # 上传到 MinIO
        minio_key = f"evidence/{case_id}/{uuid.uuid4()}_证据材料.pdf"
        minio_client.upload_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=minio_key,
            data=pdf_bytes,
            content_type="application/pdf",
        )

        case.catalog_pdf_path = minio_key
        await db.commit()

    except Exception as e:
        logger.error(f"Failed to generate materials PDF for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate materials PDF")

    safe_filename = quote(f"证据材料_{case.case_name}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


# ─── Phase 2: 分析 → 导出 ───────────────────────────────────────────────────

@router.post("/cases/{case_id}/analyze", response_model=ProcessResponse)
@limiter.limit("5/minute")
async def start_analysis(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """分析清单 → 生成文档数据"""
    if analyze_evidence is None:
        raise HTTPException(status_code=500, detail="Celery task dispatcher not available")

    case = await _get_case_or_404(case_id, db, tenant_id)

    # 允许 failed 状态重新分析
    if case.status not in ("catalog_ready", "analysis_done", "failed"):
        if case.status == "analyzing":
            return ProcessResponse(
                case_id=str(case_id),
                message="Analysis already in progress",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Cannot analyze case with status: {case.status}. Need catalog_ready or retry failed.",
        )

    # failed 状态重新分析时，清理旧的分析步骤
    if case.status == "failed":
        from db.models_evidence import EvidenceStep
        from sqlalchemy import delete as sql_delete
        await db.execute(
            sql_delete(EvidenceStep).where(
                EvidenceStep.case_id == case_id,
                EvidenceStep.step_name.in_(("analysis", "analyze")),
            )
        )
        await db.flush()
        logger.info(f"Cleaned up old analysis steps for failed case {case_id}")

    # 重新分析时，清理旧的导出文件（基于旧分析结果生成的文档已过期）
    _cleanup_all_exports(case)

    try:
        task = analyze_evidence.delay(str(case_id))
    except Exception as e:
        logger.error(f"Failed to dispatch analysis task for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch analysis task")

    return ProcessResponse(
        case_id=str(case_id),
        message="Analysis started",
        task_id=task.id,
    )


@router.get("/cases/{case_id}/analysis", response_model=AnalysisResponse)
@limiter.limit("60/minute")
async def get_analysis(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """获取分析结果"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 如果分析失败，从 steps 中提取错误信息
    error_message = None
    if case.status == "failed":
        for step in (case.steps or []):
            if step.step_name == "analyze" and step.error_message:
                error_message = step.error_message
                break
        if not error_message:
            error_message = "分析任务执行失败，请检查材料完整性后重新分析。如问题持续，请尝试删除问题材料后重新上传"

    return AnalysisResponse(
        case_id=str(case_id),
        status=case.status,
        analysis_result=case.analysis_result,
        validation_result=case.validation_result,
        missing_items=case.missing_items,
        error_message=error_message,
    )


@router.get("/cases/{case_id}/export/filing-evidence")
@limiter.limit("10/minute")
async def export_filing_evidence(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出立案证据 Word"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 清理旧文件
    _cleanup_old_export(case, "立案证据.docx")

    try:
        from services.evidence.word_generator import generate_filing_evidence_inline_data
        catalog_data = case.catalog_data or {}
        analysis_result = copy.deepcopy(case.analysis_result or {})
        doc_bytes = generate_filing_evidence_inline_data(catalog_data, analysis_result)
        if not doc_bytes:
            raise ValueError("Generated document is empty")
    except Exception as e:
        logger.error(f"Failed to generate filing evidence for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    safe_filename = quote(f"立案证据_{case.case_name}.docx")
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.get("/cases/{case_id}/export/complaint")
@limiter.limit("10/minute")
async def export_complaint(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出民事起诉状 Word（纯数据驱动，无 event loop 冲突）"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    catalog_data = case.catalog_data or {}
    analysis_result = copy.deepcopy(case.analysis_result or {})
    lawyer_info = case.lawyer_info or []

    # 注入赔偿计算总额（供民事起诉状诉讼请求引用）
    compensation_data = case.compensation_data or {}
    if compensation_data.get("total_amount"):
        analysis_result["compensation_total_amount"] = compensation_data["total_amount"]

    # 校验：检查是否有LLM生成失败的段落（硬性阻断）
    from services.evidence.word_generator import validate_analysis_result, validate_required_fields
    failed_sections = validate_analysis_result(analysis_result)
    if failed_sections:
        raise HTTPException(
            status_code=422,
            detail=f"以下段落生成失败，请重新分析案件后再导出: {', '.join(failed_sections)}"
        )

    # 校验：检查必要字段（仅警告，不阻断导出 — 缺失字段在文档中用占位符代替）
    missing_fields = validate_required_fields(analysis_result)
    if missing_fields:
        logger.warning(
            f"Case {case_id}: exporting complaint with missing fields: {missing_fields}. "
            "Placeholders will be used in the document."
        )

    try:
        from services.evidence.word_generator import generate_complaint_inline_data
        doc_bytes = await asyncio.to_thread(
            generate_complaint_inline_data, catalog_data, analysis_result, lawyer_info
        )
        if not doc_bytes:
            raise HTTPException(status_code=500, detail="Failed to generate document")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate complaint for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    safe_filename = quote(f"民事起诉状_{case.case_name}.docx")
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.get("/cases/{case_id}/export/appraisal-app")
@limiter.limit("10/minute")
async def export_appraisal_app(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出司法鉴定申请书 Word"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 清理旧文件
    _cleanup_old_export(case, "司法鉴定申请书.docx")

    try:
        from services.evidence.word_generator import generate_appraisal_inline_data
        catalog_data = case.catalog_data or {}
        analysis_result = copy.deepcopy(case.analysis_result or {})
        doc_bytes = generate_appraisal_inline_data(catalog_data, analysis_result)
        if not doc_bytes:
            raise ValueError("Generated document is empty")
    except Exception as e:
        logger.error(f"Failed to generate appraisal application for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    safe_filename = quote(f"司法鉴定申请书_{case.case_name}.docx")
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.get("/cases/{case_id}/export/compensation")
@limiter.limit("10/minute")
async def export_compensation(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出赔偿费用总表 Excel"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 清理旧文件
    _cleanup_old_export(case, "赔偿费用清单.xlsx")

    try:
        from services.evidence.excel_generator import generate_compensation_inline_data
        catalog_data = case.catalog_data or {}
        analysis_result = copy.deepcopy(case.analysis_result or {})
        doc_bytes = generate_compensation_inline_data(catalog_data, analysis_result)
        if not doc_bytes:
            raise ValueError("Generated document is empty")
    except Exception as e:
        logger.error(f"Failed to generate compensation summary for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    safe_filename = quote(f"赔偿费用清单_{case.case_name}.xlsx")
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.get("/cases/{case_id}/export/compensation/{fee_type}")
@limiter.limit("10/minute")
async def export_fee_detail(
    request: Request,
    case_id: uuid.UUID,
    fee_type: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出单项费用明细 Excel"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    try:
        from services.evidence.excel_generator import generate_fee_type_detail
        doc_key = generate_fee_type_detail(str(case_id), fee_type)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate fee detail for case {case_id} type={fee_type}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    try:
        from services.storage.minio_client import minio_client
        data = minio_client.download_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=doc_key,
        )
    except Exception as e:
        logger.error(f"Failed to download fee detail for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document")

    safe_filename = quote(f"{fee_type}_{case.case_name}.xlsx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


@router.post("/cases/{case_id}/export/bundle", response_model=ExportBundleResponse)
@limiter.limit("3/minute")
async def create_bundle(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """全部打包 ZIP"""
    if export_evidence_bundle is None:
        raise HTTPException(status_code=500, detail="Celery task dispatcher not available")

    case = await _get_case_or_404(case_id, db, tenant_id)

    if case.status not in ("analysis_done", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export bundle for case with status: {case.status}. Need analysis_done.",
        )

    try:
        task = export_evidence_bundle.delay(str(case_id))
    except Exception as e:
        logger.error(f"Failed to dispatch bundle export for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch export task")

    return ExportBundleResponse(
        case_id=str(case_id),
        message="Bundle export started",
        bundle_path=None,
    )


@router.get("/cases/{case_id}/export/bundle/download")
@limiter.limit("10/minute")
async def download_bundle(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """下载打包好的 ZIP 文件

    如果已有 bundle_path（之前打包过），直接下载；
    否则在当前 async 上下文中获取数据，同步生成文档后打包下载。
    """
    case = await _get_case_or_404(case_id, db, tenant_id)

    if case.status not in ("analysis_done", "completed", "exporting"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot download bundle for case with status: {case.status}. Need analysis_done.",
        )

    # 如果已有打包好的 ZIP，直接下载
    bundle_key = case.export_bundle_path
    if bundle_key:
        try:
            from services.storage.minio_client import minio_client
            data = minio_client.download_bytes(
                bucket=EVIDENCE_MINIO_BUCKET,
                object_key=bundle_key,
            )
            safe_filename = quote(f"{case.case_name or '案件'}立案立档包.zip")
            return Response(
                content=data,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
                },
            )
        except Exception as e:
            logger.warning(f"Cached bundle not found, regenerating: {e}")

    # ---- 实时生成打包 ----
    import asyncio as _aio
    import zipfile as _zf

    case_name = case.case_name or "案件"
    folder_name = f"{case_name}立案立档包"
    catalog_data = case.catalog_data or {}
    analysis_result = copy.deepcopy(case.analysis_result or {})
    lawyer_info = case.lawyer_info or []
    export_files: dict[str, bytes] = {}

    # 注入赔偿计算总额（供民事起诉状诉讼请求引用）
    compensation_data = case.compensation_data or {}
    if compensation_data.get("total_amount"):
        analysis_result["compensation_total_amount"] = compensation_data["total_amount"]

    # 校验：确保目录和分析结果已生成
    if not catalog_data or not catalog_data.get("groups"):
        raise HTTPException(
            status_code=422,
            detail="证据目录尚未生成，请先完成素材处理（OCR + 分类）后再导出"
        )
    if not analysis_result:
        raise HTTPException(
            status_code=422,
            detail="智能分析尚未完成，请先完成分析后再导出"
        )

    # 校验：检查是否有LLM生成失败的段落（影响起诉状质量）
    from services.evidence.word_generator import validate_analysis_result
    failed_sections = validate_analysis_result(analysis_result)
    if failed_sections:
        raise HTTPException(
            status_code=422,
            detail=f"以下段落生成失败，请重新分析案件后再导出: {', '.join(failed_sections)}"
        )

    # 同步生成函数（纯 CPU 操作，无 DB 调用）
    def _generate_all_docs():
        from services.evidence.word_generator import (
            generate_filing_evidence_inline_data,
            generate_complaint_inline_data,
            generate_appraisal_inline_data,
        )
        from services.evidence.excel_generator import (
            generate_compensation_inline_data,
            generate_fee_details_inline_data,
        )
        files = {}
        failures = []
        # 1. 立案证据
        try:
            b = generate_filing_evidence_inline_data(catalog_data, analysis_result)
            if b:
                files["01_立案证据.docx"] = b
        except Exception as e:
            logger.error(f"Failed to generate filing evidence: {e}")
            failures.append(f"立案证据: {e}")
        # 2. 民事起诉状
        try:
            b = generate_complaint_inline_data(catalog_data, analysis_result, lawyer_info=lawyer_info)
            if b:
                files["02_民事起诉状.docx"] = b
        except Exception as e:
            logger.error(f"Failed to generate complaint: {e}")
            failures.append(f"民事起诉状: {e}")
        # 3. 司法鉴定申请书
        try:
            b = generate_appraisal_inline_data(catalog_data, analysis_result)
            if b:
                files["03_司法鉴定申请书.docx"] = b
        except Exception as e:
            logger.error(f"Failed to generate appraisal: {e}")
            failures.append(f"司法鉴定申请书: {e}")
        # 4. 赔偿费用清单（始终生成，无数据时出空模板）
        try:
            from services.evidence.excel_generator import generate_compensation_calculation_excel
            b = generate_compensation_calculation_excel(
                compensation_data,  # 可为空，函数内部会生成模板
                case_name or "",
                analysis_result.get("plaintiff_name", ""),
                case.case_type or "injury",
            )
            if b:
                files["04_赔偿费用清单.xlsx"] = b
        except Exception as e:
            logger.error(f"Failed to generate compensation: {e}")
            failures.append(f"赔偿费用清单: {e}")
        # 5. 医疗费用汇总表（按医院分组）
        try:
            details = generate_fee_details_inline_data(catalog_data, analysis_result)
            for sheet_name, fb in details.items():
                safe_name = sheet_name.replace("/", "_").replace("\\", "_")
                files[f"05_{safe_name}.xlsx"] = fb
        except Exception as e:
            logger.error(f"Failed to generate fee details: {e}")
            failures.append(f"费用明细: {e}")

        # 如果有失败的文档，生成报告
        if failures:
            report = f"打包生成报告\n{'='*40}\n\n"
            report += f"成功: {len(files)} 个文件\n"
            report += f"失败: {len(failures)} 个文件\n\n"
            report += "失败详情:\n"
            for f in failures:
                report += f"  - {f}\n"
            report += f"\n建议: 请检查案件数据完整性后重新打包\n"
            files["_生成报告.txt"] = report.encode("utf-8")

        return files

    # 在线程池中执行同步文件生成
    try:
        export_files = await _aio.to_thread(_generate_all_docs)
    except Exception as e:
        logger.error(f"Failed to generate docs for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate documents")

    # 6. 证据目录 PDF
    try:
        from services.evidence.pdf_generator import generate_catalog_table_pdf
        catalog_pdf_bytes = await _aio.to_thread(
            generate_catalog_table_pdf,
            case.case_name,
            case.case_type,
            catalog_data,
        )
        if catalog_pdf_bytes:
            export_files["06_证据目录.pdf"] = catalog_pdf_bytes
    except Exception as e:
        logger.error(f"Failed to generate catalog table PDF: {e}")

    # 7. 证据材料 PDF（需要从MinIO下载素材文件）
    try:
        from services.evidence.pdf_generator import generate_catalog_pdf_inline
        from services.storage.minio_client import minio_client as _mc

        # 获取所有素材
        materials_result = await db.execute(
            select(EvidenceMaterial).where(
                EvidenceMaterial.evidence_case_id == case_id
            ).order_by(EvidenceMaterial.created_at)
        )
        materials = materials_result.scalars().all()

        # 从MinIO下载素材文件
        material_files: dict[str, tuple[str, str, bytes]] = {}
        ocr_texts: dict[str, str] = {}
        for mat in materials:
            try:
                file_bytes = _mc.download_bytes(
                    bucket=mat.minio_bucket or EVIDENCE_MINIO_BUCKET,
                    object_key=mat.minio_key,
                )
                material_files[str(mat.id)] = (
                    mat.original_filename or "unknown",
                    mat.file_type or "unknown",
                    file_bytes,
                )
                if mat.ocr_text:
                    ocr_texts[str(mat.id)] = mat.ocr_text
            except Exception as e:
                logger.warning(f"Failed to download material {mat.id} for bundle: {e}")

        if material_files:
            materials_pdf_bytes = await _aio.to_thread(
                generate_catalog_pdf_inline,
                str(case_id),
                case.case_name,
                case.case_type,
                catalog_data,
                material_files,
                case.analysis_result,
                ocr_texts,
            )
            if materials_pdf_bytes:
                export_files["07_证据材料.pdf"] = materials_pdf_bytes
    except Exception as e:
        logger.error(f"Failed to generate materials PDF for bundle: {e}")

    if not export_files:
        raise HTTPException(status_code=500, detail="No documents generated")

    # 打包 ZIP
    zip_buffer = io.BytesIO()
    with _zf.ZipFile(zip_buffer, "w", _zf.ZIP_DEFLATED) as zf:
        for arc_name, file_bytes in export_files.items():
            zf.writestr(f"{folder_name}/{arc_name}", file_bytes)

    zip_bytes = zip_buffer.getvalue()

    # 上传到 MinIO 缓存
    try:
        from services.storage.minio_client import minio_client
        # 清理旧的 bundle ZIP
        if case.export_bundle_path:
            try:
                minio_client.delete_object(EVIDENCE_MINIO_BUCKET, case.export_bundle_path)
            except Exception:
                pass

        minio_key = f"evidence/{case_id}/{uuid.uuid4()}_{folder_name}.zip"
        minio_client.upload_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=minio_key,
            data=zip_bytes,
            content_type="application/zip",
        )
        # 更新数据库缓存路径
        case.export_bundle_path = minio_key
        case.export_files = {k: "" for k in export_files}
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to cache bundle to MinIO: {e}")

    safe_filename = quote(f"{case_name}立案立档包.zip")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )


# ─── 赔偿计算 API ────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/compensation/calculate")
@limiter.limit("5/minute")
async def calculate_compensation(
    request: Request,
    case_id: uuid.UUID,
    req: Optional[CompensationCalculateRequest] = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """自动提取 + 计算赔偿费用"""
    from services.evidence.compensation_calculator import calculate_all, merge_params
    from services.evidence.compensation_extractor import extract_from_materials

    case = await _get_case_or_404(case_id, db, tenant_id)

    # 获取素材
    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.evidence_case_id == case_id
    )
    result = await db.execute(stmt)
    materials = result.scalars().all()

    # 从 OCR 提取费用
    fee_items, stay_info = extract_from_materials(materials)

    # 合并参数
    user_params: dict = {}
    if req and req.params:
        user_params = {k: v for k, v in req.params.model_dump().items() if v is not None}

    if stay_info.days > 0 and "hospital_days" not in user_params:
        user_params["hospital_days"] = stay_info.days

    params = merge_params(user_params, hospital_days=stay_info.days)

    # 计算
    # 兼容旧的 neonatal 类型
    case_type = case.case_type
    if case_type == "neonatal":
        case_type = "injury"

    result_data = calculate_all(case_type, params, fee_items)

    # 保存
    case.compensation_data = result_data
    await db.commit()

    return {"case_id": str(case_id), **result_data}


@router.get("/cases/{case_id}/compensation")
@limiter.limit("30/minute")
async def get_compensation(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """获取赔偿计算结果"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 获取 fee_receipt 类素材列表
    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.evidence_case_id == case_id,
        EvidenceMaterial.effective_category.in_(['fee_receipt', 'invoice', 'receipt']),
    )
    result = await db.execute(stmt)
    materials = result.scalars().all()

    fee_materials = [
        {
            "id": str(m.id),
            "filename": m.original_filename,
            "category": m.effective_category,
            "ocr_status": m.ocr_status,
        }
        for m in materials
    ]

    return {
        "case_id": str(case_id),
        "compensation_data": case.compensation_data or {},
        "fee_materials": fee_materials,
    }


@router.put("/cases/{case_id}/compensation")
@limiter.limit("10/minute")
async def update_compensation(
    request: Request,
    case_id: uuid.UUID,
    req: CompensationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """保存手动调整的赔偿数据"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 深拷贝，确保 SQLAlchemy 检测到 JSONB 变更（原地修改不触发脏标记）
    import copy
    data = copy.deepcopy(case.compensation_data or {})
    items = data.get("items", [])

    # 更新手动金额（存为数字而非字符串，避免前端类型混乱）
    update_map = {u.fee_type: u.manual_amount for u in req.items}
    for item in items:
        if item["fee_type"] in update_map:
            new_amount = update_map[item["fee_type"]]
            item["manual_amount"] = float(new_amount) if new_amount is not None else None

    # 更新参数
    if req.params:
        params = data.get("params", {})
        for k, v in req.params.model_dump().items():
            if v is not None:
                params[k] = str(v) if isinstance(v, Decimal) else v
        data["params"] = params

    # 重算合计（如有手动设置的总计则优先使用）
    if req.manual_total is not None:
        data["total_amount"] = float(req.manual_total)
        data["manual_total"] = float(req.manual_total)
    else:
        total = Decimal("0")
        for item in items:
            # dependent_living 不计入合计（已包含在残疾/死亡赔偿金中）
            if item.get("fee_type") == "dependent_living":
                continue
            amt = item.get("manual_amount") or item.get("amount", 0)
            total += Decimal(str(amt))
        data["total_amount"] = float(total)

    case.compensation_data = data
    await db.commit()

    return {"case_id": str(case_id), **data}


@router.get("/cases/{case_id}/compensation/export")
@limiter.limit("10/minute")
async def export_compensation_calculation(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """导出赔偿计算 Excel（无数据时生成空模板）"""
    case = await _get_case_or_404(case_id, db, tenant_id)

    # 不再强制要求有计算数据，无数据时生成模板（金额留白）
    try:
        from services.evidence.excel_generator import generate_compensation_calculation_excel
        analysis_result = copy.deepcopy(case.analysis_result or {})
        excel_bytes = await asyncio.to_thread(
            generate_compensation_calculation_excel,
            case.compensation_data,  # 可为 None/空
            case.case_name or "",
            analysis_result.get("plaintiff_name", ""),
            case.case_type or "injury",
        )
    except Exception as e:
        logger.error(f"Failed to generate compensation calculation Excel for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate document")

    filename = quote(f"赔偿费用清单_{case.case_name}.xlsx")
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
