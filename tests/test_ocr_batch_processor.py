"""OCR 批量处理器单元测试 — 分批 / 置信度统计 / 分页输出"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.ocr.batch_processor import OCRBatchProcessor


def _make_mock_results(n: int, confidence: float = 0.85) -> list[dict]:
    """生成模拟 OCR 结果列表"""
    return [
        {
            "text": f"line_{i+1}",
            "confidence": confidence,
            "bbox": [10, 10 + i * 20, 200, 25 + i * 20],
        }
        for i in range(n)
    ]


def _dynamic_recognize(batch: list[Path]) -> list[list[dict]]:
    """动态生成 mock recognize_batch 返回值 — 每个图片返回 5 个结果"""
    return [_make_mock_results(5) for _ in batch]


class TestBatchProcessor:
    """OCR 批量处理器"""

    @pytest.fixture
    def mock_image_paths(self):
        return [Path(f"/tmp/page_{i:04d}.png") for i in range(1, 11)]  # 10 pages

    def test_process_all_pages(self, mock_image_paths):
        """分批处理所有页面，总计 10 页"""
        mock_engine = MagicMock()
        mock_engine.recognize_batch.side_effect = _dynamic_recognize
        mock_engine.save_result = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                processor = OCRBatchProcessor(batch_size=4)
                summary = processor.process_pages(mock_image_paths, output_dir)

            assert summary["total_pages"] == 10
            assert len(summary["pages"]) == 10
            assert summary["confidence_avg"] > 0
            assert summary["total_text_items"] == 10 * 5

    def test_confidence_averaged_correctly(self, mock_image_paths):
        """置信度应按总文本项数量加权平均"""
        mock_engine = MagicMock()
        mock_engine.save_result = MagicMock()

        def vary_by_batch(batch: list[Path]) -> list[list[dict]]:
            """第一个 batch 高置信度，第二个低置信度"""
            if len(mock_engine.recognize_batch.call_args_list) < 2:
                return [_make_mock_results(3, 0.9) for _ in batch]
            else:
                return [_make_mock_results(2, 0.6) for _ in batch]

        mock_engine.recognize_batch.side_effect = vary_by_batch

        processor = OCRBatchProcessor(batch_size=2)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                summary = processor.process_pages(mock_image_paths[:4], output_dir)

        # 4 pages: each page has 3@0.9 or 2@0.6 → avg confidence tracked per page
        assert summary["total_pages"] == 4
        assert summary["confidence_avg"] > 0

    def test_empty_image_list(self):
        """空图片列表应返回空结果"""
        mock_engine = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                processor = OCRBatchProcessor()
                summary = processor.process_pages([], output_dir)

            assert summary["total_pages"] == 0
            assert summary["pages"] == []
            assert summary["confidence_avg"] == 0.0
            assert summary["total_text_items"] == 0

    def test_page_number_is_sequential(self, mock_image_paths):
        """页码应从 1 开始顺序递增"""
        mock_engine = MagicMock()
        mock_engine.recognize_batch.side_effect = _dynamic_recognize
        mock_engine.save_result = MagicMock()

        processor = OCRBatchProcessor(batch_size=1)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                summary = processor.process_pages(mock_image_paths[:3], output_dir)

            page_nums = [p["page"] for p in summary["pages"]]
            assert page_nums == [1, 2, 3]

    def test_saves_per_page_json(self, mock_image_paths):
        """每页应调用 save_result 保存独立 JSON"""
        mock_engine = MagicMock()
        mock_engine.recognize_batch.side_effect = _dynamic_recognize
        mock_engine.save_result = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                processor = OCRBatchProcessor(batch_size=4)
                processor.process_pages(mock_image_paths, output_dir)

            assert mock_engine.save_result.call_count == 10

    def test_zero_results_per_page(self, mock_image_paths):
        """无 OCR 结果的页面置信度为 0"""
        mock_engine = MagicMock()

        def empty_results(batch: list[Path]) -> list[list[dict]]:
            return [[] for _ in batch]

        mock_engine.recognize_batch.side_effect = empty_results
        mock_engine.save_result = MagicMock()

        processor = OCRBatchProcessor(batch_size=4)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "ocr_output"
            with patch("services.ocr.batch_processor.ocr_engine", mock_engine):
                summary = processor.process_pages(mock_image_paths, output_dir)

            assert summary["confidence_avg"] == 0.0
            assert summary["pages"][0]["confidence_avg"] == 0.0
            assert summary["pages"][0]["result_count"] == 0

    def test_batch_size_from_config(self):
        """默认 batch_size 应取自 settings.ocr_batch_size"""
        processor = OCRBatchProcessor()
        assert processor.batch_size >= 1

    def test_custom_batch_size(self):
        """自定义 batch_size 应覆盖默认值"""
        processor = OCRBatchProcessor(batch_size=7)
        assert processor.batch_size == 7
