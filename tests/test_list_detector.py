"""
列表检测器单元测试
"""
import pytest
from services.structurer.list_detector import detect_lists, _match_list_item


def make_block(text, y, x=100, confidence=0.9):
    """快捷创建文本块"""
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[x, y], [x + 200, y], [x + 200, y + 20], [x, y + 20]],
    }


class TestMatchListItem:
    def test_arabic_numbered_dot(self):
        result = _match_list_item("1. 项目内容")
        assert result is not None
        assert result[0] == "numbered_arabic"
        assert result[1] == "1"
        assert result[2] == "项目内容"

    def test_arabic_numbered_chinese_comma(self):
        result = _match_list_item("3、第三项")
        assert result is not None
        assert result[0] == "numbered_arabic"
        assert result[1] == "3"

    def test_parenthesized_arabic(self):
        result = _match_list_item("（5）第五项")
        assert result is not None
        assert result[0] == "numbered_arabic"

    def test_chinese_numbered(self):
        result = _match_list_item("三、分析结果")
        assert result is not None
        assert result[0] == "numbered_chinese"
        assert result[1] == "三"

    def test_lettered(self):
        result = _match_list_item("a) 选项A")
        assert result is not None
        assert result[0] == "lettered_lower"
        assert result[1] == "a"

    def test_upper_lettered(self):
        result = _match_list_item("B. 选项B")
        assert result is not None
        assert result[0] == "lettered_upper"

    def test_bulleted_dash(self):
        result = _match_list_item("- 要点说明")
        assert result is not None
        assert result[0] == "bulleted"

    def test_bulleted_dot(self):
        result = _match_list_item("• 要点")
        assert result is not None
        assert result[0] == "bulleted"

    def test_not_a_list(self):
        result = _match_list_item("这是一个普通句子。")
        assert result is None

    def test_empty_text(self):
        result = _match_list_item("")
        assert result is None


class TestDetectLists:
    def test_empty_blocks(self):
        result = detect_lists([])
        assert result == []

    def test_single_list(self):
        blocks = [
            make_block("1. 第一项", 100),
            make_block("2. 第二项", 150),
            make_block("3. 第三项", 200),
        ]
        result = detect_lists(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "numbered_arabic"
        assert result[0]["item_count"] == 3

    def test_mixed_list_not_merged(self):
        blocks = [
            make_block("1. 编号项", 100),
            make_block("- 符号项", 150),
        ]
        result = detect_lists(blocks)
        assert len(result) == 0  # 少于2项的列表被丢弃

    def test_bulleted_list(self):
        blocks = [
            make_block("- 要点一", 100),
            make_block("- 要点二", 150),
            make_block("- 要点三", 200),
        ]
        result = detect_lists(blocks)
        assert len(result) == 1
        assert result[0]["type"] == "bulleted"

    def test_list_interrupted_by_text(self):
        blocks = [
            make_block("1. 第一项", 100),
            make_block("2. 第二项", 150),
            make_block("这是一段普通文本。", 200),
            make_block("3. 第三项", 250),
        ]
        result = detect_lists(blocks)
        # 第一组应该有2项（满足≥2），第二组只有1项被丢弃
        assert len(result) == 1
        assert result[0]["item_count"] == 2

    def test_confidence_avg(self):
        blocks = [
            make_block("1. 项A", 100, confidence=0.8),
            make_block("2. 项B", 150, confidence=0.9),
            make_block("3. 项C", 200, confidence=1.0),
        ]
        result = detect_lists(blocks)
        assert len(result) == 1
        assert 0.85 < result[0]["confidence_avg"] < 0.95

    def test_single_item_not_a_list(self):
        blocks = [
            make_block("1. 只有一项", 100),
        ]
        result = detect_lists(blocks)
        assert result == []
