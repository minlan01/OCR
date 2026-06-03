"""
纯文字 PDF 提取器单元测试
覆盖 TextPDFExtractor.extract 和 extract_structured
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.preprocessor.text_pdf_extractor import TextPDFExtractor, text_extractor


# ── Helpers ────────────────────────────────────────────────

def _make_mock_page(page_num, mode_text, mode_blocks, mode_dict):
    """构造 mock PDF 页面，支持 get_text 的不同 mode"""
    page = MagicMock()
    page.rect.width = 595
    page.rect.height = 842

    def get_text(mode="text"):
        if mode == "text":
            return mode_text
        elif mode == "blocks":
            return mode_blocks
        elif mode == "dict":
            return mode_dict
        return ""

    page.get_text.side_effect = get_text
    return page


def _make_blocks_output(blocks):
    """构造 get_text('blocks') 返回值"""
    result = []
    for b in blocks:
        result.append((
            b["bbox"][0], b["bbox"][1], b["bbox"][2], b["bbox"][3],
            b["text"],
            b.get("type", 0),
            b.get("block_no", 0),
        ))
    return result


def _make_dict_output(blocks):
    """构造 get_text('dict') 返回值"""
    result_blocks = []
    for b in blocks:
        span = {
            "text": b["text"],
            "size": b.get("font_size", 12),
            "font": b.get("font_name", "TimesNewRoman"),
        }
        line = {"spans": [span], "bbox": b["bbox"]}
        result_blocks.append({"type": 0, "lines": [line]})
    return {"blocks": result_blocks}


def _setup_mock_fitz(page_count, pages_config):
    """构造 mock fitz 和 doc

    pages_config: list of (mode_text, mode_blocks, mode_dict) per page
    """
    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_count = page_count
    mock_pages = [
        _make_mock_page(i, t, b, d)
        for i, (t, b, d) in enumerate(pages_config)
    ]
    mock_doc.__getitem__.side_effect = mock_pages
    mock_fitz.open.return_value = mock_doc
    return mock_fitz


# ── TextPDFExtractor.extract ───────────────────────────────

class TestTextPDFExtractorExtract:
    def test_extract_single_page(self):
        blocks = [{"bbox": [50, 50, 200, 70], "text": "Hello World"}]
        mock_fitz = _setup_mock_fitz(1, [
            ("Hello World", _make_blocks_output(blocks), _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract(Path("test.pdf"))

        assert result["page_count"] == 1
        assert len(result["pages"]) == 1
        page = result["pages"][0]
        assert page["page"] == 1
        assert "Hello World" in page["text"]
        assert len(page["blocks"]) == 1
        assert page["blocks"][0]["text"] == "Hello World"

    def test_extract_multi_page(self):
        blocks_p1 = [{"bbox": [50, 50, 200, 70], "text": "Page One"}]
        blocks_p2 = [{"bbox": [50, 50, 200, 70], "text": "Page Two"}]
        mock_fitz = _setup_mock_fitz(2, [
            ("Page One", _make_blocks_output(blocks_p1), _make_dict_output(blocks_p1)),
            ("Page Two", _make_blocks_output(blocks_p2), _make_dict_output(blocks_p2)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract(Path("test.pdf"))

        assert result["page_count"] == 2
        assert result["pages"][0]["page"] == 1
        assert result["pages"][1]["page"] == 2

    def test_extract_skips_non_text_blocks(self):
        """type != 0 的块（图片等）应被跳过"""
        text_block = [{"bbox": [50, 50, 200, 70], "text": "visible"}]
        # 模拟 blocks 输出包含一个图片块
        blocks_output = [
            (50, 50, 200, 70, "visible", 0, 0),
            (60, 100, 190, 200, "image_data", 1, 1),
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("visible", blocks_output, _make_dict_output(text_block)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract(Path("test.pdf"))

        assert len(result["pages"][0]["blocks"]) == 1

    def test_extract_empty_pdf(self):
        mock_fitz = _setup_mock_fitz(0, [])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract(Path("empty.pdf"))

        assert result["page_count"] == 0
        assert result["pages"] == []


# ── TextPDFExtractor.extract_structured ────────────────────

class TestTextPDFExtractorStructured:
    def test_extract_structured_basic(self):
        """基本结构化提取 — 含字体大小和粗体判定"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "Chapter 1 Title", "font_size": 24, "font_name": "Arial-Bold"},
            {"bbox": [50, 100, 500, 120], "text": "Normal text content.", "font_size": 12, "font_name": "TimesNewRoman"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        assert result["page_count"] == 1
        assert result["pages"][0]["blocks"][0]["is_bold"] is True
        assert result["pages"][0]["blocks"][1]["is_bold"] is False

    def test_extract_structured_font_distribution(self):
        """字体大小分布统计"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "Title", "font_size": 24, "font_name": "Arial"},
            {"bbox": [50, 100, 500, 120], "text": "Body", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 140, 500, 160], "text": "More", "font_size": 12, "font_name": "Arial"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        dist = result["font_size_distribution"]
        sizes = {d["size"]: d["count"] for d in dist}
        assert sizes[24] == 1
        assert sizes[12] == 2

    def test_extract_structured_heading_candidates(self):
        """标题候选推断 — 大字体和粗体均应被识别"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "Big Title", "font_size": 30, "font_name": "Arial"},
            {"bbox": [50, 80, 500, 100], "text": "Small bold", "font_size": 12, "font_name": "Arial-Bold"},
            {"bbox": [50, 120, 500, 140], "text": "Normal", "font_size": 10, "font_name": "Arial"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        candidates = result["heading_candidates"]
        texts = {c["text"] for c in candidates}
        assert "Big Title" in texts
        assert "Small bold" in texts

    def test_extract_structured_single_font_size(self):
        """只有一种字体大小时无标题候选"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "All same", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 80, 500, 100], "text": "All same", "font_size": 12, "font_name": "Arial"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        assert result["heading_candidates"] == []

    def test_extract_structured_skips_empty_lines(self):
        """空行被过滤"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 80, 500, 100], "text": "   ", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 120, 500, 140], "text": "Real text", "font_size": 12, "font_name": "Arial"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        assert len(result["pages"][0]["blocks"]) == 1
        assert result["pages"][0]["blocks"][0]["text"] == "Real text"

    def test_extract_structured_black_font_also_bold(self):
        """"black" 在字体名中也判定为粗体"""
        blocks = [
            {"bbox": [50, 40, 500, 70], "text": "Bold Black", "font_size": 14, "font_name": "Arial-Black"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        assert result["pages"][0]["blocks"][0]["is_bold"] is True

    def test_extract_structured_reading_order(self):
        """页面 blocks 按 y 坐标排序（阅读顺序）"""
        blocks = [
            {"bbox": [50, 200, 500, 220], "text": "Bottom", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 40, 500, 60], "text": "Top", "font_size": 12, "font_name": "Arial"},
            {"bbox": [50, 120, 500, 140], "text": "Middle", "font_size": 12, "font_name": "Arial"},
        ]
        mock_fitz = _setup_mock_fitz(1, [
            ("text", [], _make_dict_output(blocks)),
        ])

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            extractor = TextPDFExtractor()
            result = extractor.extract_structured(Path("test.pdf"))

        page_blocks = result["pages"][0]["blocks"]
        assert page_blocks[0]["text"] == "Top"
        assert page_blocks[1]["text"] == "Middle"
        assert page_blocks[2]["text"] == "Bottom"


# ── 全局单例 ──────────────────────────────────────────────

class TestGlobalSingleton:
    def test_text_extractor_is_instance(self):
        assert isinstance(text_extractor, TextPDFExtractor)
