"""大 PDF 分片 OCR 端到端测试

不依赖真实 Celery runtime / 真实 PostgreSQL / 真实云 OCR。
通过直接调用 services/evidence/ocr_shard.py 的编排纯函数 + mock EvidenceOCRStore
+ mock OCR 引擎，跑完整 dispatch → batch×N → finalize → check 流程。

校验点：
  - MinIO 有 N 个 page_NNNN.json + 1 个 full_text.txt + 1 个 manifest.json
  - finalize 拼接的 full_text 按页号顺序
  - DB 进度（mock）记录所有批次 completed
  - 断点续传：模拟中途失败后只重派缺失批次
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.evidence import ocr_shard


CASE_ID = "00000000-0000-0000-0000-e2e000000001"
MATERIAL_ID = "00000000-0000-0000-0000-e2e000000002"


# ─── 共享 mock MinIO ────────────────────────────────────────────────────────

@pytest.fixture
def mem_minio():
    """内存版 MinIO：upload_bytes/download_bytes 走 dict。"""
    store: dict[str, bytes] = {}

    mock = MagicMock()

    def _upload_bytes(bucket, key, data, content_type="application/octet-stream"):
        if isinstance(data, (bytes, bytearray)):
            store[key] = bytes(data)
        else:
            store[key] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        return len(store[key])

    def _upload_file(bucket, key, file_path, content_type="application/octet-stream"):
        with open(file_path, "rb") as f:
            store[key] = f.read()
        return len(store[key])

    def _download(bucket, key):
        if key not in store:
            raise KeyError(key)
        return store[key]

    mock.upload_bytes = _upload_bytes
    mock.upload_file = _upload_file
    mock.download_bytes = _download
    mock._store = store
    return mock


@pytest.fixture
def patch_minio(mem_minio):
    with patch("services.storage.minio_client.minio_client", mem_minio):
        yield mem_minio


# ─── mock OCR：直接生成 page_NNNN.json（跳过真实 OCR 引擎） ────────────────

def _write_page_directly(case_id, material_id, page_num, text, minio_store):
    """直接往 mock MinIO 写一个 page_NNNN.json（模拟 OCR 引擎输出）。"""
    from services.evidence.ocr_storage import make_ocr_prefix
    prefix = make_ocr_prefix(case_id, material_id)
    payload = json.dumps(
        {"page": page_num, "text": text, "blocks": [{"text": text, "confidence": 0.95, "page": page_num}]},
        ensure_ascii=False,
    ).encode("utf-8")
    minio_store[f"{prefix}/pages/page_{page_num:04d}.json"] = payload


# ─── mock DB 进度（避免依赖真实 PostgreSQL） ────────────────────────────────

@pytest.fixture
def mock_progress_db(monkeypatch):
    """用内存 dict 模拟 DB step_metadata 进度存储。"""
    state: dict[str, dict] = {}

    def _load_progress(material_id):
        return state.get(material_id)

    def _write_progress(material_id, **fields):
        state[material_id] = fields

    def _mark_batch_completed(material_id, batch_index):
        prog = state.get(material_id) or {"completed_batches": []}
        completed = list(prog.get("completed_batches") or [])
        if batch_index not in completed:
            completed.append(batch_index)
        prog["completed_batches"] = completed
        state[material_id] = prog

    def _mark_batch_failed(material_id, batch_index, error, retries):
        prog = state.get(material_id) or {"failed_batches": []}
        failed = [b for b in (prog.get("failed_batches") or []) if b.get("index") != batch_index]
        failed.append({"index": batch_index, "error": error, "retries": retries})
        prog["failed_batches"] = failed
        state[material_id] = prog

    def _set_progress_status(material_id, status, **extra):
        prog = state.get(material_id) or {}
        prog["status"] = status
        prog.update(extra)
        state[material_id] = prog

    monkeypatch.setattr(ocr_shard, "load_progress", _load_progress)
    monkeypatch.setattr(ocr_shard, "write_progress", _write_progress)
    monkeypatch.setattr(ocr_shard, "mark_batch_completed", _mark_batch_completed)
    monkeypatch.setattr(ocr_shard, "mark_batch_failed", _mark_batch_failed)
    monkeypatch.setattr(ocr_shard, "set_progress_status", _set_progress_status)
    return state


# ─── e2e：完整成功流程 ─────────────────────────────────────────────────────

def test_e2e_full_success_flow(patch_minio, mock_progress_db, tmp_path, monkeypatch):
    """模拟 600 页 PDF（越 500 阈值，3 批）→ 全部完成 → finalize 拼接。

    不调真实 Celery task，直接调 ocr_shard 纯函数 + 手动写 page json 模拟批次输出。
    """
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(ocr_shard.settings, "ocr_shard_threshold_pages", 500)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_page_size", 200)

    total_pages = 600

    # 1. 派发器：切批 + 初始化进度
    plan = ocr_shard.dispatch_plan(
        material_id=MATERIAL_ID,
        case_id=CASE_ID,
        pdf_local_path="/tmp/fake.pdf",
        total_pages=total_pages,
    )
    assert plan["reason"] == "fresh"
    assert len(plan["batches"]) == 3  # 600 / 200
    assert plan["batches"] == [(0, 1, 200), (1, 201, 400), (2, 401, 600)]

    # 2. 模拟 3 个批次 task 执行：每批写 200 页 page json + checkpoint completed
    for batch_idx, start, end in plan["batches"]:
        # 批次 task 内部会调 EvidenceOCRStore.write_page，这里直接模拟其产物
        for page_num in range(start, end + 1):
            _write_page_directly(CASE_ID, MATERIAL_ID, page_num, f"Page{page_num}Text", patch_minio._store)
        # 写 checkpoint completed
        ocr_shard.write_checkpoint(
            CASE_ID, MATERIAL_ID, batch_idx,
            status="completed", start=start, end=end,
            pages_written=list(range(start, end + 1)),
        )
        # 更新 DB 进度
        ocr_shard.mark_batch_completed(MATERIAL_ID, batch_idx)

    # 3. 收口器：检查是否全完成
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is True
    assert state["missing"] == []
    assert state["retryable"] == []

    # 4. finalize：拼接 full_text + 写 manifest
    summary = ocr_shard.finalize_assemble_and_manifest(MATERIAL_ID, CASE_ID)

    # 校验 summary
    assert summary["storage"] == "minio"
    assert summary["page_count"] == 600
    assert summary["source_type"] == "pdf_ocr_shard"
    assert summary["full_text_length"] > 0

    # 校验 MinIO 产物
    from services.evidence.ocr_storage import make_ocr_prefix
    prefix = make_ocr_prefix(CASE_ID, MATERIAL_ID)
    # 600 个 page json
    page_count = sum(
        1 for k in patch_minio._store if k.startswith(f"{prefix}/pages/page_")
    )
    assert page_count == 600, f"expected 600 page json, got {page_count}"
    # full_text.txt
    full_text_key = f"{prefix}/full_text.txt"
    assert full_text_key in patch_minio._store
    full_text = patch_minio._store[full_text_key].decode("utf-8")
    # 必须按页号顺序
    assert full_text.index("Page1Text") < full_text.index("Page200Text")
    assert full_text.index("Page200Text") < full_text.index("Page201Text")
    assert full_text.index("Page599Text") < full_text.index("Page600Text")
    # manifest.json
    manifest_key = f"{prefix}/manifest.json"
    assert manifest_key in patch_minio._store
    manifest = json.loads(patch_minio._store[manifest_key].decode("utf-8"))
    assert manifest["storage"] == "minio"
    assert manifest["page_count"] == 600

    # 5. 校验 DB 进度标 completed
    prog = mock_progress_db[MATERIAL_ID]
    assert prog["status"] == ocr_shard.STATUS_COMPLETED


# ─── e2e：断点续传（中途失败后只重派缺失批次） ─────────────────────────────

def test_e2e_resume_after_partial_failure(patch_minio, mock_progress_db, tmp_path, monkeypatch):
    """模拟：批 0、批 1 完成，批 2 失败 → retry-ocr → 只重派批 2 → finalize 成功。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(ocr_shard.settings, "ocr_shard_threshold_pages", 500)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_page_size", 200)

    total_pages = 600

    # 1. 首次派发
    plan = ocr_shard.dispatch_plan(
        material_id=MATERIAL_ID, case_id=CASE_ID,
        pdf_local_path="/tmp/fake.pdf", total_pages=total_pages,
    )
    assert len(plan["batches"]) == 3

    # 2. 批 0、批 1 成功；批 2 失败（耗尽重试）
    for batch_idx, start, end in [(0, 1, 200), (1, 201, 400)]:
        for page_num in range(start, end + 1):
            _write_page_directly(CASE_ID, MATERIAL_ID, page_num, f"Page{page_num}", patch_minio._store)
        ocr_shard.write_checkpoint(
            CASE_ID, MATERIAL_ID, batch_idx,
            status="completed", start=start, end=end, pages_written=list(range(start, end + 1)),
        )
        ocr_shard.mark_batch_completed(MATERIAL_ID, batch_idx)

    # 批 2 失败
    ocr_shard.write_checkpoint(
        CASE_ID, MATERIAL_ID, 2,
        status="failed", start=401, end=600, error="ocr boom", retries=3,
    )
    ocr_shard.mark_batch_failed(MATERIAL_ID, 2, "ocr boom", 3)

    # 3. 收口器检查：批 2 不可救（retries>=max）
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_retries", 3)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is False
    assert len(state["unrecoverable"]) == 1
    assert state["unrecoverable"][0]["index"] == 2

    # 4. 用户点"重试" → 重置批 2 的 checkpoint（模拟用户主动重试清除 retries 计数）
    ocr_shard.write_checkpoint(
        CASE_ID, MATERIAL_ID, 2,
        status="processing", start=401, end=600, pages_written=[],
    )
    # 清除 failed_batches 中批 2 的记录（模拟 retry-ocr 端点的状态重置）
    prog = mock_progress_db[MATERIAL_ID]
    prog["failed_batches"] = [b for b in prog.get("failed_batches", []) if b.get("index") != 2]

    # 5. 重派批 2 → 成功
    start, end = 401, 600
    for page_num in range(start, end + 1):
        _write_page_directly(CASE_ID, MATERIAL_ID, page_num, f"Page{page_num}", patch_minio._store)
    ocr_shard.write_checkpoint(
        CASE_ID, MATERIAL_ID, 2,
        status="completed", start=start, end=end, pages_written=list(range(start, end + 1)),
    )
    ocr_shard.mark_batch_completed(MATERIAL_ID, 2)

    # 6. 收口器再次检查 → 全完成
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is True

    # 7. finalize
    summary = ocr_shard.finalize_assemble_and_manifest(MATERIAL_ID, CASE_ID)
    assert summary["page_count"] == 600

    # 校验 MinIO 有 600 个 page json（断点续传未覆盖前 400 个）
    from services.evidence.ocr_storage import make_ocr_prefix
    prefix = make_ocr_prefix(CASE_ID, MATERIAL_ID)
    page_count = sum(1 for k in patch_minio._store if k.startswith(f"{prefix}/pages/page_"))
    assert page_count == 600


# ─── e2e：协作式取消 ───────────────────────────────────────────────────────

def test_e2e_cooperative_cancel(patch_minio, mock_progress_db, tmp_path, monkeypatch):
    """用户取消 → 批次 task 检查 cancelled 直接返回跳过。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(ocr_shard.settings, "ocr_shard_threshold_pages", 500)

    plan = ocr_shard.dispatch_plan(
        material_id=MATERIAL_ID, case_id=CASE_ID,
        pdf_local_path="/tmp/fake.pdf", total_pages=600,
    )
    # 用户取消
    ocr_shard.set_cancelled(MATERIAL_ID)

    # 批次 task 开头检查 → 应返回跳过
    assert ocr_shard.is_material_cancelled(MATERIAL_ID) is True
    # 不应写任何 page json
    from services.evidence.ocr_storage import make_ocr_prefix
    prefix = make_ocr_prefix(CASE_ID, MATERIAL_ID)
    page_count = sum(1 for k in patch_minio._store if k.startswith(f"{prefix}/pages/page_"))
    assert page_count == 0


# ─── e2e：小文件不进分片 ───────────────────────────────────────────────────

def test_e2e_small_file_skip_shard(monkeypatch):
    """300 页 PDF（< 500 阈值）→ 不进分片，should_shard 返回 False。"""
    monkeypatch.setattr(ocr_shard.settings, "ocr_shard_threshold_pages", 500)
    assert ocr_shard.should_shard("pdf", 300) is False
    assert ocr_shard.should_shard("pdf", 500) is False  # 边界
    assert ocr_shard.should_shard("pdf", 501) is True


# ─── e2e：批次乱序完成，finalize 仍按页号拼接 ──────────────────────────────

def test_e2e_out_of_order_batch_completion(patch_minio, mock_progress_db, tmp_path, monkeypatch):
    """批 2 先完成，批 0、批 1 后完成 → full_text 仍按页号 1..600 顺序。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_page_size", 200)

    plan = ocr_shard.dispatch_plan(
        material_id=MATERIAL_ID, case_id=CASE_ID,
        pdf_local_path="/tmp/fake.pdf", total_pages=600,
    )
    # 乱序完成：批 2 → 批 0 → 批 1
    order = [plan["batches"][2], plan["batches"][0], plan["batches"][1]]
    for batch_idx, start, end in order:
        for page_num in range(start, end + 1):
            _write_page_directly(CASE_ID, MATERIAL_ID, page_num, f"P{page_num}", patch_minio._store)
        ocr_shard.write_checkpoint(
            CASE_ID, MATERIAL_ID, batch_idx,
            status="completed", start=start, end=end, pages_written=list(range(start, end + 1)),
        )
        ocr_shard.mark_batch_completed(MATERIAL_ID, batch_idx)

    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is True

    summary = ocr_shard.finalize_assemble_and_manifest(MATERIAL_ID, CASE_ID)
    from services.evidence.ocr_storage import make_ocr_prefix
    prefix = make_ocr_prefix(CASE_ID, MATERIAL_ID)
    full_text = patch_minio._store[f"{prefix}/full_text.txt"].decode("utf-8")
    # 必须按页号顺序，与批次完成顺序无关
    assert full_text.index("P1") < full_text.index("P200")
    assert full_text.index("P200") < full_text.index("P201")
    assert full_text.index("P400") < full_text.index("P401")
    assert full_text.index("P599") < full_text.index("P600")


# ─── e2e：finalize 检测缺失批次 ────────────────────────────────────────────

def test_e2e_finalize_detects_missing(patch_minio, mock_progress_db, tmp_path, monkeypatch):
    """只完成批 0、批 1，缺批 2 → is_finalize_ready 返回 missing=[2]。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_page_size", 200)

    plan = ocr_shard.dispatch_plan(
        material_id=MATERIAL_ID, case_id=CASE_ID,
        pdf_local_path="/tmp/fake.pdf", total_pages=600,
    )
    # 只完成批 0、批 1
    for batch_idx, start, end in [plan["batches"][0], plan["batches"][1]]:
        ocr_shard.write_checkpoint(
            CASE_ID, MATERIAL_ID, batch_idx,
            status="completed", start=start, end=end, pages_written=list(range(start, end + 1)),
        )
        ocr_shard.mark_batch_completed(MATERIAL_ID, batch_idx)

    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is False
    assert state["missing"] == [2]
    assert state["retryable"] == []
