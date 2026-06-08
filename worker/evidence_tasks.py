"""
证据模块 Celery 异步任务（优化版）
=================================
核心优化：单材料流水线 + 合并LLM调用 + 批量LLM调用
- 每个材料独立流水线：OCR → 分类+提取，一气呵成
- OCR完成后立即进入分类+提取，不等其他材料
- 合并分类+提取为一次LLM调用
- 批量LLM调用（每批最多5个材料）
- 临时文件及时清理，防止 /tmp 磁盘满
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime, timezone

from loguru import logger

from worker.celery_app import celery_app
from config.settings import settings


# ─── 临时文件清理 ────────────────────────────────────────────────────────────

def _cleanup_temp_files(*paths: str) -> None:
    """清理临时文件/目录（静默忽略错误）"""
    for p in paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.unlink(p)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {p}: {e}")


def _cleanup_tmp_dir() -> None:
    """清理 /tmp 下的 OCR 临时目录和工作文件"""
    import glob as _glob
    tmp_dir = "/tmp"
    try:
        # 清理 OCR 工作目录
        for d in _glob.glob(os.path.join(tmp_dir, "ocr_*")):
            _cleanup_temp_files(d)
        for d in _glob.glob(os.path.join(tmp_dir, "tmp*")):
            # 只清理超过 1 小时的临时文件/目录（避免清理正在使用的）
            try:
                mtime = os.path.getmtime(d)
                if (datetime.now().timestamp() - mtime) > 3600:
                    _cleanup_temp_files(d)
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"Failed to cleanup /tmp: {e}")


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


@celery_app.task(bind=True, name="process_evidence_ocr", max_retries=2)
def process_evidence_ocr(self, case_id: str):
    """OCR 识别所有待处理材料"""
    logger.info(f"Evidence OCR processing started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        result = _run_ocr_pipeline(case_id)
        return {"case_id": case_id, "status": result.get("status", "completed"), "summary": result}
    except Exception as e:
        logger.error(f"Evidence OCR fatal error: case_id={case_id} | {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="process_evidence_classify", max_retries=2)
def process_evidence_classify(self, case_id: str):
    """分类所有已 OCR 的材料（兼容旧接口）"""
    logger.info(f"Evidence classification started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        result = _run_classify_pipeline(case_id)
        return {"case_id": case_id, "status": result.get("status", "completed"), "summary": result}
    except Exception as e:
        logger.error(f"Evidence classification fatal error: case_id={case_id} | {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="generate_evidence_catalog", max_retries=2)
def generate_evidence_catalog(self, case_id: str):
    """生成证据材料清单"""
    logger.info(f"Evidence catalog generation started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        from services.evidence.catalog_generator import generate_catalog
        catalog_data = generate_catalog(case_id)

        _update_case_status(case_id, "catalog_ready")

        return {
            "case_id": case_id,
            "status": "completed",
            "total_items": catalog_data.get("total_items", 0),
            "total_amount": catalog_data.get("total_amount", 0),
        }
    except Exception as e:
        logger.error(f"Evidence catalog generation fatal error: case_id={case_id} | {e}")
        _update_case_status(case_id, "failed")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="process_evidence_full", max_retries=5)
def process_evidence_full(self, case_id: str):
    """一键处理（优化版）：流水线并发 OCR → 分类+提取 → 目录

    改造要点：
    1. OCR 阶段：多线程并发（max_workers = 2，保守值防止10人并发时CPU过载）
    2. 分类+提取：OCR 完成后立即批量分类+提取（合并 LLM 调用）
    3. 目录生成：全部分类完成后生成
    4. 并发控制：通过 Redis 信号量限制同时处理的案件数（默认3个）
    """
    from services.utils.task_concurrency import try_acquire_case, release_case

    # 并发控制：超过上限则排队等待
    if not try_acquire_case():
        logger.warning(f"[并发控制] case_id={case_id} 系统繁忙，60秒后重试")
        raise self.retry(countdown=60)

    try:
        return _do_process_evidence_full(self, case_id)
    finally:
        release_case()


def _do_process_evidence_full(self, case_id: str):
    """process_evidence_full 的实际处理逻辑（已获取并发许可）"""
    logger.info(f"Evidence full processing (pipeline) started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        _update_case_status(case_id, "processing")

        # Step 1: OCR 全部材料（并发）
        ocr_result = _run_ocr_pipeline(case_id)
        logger.info(f"OCR done for {case_id}: processed={ocr_result.get('processed')}, errors={len(ocr_result.get('errors', []))}")

        # Step 2: 分类+提取（使用合并后的批量函数）
        classify_result = _run_classify_pipeline_optimized(case_id)
        logger.info(f"Classify done for {case_id}: classified={classify_result.get('classified')}, errors={len(classify_result.get('errors', []))}")

        # Step 3: 生成证据目录
        from services.evidence.catalog_generator import generate_catalog
        catalog_data = generate_catalog(case_id)

        _update_case_status(case_id, "catalog_ready")

        return {
            "case_id": case_id,
            "status": "completed",
            "ocr_summary": ocr_result,
            "classify_summary": classify_result,
            "total_items": catalog_data.get("total_items", 0),
            "total_amount": catalog_data.get("total_amount", 0),
        }
    except Exception as e:
        logger.error(f"Evidence full processing fatal error: case_id={case_id} | {e}")
        _update_case_status(case_id, "failed")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="analyze_evidence", max_retries=2)
def analyze_evidence(self, case_id: str):
    """分析证据清单 → 提取槽位数据 → 生成文档数据"""
    logger.info(f"Evidence analysis started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        _update_case_status(case_id, "analyzing")

        from services.evidence.document_analyzer import analyze_catalog
        result = analyze_catalog(case_id)

        _update_case_status(case_id, "analysis_done")

        return {
            "case_id": case_id,
            "status": "completed",
            "missing_count": len(result.get("missing_items", {}).get("items", [])),
        }
    except Exception as e:
        logger.error(f"Evidence analysis fatal error: case_id={case_id} | {e}")
        _update_case_status(case_id, "failed")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="export_evidence_bundle", max_retries=1)
def export_evidence_bundle(self, case_id: str):
    """一键打包导出"""
    logger.info(f"Evidence bundle export started: case_id={case_id}")


@celery_app.task(bind=True, name="process_single_material_ocr", max_retries=2)
def process_single_material_ocr(self, material_id: str):
    """重试单个素材的 OCR 识别"""
    logger.info(f"Single material OCR retry started: material_id={material_id}")

    try:
        uuid.UUID(material_id)
    except ValueError:
        return {"material_id": material_id, "status": "failed", "error": "Invalid material_id format"}

    async def _process():
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from db.models_evidence import EvidenceMaterial
        from services.ocr.bailian_engine import BailianOCREngine
        from services.storage.minio_client import minio_client
        from services.evidence.catalog_generator import _classify_and_extract_single

        engine = _create_worker_engine()
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with async_session() as db:
                stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == uuid.UUID(material_id))
                result = await db.execute(stmt)
                material = result.scalar_one_or_none()

                if not material:
                    logger.error(f"Material not found: {material_id}")
                    return {"material_id": material_id, "status": "failed", "error": "Material not found"}

                # 从 MinIO 下载文件
                bucket = material.minio_bucket or "evidence"
                file_bytes = await asyncio.to_thread(
                    minio_client.download_bytes, bucket, material.minio_key
                )

                # 执行 OCR
                ocr_engine = BailianOCREngine()
                ocr_result = await asyncio.to_thread(
                    ocr_engine.recognize_bytes,
                    file_bytes,
                    material.original_filename or "unknown",
                    material.file_type or "image",
                )

                # 更新 OCR 结果
                material.ocr_status = "completed"
                material.ocr_text = ocr_result.get("text", "")
                material.ocr_result = ocr_result

                # 执行分类和提取
                classify_result = await _classify_and_extract_single(material, ocr_result)
                if classify_result:
                    material.auto_category = classify_result.get("category")
                    material.effective_category = classify_result.get("category")
                    material.category_confidence = classify_result.get("confidence")
                    material.extracted_data = classify_result.get("extracted_data", {})

                await db.commit()
                logger.info(f"Single material OCR completed: {material_id}")
                return {"material_id": material_id, "status": "completed"}

        except Exception as e:
            logger.error(f"Single material OCR failed: {material_id} | {e}")
            # 更新失败状态
            try:
                async with async_session() as db:
                    stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == uuid.UUID(material_id))
                    result = await db.execute(stmt)
                    material = result.scalar_one_or_none()
                    if material:
                        material.ocr_status = "failed"
                        material.ocr_result = {"error": str(e)}
                        await db.commit()
            except Exception:
                pass
            return {"material_id": material_id, "status": "failed", "error": str(e)}
        finally:
            await engine.dispose()

    # 运行异步任务
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_process())
        return result
    except Exception as e:
        logger.error(f"Single material OCR fatal error: {material_id} | {e}")
        raise self.retry(exc=e)
    finally:
        loop.close()

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        _update_case_status(case_id, "exporting")

        from services.evidence.bundle_packager import create_export_bundle
        bundle_path = create_export_bundle(case_id)

        _update_case_status(case_id, "completed")

        return {
            "case_id": case_id,
            "status": "completed",
            "bundle_path": bundle_path,
        }
    except Exception as e:
        logger.error(f"Evidence bundle export fatal error: case_id={case_id} | {e}")
        _update_case_status(case_id, "failed")
        raise self.retry(exc=e)


# ─── 内部管线函数 ────────────────────────────────────────────────────────────

def _run_ocr_pipeline(case_id: str) -> dict:
    """执行 OCR 识别管线（engine 在 async 内部创建，避免 event loop 绑定冲突）"""
    from db.models_evidence import EvidenceCase, EvidenceStep, EvidenceMaterial

    summary = {"case_id": case_id, "status": "completed", "processed": 0, "errors": []}

    async def _pipeline():
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from sqlalchemy import select
        from concurrent.futures import ThreadPoolExecutor

        _engine = _create_worker_engine()
        _factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        try:
            case_uuid = uuid.UUID(case_id)
            async with _factory() as db:
                # 记录步骤
                step = EvidenceStep(
                    case_id=case_uuid,
                    step_name="ocr",
                    status="processing",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(step)
                await db.flush()

                # 获取待处理材料（包括之前失败的，允许重试；排除 audio 标记 not_applicable）
                stmt = select(EvidenceMaterial).where(
                    EvidenceMaterial.evidence_case_id == case_uuid,
                    EvidenceMaterial.ocr_status.in_(("pending", "failed")),
                )
                result = await db.execute(stmt)
                materials = result.scalars().all()

                if not materials:
                    step.status = "completed"
                    step.completed_at = datetime.now(timezone.utc)
                    step.duration_ms = 0
                    await db.commit()
                    return summary

                def _process_one(mid: str):
                    return _ocr_single_material(mid)

                mat_ids = [str(m.id) for m in materials]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {pool.submit(_process_one, mid): mid for mid in mat_ids}
                    for future in futures:
                        try:
                            res = future.result()
                            if res.get("success"):
                                summary["processed"] += 1
                            else:
                                summary["errors"].append(res.get("error", "unknown"))
                        except Exception as e:
                            summary["errors"].append(str(e))

                step.status = "completed"
                step.completed_at = datetime.now(timezone.utc)
                if step.started_at:
                    step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                await db.commit()

                # 清理 OCR 临时文件
                _cleanup_tmp_dir()

                return summary
        finally:
            await _engine.dispose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        loop.close()


def _ocr_single_material(material_id: str) -> dict:
    """OCR 识别单个材料（在独立线程中运行，engine 在 async 内部创建）

    支持多页文档精准提取：
    - 如果 material.selected_pages 非空，只 OCR 选定页
    - 如果为空列表或 None，OCR 全部页面（默认行为）
    """
    import asyncio

    from db.models_evidence import EvidenceMaterial
    from services.complaint.ocr_service import ocr_upload
    from services.storage.minio_client import minio_client

    material_uuid = uuid.UUID(material_id)

    async def _do():
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from sqlalchemy import select

        _engine = _create_worker_engine()
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with _session_factory() as db:
                stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == material_uuid)
                result = await db.execute(stmt)
                material = result.scalar_one_or_none()
                if not material:
                    return {"success": False, "error": "Material not found"}

                try:
                    material.ocr_status = "processing"
                    await db.flush()

                    # 跳过音频文件等不需要 OCR 的类型
                    if material.file_type == "audio":
                        material.ocr_status = "not_applicable"
                        material.ocr_text = ""
                        material.ocr_result = {"source_type": "audio", "note": "Audio file - OCR not applicable"}
                        await db.commit()
                        return {"success": True}

                    if material.minio_bucket and material.minio_key:
                        file_bytes = minio_client.download_bytes(
                            bucket=material.minio_bucket,
                            object_key=material.minio_key,
                        )
                        filename = material.original_filename or "upload"
                        selected = material.selected_pages  # JSONB list[int] | None

                        # 判断是否需要选择性 OCR
                        if (
                            selected
                            and len(selected) > 0
                            and material.file_type == "pdf"
                        ):
                            # 只 OCR 选定页面
                            ocr_result = _ocr_pdf_selected_pages(
                                file_bytes, filename, selected
                            )
                        else:
                            ocr_result = ocr_upload(file_bytes, filename)

                        ocr_text = ocr_result.get("full_text", "")
                        block_count = ocr_result.get("block_count", 0)

                        material.ocr_text = ocr_text
                        material.ocr_result = ocr_result
                        material.page_count = ocr_result.get("page_count")

                        # ── OCR 返回空结果时标记为 failed（允许重试） ──
                        # 排除 docx/xlsx 等格式化文档（它们用结构化提取而非图像OCR）
                        _struct_suffixes = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}
                        _fn_lower = filename.lower()
                        is_struct_doc = any(_fn_lower.endswith(s) for s in _struct_suffixes)
                        if not ocr_text.strip() and block_count == 0 and not is_struct_doc:
                            logger.warning(
                                f"OCR returned empty result for '{filename}' "
                                f"(source_type={ocr_result.get('source_type')}), "
                                f"marking as failed to allow retry"
                            )
                            material.ocr_status = "failed"
                            material.ocr_result = {
                                **ocr_result,
                                "error": "OCR returned empty text - possible rate limit or image quality issue",
                            }
                        else:
                            material.ocr_status = "completed"
                    else:
                        material.ocr_status = "skipped"

                    await db.commit()
                    return {"success": True}

                except Exception as e:
                    logger.error(f"OCR failed for material {material_id}: {e}")
                    material.ocr_status = "failed"
                    material.ocr_result = {"error": str(e)}
                    await db.commit()
                    return {"success": False, "error": str(e)}
        finally:
            await _engine.dispose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_do())
    finally:
        loop.close()


def _ocr_pdf_selected_pages(
    pdf_bytes: bytes, filename: str, selected_pages: list[int]
) -> dict:
    """只 OCR PDF 中的选定页面（1-based 页码列表）

    使用 fitz 提取指定页 → 转图片 → OCR
    """
    import io
    import tempfile
    from pathlib import Path

    import fitz

    logger.info(
        f"Selective OCR for {filename}: pages {selected_pages}"
    )

    all_text_parts: list[str] = []
    all_blocks: list[dict] = []
    total_pages = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)

        # 提取选定页面为图片
        image_paths: list[Path] = []
        for page_num in sorted(set(selected_pages)):
            if page_num < 1 or page_num > total_pages:
                logger.warning(f"Page {page_num} out of range (1-{total_pages}), skipping")
                continue

            page = doc[page_num - 1]
            zoom = 150 / 72.0  # 150 DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            img_path = tmp_path / f"page_{page_num:04d}.png"
            pix.save(str(img_path))
            image_paths.append(img_path)

        doc.close()

        if not image_paths:
            return {
                "full_text": "",
                "blocks": [],
                "block_count": 0,
                "page_count": total_pages,
                "selected_pages": selected_pages,
                "source_type": "pdf_ocr_selected",
            }

        # OCR 提取的页面
        from services.ocr.batch_processor import OCRBatchProcessor

        processor = OCRBatchProcessor()
        ocr_summary = processor.process_pages(image_paths, tmp_path / "ocr")

        for page_data in ocr_summary.get("pages", []):
            # 恢复原始页码
            idx = page_data.get("page", 0) - 1
            real_page = (
                sorted(set(selected_pages))[idx]
                if idx < len(sorted(set(selected_pages)))
                else page_data.get("page", 0)
            )
            for r in page_data.get("results", []):
                all_blocks.append({
                    "text": r.get("text", ""),
                    "confidence": r.get("confidence", 0),
                    "page": real_page,
                })
                all_text_parts.append(r.get("text", ""))

    return {
        "full_text": "\n".join(all_text_parts),
        "blocks": all_blocks,
        "block_count": len(all_blocks),
        "page_count": total_pages,
        "selected_pages": selected_pages,
        "pages_ocr": len(image_paths),
        "source_type": "pdf_ocr_selected",
    }


def _run_classify_pipeline(case_id: str) -> dict:
    """执行分类管线（兼容旧接口，单材料模式，engine 在 async 内部创建）"""
    import asyncio

    from db.models_evidence import EvidenceCase, EvidenceStep, EvidenceMaterial

    summary = {"case_id": case_id, "status": "completed", "classified": 0, "errors": []}

    async def _pipeline():
        from services.evidence.classifier import classify_material
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from sqlalchemy import select
        from concurrent.futures import ThreadPoolExecutor

        _engine = _create_worker_engine()
        _factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        try:
            case_uuid = uuid.UUID(case_id)
            async with _factory() as db:
                step = EvidenceStep(
                    case_id=case_uuid,
                    step_name="classify",
                    status="processing",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(step)
                await db.flush()

                # 获取已 OCR 但未分类的材料
                stmt = select(EvidenceMaterial).where(
                    EvidenceMaterial.evidence_case_id == case_uuid,
                    EvidenceMaterial.ocr_status == "completed",
                    EvidenceMaterial.effective_category.is_(None),
                )
                result = await db.execute(stmt)
                materials = result.scalars().all()

                def _classify_one(mid: str):
                    try:
                        classify_material(mid)
                        return {"success": True}
                    except Exception as e:
                        return {"success": False, "error": str(e)}

                mat_ids = [str(m.id) for m in materials]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {pool.submit(_classify_one, mid): mid for mid in mat_ids}
                    for future in futures:
                        try:
                            res = future.result()
                            if res.get("success"):
                                summary["classified"] += 1
                            else:
                                summary["errors"].append(res.get("error", "unknown"))
                        except Exception as e:
                            summary["errors"].append(str(e))

                step.status = "completed"
                step.completed_at = datetime.now(timezone.utc)
                if step.started_at:
                    step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                await db.commit()

                return summary
        finally:
            await _engine.dispose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        loop.close()


def _run_classify_pipeline_optimized(case_id: str) -> dict:
    """优化的分类管线：使用合并函数 + 批量LLM调用（engine 在 async 内部创建）

    改造要点：
    1. 收集所有已OCR材料的文本
    2. 使用 classify_and_extract_batch 批量处理
    3. 批量更新数据库（减少DB往返）
    """
    import asyncio

    from db.models_evidence import EvidenceCase, EvidenceStep, EvidenceMaterial

    summary = {"case_id": case_id, "status": "completed", "classified": 0, "errors": []}

    async def _pipeline():
        from services.evidence.classifier import (
            classify_and_extract_batch,
            _generate_title_v2,
            _generate_proof_purpose_v2,
            CATEGORY_NAMES,
        )
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
        from sqlalchemy import select

        _engine = _create_worker_engine()
        _factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        try:
            case_uuid = uuid.UUID(case_id)
            async with _factory() as db:
                step = EvidenceStep(
                    case_id=case_uuid,
                    step_name="classify_optimized",
                    status="processing",
                    started_at=datetime.now(timezone.utc),
                )
                db.add(step)
                await db.flush()

                # 获取案件类型
                case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
                case_result = await db.execute(case_stmt)
                case = case_result.scalar_one_or_none()
                case_type = case.case_type if case else "injury"

                # 获取已 OCR 但未分类的材料
                stmt = select(EvidenceMaterial).where(
                    EvidenceMaterial.evidence_case_id == case_uuid,
                    EvidenceMaterial.ocr_status == "completed",
                    EvidenceMaterial.effective_category.is_(None),
                )
                result = await db.execute(stmt)
                materials = result.scalars().all()

                if not materials:
                    step.status = "completed"
                    step.completed_at = datetime.now(timezone.utc)
                    step.duration_ms = 0
                    await db.commit()
                    return summary

                # 批量分类+提取
                items = [(str(m.id), m.ocr_text or "") for m in materials]
                batch_results = classify_and_extract_batch(items, case_type)

                # 构建 material_id → material 对象的映射
                mat_map = {str(m.id): m for m in materials}

                # 批量更新数据库
                for res in batch_results:
                    mid = res["material_id"]
                    material = mat_map.get(mid)
                    if not material:
                        summary["errors"].append(f"Material {mid} not found in map")
                        continue

                    try:
                        category = res["category"]
                        confidence = res["confidence"]
                        extracted = res["extracted"]

                        material.auto_category = category
                        material.category_confidence = confidence
                        if not material.manual_category:
                            material.effective_category = category
                        else:
                            material.effective_category = material.manual_category

                        material.extracted_data = extracted

                        # 从四层数据生成清单标题和证明目的
                        material.catalog_title = _generate_title_v2(category, extracted, material)
                        material.proof_purpose = _generate_proof_purpose_v2(category, extracted, case_type)

                        # 从第4层填充 fee_detail
                        fees = extracted.get("layer_4_fees", {})
                        if fees.get("items") or fees.get("total_amount"):
                            material.fee_detail = {
                                "items": fees.get("items", []),
                                "total_amount": fees.get("total_amount", 0.0),
                                "insurance_amount": fees.get("insurance_amount"),
                                "out_of_pocket": fees.get("out_of_pocket"),
                            }

                        summary["classified"] += 1
                    except Exception as e:
                        summary["errors"].append(f"Material {mid}: {e}")

                await db.commit()

                step.status = "completed"
                step.completed_at = datetime.now(timezone.utc)
                if step.started_at:
                    step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                await db.commit()

                logger.info(
                    f"Optimized classify done for {case_id}: "
                    f"classified={summary['classified']}, errors={len(summary['errors'])}"
                )
                return summary
        finally:
            await _engine.dispose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        loop.close()


def _update_case_status(case_id: str, status: str) -> None:
    """更新案件状态（独立 DB 连接，engine 在 async 内部创建）"""
    import asyncio

    async def _do():
        from sqlalchemy import select
        from db.models_evidence import EvidenceCase
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        case_uuid = uuid.UUID(case_id)
        _engine = _create_worker_engine()
        _factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with _factory() as db:
                stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
                result = await db.execute(stmt)
                case = result.scalar_one_or_none()
                if case:
                    case.status = status
                    await db.commit()
        finally:
            await _engine.dispose()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"Failed to update case status: {e}")
    finally:
        loop.close()
