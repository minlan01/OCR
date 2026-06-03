"""
质量评分器单元测试
"""
import pytest
from services.structurer.quality_scorer import (
    score_structure,
    _score_ocr_confidence,
    _score_structure_completeness,
    _score_heading_quality,
    _max_heading_depth,
)


class TestOCRConfidence:
    def test_high_confidence(self):
        ocr = {"confidence_avg": 0.95, "total_pages": 5, "pages": [
            {"confidence_avg": 0.95}, {"confidence_avg": 0.94}, {"confidence_avg": 0.96},
            {"confidence_avg": 0.93}, {"confidence_avg": 0.97},
        ]}
        score, detail = _score_ocr_confidence(ocr)
        assert score > 0.9

    def test_low_confidence_penalty(self):
        ocr = {"confidence_avg": 0.55, "total_pages": 5, "pages": [
            {"confidence_avg": 0.5}, {"confidence_avg": 0.4}, {"confidence_avg": 0.6},
            {"confidence_avg": 0.3}, {"confidence_avg": 0.7},
        ]}
        score, detail = _score_ocr_confidence(ocr)
        assert score < 0.6
        assert detail["low_confidence_pages"] >= 2

    def test_empty_ocr(self):
        score, detail = _score_ocr_confidence({})
        assert score == 0.0


class TestStructureCompleteness:
    def test_well_structured(self):
        struct = {
            "sections": [{"level": 1, "title": "A", "subsections": [
                {"level": 2, "title": "A.1", "subsections": [
                    {"level": 3, "title": "A.1.1"}
                ]}
            ]}],
            "orphan_paragraphs": [],
            "total_paragraphs": 10,
            "total_sections": 3,
        }
        score, detail = _score_structure_completeness(struct)
        assert score > 0.7
        assert detail["max_heading_depth"] == 3

    def test_no_structure(self):
        struct = {
            "sections": [],
            "orphan_paragraphs": [],
            "total_paragraphs": 0,
            "total_sections": 0,
        }
        score, detail = _score_structure_completeness(struct)
        assert score == 0.0

    def test_high_orphan_ratio(self):
        struct = {
            "sections": [{"level": 1, "title": "A"}],
            "orphan_paragraphs": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
            "total_paragraphs": 3,
            "total_sections": 1,
        }
        score, detail = _score_structure_completeness(struct)
        assert score < 0.5  # high orphan ratio


class TestHeadingQuality:
    def test_valid_hierarchy(self):
        sections = [
            {"level": 1, "title": "Chapter 1", "subsections": [
                {"level": 2, "title": "Section 1.1"},
                {"level": 2, "title": "Section 1.2"},
            ]},
        ]
        score, detail = _score_heading_quality(sections)
        assert score >= 0.6

    def test_level_skip(self):
        sections = [
            {"level": 1, "title": "A", "subsections": [
                {"level": 3, "title": "C"},  # skipped level 2
            ]},
        ]
        score, detail = _score_heading_quality(sections)
        assert score < 0.7  # penalty
        assert any("level_skip" in issue for issue in detail["issues"])

    def test_empty_sections(self):
        score, detail = _score_heading_quality([])
        assert score == 0.0


class TestMaxHeadingDepth:
    def test_depth_3(self):
        sections = [{"level": 1, "subsections": [
            {"level": 2, "subsections": [
                {"level": 3}
            ]}
        ]}]
        assert _max_heading_depth(sections) == 3

    def test_empty(self):
        assert _max_heading_depth([]) == 0

    def test_flat(self):
        sections = [{"level": 1}, {"level": 1}]
        assert _max_heading_depth(sections) == 1


class TestScoreStructure:
    def test_full_scoring(self):
        structured = {
            "sections": [
                {"level": 1, "title": "第一章", "paragraphs": [{"text": "p1"}], "subsections": [
                    {"level": 2, "title": "第一节", "paragraphs": [{"text": "p2"}]}
                ]}
            ],
            "orphan_paragraphs": [],
            "total_sections": 2,
            "total_paragraphs": 2,
        }
        ocr = {
            "confidence_avg": 0.92,
            "total_pages": 3,
            "pages": [
                {"confidence_avg": 0.9}, {"confidence_avg": 0.93}, {"confidence_avg": 0.93}
            ],
        }
        result = score_structure(structured, ocr)
        assert "structure_score" in result
        assert "dimensions" in result
        assert 0 <= result["structure_score"] <= 1.0
        assert "ocr_confidence" in result["dimensions"]
        assert "structure_completeness" in result["dimensions"]

    def test_low_quality_warnings(self):
        result = score_structure({"sections": [], "total_paragraphs": 0, "total_sections": 0})
        assert result["structure_score"] < 0.5
        assert len(result["warnings"]) > 0

    def test_default_params(self):
        result = score_structure({"sections": [], "total_paragraphs": 0, "total_sections": 0})
        assert isinstance(result, dict)
