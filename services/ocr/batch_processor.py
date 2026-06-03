"""
OCR 流式处理器
所有页面一次性提交到线程池，消除批次边界等待
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from config.settings import settings
from services.ocr.engine import ocr_engine


class OCRBatchProcessor:
    """OCR 流式处理器"""

    def __init__(self, batch_size: int | None = None):
        self.batch_size = batch_size if batch_size is not None else settings.ocr_batch_size

    def process_pages(
        self,
        page_images: list[Path],
        output_dir: Path,
    ) -> dict:
        """
        流式处理所有页面图片
        一次性提交全部页面到线程池，消除批次边界等待
        返回: {
            "total_pages": int,
            "pages": [{"page": N, "results": [...], "confidence_avg": float}, ...],
            "confidence_avg": float,
        }
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        all_pages = []
        total_confidence = 0.0
        total_results = 0

        logger.info(f"OCR streaming: {len(page_images)} pages with {getattr(ocr_engine, '_max_concurrent', 6)} workers")
        batch_results = ocr_engine.recognize_batch(page_images)

        for j, results in enumerate(batch_results):
            page_num = j + 1
            confidence_avg = 0.0
            if results:
                confidence_avg = sum(r["confidence"] for r in results) / len(results)
                total_confidence += sum(r["confidence"] for r in results)
                total_results += len(results)

            page_data = {
                "page": page_num,
                "image": page_images[j].name,
                "results": results,
                "result_count": len(results),
                "confidence_avg": round(confidence_avg, 4),
            }
            all_pages.append(page_data)

            ocr_engine.save_result(
                results,
                output_dir / f"page_{page_num:04d}.json",
            )

        overall_confidence = total_confidence / total_results if total_results > 0 else 0.0

        summary = {
            "total_pages": len(page_images),
            "pages": all_pages,
            "confidence_avg": round(overall_confidence, 4),
            "total_text_items": total_results,
        }

        logger.info(
            f"OCR complete: {len(page_images)} pages | "
            f"avg confidence: {overall_confidence:.4f} | "
            f"total items: {total_results}"
        )

        return summary
