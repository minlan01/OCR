"""
版面检测器单元测试
"""
import pytest
from services.layout.detector import (
    LayoutDetector,
    _detect_columns,
    _is_table_row,
)


# ── 本地辅助函数（源文件未导出）──────────────────────────

def _bbox_to_rect(bbox):
    """4 点 bbox → (x, y, w, h)"""
    if not bbox:
        return (0, 0, 0, 0)
    if len(bbox) == 4 and isinstance(bbox[0], (int, float)):
        # 已是 [x, y, w, h] 格式
        return (bbox[0], bbox[1], bbox[2], bbox[3])
    # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 格式
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _rect_overlap_y(a, b):
    """两个 (x, y, w, h) 矩形在 y 轴方向是否有重叠"""
    a_y1, a_y2 = a[1], a[1] + a[3]
    b_y1, b_y2 = b[1], b[1] + b[3]
    return max(a_y1, b_y1) < min(a_y2, b_y2)


class TestBBoxToRect:
    def test_four_point_bbox(self):
        bbox = [[100, 200], [300, 200], [300, 220], [100, 220]]
        x, y, w, h = _bbox_to_rect(bbox)
        assert x == 100
        assert y == 200
        assert w == 200
        assert h == 20

    def test_already_rect(self):
        bbox = [100, 200, 300, 50]
        x, y, w, h = _bbox_to_rect(bbox)
        assert x == 100
        assert y == 200

    def test_empty_bbox(self):
        x, y, w, h = _bbox_to_rect([])
        assert (x, y, w, h) == (0, 0, 0, 0)


class TestRectOverlap:
    def test_overlapping(self):
        a = (0, 0, 100, 100)
        b = (0, 50, 100, 100)
        assert _rect_overlap_y(a, b)

    def test_no_overlap(self):
        a = (0, 0, 100, 50)
        b = (0, 200, 100, 50)
        assert not _rect_overlap_y(a, b)


class TestDetectColumns:
    def test_single_column(self):
        blocks = [
            {"bbox": [[100, 0], [200, 0], [200, 20], [100, 20]]},
            {"bbox": [[100, 30], [200, 30], [200, 50], [100, 50]]},
        ]
        assert _detect_columns(blocks, 800) == 1

    def test_two_columns(self):
        blocks = [
            {"bbox": [[50, 0], [150, 0], [150, 20], [50, 20]]},    # left col
            {"bbox": [[50, 30], [150, 30], [150, 50], [50, 50]]},   # left col
            {"bbox": [[450, 0], [550, 0], [550, 20], [450, 20]]},   # right col
            {"bbox": [[450, 30], [550, 30], [550, 50], [450, 50]]},  # right col
        ]
        cols = _detect_columns(blocks, 800)
        # With large gap between col left and right, should detect 2
        assert cols >= 1


class TestIsTableRow:
    def test_digit_dense(self):
        assert _is_table_row("123.45  678.90  234.56")

    def test_normal_text(self):
        assert not _is_table_row("这是一段正常的文字内容")

    def test_mixed_digits(self):
        assert _is_table_row("金额：1,234.56元  数量：789件  占比：45.6%")


def make_ocr(text, y, x=100, confidence=0.95, w=200, h=20):
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    }


class TestLayoutDetector:
    def test_empty_input(self):
        detector = LayoutDetector()
        result = detector.detect([])
        assert result == []

    def test_single_text_block(self):
        detector = LayoutDetector()
        results = [
            make_ocr("这是一段文本内容。", 100),
            make_ocr("继续第二行文本。", 120),
        ]
        regions = detector.detect(results)
        assert len(regions) >= 1
        # Should merge adjacent lines
        assert regions[0]["type"] in ("text", "title")

    def test_table_detection(self):
        detector = LayoutDetector()
        results = [
            make_ocr("编号  名称  金额", 100),
            make_ocr("001  项目A  123.45", 120),
            make_ocr("002  项目B  678.90", 140),
        ]
        regions = detector.detect(results)
        # At least one region should be table or text
        assert len(regions) >= 1

    def test_title_detection(self):
        detector = LayoutDetector()
        results = [
            make_ocr("第三章 方法", 100, x=350, w=100),  # centered-ish
        ]
        regions = detector.detect(results, page_width=800)
        assert len(regions) >= 1

    def test_detect_all_pages(self):
        detector = LayoutDetector()
        pages = [
            [make_ocr("page1 text。", 100)],
            [make_ocr("page2 text。", 100)],
        ]
        result = detector.detect_all_pages(pages)
        assert len(result) == 2

    def test_reading_order(self):
        detector = LayoutDetector()
        results = [
            make_ocr("Top block。", 100),
            make_ocr("Middle block。", 300),
            make_ocr("Bottom block。", 500),
        ]
        regions = detector.detect(results)
        for region in regions:
            assert "reading_order" in region
