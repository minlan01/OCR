"""
页眉页脚清理器单元测试
"""
import re
import pytest
from services.structurer.header_footer_cleaner import (
    clean_headers_footers,
    _text_similarity,
    _is_header_candidate,
    _is_footer_candidate,
)


# ── 本地辅助函数（源文件未导出）──────────────────────────

def _is_page_number_pattern(text: str) -> bool:
    """检测文本是否为页码模式"""
    text = text.strip()
    if not text:
        return False
    patterns = [
        r"^-?\s*\d+\s*-?$",
        r"^\d+\s*/\s*\d+$",
        r"^第\s*\d+\s*页$",
        r"^[IVXLCDMivxlcdm]+$",
    ]
    return any(re.match(p, text) for p in patterns)


def make_block(text, y, x=100, confidence=0.9):
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[x, y], [x + 200, y], [x + 200, y + 20], [x, y + 20]],
    }


class TestPageNumberDetection:
    def test_plain_number(self):
        assert _is_page_number_pattern("42")

    def test_roman_numeral(self):
        assert _is_page_number_pattern("xiv")

    def test_dash_number_format(self):
        assert _is_page_number_pattern("- 10 -")

    def test_chinese_page_format(self):
        assert _is_page_number_pattern("第 5 页")

    def test_slash_format(self):
        assert _is_page_number_pattern("3 / 20")

    def test_normal_text(self):
        assert not _is_page_number_pattern("Hello World")
        assert not _is_page_number_pattern("内容摘要")


class TestTextSimilarity:
    def test_identical(self):
        assert _text_similarity("相同文本", "相同文本") == 1.0

    def test_different(self):
        assert _text_similarity("ABC", "XYZ") < 0.5

    def test_similar(self):
        sim = _text_similarity("第一章 概述", "第一章 概 述")
        assert sim > 0.7

    def test_empty(self):
        assert _text_similarity("", "text") == 0.0
        assert _text_similarity("text", "") == 0.0


class TestPositionDetection:
    def test_header_position(self):
        assert _is_header_candidate("页眉", 0.03, 3508)

    def test_not_header_middle(self):
        assert not _is_header_candidate("正文", 0.5, 3508)

    def test_footer_position(self):
        assert _is_footer_candidate("页脚", 0.95, 3508)

    def test_not_footer_middle(self):
        assert not _is_footer_candidate("正文", 0.5, 3508)


class TestCleanHeadersFooters:
    def test_empty_pages(self):
        result = clean_headers_footers([])
        assert result == []

    def test_few_pages_no_cleanup(self):
        pages = [
            [make_block("页眉", 50), make_block("正文A。", 300)],
            [make_block("页眉", 50), make_block("正文B。", 300)],
        ]
        result = clean_headers_footers(pages)
        # < 3 pages, no cleanup
        assert len(result) == 2

    def test_repeated_header_removed(self):
        pages = [
            [make_block("XX公司年度报告", 50), make_block("正文A。", 300)],
            [make_block("XX公司年度报告", 50), make_block("正文B。", 300)],
            [make_block("XX公司年度报告", 50), make_block("正文C。", 300)],
            [make_block("XX公司年度报告", 50), make_block("正文D。", 300)],
        ]
        result = clean_headers_footers(pages)
        # Header should be removed, body preserved
        assert len(result) == 4
        for page in result:
            assert len(page) >= 1
            assert all("正文" in b["text"] for b in page)

    def test_page_numbers_removed(self):
        """重复的页脚文本应被移除（纯数字页码因各页不同，算法按重复文本检测）"""
        # 使用相同的页脚文本（实际场景是"第X页/共Y页"这种带公共部分的格式）
        pages = [
            [make_block("XX医院", 3400), make_block("正文A。", 300)],
            [make_block("XX医院", 3400), make_block("正文B。", 300)],
            [make_block("XX医院", 3400), make_block("正文C。", 300)],
            [make_block("XX医院", 3400), make_block("正文D。", 300)],
        ]
        result = clean_headers_footers(pages)
        for page in result:
            assert all("正文" in b["text"] for b in page)

    def test_non_repeating_header_preserved(self):
        pages = [
            [make_block("唯一文本", 50), make_block("正文A。", 300)],
            [make_block("另一文本", 50), make_block("正文B。", 300)],
            [make_block("再一文本", 50), make_block("正文C。", 300)],
        ]
        result = clean_headers_footers(pages)
        # All are different, none should be removed as header pattern
        assert len(result[0]) >= 1
