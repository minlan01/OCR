"""
步骤0 · Celery 异步任务
======================
process_step0_preprocess: 逐个下载 raw 文件 → OCR → LLM 分类 → 归档/PDF拆分

⚠️ 顶部必须 import db.models_evidence 确保模型注册！
⚠️ worker_concurrency=2 + ThreadPoolExecutor(max_workers=2) 配合 OCR Semaphore(1)
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from loguru import logger

from worker.celery_app import celery_app

# ── 确保模型注册到 Base.metadata（ForeignKey 依赖） ──
import db.models_auth  # noqa: F401 — Tenant 表
import db.models_evidence  # noqa: F401 — EvidenceCase / EvidenceMaterial / EvidenceStep

from config.settings import settings


def _create_worker_engine():
    """创建 Celery worker 用的数据库引擎（NullPool，避免连接泄漏）"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    return create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
    )


@celery_app.task(bind=True, name="process_step0_preprocess", max_retries=2)
def process_step0_preprocess(self, case_id: str):
    """步骤0 预处理主任务

    1. 创建 worker engine + async_sessionmaker
    2. 更新 EvidenceCase.metadata_.step0_status='in_progress'，创建 EvidenceStep
    3. SELECT pending materials WHERE source='step0_preprocess' AND ocr_status='pending'
    4. ThreadPoolExecutor(max_workers=2) 逐个处理：
       - MinIO 下载 raw 文件
       - ocr_upload(file_bytes, filename) 获取 OCR 文本
       - step0_classifier.classify_fee(ocr_text) 获取 (category, confidence)
       - PDF → _split_pdf_and_archive；否则 _archive_material
       - OCR 失败 → ocr_status='failed'；confidence<0.6 → needs_review=True
    5. 完成更新 step0_status='completed' + EvidenceStep status='completed'
    6. max_retries=2
    """
    logger.info(f"step0 preprocess started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        result = _run_step0_pipeline(case_id)
        return {"case_id": case_id, "status": "completed", "summary": result}
    except Exception as e:
        logger.error(f"step0 preprocess fatal error: case_id={case_id} | {e}", exc_info=True)
        if self.request.retries >= self.max_retries:
            _mark_case_failed(case_id)
        else:
            logger.info(
                f"step0 will retry ({self.request.retries + 1}/{self.max_retries}) "
                f"for case {case_id}"
            )
        raise self.retry(exc=e)


def _run_step0_pipeline(case_id: str) -> dict:
    """执行步骤0 预处理管线"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _create_worker_engine()
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        return asyncio.run(_async_run_pipeline(case_id, async_session))
    finally:
        # 清理引擎
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass


async def _async_run_pipeline(case_id: str, async_session) -> dict:
    """异步执行步骤0 管线"""
    import copy

    from sqlalchemy import select
    from db.models_evidence import EvidenceCase, EvidenceMaterial, EvidenceStep
    from services.evidence.step0_constants import (
        STEP0_CONFIDENCE_THRESHOLD,
        STEP0_STATUS_COMPLETED,
        STEP0_STATUS_IN_PROGRESS,
    )
    from services.evidence.step0_service import (
        EVIDENCE_MINIO_BUCKET,
        _archive_material,
        _split_pdf_and_archive,
        _update_case_step0_status,
    )

    case_uuid = uuid.UUID(case_id)

    async with async_session() as db:
        # 1. 更新 case step0_status='in_progress'
        case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
        case_result = await db.execute(case_stmt)
        case = case_result.scalar_one_or_none()
        if not case:
            logger.error(f"step0: case not found: {case_id}")
            return {"status": "failed", "error": "case not found"}

        case_md = copy.deepcopy(case.metadata_ or {})
        case_md["step0_status"] = STEP0_STATUS_IN_PROGRESS
        case.metadata_ = case_md
        await db.flush()
        await db.commit()

        # 创建 EvidenceStep
        step = EvidenceStep(
            case_id=case_uuid,
            step_name="step0_preprocess",
            status="processing",
            progress=0,
            started_at=datetime.now(timezone.utc),
        )
        db.add(step)
        await db.flush()
        await db.commit()

        # 2. 查询 pending materials
        mats_stmt = (
            select(EvidenceMaterial)
            .where(EvidenceMaterial.evidence_case_id == case_uuid)
            .order_by(EvidenceMaterial.created_at)
        )
        mats_result = await db.execute(mats_stmt)
        all_mats = mats_result.scalars().all()

        pending_mats = [
            m for m in all_mats
            if (m.metadata_ or {}).get("source") == "step0_preprocess"
            and m.ocr_status == "pending"
        ]

        total = len(pending_mats)
        logger.info(f"step0: {total} pending materials for case {case_id}")

        if total == 0:
            # 没有待处理的素材，直接完成
            await _finalize(case_uuid, step, db, total=0, processed=0, failed=0)
            return {"status": "completed", "total": 0, "processed": 0, "failed": 0}

        # 3. ThreadPoolExecutor 逐个处理
        processed = 0
        failed = 0

        def _process_single(material_id_str: str) -> bool:
            """在线程中处理单个素材，返回是否成功"""
            try:
                return asyncio.run(_process_single_async(
                    case_id, material_id_str, async_session
                ))
            except Exception as e:
                logger.error(f"step0: failed to process material {material_id_str}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            for mat in pending_mats:
                mat_id_str = str(mat.id)
                future = executor.submit(_process_single, mat_id_str)
                futures[future] = mat_id_str

            for future in futures:
                mat_id_str = futures[future]
                try:
                    success = future.result()
                    if success:
                        processed += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"step0: material {mat_id_str} processing error: {e}")
                    failed += 1

                # 更新 step progress
                step.progress = int((processed + failed) / total * 100)
                try:
                    asyncio.run(_update_step_progress(step.id, step.progress, async_session))
                except Exception:
                    pass

        # 4. 完成
        await _finalize(case_uuid, step, db, total=total, processed=processed, failed=failed)

        return {
            "status": "completed",
            "total": total,
            "processed": processed,
            "failed": failed,
        }


async def _process_single_async(
    case_id: str,
    material_id_str: str,
    async_session,
) -> bool:
    """异步处理单个素材：下载 → OCR → 分类 → 归档"""
    import copy

    from sqlalchemy import select
    from db.models_evidence import EvidenceMaterial
    from services.storage.minio_client import minio_client
    from services.complaint.ocr_service import ocr_upload
    from services.evidence.step0_classifier import classify_fee
    from services.evidence.step0_constants import STEP0_CONFIDENCE_THRESHOLD
    from services.evidence.step0_service import (
        EVIDENCE_MINIO_BUCKET,
        _archive_material,
        _split_pdf_and_archive,
    )

    material_uuid = uuid.UUID(material_id_str)

    async with async_session() as db:
        # 查询 material
        stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == material_uuid)
        result = await db.execute(stmt)
        material = result.scalar_one_or_none()
        if not material:
            logger.error(f"step0: material not found: {material_id_str}")
            return False

        # 标记为 processing
        material.ocr_status = "processing"
        await db.flush()
        await db.commit()

        try:
            # 下载 raw 文件
            raw_key = (material.metadata_ or {}).get("step0_raw_key") or material.minio_key
            if not raw_key:
                logger.error(f"step0: no raw_key for material {material_id_str}")
                material.ocr_status = "failed"
                await db.flush()
                await db.commit()
                return False

            file_bytes = minio_client.download_bytes(
                bucket=EVIDENCE_MINIO_BUCKET,
                object_key=raw_key,
            )
        except Exception as e:
            logger.error(f"step0: failed to download raw file for {material_id_str}: {e}")
            md = copy.deepcopy(material.metadata_ or {})
            material.metadata_ = md
            material.ocr_status = "failed"
            await db.flush()
            await db.commit()
            return False

        # OCR
        try:
            ocr_result = ocr_upload(file_bytes, material.original_filename or "upload")
            ocr_text = ocr_result.get("full_text", "")
            material.ocr_text = ocr_text
            material.ocr_result = ocr_result
        except Exception as e:
            logger.error(f"step0: OCR failed for {material_id_str}: {e}")
            md = copy.deepcopy(material.metadata_ or {})
            material.metadata_ = md
            material.ocr_status = "failed"
            await db.flush()
            await db.commit()
            return False

        # LLM 分类
        try:
            category, confidence = classify_fee(ocr_text)
        except Exception as e:
            logger.error(f"step0: classify_fee failed for {material_id_str}: {e}")
            category, confidence = None, 0.0

        if not category:
            # LLM 全部失败
            md = copy.deepcopy(material.metadata_ or {})
            md["step0_needs_review"] = True
            material.metadata_ = md
            material.ocr_status = "completed"
            material.auto_category = None
            material.effective_category = None
            material.category_confidence = 0.0
            await db.flush()
            await db.commit()
            # 标记为需要人工审查但仍算完成
            return True

        # 归档
        try:
            if material.file_type == "pdf":
                # PDF 拆分归档
                await _split_pdf_and_archive(
                    parent_material=material,
                    file_bytes=file_bytes,
                    category=category,
                    confidence=confidence,
                    db=db,
                )
            else:
                # 单图归档
                await _archive_material(
                    material=material,
                    category=category,
                    confidence=confidence,
                    db=db,
                    file_bytes=file_bytes,
                )
            await db.commit()
            logger.info(
                f"step0: material {material_id_str} archived: "
                f"category={category}, confidence={confidence}"
            )
            return True
        except Exception as e:
            logger.error(f"step0: archive failed for {material_id_str}: {e}")
            md = copy.deepcopy(material.metadata_ or {})
            material.metadata_ = md
            material.ocr_status = "failed"
            await db.flush()
            await db.commit()
            return False


async def _update_step_progress(step_id: int, progress: int, async_session) -> None:
    """更新 EvidenceStep progress"""
    from sqlalchemy import select, update
    from db.models_evidence import EvidenceStep

    async with async_session() as db:
        await db.execute(
            update(EvidenceStep).where(EvidenceStep.id == step_id).values(progress=progress)
        )
        await db.commit()


async def _finalize(
    case_uuid: uuid.UUID,
    step: EvidenceStep,
    db,
    total: int,
    processed: int,
    failed: int,
) -> None:
    """完成步骤0：更新 case status + step status"""
    import copy

    from sqlalchemy import select
    from db.models_evidence import EvidenceCase, EvidenceStep
    from services.evidence.step0_constants import STEP0_STATUS_COMPLETED

    # 更新 case step0_status='completed'
    case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
    case_result = await db.execute(case_stmt)
    case = case_result.scalar_one_or_none()
    if case:
        case_md = copy.deepcopy(case.metadata_ or {})
        case_md["step0_status"] = STEP0_STATUS_COMPLETED
        case_md["step0_completed_at"] = datetime.now(timezone.utc).isoformat()
        case_md["step0_total_raw"] = total
        case.metadata_ = case_md

    # 更新 step
    step_stmt = select(EvidenceStep).where(EvidenceStep.id == step.id)
    step_result = await db.execute(step_stmt)
    step_obj = step_result.scalar_one_or_none()
    if step_obj:
        step_obj.status = "completed"
        step_obj.progress = 100
        step_obj.completed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.commit()
    logger.info(
        f"step0 finalized: case={case_uuid}, total={total}, "
        f"processed={processed}, failed={failed}"
    )


def _mark_case_failed(case_id: str) -> None:
    """标记案件步骤0 为失败"""
    try:
        asyncio.run(_async_mark_case_failed(case_id))
    except Exception as e:
        logger.error(f"step0: failed to mark case {case_id} as failed: {e}")


async def _async_mark_case_failed(case_id: str) -> None:
    """异步标记案件步骤0 失败"""
    import copy

    from sqlalchemy import select
    from db.models_evidence import EvidenceCase, EvidenceStep

    engine = _create_worker_engine()
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        case_uuid = uuid.UUID(case_id)
        async with async_session() as db:
            case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            case_result = await db.execute(case_stmt)
            case = case_result.scalar_one_or_none()
            if case:
                case_md = copy.deepcopy(case.metadata_ or {})
                case_md["step0_status"] = "failed"
                case.metadata_ = case_md

            # 更新 step
            step_stmt = select(EvidenceStep).where(
                EvidenceStep.case_id == case_uuid,
                EvidenceStep.step_name == "step0_preprocess",
            ).order_by(EvidenceStep.id.desc()).limit(1)
            step_result = await db.execute(step_stmt)
            step = step_result.scalar_one_or_none()
            if step:
                step.status = "failed"
                step.completed_at = None

            await db.flush()
            await db.commit()
    finally:
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass
