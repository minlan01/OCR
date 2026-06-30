"""OCR 结果 MinIO 存储单元测试"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from services.evidence.ocr_storage import (
    OCR_STORAGE_INLINE,
    OCR_STORAGE_MINIO,
    make_ocr_prefix,
    persist_inline_ocr,
    should_offload_ocr,
)


def test_make_ocr_prefix():
    assert make_ocr_prefix("case-1", "mat-2") == "evidence/case-1/ocr/mat-2"


def test_persist_inline_strips_blocks():
    ocr_result = {
        "full_text": "hello world",
        "blocks": [{"text": "hello", "page": 1}],
        "source_type": "docx",
        "page_count": 1,
    }
    db_text, summary = persist_inline_ocr(ocr_result)
    assert db_text == "hello world"
    assert summary["storage"] == OCR_STORAGE_INLINE
    assert "blocks" not in summary
    assert summary["block_count"] == 1


def test_should_offload_pdf():
    assert should_offload_ocr({"source_type": "pdf_ocr", "page_count": 1}) is True
    assert should_offload_ocr({"source_type": "docx", "page_count": 1}) is False


def test_evidence_ocr_store_write_and_finalize(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    from services.evidence.ocr_storage import EvidenceOCRStore

    mock_minio = MagicMock()
    uploaded: dict[str, bytes] = {}

    def _upload_bytes(bucket, key, data, content_type="application/octet-stream"):
        uploaded[key] = data
        return len(data)

    def _upload_file(bucket, key, file_path, content_type="application/octet-stream"):
        uploaded[key] = open(file_path, "rb").read()
        return len(uploaded[key])

    mock_minio.upload_bytes = _upload_bytes
    mock_minio.upload_file = _upload_file

    with patch("services.storage.minio_client.minio_client", mock_minio):
        store = EvidenceOCRStore("c1", "m1")
        store.set_meta("pdf_ocr")
        store.write_page(1, [{"text": "第一页", "confidence": 0.9}])
        store.write_page(2, [{"text": "第二页", "confidence": 0.8}])
        preview, summary = store.finalize()

    assert summary["storage"] == OCR_STORAGE_MINIO
    assert summary["page_count"] == 2
    assert summary["block_count"] == 2
    assert "第一页" in preview
    assert summary["minio_prefix"] == "evidence/c1/ocr/m1"
    assert any(k.endswith("page_0001.json") for k in uploaded)
    page1 = json.loads(
        next(v for k, v in uploaded.items() if k.endswith("page_0001.json")).decode("utf-8")
    )
    assert page1["page"] == 1
    assert page1["text"] == "第一页"
