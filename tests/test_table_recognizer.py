"""
表格识别器单元测试
"""
import pytest
from services.layout.table_recognizer import (
    recognize_table,
    _cluster_1d,
    _estimate_font_height,
    _build_html_table,
    _trim_empty_rows_cols,
)


class TestCluster1D:
    def test_empty(self):
        assert _cluster_1d([], 10) == []

    def test_single_value(self):
        assert _cluster_1d([5.0], 10) == [5.0]

    def test_close_values_merged(self):
        result = _cluster_1d([10, 12, 14], 5)
        assert len(result) == 1

    def test_far_values_separate(self):
        result = _cluster_1d([10, 50, 90], 5)
        assert len(result) == 3

    def test_mixed_clusters(self):
        result = _cluster_1d([10, 12, 50, 52, 90, 92], 3)
        assert len(result) == 3


class TestEstimateFontHeight:
    def test_from_items(self):
        items = [
            {"bbox": [[0, 0], [100, 0], [100, 20], [0, 20]]},
            {"bbox": [[0, 0], [100, 0], [100, 25], [0, 25]]},
        ]
        h = _estimate_font_height(items)
        assert 20 <= h <= 25

    def test_empty_default(self):
        h = _estimate_font_height([])
        assert h == 20


class TestBuildHTMLTable:
    def test_simple_table(self):
        cells = [
            ["Name", "Age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ]
        html = _build_html_table(cells)
        assert "<table" in html
        assert "<tr>" in html
        assert "<td>Name</td>" in html
        assert "<td>Alice</td>" in html

    def test_empty(self):
        html = _build_html_table([])
        assert "<table" in html


class TestTrimEmptyRowsCols:
    def test_remove_empty_row(self):
        cells = [
            ["A", "B"],
            ["", ""],
            ["C", "D"],
        ]
        result = _trim_empty_rows_cols(cells)
        assert len(result) == 2

    def test_remove_empty_col(self):
        cells = [
            ["A", "", "B"],
            ["C", "", "D"],
        ]
        result = _trim_empty_rows_cols(cells)
        assert len(result[0]) == 2


def make_ocr(text, y, x, confidence=0.95, w=80, h=20):
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    }


class TestRecognizeTable:
    def test_empty_input(self):
        result = recognize_table([])
        assert result["rows"] == 0
        assert result["cols"] == 0

    def test_single_item(self):
        result = recognize_table([make_ocr("A", 100, 100)])
        assert result["rows"] == 0  # needs >=2 items

    def test_simple_2x2_table(self):
        items = [
            make_ocr("Name", 100, 100),
            make_ocr("Age", 100, 250),
            make_ocr("Alice", 130, 100),
            make_ocr("30", 130, 250),
        ]
        result = recognize_table(items)
        assert result["rows"] >= 2
        assert result["cols"] >= 2
        assert result["html"] != ""

    def test_confidence_avg(self):
        items = [
            make_ocr("A", 100, 100, confidence=0.8),
            make_ocr("B", 100, 250, confidence=0.9),
            make_ocr("C", 130, 100, confidence=1.0),
        ]
        result = recognize_table(items)
        assert 0.85 < result["confidence_avg"] < 0.95

    def test_html_output_contains_cells(self):
        items = [
            make_ocr("Col1", 100, 100),
            make_ocr("Col2", 100, 250),
            make_ocr("Val1", 130, 100),
            make_ocr("Val2", 130, 250),
        ]
        result = recognize_table(items)
        assert "Col1" in result["html"]
        assert "Col2" in result["html"]
