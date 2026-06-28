"""
步骤0 · 原始素材预处理 — Service 层
====================================
核心业务逻辑：上传原始素材 → OCR → LLM分类 → 归档 → PDF拆分 → 手动纠正

⚠️ 铁律：
1. JSONB 深拷贝：修改 metadata_ 必须 copy.deepcopy，禁止原地 .update()
2. flush() 后显式 commit()
3. MinIO bucket 统一用 EVIDENCE_MINIO_BUCKET = "scan-result"
4. 追加不重排：新类别序号=已有数+1，旧类别不重排
"""
from __future__ import annotations

import copy
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models_evidence import EvidenceCase, EvidenceMaterial
from services.evidence.step0_constants import (
    STEP0_CONFIDENCE_THRESHOLD,
    STEP0_FEE_CATEGORIES,
    STEP0_STATUS_COMPLETED,
    STEP0_STATUS_IN_PROGRESS,
    STEP0_STATUS_NOT_STARTED,
    STEP0_STATUS_SKIPPED,
    get_fee_cn_name,
    validate_fee_category,
)

EVIDENCE_MINIO_BUCKET = "scan-result"

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 上传原始素材
# ═══════════════════════════════════════════════════════════════════════════════

async def upload_raw_materials(
    case_id: uuid.UUID,
    files: list[UploadFile],
    tenant_id: Optional[uuid.UUID],
    db: AsyncSession,
) -> list[EvidenceMaterial]:
    """上传原始素材到 MinIO raw/ 目录，创建 EvidenceMaterial 记录

    每个 material 标记：
    - ocr_status='pending'
    - metadata_.source='step0_preprocess'
    - metadata_.step0_raw_key=原始 MinIO key
    - metadata_.step0_page_number=None
    - metadata_.step0_parent_material_id=None
    - metadata_.step0_corrected=False
    - metadata_.step0_needs_review=False
    """
    from services.storage.minio_client import minio_client

    created_materials: list[EvidenceMaterial] = []

    for file in files:
        # 文件大小校验
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(
                f"文件过大: {file.filename}（最大允许 {MAX_FILE_SIZE // (1024 * 1024)} MB）"
            )

        original_filename = file.filename or "upload"
        ext = _get_extension(original_filename)
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"不支持的文件类型: {original_filename}（仅支持 jpg/png/pdf）"
            )

        file_type = "pdf" if ext == ".pdf" else "image"

        # MinIO 存储路径: evidence/{case_id}/preprocess/raw/{uuid}_{原名}
        raw_key = f"evidence/{case_id}/preprocess/raw/{uuid.uuid4()}_{quote(original_filename)}"
        content_type = file.content_type or "application/octet-stream"

        minio_client.upload_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=raw_key,
            data=content,
            content_type=content_type,
        )

        # 深拷贝 metadata_
        md: dict[str, Any] = {
            "source": "step0_preprocess",
            "step0_fee_category": None,
            "step0_raw_key": raw_key,
            "step0_archived_key": None,
            "step0_page_number": None,
            "step0_parent_material_id": None,
            "step0_corrected": False,
            "step0_needs_review": False,
        }

        material = EvidenceMaterial(
            evidence_case_id=case_id,
            original_filename=original_filename,
            file_type=file_type,
            minio_bucket=EVIDENCE_MINIO_BUCKET,
            minio_key=raw_key,
            file_size=len(content),
            ocr_status="pending",
            metadata_=md,
        )
        db.add(material)
        await db.flush()
        await db.refresh(material)
        created_materials.append(material)

    await db.commit()
    logger.info(f"step0: uploaded {len(created_materials)} raw materials for case {case_id}")

    # 更新 case step0 状态
    await _update_case_step0_status(case_id, STEP0_STATUS_NOT_STARTED, db, total_raw=len(created_materials))

    return created_materials


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 序号生成
# ═══════════════════════════════════════════════════════════════════════════════

async def _generate_seq(
    case_id: uuid.UUID,
    category_cn: str,
    db: AsyncSession,
) -> int:
    """查询该 case 下该类别已归档 material 数量 +1（追加不重排）"""
    stmt = select(func.count(EvidenceMaterial.id)).where(
        EvidenceMaterial.evidence_case_id == case_id,
        EvidenceMaterial.minio_bucket == EVIDENCE_MINIO_BUCKET,
    )
    result = await db.execute(stmt)
    count = result.scalar() or 0

    # 筛选 metadata_.step0_fee_category 对应中文名匹配的已归档 material
    # 由于 JSONB 查询复杂，这里用 Python 过滤
    all_materials_stmt = select(EvidenceMaterial).where(
        EvidenceMaterial.evidence_case_id == case_id,
    )
    all_result = await db.execute(all_materials_stmt)
    all_mats = all_result.scalars().all()

    seq = 0
    for mat in all_mats:
        mat_md = mat.metadata_ or {}
        if mat_md.get("source") != "step0_preprocess":
            continue
        mat_category = mat_md.get("step0_fee_category")
        if mat_category and get_fee_cn_name(mat_category) == category_cn:
            if mat_md.get("step0_archived_key"):
                seq += 1

    return seq + 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 构建 MinIO 归档路径
# ═══════════════════════════════════════════════════════════════════════════════

def _build_archive_key(
    case_id: uuid.UUID,
    category_cn: str,
    seq: int,
    ext: str,
    page: Optional[int] = None,
) -> str:
    """组装归档路径

    图片/单页: evidence/{case_id}/preprocess/{类别名}/{类别名}{序号}.{ext}
    PDF拆分单页: evidence/{case_id}/preprocess/{类别名}/{类别名}{序号}_{页码}.jpg
    """
    if page is not None:
        return f"evidence/{case_id}/preprocess/{category_cn}/{category_cn}{seq}_{page}.jpg"
    return f"evidence/{case_id}/preprocess/{category_cn}/{category_cn}{seq}{ext}"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 归档单个素材
# ═══════════════════════════════════════════════════════════════════════════════

async def _archive_material(
    material: EvidenceMaterial,
    category: str,
    confidence: float,
    db: AsyncSession,
    file_bytes: Optional[bytes] = None,
    page: Optional[int] = None,
) -> None:
    """归档单个素材：生成序号 → 构建新key → MinIO 上传 → 更新 DB

    Args:
        material: 要归档的 EvidenceMaterial（如果是 PDF 子页，这是新创建的子 material）
        category: fee_xxx category key
        confidence: LLM 分类置信度
        db: AsyncSession
        file_bytes: 已下载的文件字节（PDF子页直接传入渲染后的JPEG，避免重复下载）
        page: PDF 拆分页码（非PDF为 None）
    """
    from services.storage.minio_client import minio_client

    case_id = material.evidence_case_id
    category_cn = get_fee_cn_name(category)
    ext = _get_extension(material.original_filename or ".jpg")

    # PDF 拆分页统一用 .jpg
    if page is not None:
        ext = ".jpg"

    seq = await _generate_seq(case_id, category_cn, db)
    archive_key = _build_archive_key(case_id, category_cn, seq, ext, page)

    # 获取文件字节
    if file_bytes is None:
        # 从 MinIO 下载原始文件
        raw_key = (material.metadata_ or {}).get("step0_raw_key") or material.minio_key
        file_bytes = minio_client.download_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=raw_key,
        )

    # 上传到归档路径
    content_type = "image/jpeg" if ext in (".jpg", ".jpeg") or page is not None else "image/png"
    minio_client.upload_bytes(
        bucket=EVIDENCE_MINIO_BUCKET,
        object_key=archive_key,
        data=file_bytes,
        content_type=content_type,
    )

    # 深拷贝 metadata_ 更新
    md = copy.deepcopy(material.metadata_ or {})
    md["step0_fee_category"] = category
    md["step0_archived_key"] = archive_key
    if page is not None:
        md["step0_page_number"] = page
    md["step0_needs_review"] = confidence < STEP0_CONFIDENCE_THRESHOLD

    material.metadata_ = md
    material.auto_category = category
    material.effective_category = category
    material.category_confidence = confidence
    material.ocr_status = "completed"

    await db.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PDF 拆分归档
# ═══════════════════════════════════════════════════════════════════════════════

async def _split_pdf_and_archive(
    parent_material: EvidenceMaterial,
    file_bytes: bytes,
    category: str,
    confidence: float,
    db: AsyncSession,
) -> None:
    """PDF 逐页渲染为 JPG → 每页独立 OCR + 分类 + 归档

    母 material 标记 ocr_status='completed' 但 minio_key 保持指向 raw 原始 PDF。
    每页创建独立子 material（metadata_.step0_page_number, metadata_.step0_parent_material_id）。
    """
    import fitz

    case_id = parent_material.evidence_case_id
    category_cn = get_fee_cn_name(category)

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"step0: Failed to open PDF {parent_material.original_filename}: {e}")
        md = copy.deepcopy(parent_material.metadata_ or {})
        parent_material.metadata_ = md
        parent_material.ocr_status = "failed"
        await db.flush()
        return

    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        try:
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=mat)
            page_jpeg_bytes = pix.tobytes("jpeg", jpg_quality=85)
        except Exception as e:
            logger.error(f"step0: Failed to render page {page_num} of PDF {parent_material.original_filename}: {e}")
            continue

        # 创建子 material
        child_md: dict[str, Any] = {
            "source": "step0_preprocess",
            "step0_fee_category": category,
            "step0_raw_key": (parent_material.metadata_ or {}).get("step0_raw_key") or parent_material.minio_key,
            "step0_archived_key": None,
            "step0_page_number": page_num,
            "step0_parent_material_id": str(parent_material.id),
            "step0_corrected": False,
            "step0_needs_review": confidence < STEP0_CONFIDENCE_THRESHOLD,
        }

        child_material = EvidenceMaterial(
            evidence_case_id=case_id,
            original_filename=f"{parent_material.original_filename}_p{page_num}.jpg",
            file_type="image",
            minio_bucket=EVIDENCE_MINIO_BUCKET,
            minio_key=None,  # 将在 _archive_material 中设置
            file_size=len(page_jpeg_bytes),
            ocr_status="completed",
            metadata_=child_md,
        )
        db.add(child_material)
        await db.flush()
        await db.refresh(child_material)

        # 归档子 material（直接传入渲染后的 JPEG 字节）
        await _archive_material(
            material=child_material,
            category=category,
            confidence=confidence,
            db=db,
            file_bytes=page_jpeg_bytes,
            page=page_num,
        )

    total_pages = len(doc)
    doc.close()

    # 母 material 标记 ocr_status='completed' 但 minio_key 不变（保留 raw PDF）
    parent_md = copy.deepcopy(parent_material.metadata_ or {})
    parent_md["step0_fee_category"] = category
    parent_material.auto_category = category
    parent_material.effective_category = category
    parent_material.category_confidence = confidence
    parent_material.ocr_status = "completed"
    parent_material.page_count = total_pages
    parent_material.metadata_ = parent_md

    await db.flush()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 手动纠正分类
# ═══════════════════════════════════════════════════════════════════════════════

async def correct_category(
    material_id: uuid.UUID,
    new_category: str,
    db: AsyncSession,
) -> EvidenceMaterial:
    """手动纠正素材的类别

    追加不重排：新类别序号=已有数+1，旧类别不重排。
    更新：manual_category, effective_category, metadata_.step0_fee_category,
          metadata_.step0_archived_key, metadata_.step0_corrected=True
    """
    from services.storage.minio_client import minio_client

    if not validate_fee_category(new_category):
        raise ValueError(f"无效的费用类别: {new_category}")

    # 查询 material
    stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == material_id)
    result = await db.execute(stmt)
    material = result.scalar_one_or_none()
    if not material:
        raise ValueError(f"Material not found: {material_id}")

    case_id = material.evidence_case_id
    new_category_cn = get_fee_cn_name(new_category)

    # 下载旧归档文件
    old_archive_key = (material.metadata_ or {}).get("step0_archived_key")
    file_bytes: Optional[bytes] = None
    if old_archive_key:
        try:
            file_bytes = minio_client.download_bytes(
                bucket=EVIDENCE_MINIO_BUCKET,
                object_key=old_archive_key,
            )
        except Exception as e:
            logger.warning(f"step0 correct: failed to download old archive {old_archive_key}: {e}")

    # 如果旧归档文件不存在，从 raw 下载
    if file_bytes is None:
        raw_key = (material.metadata_ or {}).get("step0_raw_key") or material.minio_key
        if raw_key:
            try:
                file_bytes = minio_client.download_bytes(
                    bucket=EVIDENCE_MINIO_BUCKET,
                    object_key=raw_key,
                )
            except Exception as e:
                logger.warning(f"step0 correct: failed to download raw {raw_key}: {e}")

    # 生成新序号
    page = (material.metadata_ or {}).get("step0_page_number")
    ext = ".jpg" if page is not None else _get_extension(material.original_filename or ".jpg")
    seq = await _generate_seq(case_id, new_category_cn, db)
    new_archive_key = _build_archive_key(case_id, new_category_cn, seq, ext, page)

    # 上传到新路径
    if file_bytes:
        content_type = "image/jpeg" if ext in (".jpg", ".jpeg") or page is not None else "image/png"
        minio_client.upload_bytes(
            bucket=EVIDENCE_MINIO_BUCKET,
            object_key=new_archive_key,
            data=file_bytes,
            content_type=content_type,
        )

    # 删除旧归档文件（不删 raw）
    if old_archive_key and old_archive_key != new_archive_key:
        try:
            minio_client.delete_object(EVIDENCE_MINIO_BUCKET, old_archive_key)
        except Exception:
            pass

    # 深拷贝更新 metadata_
    md = copy.deepcopy(material.metadata_ or {})
    md["step0_fee_category"] = new_category
    md["step0_archived_key"] = new_archive_key
    md["step0_corrected"] = True
    md["step0_needs_review"] = False

    material.metadata_ = md
    material.manual_category = new_category
    material.effective_category = new_category
    material.minio_key = new_archive_key
    material.minio_bucket = EVIDENCE_MINIO_BUCKET

    await db.flush()
    await db.commit()
    await db.refresh(material)

    logger.info(
        f"step0 correct_category: material={material_id}, "
        f"new_category={new_category}, new_archive_key={new_archive_key}"
    )
    return material


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 跳过步骤0
# ═══════════════════════════════════════════════════════════════════════════════

async def skip_step0(case_id: uuid.UUID, db: AsyncSession) -> None:
    """跳过步骤0：EvidenceCase.metadata_.step0_status='skipped'"""
    await _update_case_step0_status(case_id, STEP0_STATUS_SKIPPED, db)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 查询步骤0 产出的素材
# ═══════════════════════════════════════════════════════════════════════════════

async def get_step0_materials(
    case_id: uuid.UUID,
    db: AsyncSession,
) -> list[EvidenceMaterial]:
    """查询 metadata_.source='step0_preprocess' 的全部素材"""
    stmt = (
        select(EvidenceMaterial)
        .where(EvidenceMaterial.evidence_case_id == case_id)
        .order_by(EvidenceMaterial.created_at)
    )
    result = await db.execute(stmt)
    all_mats = result.scalars().all()

    # Python 过滤 source=step0_preprocess
    return [
        m for m in all_mats
        if (m.metadata_ or {}).get("source") == "step0_preprocess"
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 分类汇总
# ═══════════════════════════════════════════════════════════════════════════════

async def get_category_summary(
    case_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, int]:
    """按 metadata_.step0_fee_category 分组 COUNT

    Returns:
        {"fee_medical": 3, "fee_nursing": 2, ...}
    """
    materials = await get_step0_materials(case_id, db)
    summary: dict[str, int] = {}
    for m in materials:
        cat = (m.metadata_ or {}).get("step0_fee_category")
        if cat:
            summary[cat] = summary.get(cat, 0) + 1
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 预处理进度
# ═══════════════════════════════════════════════════════════════════════════════

async def get_preprocess_progress(
    case_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """统计 total/processed/failed/pending + category_summary"""
    materials = await get_step0_materials(case_id, db)

    total = len(materials)
    processed = 0
    failed = 0
    pending = 0

    for m in materials:
        if m.ocr_status == "completed":
            processed += 1
        elif m.ocr_status == "failed":
            failed += 1
        elif m.ocr_status == "pending":
            pending += 1
        # processing 也算 pending（仍在处理中）
        elif m.ocr_status == "processing":
            pending += 1

    category_summary = await get_category_summary(case_id, db)

    # 查询 case 的 step0_status
    case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_id)
    case_result = await db.execute(case_stmt)
    case = case_result.scalar_one_or_none()
    step0_status = (case.metadata_ or {}).get("step0_status", STEP0_STATUS_NOT_STARTED) if case else STEP0_STATUS_NOT_STARTED

    # 进度百分比
    if total == 0:
        progress_percent = 0.0
    else:
        progress_percent = round(processed / total * 100, 1)

    return {
        "total": total,
        "processed": processed,
        "failed": failed,
        "pending": pending,
        "progress_percent": progress_percent,
        "step0_status": step0_status,
        "category_summary": category_summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. 更新 case step0 状态
# ═══════════════════════════════════════════════════════════════════════════════

async def _update_case_step0_status(
    case_id: uuid.UUID,
    status: str,
    db: AsyncSession,
    total_raw: Optional[int] = None,
) -> None:
    """更新 EvidenceCase.metadata_.step0_status

    ⚠️ JSONB 深拷贝铁律！
    ⚠️ flush() 后显式 commit()！
    """
    stmt = select(EvidenceCase).where(EvidenceCase.id == case_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if not case:
        logger.warning(f"step0: case not found: {case_id}")
        return

    md = copy.deepcopy(case.metadata_ or {})
    md["step0_status"] = status
    if status == STEP0_STATUS_COMPLETED:
        md["step0_completed_at"] = datetime.now(timezone.utc).isoformat()
    if total_raw is not None:
        md["step0_total_raw"] = total_raw

    case.metadata_ = md
    await db.flush()
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _get_extension(filename: str) -> str:
    """获取文件扩展名（小写，含点号）"""
    import os
    _, ext = os.path.splitext(filename)
    return ext.lower()


def _detect_file_type(filename: str) -> str:
    """根据文件扩展名判断文件类型"""
    ext = _get_extension(filename)
    if ext == ".pdf":
        return "pdf"
    return "image"
