"""
ZIP 打包器 — 将所有导出文档打包为 ZIP
"""
from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any

from loguru import logger

MINIO_BUCKET = "scan-result"


def create_export_bundle(case_id: str) -> str:
    """打包所有导出文档为 ZIP → 返回 MinIO key

    ZIP 结构：
    {案件名称}立案立档包/
    ├── 01_立案证据.docx
    ├── 02_民事起诉状.docx
    ├── 03_司法鉴定申请书.docx
    ├── 04_赔偿费用清单.xlsx
    ├── 05_费用明细/
    │   ├── 医疗费.xlsx
    │   ├── 交通住宿费.xlsx
    │   └── ...
    ├── 06_证据目录.pdf
    └── 07_证据材料.pdf
    """
    from db.models_evidence import EvidenceCase
    from db.session import get_session_factory, run_in_worker
    from services.storage.minio_client import minio_client
    from services.evidence.word_generator import (
        generate_filing_evidence,
        generate_complaint,
        generate_appraisal_application,
    )
    from services.evidence.excel_generator import (
        generate_compensation_summary,
        generate_all_fee_details,
    )

    # 获取案件信息
    async def _fetch_case():
        from sqlalchemy import select

        case_uuid = uuid.UUID(case_id)
        async with get_session_factory()() as db:
            stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            result = await db.execute(stmt)
            case = result.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")
            return case

    case = run_in_worker(_fetch_case())

    case_name = case.case_name or "案件"
    folder_name = f"{case_name}立案立档包"

    # 生成所有文档
    export_files: dict[str, str | bytes] = {}

    # 1. 立案证据
    try:
        key = generate_filing_evidence(case_id)
        export_files["01_立案证据.docx"] = key
    except Exception as e:
        logger.error(f"Failed to generate filing evidence: {e}")

    # 2. 民事起诉状
    try:
        key = generate_complaint(case_id)
        export_files["02_民事起诉状.docx"] = key
    except Exception as e:
        logger.error(f"Failed to generate complaint: {e}")

    # 3. 司法鉴定申请书
    try:
        key = generate_appraisal_application(case_id)
        export_files["03_司法鉴定申请书.docx"] = key
    except Exception as e:
        logger.error(f"Failed to generate appraisal application: {e}")

    # 4. 赔偿费用总表
    try:
        key = generate_compensation_summary(case_id)
        export_files["04_赔偿费用清单.xlsx"] = key
    except Exception as e:
        logger.error(f"Failed to generate compensation summary: {e}")

    # 5. 各项费用明细
    try:
        fee_details = generate_all_fee_details(case_id)
        for fee_type, key in fee_details.items():
            safe_name = fee_type.replace("/", "_").replace("\\", "_")
            export_files[f"05_费用明细/{safe_name}.xlsx"] = key
    except Exception as e:
        logger.error(f"Failed to generate fee details: {e}")

    # 6. 证据目录 PDF
    try:
        from services.evidence.pdf_generator import generate_catalog_table_pdf
        catalog_data = case.catalog_data or {}
        catalog_pdf_bytes = generate_catalog_table_pdf(
            case.case_name, case.case_type, catalog_data,
        )
        if catalog_pdf_bytes:
            # 直接存bytes，不走MinIO中转
            export_files["06_证据目录.pdf"] = catalog_pdf_bytes
    except Exception as e:
        logger.error(f"Failed to generate catalog table PDF: {e}")

    # 7. 证据材料 PDF
    try:
        from services.evidence.pdf_generator import generate_catalog_pdf_inline
        from db.models_evidence import EvidenceMaterial
        from sqlalchemy import select as _sel

        # 获取所有素材
        async def _fetch_materials():
            async with get_session_factory()() as db:
                stmt = _sel(EvidenceMaterial).where(
                    EvidenceMaterial.evidence_case_id == uuid.UUID(case_id)
                ).order_by(EvidenceMaterial.created_at)
                result = await db.execute(stmt)
                return result.scalars().all()

        from services.evidence.ocr_storage import get_material_ocr_text

        materials = run_in_worker(_fetch_materials())
        material_files: dict[str, tuple[str, str, bytes]] = {}
        ocr_texts: dict[str, str] = {}
        for mat in materials:
            try:
                file_bytes = minio_client.download_bytes(
                    bucket=mat.minio_bucket or MINIO_BUCKET,
                    object_key=mat.minio_key,
                )
                material_files[str(mat.id)] = (
                    mat.original_filename or "unknown",
                    mat.file_type or "unknown",
                    file_bytes,
                )
                ocr_full = get_material_ocr_text(mat)
                if ocr_full:
                    ocr_texts[str(mat.id)] = ocr_full
            except Exception as e:
                logger.warning(f"Failed to download material {mat.id} for bundle: {e}")

        if material_files:
            materials_pdf_bytes = generate_catalog_pdf_inline(
                case_id,
                case.case_name,
                case.case_type,
                case.catalog_data or {},
                material_files,
                case.analysis_result,
                ocr_texts,
            )
            if materials_pdf_bytes:
                export_files["07_证据材料.pdf"] = materials_pdf_bytes
    except Exception as e:
        logger.error(f"Failed to generate materials PDF for bundle: {e}")

    # 打包 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc_name, file_data in export_files.items():
            try:
                if isinstance(file_data, bytes):
                    # 直接是bytes（PDF等）
                    zf.writestr(f"{folder_name}/{arc_name}", file_data)
                else:
                    # 是MinIO key（DOCX/XLSX）
                    file_bytes = minio_client.download_bytes(
                        bucket=MINIO_BUCKET,
                        object_key=file_data,
                    )
                    zf.writestr(f"{folder_name}/{arc_name}", file_bytes)
            except Exception as e:
                logger.error(f"Failed to add {arc_name} to bundle: {e}")

    zip_bytes = zip_buffer.getvalue()

    # 上传 ZIP
    minio_key = f"evidence/{case_id}/{uuid.uuid4()}_{folder_name}.zip"
    minio_client.upload_bytes(
        bucket=MINIO_BUCKET,
        object_key=minio_key,
        data=zip_bytes,
        content_type="application/zip",
    )

    # 更新数据库
    async def _update_case():
        from sqlalchemy import select
        from db.models_evidence import EvidenceCase
        from db.session import get_session_factory

        case_uuid = uuid.UUID(case_id)
        async with get_session_factory()() as db:
            stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            result = await db.execute(stmt)
            case_obj = result.scalar_one_or_none()
            if case_obj:
                case_obj.export_bundle_path = minio_key
                # 只存储文件名列表，不存储bytes
                case_obj.export_files = {k: "" for k in export_files}
                await db.commit()

    run_in_worker(_update_case())

    logger.info(
        f"Export bundle created: case={case_id} key={minio_key} "
        f"files={len(export_files)}"
    )
    return minio_key
