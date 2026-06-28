"""
步骤0 · API 路由
================
prefix=/evidence，所有端点用 get_tenant_filter 做租户隔离、limiter 限流
"""
from __future__ import annotations

import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_tenant_filter
from api.rate_limit import limiter
from api.schemas.common import MessageResponse
from api.schemas.step0 import (
    Step0CorrectRequest,
    Step0MaterialOut,
    Step0PreprocessResponse,
    Step0ProgressResponse,
    Step0SkipResponse,
    Step0SummaryResponse,
    Step0UploadResponse,
)
from db.models_evidence import EvidenceCase, EvidenceMaterial
from db.session import get_db
from services.evidence.step0_constants import get_fee_cn_name, validate_fee_category
from services.evidence.step0_service import (
    EVIDENCE_MINIO_BUCKET,
    correct_category,
    get_category_summary,
    get_preprocess_progress,
    get_step0_materials,
    skip_step0,
    upload_raw_materials,
)
from sqlalchemy import select

router = APIRouter(prefix="/evidence")

# 允许的文件扩展名和大小
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _build_step0_material_out(m: EvidenceMaterial) -> Step0MaterialOut:
    """构建步骤0 素材响应"""
    md = m.metadata_ or {}
    fee_cat = md.get("step0_fee_category")
    return Step0MaterialOut(
        id=str(m.id),
        original_filename=m.original_filename,
        file_type=m.file_type,
        file_size=m.file_size,
        ocr_status=m.ocr_status,
        ocr_text=m.ocr_text,
        auto_category=m.auto_category,
        manual_category=m.manual_category,
        effective_category=m.effective_category,
        category_confidence=m.category_confidence,
        step0_fee_category=fee_cat,
        step0_fee_category_cn=get_fee_cn_name(fee_cat) if fee_cat else None,
        step0_page_number=md.get("step0_page_number"),
        step0_parent_material_id=md.get("step0_parent_material_id"),
        step0_corrected=md.get("step0_corrected", False),
        step0_needs_review=md.get("step0_needs_review", False),
        step0_archived_key=md.get("step0_archived_key"),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


async def _check_case_exists(
    case_id: uuid.UUID,
    db: AsyncSession,
    tenant_id: uuid.UUID | None = None,
) -> EvidenceCase:
    """检查案件是否存在且租户匹配"""
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


def _validate_file(filename: str, file_size: int) -> str:
    """校验文件扩展名和大小，返回 file_type"""
    import os
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {filename}（仅支持 jpg/png/pdf）",
        )
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大: {filename}（最大允许 50 MB）",
        )
    return "pdf" if ext == ".pdf" else "image"


# ─── 路由 ────────────────────────────────────────────────────────────────────

@router.post(
    "/cases/{case_id}/step0/upload",
    response_model=Step0UploadResponse,
    status_code=201,
)
@limiter.limit("10/minute")
async def step0_upload(
    request: Request,
    case_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 上传原始素材"""
    await _check_case_exists(case_id, db, tenant_id)

    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    # 预校验
    for f in files:
        if f.size and f.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"文件过大: {f.filename}（最大允许 50 MB）",
            )
        import os
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {f.filename}（仅支持 jpg/png/pdf）",
            )

    try:
        materials = await upload_raw_materials(case_id, files, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"step0 upload failed: {e}")
        raise HTTPException(status_code=500, detail="上传失败")

    return Step0UploadResponse(
        case_id=str(case_id),
        uploaded_count=len(materials),
        materials=[_build_step0_material_out(m) for m in materials],
    )


@router.post(
    "/cases/{case_id}/step0/preprocess",
    response_model=Step0PreprocessResponse,
)
@limiter.limit("5/minute")
async def step0_start_preprocess(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 启动预处理（Celery 异步）"""
    await _check_case_exists(case_id, db, tenant_id)

    try:
        from worker.step0_tasks import process_step0_preprocess
    except ImportError:
        raise HTTPException(status_code=500, detail="Celery task not available")

    try:
        task = process_step0_preprocess.delay(str(case_id))
    except Exception as e:
        logger.error(f"step0 preprocess dispatch failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch preprocess task")

    return Step0PreprocessResponse(
        case_id=str(case_id),
        message="预处理已启动",
        task_id=task.id,
    )


@router.get(
    "/cases/{case_id}/step0/progress",
    response_model=Step0ProgressResponse,
)
@limiter.limit("60/minute")
async def step0_get_progress(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 获取预处理进度"""
    await _check_case_exists(case_id, db, tenant_id)

    progress = await get_preprocess_progress(case_id, db)
    return Step0ProgressResponse(
        case_id=str(case_id),
        total=progress["total"],
        processed=progress["processed"],
        failed=progress["failed"],
        pending=progress["pending"],
        progress_percent=progress["progress_percent"],
        step0_status=progress["step0_status"],
        category_summary=progress["category_summary"],
    )


@router.get(
    "/cases/{case_id}/step0/materials",
    response_model=list[Step0MaterialOut],
)
@limiter.limit("60/minute")
async def step0_get_materials(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 获取步骤0 产出的素材列表"""
    await _check_case_exists(case_id, db, tenant_id)

    materials = await get_step0_materials(case_id, db)
    return [_build_step0_material_out(m) for m in materials]


@router.put(
    "/cases/{case_id}/step0/materials/{material_id}/category",
    response_model=Step0MaterialOut,
)
@limiter.limit("10/minute")
async def step0_correct_category(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    body: Step0CorrectRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 手动纠正素材分类"""
    await _check_case_exists(case_id, db, tenant_id)

    if not validate_fee_category(body.new_category):
        raise HTTPException(
            status_code=400,
            detail=f"无效的费用类别: {body.new_category}",
        )

    try:
        material = await correct_category(material_id, body.new_category, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"step0 correct_category failed: {e}")
        raise HTTPException(status_code=500, detail="纠正分类失败")

    return _build_step0_material_out(material)


@router.post(
    "/cases/{case_id}/step0/skip",
    response_model=Step0SkipResponse,
)
@limiter.limit("5/minute")
async def step0_skip(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 跳过预处理"""
    await _check_case_exists(case_id, db, tenant_id)

    await skip_step0(case_id, db)
    return Step0SkipResponse(
        case_id=str(case_id),
        message="已跳过步骤0",
    )


@router.get(
    "/cases/{case_id}/step0/summary",
    response_model=Step0SummaryResponse,
)
@limiter.limit("60/minute")
async def step0_get_summary(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 分类汇总"""
    await _check_case_exists(case_id, db, tenant_id)

    summary = await get_category_summary(case_id, db)

    # 构建详细列表
    category_detail: list[dict[str, Any]] = []
    for cat_key, count in sorted(summary.items()):
        category_detail.append({
            "category": cat_key,
            "category_cn": get_fee_cn_name(cat_key),
            "count": count,
        })

    return Step0SummaryResponse(
        case_id=str(case_id),
        category_summary=summary,
        category_detail=category_detail,
    )


@router.get(
    "/cases/{case_id}/step0/materials/{material_id}/thumbnail",
)
@limiter.limit("60/minute")
async def step0_get_thumbnail(
    request: Request,
    case_id: uuid.UUID,
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID | None = Depends(get_tenant_filter),
):
    """步骤0 — 获取素材缩略图（返回 image/jpeg）"""
    await _check_case_exists(case_id, db, tenant_id)

    stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.id == material_id,
        EvidenceMaterial.evidence_case_id == case_id,
    )
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    from services.storage.minio_client import minio_client

    # 优先使用归档后的 key，其次 raw key
    archive_key = (material.metadata_ or {}).get("step0_archived_key")
    raw_key = (material.metadata_ or {}).get("step0_raw_key") or material.minio_key
    download_key = archive_key or raw_key

    if not download_key:
        raise HTTPException(status_code=404, detail="No file available for thumbnail")

    try:
        file_bytes = minio_client.download_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=download_key,
        )
    except Exception as e:
        logger.error(f"step0 thumbnail download failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to download file")

    # 生成缩略图
    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(file_bytes))
        img.thumbnail((300, 400), PILImage.LANCZOS)
        buf = io.BytesIO()
        # 统一转 JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=70)
        thumb_bytes = buf.getvalue()
    except Exception as e:
        logger.warning(f"step0 thumbnail generation failed, returning raw: {e}")
        thumb_bytes = file_bytes

    return Response(
        content=thumb_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )
