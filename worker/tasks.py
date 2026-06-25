"""
Celery 异步任务 — 完整处理管线
编排: 下载 → 分类 → 拆页/增强 → OCR → 版面分析 → 结构化 → 导出 → 回调
每步独立 TaskStep 记录，失败不中断整体
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from worker.celery_app import celery_app
from config.settings import settings
from services.exporter.stream_publisher import publish_progress, publish_result

# ---- 预加载可能阻塞的模块（避免在 Celery task 内首次导入时卡死） ----
def _preload_modules():
    """在模块加载时预初始化关键组件"""
    try:
        import fitz  # noqa: F401 - PyMuPDF，C 扩展加载可能耗时
    except ImportError:
        pass
    try:
        from services.preprocessor.pdf_classifier import PDFClassifier  # noqa: F401
    except ImportError:
        pass
    try:
        from services.preprocessor.text_pdf_extractor import text_extractor  # noqa: F401
    except ImportError:
        pass

_preload_modules()


# ============================================================
# Celery 任务定义
# ============================================================

@celery_app.task(bind=True, name="process_scan", max_retries=3)
def process_scan(self, task_id: str):
    """
    主处理流程任务
    编排完整 Pipeline: preprocess → OCR → layout → structure → export → callback
    """
    logger.info(f"Scan processing started: task_id={task_id}")

    try:
        uuid.UUID(task_id)
    except ValueError:
        logger.error("Invalid task_id format (not a UUID): task_id={} — discarding", task_id)
        return {"task_id": task_id, "status": "failed", "error": "Invalid task_id format"}

    try:
        result = _run_pipeline(task_id)
        status = result.get("status", "completed")
        if status == "completed":
            logger.info(f"Scan processing completed: task_id={task_id}")
        else:
            logger.warning(f"Scan processing finished with issues: task_id={task_id} | {status}")
        return {"task_id": task_id, "status": status, "summary": result}
    except Exception as e:
        logger.error("Scan processing fatal error: task_id={} | {}", task_id, str(e))
        raise self.retry(exc=e)


# ============================================================
# 管线核心逻辑
# ============================================================

def _run_pipeline(task_id: str) -> dict:
    """
    运行完整处理管线（同步入口，内部 asyncio.run）
    使用 Redis 信号量限制并发管线数量，防止 Worker OOM
    包含全局并发控制 + 租户级配额控制
    """
    from services.utils.task_concurrency import (
        try_acquire_case, release_case,
        try_acquire_tenant, release_tenant,
    )

    # 全局并发控制
    acquired = try_acquire_case()
    if not acquired:
        logger.warning(f"Pipeline throttled (global busy): task_id={task_id}")
        raise Exception("System at capacity, please retry shortly")

    # 租户级并发控制
    tenant_id_str = _get_scan_tenant_id(task_id)
    if tenant_id_str and not try_acquire_tenant(tenant_id_str):
        release_case()
        logger.warning(f"Pipeline throttled (tenant limit): task_id={task_id} tenant={tenant_id_str[:8]}..")
        raise Exception("Tenant concurrency limit reached, please retry shortly")

    try:
        result = asyncio.run(_async_pipeline(task_id))
        return result
    finally:
        if tenant_id_str:
            release_tenant(tenant_id_str)
        release_case()


def _get_scan_tenant_id(task_id: str) -> str:
    """查询扫描任务所属租户 ID（同步，用于并发控制前的配额检查）"""
    try:
        import redis as _redis
        from config.settings import settings
        r = _redis.from_url(settings.redis_url_with_auth, decode_responses=True, socket_timeout=3)
        cache_key = f"scanstruct:scan_tenant:{task_id}"
        cached = r.get(cache_key)
        if cached is not None:
            return cached

        from sqlalchemy import create_engine, text
        eng = create_engine(settings.database_url_sync)
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT tenant_id FROM scan_tasks WHERE id = :tid"),
                {"tid": task_id},
            ).fetchone()
        eng.dispose()

        tid = str(row[0]) if row and row[0] else ""
        if tid:
            r.setex(cache_key, 3600, tid)
        return tid
    except Exception:
        return ""


async def _async_pipeline(task_id: str) -> dict:
    """
    异步管线核心:

    管线步骤:
      1. download     — 从 MinIO 下载原始 PDF
      2. classify     — PDF 分类（文字 PDF / 扫描 PDF）
      3a. text_fast   — 文字 PDF 快速路径
      3b. split       — 扫描 PDF 拆页
      4.  enhance     — 图像增强（去噪、纠偏、裁剪）
      5.  ocr         — OCR 批量识别
      6.  layout      — 版面分析
      7.  structure   — 结构化提取
      8.  export      — JSON 导出 + MinIO 上传
      9.  callback    — 业务回调通知
    """
    from db.models import ScanTask, TaskStep
    from services.storage.minio_client import minio_client

    summary = {
        "task_id": task_id,
        "status": "completed",
        "pages_processed": 0,
        "text_pdf_fast_path": False,
        "ocr_confidence_avg": 0.0,
        "sections_found": 0,
        "paragraphs_found": 0,
        "lists_found": 0,
        "tables_found": 0,
        "structure_score": 0.0,
        "errors": [],
    }

    async def _pipeline():
        task_uuid = uuid.UUID(task_id)
        # 使用独立的 Worker Engine（NullPool），避免跨 Event Loop 连接泄漏
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from sqlalchemy.pool import NullPool
        from config.settings import settings as _settings

        _worker_engine = create_async_engine(
            _settings.database_url,
            poolclass=NullPool,
            echo=False,
        )
        _worker_factory = async_sessionmaker(_worker_engine, class_=AsyncSession, expire_on_commit=False)

        work_dir: Path | None = None
        try:
            async with _worker_factory() as db:
                from sqlalchemy import select

            # ---- 加载任务 ----
            stmt = select(ScanTask).where(ScanTask.id == task_uuid)
            r = await db.execute(stmt)
            task = r.scalar_one_or_none()
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            task.status = "processing"
            task.started_at = datetime.now(timezone.utc)
            await db.commit()

            # ---- 推送: 任务开始 ----
            publish_progress(task_id, "start", "running", 0.0)

            # ---- 工作目录 ----
            work_dir = Path(settings.archive_dir) / "processing" / task_id
            work_dir.mkdir(parents=True, exist_ok=True)

            # ================================================
            # Step 1: 下载 PDF
            # ================================================
            step_dl = await _create_step(db, task_uuid, "download")
            try:
                if not task.original_path:
                    raise ValueError("No original file path")

                pdf_local = work_dir / task.filename
                minio_client.download_file(
                    bucket=settings.minio_bucket_raw,
                    object_key=task.original_path,
                    file_path=str(pdf_local),
                )
                await _complete_step(db, step_dl, "completed")
                logger.info(f"[download] OK: {task.filename}")
                publish_progress(task_id, "download", "completed", 5.0)
            except Exception as e:
                await _complete_step(db, step_dl, "failed", str(e))
                await _fail_task(db, task, "DOWNLOAD_ERROR", str(e))
                summary["status"] = "failed"
                summary["errors"].append(f"download: {e}")
                return summary

            # ================================================
            # Step 2: PDF 分类（可跳过）
            # ================================================
            structure_result = {}
            is_text_pdf = False

            if settings.skip_classify:
                step_cls = await _create_step(db, task_uuid, "classify")
                import fitz as _fitz
                _doc = _fitz.open(str(pdf_local))
                task.page_count = _doc.page_count
                _doc.close()
                summary["pages_processed"] = task.page_count
                await _complete_step(db, step_cls, "completed",
                    metadata={"skipped": True, "assumed_scan": True, "page_count": task.page_count})
                logger.info(f"[classify] SKIPPED: assumed scan PDF, pages={task.page_count}")
                publish_progress(task_id, "classify", "completed", 10.0)
            else:
                step_cls = await _create_step(db, task_uuid, "classify")
                try:
                    from services.preprocessor.pdf_classifier import PDFClassifier
                    classifier = PDFClassifier()
                    pdf_info = classifier.classify(pdf_local)
                    task.page_count = pdf_info.page_count
                    is_text_pdf = pdf_info.is_text_pdf
                    await _complete_step(db, step_cls, "completed",
                        metadata={"is_text_pdf": pdf_info.is_text_pdf, "page_count": pdf_info.page_count})
                    summary["pages_processed"] = pdf_info.page_count
                    logger.info(f"[classify] OK: text_pdf={pdf_info.is_text_pdf}, pages={pdf_info.page_count}")
                    publish_progress(task_id, "classify", "completed", 10.0)
                except Exception as e:
                    logger.error(f"[classify] FAILED: {e}", exc_info=True)
                    await _complete_step(db, step_cls, "failed", error_message=str(e))
                    await _fail_task(db, task, "CLASSIFY_ERROR", str(e))
                    summary["status"] = "failed"
                    summary["errors"].append(f"classify: {e}")
                    return summary

            # ================================================
            # 分支: 文字 PDF vs 扫描 PDF
            # ================================================

            if is_text_pdf:
                summary["text_pdf_fast_path"] = True
                await _run_text_pdf_path(
                    db, task, task_uuid, pdf_local, work_dir, summary, structure_result,
                )
            else:
                await _run_scan_pdf_path(
                    db, task, task_uuid, pdf_local, work_dir, summary, structure_result,
                )

            if summary["status"] == "failed":
                return summary

            # ================================================
            # Step 8: 导出 JSON + 上传 MinIO
            # ================================================
            step_exp = await _create_step(db, task_uuid, "export")
            try:
                from services.exporter.json_exporter import export_json

                result_json_path = work_dir / "structured_result.json"
                export_json(structure_result, result_json_path)

                # 上传到 MinIO
                result_key = f"{task_id}/structured_result.json"
                minio_client.upload_file(
                    bucket=settings.minio_bucket_result,
                    object_key=result_key,
                    file_path=str(result_json_path),
                )

                task.result_path = result_key

                # 更新统计
                task.confidence_avg = summary["ocr_confidence_avg"]
                task.structure_score = summary["structure_score"]
                task.heading_count = summary["sections_found"]
                task.paragraph_count = summary["paragraphs_found"]
                task.table_count = summary["tables_found"]

                await _complete_step(db, step_exp, "completed",
                    metadata={"result_key": result_key, "file_size": result_json_path.stat().st_size})
                logger.info(f"[export] OK: {result_key}")

                # ---- 推送: 发布最终结果 ----
                publish_progress(task_id, "export", "completed", 93.0)
                publish_result(task_id, structure_result)
            except Exception as e:
                await _complete_step(db, step_exp, "failed", str(e))
                summary["errors"].append(f"export: {e}")
                # export 失败不中断整体

            # ================================================
            # Step 9: 回调通知
            # ================================================
            step_cb = await _create_step(db, task_uuid, "callback")
            if task.callback_url:
                try:
                    from services.exporter.callback import send_callback

                    callback_data = {
                        "task_id": task_id,
                        "status": "completed",
                        "filename": task.filename,
                        "page_count": task.page_count,
                        "confidence_avg": task.confidence_avg,
                        "structure_score": task.structure_score,
                        "heading_count": task.heading_count,
                        "paragraph_count": task.paragraph_count,
                        "table_count": task.table_count,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }

                    success = await send_callback(task.callback_url, callback_data)
                    if success:
                        task.callback_status = "sent"
                        await _complete_step(db, step_cb, "completed")
                        logger.info(f"[callback] OK: {task.callback_url}")
                        publish_progress(task_id, "callback", "completed", 100.0)
                    else:
                        task.callback_status = "failed"
                        await _complete_step(db, step_cb, "failed", "HTTP request failed")
                        logger.warning(f"[callback] FAIL: {task.callback_url}")
                except Exception as e:
                    task.callback_status = "failed"
                    await _complete_step(db, step_cb, "failed", str(e))
                    summary["errors"].append(f"callback: {e}")
            else:
                await _complete_step(db, step_cb, "completed", metadata={"skipped": "no callback_url"})
                publish_progress(task_id, "callback", "skipped", 100.0)

            # ================================================
            # 完成
            # ================================================
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

            return summary
        finally:
            # 清理工作目录（无论成功或失败），防磁盘泄漏
            if work_dir and work_dir.exists():
                import shutil
                try:
                    await asyncio.to_thread(shutil.rmtree, str(work_dir), True)
                    logger.debug(f"Cleaned work_dir: {work_dir}")
                except Exception:
                    pass

    # 使用独立的 Event Loop，避免与全局 Session Factory 跨 Loop 绑定
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        # 先处理残余的 asyncio 任务
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()


# ============================================================
# 文字 PDF 快速路径
# ============================================================

async def _run_text_pdf_path(db, task, task_uuid, pdf_local, work_dir, summary, structure_result):
    """文字 PDF 快速路径：直接提取结构化文本"""
    from services.preprocessor.text_pdf_extractor import text_extractor

    step_txt = await _create_step(db, task_uuid, "text_extraction")
    try:
        struct = text_extractor.extract_structured(pdf_local)
        structure_result.update(struct)
        structure_result["source_type"] = "text_pdf"

        summary["ocr_confidence_avg"] = 1.0

        all_blocks = []
        pages_blocks = []
        page_dimensions = []
        for page_data in struct.get("pages", []):
            page_blocks = page_data.get("blocks", [])
            pages_blocks.append(page_blocks)
            all_blocks.extend(page_blocks)
            page_dimensions.append((page_data.get("width", 0), page_data.get("height", 0)))

        if not all_blocks:
            structure_result["sections"] = []
            structure_result["lists"] = []
            structure_result["tables"] = []
            summary["sections_found"] = 0
            summary["paragraphs_found"] = 0
            summary["tables_found"] = 0
            summary["structure_score"] = 0.0
            await _complete_step(db, step_txt, "completed",
                metadata={"pages": struct.get("page_count", 0), "warning": "no_blocks"})
            logger.info(f"[text_extraction] OK: {struct.get('page_count', 0)} pages (no blocks)")
            publish_progress(str(task_uuid), "text_extraction", "completed", 50.0)
            return

        from services.structurer.heading_parser import parse_headings
        from services.structurer.paragraph_grouper import group_paragraphs
        from services.structurer.list_detector import detect_lists
        from services.structurer.cross_page_merger import merge_cross_page
        from services.structurer.header_footer_cleaner import clean_headers_footers
        from services.structurer.quality_scorer import score_structure

        heading_annotated = parse_headings(all_blocks)

        pages_cleaned = clean_headers_footers(pages_blocks, page_dimensions)
        all_blocks_clean = []
        for page in pages_cleaned:
            all_blocks_clean.extend(page)

        all_blocks_merged = merge_cross_page(pages_cleaned)
        all_blocks_flat = []
        for page in all_blocks_merged:
            all_blocks_flat.extend(page)

        grouped = group_paragraphs(all_blocks_flat, heading_annotated)

        lists = detect_lists(all_blocks_flat)

        text_ocr_summary = {
            "confidence_avg": 1.0,
            "total_pages": struct.get("page_count", 0),
            "pages": [{"page": i + 1, "confidence_avg": 1.0, "result_count": len(p.get("blocks", []))}
                      for i, p in enumerate(struct.get("pages", []))],
        }
        quality = score_structure(grouped, text_ocr_summary, lists, [])

        structure_result["sections"] = grouped.get("sections", [])
        structure_result["orphan_paragraphs"] = grouped.get("orphan_paragraphs", [])
        structure_result["total_sections"] = grouped.get("total_sections", 0)
        structure_result["total_paragraphs"] = grouped.get("total_paragraphs", 0)
        structure_result["lists"] = lists
        structure_result["tables"] = []
        structure_result["quality"] = quality

        summary["sections_found"] = grouped.get("total_sections", 0)
        summary["paragraphs_found"] = grouped.get("total_paragraphs", 0)
        summary["tables_found"] = 0
        summary["structure_score"] = quality.get("structure_score", 0.0)

        await _complete_step(db, step_txt, "completed",
            metadata={"pages": struct.get("page_count", 0)})
        logger.info(
            f"[text_extraction] OK: {struct.get('page_count', 0)} pages, "
            f"{grouped.get('total_sections', 0)} sections, "
            f"{grouped.get('total_paragraphs', 0)} paragraphs"
        )
        publish_progress(str(task_uuid), "text_extraction", "completed", 50.0)
    except Exception as e:
        await _complete_step(db, step_txt, "failed", str(e))
        await _fail_task(db, task, "TEXT_EXTRACT_ERROR", str(e))
        summary["status"] = "failed"
        summary["errors"].append(f"text_extraction: {e}")


# ============================================================
# 扫描 PDF 完整路径
# ============================================================

async def _run_scan_pdf_path(db, task, task_uuid, pdf_local, work_dir, summary, structure_result):
    """扫描 PDF 完整处理路径：拆页→增强→OCR→版面→结构化"""

    # ---- Step 3: 拆页 ----
    step_split = await _create_step(db, task_uuid, "split")
    image_paths = []
    try:
        from services.preprocessor.pdf_splitter import PDFSplitter
        use_cloud_ocr = settings.ocr_engine_type in ("bailian", "dashscope", "qwen")
        split_dpi = 150 if use_cloud_ocr else settings.preprocess_dpi
        splitter = PDFSplitter(dpi=split_dpi)
        pages_dir = work_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        image_paths = splitter.split_to_images(pdf_local, pages_dir)
        summary["pages_processed"] = len(image_paths)
        await _complete_step(db, step_split, "completed",
            metadata={"page_count": len(image_paths), "dpi": split_dpi})
        logger.info(f"[split] OK: {len(image_paths)} pages (dpi={split_dpi})")
        publish_progress(str(task_uuid), "split", "completed", 18.0)
    except Exception as e:
        await _complete_step(db, step_split, "failed", str(e))
        await _fail_task(db, task, "SPLIT_ERROR", str(e))
        summary["status"] = "failed"
        summary["errors"].append(f"split: {e}")
        return

    if not image_paths:
        await _fail_task(db, task, "SPLIT_ERROR", "No pages extracted")
        summary["status"] = "failed"
        return

    # ---- Step 4: 图像增强 ----
    enhanced_paths = image_paths
    use_cloud_ocr = settings.ocr_engine_type in ("bailian", "dashscope", "qwen")
    need_enhance = (
        settings.preprocess_denoise
        or settings.preprocess_deskew
        or settings.preprocess_crop_border
        or settings.preprocess_binary
        or settings.preprocess_target_short_side > 0
        or settings.preprocess_clahe_clip > 0
        or settings.preprocess_sharpen
        or settings.preprocess_morph_clean
    )

    if use_cloud_ocr:
        step_enh = await _create_step(db, task_uuid, "enhance")
        await _complete_step(db, step_enh, "completed",
            metadata={"skipped": True, "reason": "cloud_ocr_has_builtin_preprocessing"})
        logger.info("[enhance] SKIPPED: cloud OCR engine has built-in preprocessing")
        publish_progress(str(task_uuid), "enhance", "completed", 25.0)
    elif need_enhance:
        step_enh = await _create_step(db, task_uuid, "enhance")
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from services.preprocessor.image_enhancer import ImageEnhancer, Deskewer

            deskewer = Deskewer()

            enhancer = ImageEnhancer(
                denoise=settings.preprocess_denoise,
                binary=settings.preprocess_binary,
                crop_border=settings.preprocess_crop_border,
                target_short_side=settings.preprocess_target_short_side,
                clahe_clip=settings.preprocess_clahe_clip,
                sharpen=settings.preprocess_sharpen,
                morph_clean=settings.preprocess_morph_clean,
            )

            enhanced_dir = work_dir / "enhanced"
            enhanced_dir.mkdir(exist_ok=True)

            do_deskew = settings.preprocess_deskew

            def _enhance_one(i_img):
                idx, img_path = i_img
                denoised = enhanced_dir / f"page_{idx+1:04d}_clean.png"
                enhancer.enhance(img_path, denoised)
                if do_deskew:
                    deskewed = enhanced_dir / f"page_{idx+1:04d}.png"
                    deskewer.deskew(denoised, deskewed)
                    return (idx, deskewed)
                return (idx, denoised)

            enhanced_map = {}
            with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as pool:
                futures = {pool.submit(_enhance_one, (i, p)): i for i, p in enumerate(image_paths)}
                for future in as_completed(futures):
                    try:
                        idx, path = future.result()
                        enhanced_map[idx] = path
                    except Exception as exc:
                        logger.warning(f"[enhance] page failed: {exc}")

            enhanced_paths = [enhanced_map.get(i, image_paths[i]) for i in range(len(image_paths))]

            await _complete_step(db, step_enh, "completed",
                metadata={"enhanced_count": len(enhanced_paths)})
            logger.info(f"[enhance] OK: {len(enhanced_paths)} images")
            publish_progress(str(task_uuid), "enhance", "completed", 25.0)
        except Exception as e:
            logger.warning(f"[enhance] partial failure: {e}, using original images")
            await _complete_step(db, step_enh, "completed",
                metadata={"warning": str(e), "fallback": "original_images"})
            enhanced_paths = image_paths
            publish_progress(str(task_uuid), "enhance", "completed", 25.0)

    # ---- Step 5: OCR ----
    step_ocr = await _create_step(db, task_uuid, "ocr")
    ocr_summary = {}
    try:
        from services.ocr.batch_processor import OCRBatchProcessor
        ocr_processor = OCRBatchProcessor()
        ocr_dir = work_dir / "ocr"
        ocr_summary = ocr_processor.process_pages(enhanced_paths, ocr_dir)

        summary["ocr_confidence_avg"] = ocr_summary.get("confidence_avg", 0.0)

        await _complete_step(db, step_ocr, "completed",
            metadata={
                "confidence_avg": ocr_summary.get("confidence_avg", 0),
                "total_items": ocr_summary.get("total_text_items", 0),
            })
        logger.info(f"[ocr] OK: confidence={ocr_summary.get('confidence_avg', 0):.4f}")
        publish_progress(str(task_uuid), "ocr", "completed", 50.0)
    except Exception as e:
        await _complete_step(db, step_ocr, "failed", str(e))
        await _fail_task(db, task, "OCR_ERROR", str(e))
        summary["status"] = "failed"
        summary["errors"].append(f"ocr: {e}")
        return

    # ---- Step 6: 版面分析 ----
    step_layout = await _create_step(db, task_uuid, "layout")
    all_regions = []
    all_tables = []
    try:
        from services.layout.detector import layout_detector
        from services.layout.table_recognizer import recognize_table

        ocr_pages = ocr_summary.get("pages", [])
        for page_data in ocr_pages:
            ocr_results = page_data.get("results", [])
            page_num = page_data.get("page", 1)

            if not ocr_results:
                continue

            # 版面检测
            regions = layout_detector.detect(ocr_results)
            for region in regions:
                region["page"] = page_num
            all_regions.extend(regions)

            # 表格识别（对 table 类型区域）
            for region in regions:
                if region.get("type") == "table" and region.get("text_lines"):
                    table_result = recognize_table(region["text_lines"])
                    if table_result.get("rows", 0) > 0:
                        table_result["page"] = page_num
                        table_result["bbox"] = region.get("bbox", [])
                        all_tables.append(table_result)

        summary["tables_found"] = len(all_tables)
        await _complete_step(db, step_layout, "completed",
            metadata={"regions": len(all_regions), "tables": len(all_tables)})
        logger.info(f"[layout] OK: {len(all_regions)} regions, {len(all_tables)} tables")
        publish_progress(str(task_uuid), "layout", "completed", 70.0)
    except Exception as e:
        await _complete_step(db, step_layout, "failed", str(e))
        logger.warning(f"[layout] failed: {e}")
        summary["errors"].append(f"layout: {e}")
        # layout 失败不中断

    # ---- Step 7: 结构化 ----
    step_struct = await _create_step(db, task_uuid, "structure")
    try:
        from services.structurer.heading_parser import parse_headings
        from services.structurer.paragraph_grouper import group_paragraphs
        from services.structurer.list_detector import detect_lists
        from services.structurer.cross_page_merger import merge_cross_page
        from services.structurer.header_footer_cleaner import clean_headers_footers
        from services.structurer.quality_scorer import score_structure

        # 收集所有页面的文本块
        all_blocks = []
        pages_blocks = []
        for page_data in ocr_summary.get("pages", []):
            page_blocks = []
            for r in page_data.get("results", []):
                block = {
                    "text": r["text"],
                    "confidence": r["confidence"],
                    "bbox": r["bbox"],
                }
                page_blocks.append(block)
                all_blocks.append(block)
            pages_blocks.append(page_blocks)

        if not all_blocks:
            logger.warning("[structure] no blocks to process")
            await _complete_step(db, step_struct, "completed", metadata={"warning": "no_blocks"})
            structure_result["sections"] = []
            structure_result["lists"] = []
            structure_result["tables"] = []
            structure_result["source_type"] = "scan_pdf"
            return

        # 7a. 解析标题
        heading_annotated = parse_headings(all_blocks)

        # 7b. 清理页眉页脚
        pages_cleaned = clean_headers_footers(pages_blocks)
        all_blocks_clean = []
        for page in pages_cleaned:
            all_blocks_clean.extend(page)

        # 7c. 跨页合并
        all_blocks_merged = merge_cross_page(pages_cleaned)
        all_blocks_flat = []
        for page in all_blocks_merged:
            all_blocks_flat.extend(page)

        # 7d. 段落分组
        grouped = group_paragraphs(all_blocks_flat, heading_annotated)

        # 7e. 列表检测
        lists = detect_lists(all_blocks_flat)

        # 7f. 质量评分
        quality = score_structure(grouped, ocr_summary, lists, all_tables)

        # 汇总
        structure_result["sections"] = grouped.get("sections", [])
        structure_result["orphan_paragraphs"] = grouped.get("orphan_paragraphs", [])
        structure_result["total_sections"] = grouped.get("total_sections", 0)
        structure_result["total_paragraphs"] = grouped.get("total_paragraphs", 0)
        structure_result["lists"] = lists
        structure_result["tables"] = all_tables
        structure_result["quality"] = quality
        structure_result["source_type"] = "scan_pdf"

        summary["sections_found"] = grouped.get("total_sections", 0)
        summary["paragraphs_found"] = grouped.get("total_paragraphs", 0)
        summary["lists_found"] = len(lists)
        summary["structure_score"] = quality.get("structure_score", 0.0)

        await _complete_step(db, step_struct, "completed",
            metadata={
                "sections": grouped.get("total_sections", 0),
                "paragraphs": grouped.get("total_paragraphs", 0),
                "lists": len(lists),
                "score": quality.get("structure_score", 0),
            })
        logger.info(
            f"[structure] OK: {grouped.get('total_sections', 0)} sections, "
            f"{grouped.get('total_paragraphs', 0)} paragraphs, "
            f"score={quality.get('structure_score', 0):.4f}"
        )
        publish_progress(str(task_uuid), "structure", "completed", 88.0)
    except Exception as e:
        await _complete_step(db, step_struct, "failed", str(e))
        logger.warning(f"[structure] failed: {e}")
        summary["errors"].append(f"structure: {e}")
        # 结构失败不中断，保留空结构
        structure_result["sections"] = []
        structure_result["lists"] = []
        structure_result["tables"] = []
        structure_result["source_type"] = "scan_pdf"


# ============================================================
# DB 辅助函数
# ============================================================

async def _create_step(db, task_uuid: uuid.UUID, step_name: str) -> "TaskStep":
    """创建处理步骤记录"""
    from db.models import TaskStep

    step = TaskStep(
        task_id=task_uuid,
        step_name=step_name,
        status="processing",
        started_at=datetime.now(timezone.utc),
    )
    db.add(step)
    await db.commit()
    return step


async def _complete_step(
    db,
    step: "TaskStep",
    status: str,
    error_message: str | None = None,
    metadata: dict | None = None,
):
    """完成处理步骤"""
    step.status = status
    step.completed_at = datetime.now(timezone.utc)
    if step.started_at:
        step.duration_ms = int(
            (step.completed_at - step.started_at).total_seconds() * 1000
        )
    if error_message:
        step.error_message = error_message
    if metadata:
        step.step_metadata = {**step.step_metadata, **metadata}
    await db.commit()


async def _fail_task(db, task: "ScanTask", error_code: str, error_message: str):
    """标记任务失败"""
    task.status = "failed"
    task.error_code = error_code
    task.error_message = error_message
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
