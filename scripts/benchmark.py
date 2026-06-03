"""性能基准测试 — 各阶段耗时 / 吞吐量 / 置信度统计"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 项目根路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from config.settings import settings


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {s:.1f}s"


def benchmark(pdf_path: Path, output_path: Path | None = None) -> dict:
    """
    对单个 PDF 运行全管线性能基准测试。

    返回 dict:
        {
            "file": str,
            "stages": [{ "stage": str, "duration_s": float, "metadata": dict }],
            "total_duration_s": float,
            "pages": int,
            "throughput_ppm": float,   # pages per minute
            "timestamp": str,
        }
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    stages = []
    work_dir = Path(settings.archive_dir) / "benchmark" / pdf_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # Stage 1: PDF 分类
    # ============================================================
    logger.info("[1/7] Classifying PDF...")
    t0 = time.perf_counter()
    from services.preprocessor.pdf_classifier import PDFClassifier

    classifier = PDFClassifier()
    pdf_info = classifier.classify(pdf_path)
    elapsed = time.perf_counter() - t0

    stages.append({
        "stage": "classify",
        "duration_s": round(elapsed, 4),
        "metadata": {
            "page_count": pdf_info.page_count,
            "is_text_pdf": pdf_info.is_text_pdf,
            "file_size_bytes": pdf_path.stat().st_size,
        },
    })
    logger.info(f"  classify: {_format_duration(elapsed)} ({pdf_info.page_count} pages, "
                f"text_pdf={pdf_info.is_text_pdf})")

    pages = pdf_info.page_count
    total_pages = pages

    # ============================================================
    # Branch: 文字 PDF → 快速路径
    # ============================================================
    if pdf_info.is_text_pdf:
        # Stage 2a: 文本提取
        logger.info("[2/7] Extracting text (text PDF fast path)...")
        t0 = time.perf_counter()
        from services.preprocessor.text_pdf_extractor import text_extractor

        struct = text_extractor.extract_structured(pdf_path)
        elapsed = time.perf_counter() - t0

        heading_count = len(struct.get("heading_candidates", []))
        stages.append({
            "stage": "text_extraction",
            "duration_s": round(elapsed, 4),
            "metadata": {"headings_found": heading_count, "pages": struct.get("page_count", 0)},
        })
        logger.info(f"  text_extraction: {_format_duration(elapsed)} "
                    f"({heading_count} headings)")

        total_time = sum(s["duration_s"] for s in stages)
        result = {
            "file": str(pdf_path),
            "pipeline": "text_pdf_fast",
            "stages": stages,
            "total_duration_s": round(total_time, 4),
            "total_duration_human": _format_duration(total_time),
            "pages": total_pages,
            "throughput_ppm": round(total_pages / (total_time / 60), 1) if total_time > 0 else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        _print_summary(result)
        if output_path:
            _save_result(result, output_path)
        return result

    # ============================================================
    # Stage 2: 拆页
    # ============================================================
    logger.info("[2/7] Splitting PDF to images...")
    t0 = time.perf_counter()
    from services.preprocessor.pdf_splitter import PDFSplitter

    splitter = PDFSplitter()
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    image_paths = splitter.split_to_images(pdf_path, pages_dir)
    elapsed = time.perf_counter() - t0

    stages.append({
        "stage": "split",
        "duration_s": round(elapsed, 4),
        "metadata": {"pages": len(image_paths), "dpi": settings.preprocess_dpi},
    })
    logger.info(f"  split: {_format_duration(elapsed)} ({len(image_paths)} pages "
                f"→ {round(len(image_paths) / elapsed, 1) if elapsed > 0 else 0} ppm)")

    # ============================================================
    # Stage 3: 图像增强
    # ============================================================
    logger.info("[3/7] Enhancing images...")
    t0 = time.perf_counter()
    from services.preprocessor.image_enhancer import ImageEnhancer, Deskewer

    deskewer = Deskewer()

    enhancer = ImageEnhancer(
        denoise=settings.preprocess_denoise,
        binary=settings.preprocess_binary,
        crop_border=settings.preprocess_crop_border,
    )
    enhanced_dir = work_dir / "enhanced"
    enhanced_dir.mkdir(exist_ok=True)

    enhanced_paths = []
    for i, img_path in enumerate(image_paths):
        denoised = enhanced_dir / f"page_{i + 1:04d}_clean.png"
        enhancer.enhance(img_path, denoised)
        if settings.preprocess_deskew:
            deskewed = enhanced_dir / f"page_{i + 1:04d}.png"
            deskewer.deskew(denoised, deskewed)
            enhanced_paths.append(deskewed)
        else:
            enhanced_paths.append(denoised)

    elapsed = time.perf_counter() - t0
    per_page = elapsed / len(image_paths) if image_paths else 0

    stages.append({
        "stage": "enhance",
        "duration_s": round(elapsed, 4),
        "metadata": {
            "pages": len(enhanced_paths),
            "per_page_ms": round(per_page * 1000, 1),
            "denoise": settings.preprocess_denoise,
            "deskew": settings.preprocess_deskew,
            "crop_border": settings.preprocess_crop_border,
        },
    })
    logger.info(f"  enhance: {_format_duration(elapsed)} "
                f"({round(per_page * 1000, 1)} ms/page)")

    # ============================================================
    # Stage 4: OCR
    # ============================================================
    logger.info("[4/7] Running OCR...")
    t0 = time.perf_counter()
    from services.ocr.batch_processor import OCRBatchProcessor

    ocr_dir = work_dir / "ocr"
    ocr_processor = OCRBatchProcessor()
    ocr_summary = ocr_processor.process_pages(enhanced_paths, ocr_dir)
    elapsed = time.perf_counter() - t0

    confidence_values = []
    total_items = 0
    for page_data in ocr_summary.get("pages", []):
        for r in page_data.get("results", []):
            confidence_values.append(r.get("confidence", 0))
            total_items += 1

    avg_conf = ocr_summary.get("confidence_avg", 0.0)
    min_conf = min(confidence_values) if confidence_values else 0
    max_conf = max(confidence_values) if confidence_values else 0

    stages.append({
        "stage": "ocr",
        "duration_s": round(elapsed, 4),
        "metadata": {
            "pages": len(enhanced_paths),
            "total_text_items": total_items,
            "confidence_avg": round(avg_conf, 4),
            "confidence_min": round(min_conf, 4),
            "confidence_max": round(max_conf, 4),
            "ppm": round(len(enhanced_paths) / elapsed, 1) if elapsed > 0 else 0,
        },
    })
    logger.info(f"  ocr: {_format_duration(elapsed)} "
                f"(confidence: avg={avg_conf:.3f} min={min_conf:.3f} max={max_conf:.3f})")

    # ============================================================
    # Stage 5: 版面分析
    # ============================================================
    logger.info("[5/7] Layout analysis...")
    t0 = time.perf_counter()
    from services.layout.detector import layout_detector
    from services.layout.table_recognizer import recognize_table

    all_regions = []
    all_tables = []
    for page_data in ocr_summary.get("pages", []):
        ocr_results = page_data.get("results", [])
        page_num = page_data.get("page", 1)
        if not ocr_results:
            continue
        regions = layout_detector.detect(ocr_results)
        for region in regions:
            region["page"] = page_num
        all_regions.extend(regions)
        for region in regions:
            if region.get("type") == "table" and region.get("text_lines"):
                table_result = recognize_table(region["text_lines"])
                if table_result.get("rows", 0) > 0:
                    table_result["page"] = page_num
                    table_result["bbox"] = region.get("bbox", [])
                    all_tables.append(table_result)

    elapsed = time.perf_counter() - t0

    stages.append({
        "stage": "layout",
        "duration_s": round(elapsed, 4),
        "metadata": {"regions": len(all_regions), "tables": len(all_tables)},
    })
    logger.info(f"  layout: {_format_duration(elapsed)} "
                f"({len(all_regions)} regions, {len(all_tables)} tables)")

    # ============================================================
    # Stage 6: 结构化
    # ============================================================
    logger.info("[6/7] Structuring...")
    t0 = time.perf_counter()
    from services.structurer.heading_parser import parse_headings
    from services.structurer.paragraph_grouper import group_paragraphs
    from services.structurer.list_detector import detect_lists
    from services.structurer.cross_page_merger import merge_cross_page
    from services.structurer.header_footer_cleaner import clean_headers_footers
    from services.structurer.quality_scorer import score_structure

    # 收集所有文本块
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

    heading_annotated = parse_headings(all_blocks)
    pages_cleaned = clean_headers_footers(pages_blocks)
    all_blocks_merged = merge_cross_page(pages_cleaned)
    all_blocks_flat = []
    for page in all_blocks_merged:
        all_blocks_flat.extend(page)
    grouped = group_paragraphs(all_blocks_flat, heading_annotated)
    lists = detect_lists(all_blocks_flat)
    quality = score_structure(grouped, ocr_summary, lists, all_tables)
    elapsed = time.perf_counter() - t0

    stages.append({
        "stage": "structure",
        "duration_s": round(elapsed, 4),
        "metadata": {
            "sections": grouped.get("total_sections", 0),
            "paragraphs": grouped.get("total_paragraphs", 0),
            "lists": len(lists),
            "tables": len(all_tables),
            "score": quality.get("structure_score", 0),
        },
    })
    logger.info(f"  structure: {_format_duration(elapsed)} "
                f"({grouped.get('total_sections', 0)} sections, "
                f"{grouped.get('total_paragraphs', 0)} paragraphs, "
                f"score={quality.get('structure_score', 0):.3f})")

    # ============================================================
    # Stage 7: 导出 JSON
    # ============================================================
    logger.info("[7/7] Exporting JSON...")
    t0 = time.perf_counter()
    from services.exporter.json_exporter import export_json

    structure_result = {
        "sections": grouped.get("sections", []),
        "orphan_paragraphs": grouped.get("orphan_paragraphs", []),
        "total_sections": grouped.get("total_sections", 0),
        "total_paragraphs": grouped.get("total_paragraphs", 0),
        "lists": lists,
        "tables": all_tables,
        "quality": quality,
        "source_type": "scan_pdf",
    }
    result_path = work_dir / f"structured_result.json"
    export_json(structure_result, result_path)
    elapsed = time.perf_counter() - t0

    output_size = result_path.stat().st_size if result_path.exists() else 0
    stages.append({
        "stage": "export",
        "duration_s": round(elapsed, 4),
        "metadata": {"output_size_bytes": output_size, "path": str(result_path)},
    })
    logger.info(f"  export: {_format_duration(elapsed)} "
                f"({output_size:,} bytes → {result_path})")

    # ============================================================
    # 汇总
    # ============================================================
    total_time = sum(s["duration_s"] for s in stages)
    result = {
        "file": str(pdf_path),
        "pipeline": "scan_pdf_full",
        "stages": stages,
        "total_duration_s": round(total_time, 4),
        "total_duration_human": _format_duration(total_time),
        "pages": total_pages,
        "throughput_ppm": round(total_pages / (total_time / 60), 1) if total_time > 0 else 0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _print_summary(result)
    if output_path:
        _save_result(result, output_path)

    return result


def _print_summary(result: dict):
    """打印格式化汇总报告"""
    stages = result["stages"]
    total = result["total_duration_s"]

    print()
    print("=" * 62)
    print(f"  ScanStruct 性能基准报告")
    print(f"  文件: {result['file']}")
    print(f"  管线: {result['pipeline']}")
    print(f"  页数: {result['pages']}")
    print(f"  吞吐: {result['throughput_ppm']} 页/分钟")
    print(f"  总耗时: {result['total_duration_human']}")
    print("-" * 62)
    print(f"  {'阶段':<18} {'耗时':>10}  {'占比':>7}")
    print("-" * 62)

    for s in stages:
        pct = (s["duration_s"] / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {s['stage']:<18} {_format_duration(s['duration_s']):>10}  {pct:>5.1f}% {bar}")

    print("-" * 62)
    print(f"  {'总计':<18} {result['total_duration_human']:>10}  {'100.0%':>7}")
    print("=" * 62)
    print()


def _save_result(result: dict, path: Path):
    """将结果写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"Benchmark result saved → {path}")


def main():
    parser = argparse.ArgumentParser(
        description="ScanStruct 性能基准测试 — 逐阶段计时",
    )
    parser.add_argument(
        "pdf", type=str,
        help="待测试的 PDF 文件路径",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="可选：将结果 JSON 写入指定路径",
    )
    args = parser.parse_args()

    logger.info("ScanStruct Benchmark")
    logger.info(f"PDF: {args.pdf}")

    pdf_path = Path(args.pdf)
    output_path = Path(args.output) if args.output else None

    benchmark(pdf_path, output_path)


if __name__ == "__main__":
    main()
