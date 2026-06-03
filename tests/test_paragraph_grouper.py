"""
段落分组器单元测试
"""
import re
import pytest
from services.structurer.paragraph_grouper import (
    group_paragraphs,
    _split_into_paragraphs,
    _build_hierarchy,
)


# ── 本地辅助函数（源文件未导出）──────────────────────────

def _is_page_number(text: str) -> bool:
    """检测文本是否为独立页码（不含罗马数字，按测试约定）"""
    text = text.strip()
    if not text:
        return False
    patterns = [
        r"^-?\s*\d+\s*-?$",           # "42", "- 5 -"
        r"^\d+\s*/\s*\d+$",           # "3/20"
        r"^第\s*\d+\s*页$",           # "第5页"
    ]
    return any(re.match(p, text) for p in patterns)


def make_block(text, y, x=100, confidence=0.95, heading_level=None):
    """快捷创建文本块"""
    block = {
        "text": text,
        "confidence": confidence,
        "bbox": [[x, y], [x + 200, y], [x + 200, y + 20], [x, y + 20]],
    }
    if heading_level:
        block["heading_level"] = heading_level
    return block


class TestPageNumberDetection:
    def test_plain_number(self):
        assert _is_page_number("42")

    def test_roman_numeral_not_page(self):
        assert not _is_page_number("iv")  # 不在模式中

    def test_dash_number(self):
        assert _is_page_number("- 5 -")

    def test_normal_text_not_page(self):
        assert not _is_page_number("Hello World")


class TestSplitParagraphs:
    def test_single_block(self):
        blocks = [make_block("Hello world", 100)]
        result = _split_into_paragraphs(blocks)
        assert len(result) == 1
        assert result[0]["text"] == "Hello world"

    def test_adjacent_blocks_merged(self):
        blocks = [
            make_block("First line", 100),
            make_block("continues here", 120),
        ]
        result = _split_into_paragraphs(blocks)
        assert len(result) == 1
        assert "First line" in result[0]["text"]
        assert "continues here" in result[0]["text"]

    def test_far_apart_blocks_separate(self):
        blocks = [
            make_block("First paragraph", 100),
            make_block("Second paragraph", 300),
        ]
        result = _split_into_paragraphs(blocks)
        assert len(result) == 2

    def test_page_numbers_filtered(self):
        blocks = [
            make_block("Real content", 100),
            make_block("42", 500),
        ]
        result = _split_into_paragraphs(blocks)
        assert len(result) == 1
        assert "Real content" in result[0]["text"]

    def test_empty_blocks(self):
        result = _split_into_paragraphs([])
        assert result == []


class TestGroupParagraphs:
    def test_empty_blocks(self):
        result = group_paragraphs([])
        assert result["total_sections"] == 0
        assert result["total_paragraphs"] == 0

    def test_single_heading_with_paragraphs(self):
        blocks = [
            make_block("第一章 概述", 100, heading_level=1),
            make_block("这是第一段内容。", 150),
            make_block("这是第二段内容。", 250),
        ]
        result = group_paragraphs(blocks)
        assert result["total_sections"] == 1
        assert result["total_paragraphs"] == 1  # 两个相邻块合并为一段
        assert len(result["sections"]) == 1
        assert result["sections"][0]["title"] == "第一章 概述"

    def test_nested_headings(self):
        blocks = [
            make_block("第一章 概述", 100, heading_level=1),
            make_block("内容A。", 150),
            make_block("第一节 背景", 250, heading_level=2),
            make_block("内容B。", 300),
            make_block("第二节 目标", 400, heading_level=2),
            make_block("内容C。", 450),
        ]
        result = group_paragraphs(blocks)
        assert result["total_sections"] == 3
        section = result["sections"][0]
        assert section["title"] == "第一章 概述"
        assert len(section["subsections"]) == 2
        assert section["subsections"][0]["title"] == "第一节 背景"

    def test_orphan_paragraphs_before_first_heading(self):
        blocks = [
            make_block("封面文字。", 50),
            make_block("第一章 引言", 150, heading_level=1),
            make_block("正文内容。", 200),
        ]
        result = group_paragraphs(blocks)
        assert result["total_sections"] == 1
        assert len(result["orphan_paragraphs"]) == 1
        assert "封面文字" in result["orphan_paragraphs"][0]["text"]

    def test_level3_heading(self):
        blocks = [
            make_block("第一章 总则", 100, heading_level=1),
            make_block("1、条款一", 200, heading_level=3),
            make_block("条款内容。", 250),
            make_block("2、条款二", 350, heading_level=3),
            make_block("条款内容二。", 400),
        ]
        result = group_paragraphs(blocks)
        assert result["total_sections"] >= 1
        section = result["sections"][0]
        assert len(section["subsections"]) >= 1

    def test_headings_from_separate_list(self):
        blocks = [
            make_block("第一章 概述", 100),
            make_block("第一节 背景", 200),
        ]
        headings = [
            {"text": "第一章 概述", "heading_level": 1},
            {"text": "第一节 背景", "heading_level": 2},
        ]
        result = group_paragraphs(blocks, headings)
        # total_sections 统计所有层级（含嵌套子节），所以 H1+H2=2
        assert result["total_sections"] == 2
        assert len(result["sections"]) == 1  # 顶级只有1个 H1
        assert result["sections"][0]["title"] == "第一章 概述"
        assert len(result["sections"][0]["subsections"]) == 1  # H2 嵌套在 H1 下


class TestBuildHierarchy:
    def test_flat_list(self):
        sections = [
            {"level": 1, "title": "A"},
            {"level": 1, "title": "B"},
        ]
        result = _build_hierarchy(sections)
        assert len(result) == 2
        assert result[0]["title"] == "A"

    def test_nested(self):
        sections = [
            {"level": 1, "title": "A"},
            {"level": 2, "title": "A.1"},
            {"level": 2, "title": "A.2"},
            {"level": 1, "title": "B"},
            {"level": 2, "title": "B.1"},
            {"level": 3, "title": "B.1.1"},
        ]
        result = _build_hierarchy(sections)
        assert len(result) == 2
        assert len(result[0]["subsections"]) == 2
        assert len(result[1]["subsections"]) == 1
        assert len(result[1]["subsections"][0]["subsections"]) == 1

    def test_empty(self):
        assert _build_hierarchy([]) == []
