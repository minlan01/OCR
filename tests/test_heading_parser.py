"""
标题层级解析测试
覆盖 services/structurer/heading_parser.py 全部 5 级中文标题模式
"""
import pytest
from services.structurer.heading_parser import (
    HEADING_PATTERNS,
    detect_heading_level,
    parse_headings,
)


class TestHeadingLevelDetection:
    """detect_heading_level 单文本级测试"""

    # ── H1: 第X章 / 第X篇 / 第X部 ──
    @pytest.mark.parametrize("text,expected", [
        ("第一章 概述", 1),
        ("第十二章 法律责任", 1),
        ("第3章 技术规范", 1),
        ("第一篇 总则", 1),
        ("第5部 附则", 1),
    ])
    def test_h1_chinese_chapter_patterns(self, text, expected):
        assert detect_heading_level(text) == expected

    # ── H2: 第X节 / 第X条 / X、 ──
    @pytest.mark.parametrize("text,expected", [
        ("第一节 定义", 2),
        ("第三条 适用范围", 2),
        ("一、项目背景", 2),
        ("九、其他事项", 2),
    ])
    def test_h2_section_patterns(self, text, expected):
        assert detect_heading_level(text) == expected

    # ── H3: 1、 / 1. / （X） ──
    @pytest.mark.parametrize("text,expected", [
        ("1、步骤说明", 3),
        ("15、附录", 3),
        ("1. 执行标准", 3),
        ("（一）基本原则", 3),
        ("（三）例外情况", 3),
    ])
    def test_h3_numbered_patterns(self, text, expected):
        assert detect_heading_level(text) == expected

    # ── H4: （1） / 1.1 ──
    @pytest.mark.parametrize("text,expected", [
        ("（1）数据采集", 4),
        ("（15）结果校验", 4),
        ("1.1 环境配置", 4),
        ("3.2 性能调优", 4),
    ])
    def test_h4_subsection_patterns(self, text, expected):
        assert detect_heading_level(text) == expected

    # ── H5: 1.1.1 ──
    @pytest.mark.parametrize("text,expected", [
        ("1.1.1 详细说明", 5),
        ("2.3.5 异常处理", 5),
    ])
    def test_h5_deep_patterns(self, text, expected):
        assert detect_heading_level(text) == expected

    # ── Non-heading texts ──
    @pytest.mark.parametrize("text", [
        "这是普通正文内容。",
        "扫描件结构化处理系统",
        "Table of Contents",
        "",
        "   ",
        "注：特殊说明",
    ])
    def test_non_heading_texts(self, text):
        assert detect_heading_level(text) is None

    def test_detect_none_on_ambiguous(self):
        """不应将普通数字开头误判为标题"""
        assert detect_heading_level("12345 编号段落") is None
        assert detect_heading_level("10月1日生效") is None


class TestParseHeadings:
    """parse_headings 批量解析测试"""

    def test_parse_headings_returns_all_with_levels(self):
        blocks = [
            {"text": "第一章 总则", "confidence": 0.99, "bbox": [[100, 0], [300, 0], [300, 20], [100, 20]]},
            {"text": "第一条 目的", "confidence": 0.95, "bbox": [[100, 30], [280, 30], [280, 50], [100, 50]]},
            {"text": "1、适用范围", "confidence": 0.93, "bbox": [[110, 60], [280, 60], [280, 80], [110, 80]]},
        ]
        result = parse_headings(blocks)
        assert len(result) == 3
        assert result[0]["heading_level"] == 1
        assert result[1]["heading_level"] == 2
        assert result[2]["heading_level"] == 3

    def test_parse_headings_preserves_original_fields(self):
        blocks = [
            {"text": "一、引言", "confidence": 0.97, "bbox": [[0, 0], [200, 0], [200, 20], [0, 20]], "page": 1},
        ]
        result = parse_headings(blocks)
        assert result[0]["text"] == "一、引言"
        assert result[0]["confidence"] == 0.97
        assert result[0]["page"] == 1
        assert result[0]["heading_level"] == 2

    def test_parse_headings_mixed_content(self):
        """混合标题与正文，全部返回，标题带 heading_level"""
        blocks = [
            {"text": "这是正文内容。", "confidence": 0.90, "bbox": [[100, 300], [400, 300], [400, 320], [100, 320]]},
            {"text": "第二章 数据采集", "confidence": 0.98, "bbox": [[100, 330], [350, 330], [350, 350], [100, 350]]},
            {"text": "又是一段正文，描述采集过程。", "confidence": 0.88, "bbox": [[100, 360], [400, 360], [400, 380], [100, 380]]},
            {"text": "第一节 传感器选型", "confidence": 0.96, "bbox": [[100, 390], [350, 390], [350, 410], [100, 410]]},
        ]
        result = parse_headings(blocks)
        assert len(result) == 4
        # 正文无 heading_level
        assert "heading_level" not in result[0]
        # 标题带 heading_level
        assert result[1]["text"] == "第二章 数据采集"
        assert result[1]["heading_level"] == 1
        assert result[3]["text"] == "第一节 传感器选型"
        assert result[3]["heading_level"] == 2

    def test_parse_headings_empty_blocks(self):
        assert parse_headings([]) == []

    def test_parse_headings_strips_whitespace(self):
        blocks = [
            {"text": "  第一章 概述  ", "confidence": 0.95, "bbox": [[0, 0], [200, 0], [200, 20], [0, 20]]},
        ]
        result = parse_headings(blocks)
        assert len(result) == 1
        assert result[0]["heading_level"] == 1

    def test_parse_headings_no_headings(self):
        """无标题时返回原块，不添加 heading_level（y>200 避免误判为页面顶部）"""
        blocks = [
            {"text": "普通段落一", "confidence": 0.9, "bbox": [[0, 200], [200, 220]]},
            {"text": "普通段落二", "confidence": 0.9, "bbox": [[0, 230], [200, 250]]},
        ]
        result = parse_headings(blocks)
        assert len(result) == 2
        for block in result:
            assert "heading_level" not in block


class TestHeadingPatternsRegistry:
    """验证 HEADING_PATTERNS 注册表完整性"""

    def test_all_five_levels_defined(self):
        for level in range(1, 6):
            assert level in HEADING_PATTERNS, f"Level {level} missing from HEADING_PATTERNS"
            assert len(HEADING_PATTERNS[level]) > 0, f"Level {level} has no patterns"

    def test_patterns_are_valid_regex(self):
        import re
        for level, patterns in HEADING_PATTERNS.items():
            for pat in patterns:
                try:
                    re.compile(pat)
                except re.error as e:
                    pytest.fail(f"Level {level} pattern '{pat}' is invalid regex: {e}")

    def test_h1_does_not_capture_h4(self):
        """H1 模式不应匹配 1.1.1 格式"""
        h1_texts = ["1. 概述", "（1）细节", "1.1 配置"]
        for text in h1_texts:
            level = detect_heading_level(text)
            assert level != 1, f"'{text}' should not be level 1"
