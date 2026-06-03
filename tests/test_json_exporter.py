"""json_exporter 单元测试 — 结构化结果导出 JSON"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from services.exporter.json_exporter import export_json


class TestExportJson:
    """结构化结果 JSON 导出"""

    @pytest.fixture
    def sample_result(self):
        """标准结构化结果样本"""
        return {
            "sections": [
                {
                    "level": 1,
                    "title": "第一章 概述",
                    "paragraphs": [
                        {"text": "这是第一段内容。", "confidence": 0.95},
                        {"text": "这是第二段内容。", "confidence": 0.88},
                    ],
                    "subsections": [
                        {
                            "level": 2,
                            "title": "1.1 背景",
                            "paragraphs": [{"text": "背景介绍内容。", "confidence": 0.92}],
                            "subsections": [],
                        }
                    ],
                }
            ],
            "orphan_paragraphs": [],
            "total_sections": 2,
            "total_paragraphs": 3,
            "lists": [
                {
                    "type": "numbered",
                    "items": [
                        {"text": "第一项", "indent": 0},
                        {"text": "第二项", "indent": 0},
                    ],
                }
            ],
            "tables": [
                {
                    "page": 1,
                    "rows": 3,
                    "columns": 2,
                    "data": [["项目", "金额"], ["A", "100"], ["B", "200"]],
                }
            ],
            "quality": {"structure_score": 0.92},
            "source_type": "scan_pdf",
        }

    def test_export_writes_json_file(self, sample_result):
        """导出的文件应存在且为合法 JSON"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_json(sample_result, output_path)
            assert output_path.exists()
            assert output_path.stat().st_size > 0
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_preserves_all_keys(self, sample_result):
        """导出应保留所有顶层键"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_json(sample_result, output_path)
            with open(output_path, encoding="utf-8") as f:
                loaded = json.load(f)

            assert loaded["total_sections"] == 2
            assert loaded["total_paragraphs"] == 3
            assert loaded["source_type"] == "scan_pdf"
            assert loaded["quality"]["structure_score"] == 0.92
            assert len(loaded["sections"]) == 1
            assert len(loaded["lists"]) == 1
            assert len(loaded["tables"]) == 1
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_nested_subsections(self, sample_result):
        """嵌套子节应被正确序列化"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_json(sample_result, output_path)
            with open(output_path, encoding="utf-8") as f:
                loaded = json.load(f)

            section = loaded["sections"][0]
            assert len(section["subsections"]) == 1
            assert section["subsections"][0]["title"] == "1.1 背景"
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_empty_result(self):
        """空结果应正常导出"""
        empty = {"sections": [], "orphan_paragraphs": [], "total_sections": 0,
                  "total_paragraphs": 0, "lists": [], "tables": [], "quality": {},
                  "source_type": "none"}

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_json(empty, output_path)
            with open(output_path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["total_sections"] == 0
            assert loaded["sections"] == []
            assert loaded["tables"] == []
            assert loaded["lists"] == []
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_unicode_content(self):
        """中文 Unicode 内容应正确写入"""
        result = {"sections": [{"title": "第一章 绪论", "paragraphs": [
            {"text": "这是一段包含特殊字符的文本：①②③αβγ©®™", "confidence": 0.9}
        ]}], "total_sections": 1, "total_paragraphs": 1, "source_type": "scan_pdf",
            "orphan_paragraphs": [], "lists": [], "tables": [], "quality": {}}

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_json(result, output_path)
            with open(output_path, encoding="utf-8") as f:
                content = f.read()
            assert "绪论" in content
            assert "①②③αβγ" in content
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_creates_parent_directories(self):
        """应自动创建父目录"""
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "deep" / "nested" / "result.json"
            result = {"sections": [], "total_sections": 0, "total_paragraphs": 0,
                      "orphan_paragraphs": [], "lists": [], "tables": [], "quality": {},
                      "source_type": "none"}

            export_json(result, output_path)
            assert output_path.exists()

    def test_export_overwrites_existing_file(self, sample_result):
        """覆盖写入应替换旧内容"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = Path(f.name)
            f.write(b"old data")

        try:
            export_json(sample_result, output_path)
            with open(output_path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["total_sections"] == 2
        finally:
            output_path.unlink(missing_ok=True)
