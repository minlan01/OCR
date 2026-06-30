"""大 PDF 分片 OCR 编排层单元测试

mock MinIO + mock DB（不依赖真实 Celery runtime / 真实 PostgreSQL）。
覆盖 docs/superpowers/specs/2026-06-29-large-pdf-shard-ocr-design.md §6.1 的用例。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from services.evidence import ocr_shard


# ─── 测试夹具 ───────────────────────────────────────────────────────────────

CASE_ID = "00000000-0000-0000-0000-case000000001"
MATERIAL_ID = "00000000-0000-0000-0000-mat0000000001"


@pytest.fixture
def mock_minio():
    """mock MinIO 客户端，checkpoint/page 用内存 dict 存储。"""
    store: dict[str, bytes] = {}

    mock = MagicMock()
    mock.upload_bytes = lambda b, k, d, content_type="application/octet-stream": store.__setitem__(k, d) or len(d)
    mock.upload_file = lambda b, k, fp, content_type="application/octet-stream": store.__setitem__(k, open(fp, "rb").read()) or len(store[k])
    def _download(bucket, key):
        if key not in store:
            raise KeyError(key)
        return store[key]
    mock.download_bytes = _download
    mock._store = store
    return mock


@pytest.fixture
def patch_minio(mock_minio):
    with patch("services.storage.minio_client.minio_client", mock_minio):
        yield mock_minio


# ─── 1. 批次切分 ────────────────────────────────────────────────────────────

def test_batch_plan_10000_pages():
    """10000 页 → 50 批，每批 200 页，最后一批正好 200。"""
    batches = ocr_shard.plan_batches(10000, batch_page_size=200)
    assert len(batches) == 50
    assert batches[0] == (0, 1, 200)
    assert batches[49] == (49, 9801, 10000)


def test_batch_plan_uneven_last_batch():
    """550 页 / 200 每批 → 3 批，最后一批 150 页。"""
    batches = ocr_shard.plan_batches(550, batch_page_size=200)
    assert len(batches) == 3
    assert batches[0] == (0, 1, 200)
    assert batches[1] == (1, 201, 400)
    assert batches[2] == (2, 401, 550)


def test_batch_plan_zero_pages():
    assert ocr_shard.plan_batches(0) == []


def test_should_shard_threshold():
    """500 页以下不分片，501 页以上分片；非 PDF 不分片。"""
    assert ocr_shard.should_shard("pdf", 501) is True
    assert ocr_shard.should_shard("pdf", 500) is False
    assert ocr_shard.should_shard("pdf", 100) is False
    assert ocr_shard.should_shard("docx", 10000) is False
    assert ocr_shard.should_shard(None, 10000) is False


# ─── 2. Checkpoint 幂等 ─────────────────────────────────────────────────────

def test_checkpoint_idempotent(patch_minio):
    """同一批次重跑 → 读到 checkpoint completed → 直接返回跳过标记。"""
    ocr_shard.write_checkpoint(
        CASE_ID, MATERIAL_ID, 0,
        status="completed", start=1, end=200, pages_written=list(range(1, 201)),
    )
    cp = ocr_shard.load_checkpoint(CASE_ID, MATERIAL_ID, 0)
    assert cp is not None
    assert cp["status"] == "completed"
    assert set(cp["pages_written"]) == set(range(1, 201))


def test_checkpoint_partial_retry(patch_minio):
    """checkpoint 记录 pages_written=[1..100]，重跑只处理 [101..200]。"""
    ocr_shard.write_checkpoint(
        CASE_ID, MATERIAL_ID, 0,
        status="processing", start=1, end=200, pages_written=list(range(1, 101)),
    )
    # 追加 101
    ocr_shard.append_checkpoint_page(CASE_ID, MATERIAL_ID, 0, 101)
    cp = ocr_shard.load_checkpoint(CASE_ID, MATERIAL_ID, 0)
    assert 101 in cp["pages_written"]
    assert 100 in cp["pages_written"]
    assert 102 not in cp["pages_written"]


def test_checkpoint_load_missing_returns_none(patch_minio):
    assert ocr_shard.load_checkpoint(CASE_ID, MATERIAL_ID, 99) is None


# ─── 3. 信号量 ─────────────────────────────────────────────────────────────

def test_acquire_release_batch_slot(monkeypatch):
    """信号量获取/释放正常工作。"""
    fake_redis = MagicMock()
    fake_redis.eval.return_value = 1  # acquire 成功
    fake_redis.decr.return_value = 0
    monkeypatch.setattr(ocr_shard, "_redis", lambda: fake_redis)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_concurrent_per_material", 4)

    assert ocr_shard.acquire_batch_slot(MATERIAL_ID) is True
    ocr_shard.release_batch_slot(MATERIAL_ID)
    fake_redis.eval.assert_called_once()
    fake_redis.decr.assert_called_once()


def test_acquire_batch_slot_full(monkeypatch):
    """信号量已满 → 返回 False，应走 retry。"""
    fake_redis = MagicMock()
    fake_redis.eval.return_value = 0  # 已满
    monkeypatch.setattr(ocr_shard, "_redis", lambda: fake_redis)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_concurrent_per_material", 4)

    assert ocr_shard.acquire_batch_slot(MATERIAL_ID) is False


def test_acquire_batch_slot_unlimited(monkeypatch):
    """limit=0 表示不限流，直接放行。"""
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_concurrent_per_material", 0)
    assert ocr_shard.acquire_batch_slot(MATERIAL_ID) is True
    assert ocr_shard.release_batch_slot(MATERIAL_ID) is None


def test_clear_batch_semaphore(monkeypatch):
    """clear_batch_semaphore 删除 key（Bug 7 修复：finalize 终态清理）。"""
    fake_redis = MagicMock()
    fake_redis.delete.return_value = 1
    monkeypatch.setattr(ocr_shard, "_redis", lambda: fake_redis)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_concurrent_per_material", 4)

    ocr_shard.clear_batch_semaphore(MATERIAL_ID)
    fake_redis.delete.assert_called_once_with(
        f"scanstruct:ocr_batch_concurrent:{MATERIAL_ID}"
    )


def test_clear_batch_semaphore_unlimited(monkeypatch):
    """limit=0 时不操作 Redis。"""
    fake_redis = MagicMock()
    monkeypatch.setattr(ocr_shard, "_redis", lambda: fake_redis)
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_concurrent_per_material", 0)

    ocr_shard.clear_batch_semaphore(MATERIAL_ID)
    fake_redis.delete.assert_not_called()


# ─── 4. full_text 拼接 ─────────────────────────────────────────────────────

def test_assemble_full_text_order(patch_minio, tmp_path, monkeypatch):
    """按页号顺序拼接 full_text，并发下载后顺序写。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))

    # 写 5 页 page json（乱序写，验证顺序拼）
    from services.evidence.ocr_storage import EvidenceOCRStore
    with patch("services.storage.minio_client.minio_client", patch_minio):
        store = EvidenceOCRStore(CASE_ID, MATERIAL_ID)
        store.write_page(1, [{"text": "Page1", "confidence": 0.9}])
        store.write_page(3, [{"text": "Page3", "confidence": 0.9}])
        store.write_page(2, [{"text": "Page2", "confidence": 0.9}])
        store.write_page(5, [{"text": "Page5", "confidence": 0.9}])
        store.write_page(4, [{"text": "Page4", "confidence": 0.9}])
        store.abort_text_only()

    tmp_path_str, total_len = ocr_shard.assemble_full_text(CASE_ID, MATERIAL_ID, 5)
    try:
        with open(tmp_path_str, "r", encoding="utf-8") as f:
            content = f.read()
        # 必须按页号 1-5 顺序
        assert content.index("Page1") < content.index("Page2")
        assert content.index("Page2") < content.index("Page3")
        assert content.index("Page3") < content.index("Page4")
        assert content.index("Page4") < content.index("Page5")
    finally:
        ocr_shard.cleanup_temp_files(tmp_path_str)


def test_assemble_full_text_missing_page(patch_minio, tmp_path, monkeypatch):
    """缺失页用空串占位，不报错。"""
    monkeypatch.setenv("OCR_WORK_DIR", str(tmp_path))
    from services.evidence.ocr_storage import EvidenceOCRStore
    with patch("services.storage.minio_client.minio_client", patch_minio):
        store = EvidenceOCRStore(CASE_ID, MATERIAL_ID)
        store.write_page(1, [{"text": "P1", "confidence": 0.9}])
        store.write_page(3, [{"text": "P3", "confidence": 0.9}])
        # 故意不写 page 2
        store.abort_text_only()

    tmp_path_str, _ = ocr_shard.assemble_full_text(CASE_ID, MATERIAL_ID, 3)
    try:
        with open(tmp_path_str, "r", encoding="utf-8") as f:
            content = f.read()
        assert "P1" in content
        assert "P3" in content
    finally:
        ocr_shard.cleanup_temp_files(tmp_path_str)


# ─── 5. finalize_ready 判断 ─────────────────────────────────────────────────

def test_is_finalize_ready_all_completed(monkeypatch):
    """全部批次 completed → ready=True。"""
    progress = {
        "total_batches": 3,
        "completed_batches": [0, 1, 2],
        "failed_batches": [],
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: progress)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is True
    assert state["missing"] == []
    assert state["retryable"] == []


def test_is_finalize_ready_missing(monkeypatch):
    """缺批 2 → ready=False, missing=[2]。"""
    progress = {
        "total_batches": 3,
        "completed_batches": [0, 1],
        "failed_batches": [],
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: progress)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is False
    assert state["missing"] == [2]


def test_is_finalize_ready_unrecoverable(monkeypatch):
    """批 2 retries>=max → 不可救。"""
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_retries", 3)
    progress = {
        "total_batches": 3,
        "completed_batches": [0, 1],
        "failed_batches": [{"index": 2, "error": "boom", "retries": 3}],
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: progress)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is False
    assert len(state["unrecoverable"]) == 1
    assert state["unrecoverable"][0]["index"] == 2


def test_is_finalize_ready_retryable(monkeypatch):
    """批 2 retries<max → 可重派。"""
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_retries", 3)
    progress = {
        "total_batches": 3,
        "completed_batches": [0, 1],
        "failed_batches": [{"index": 2, "error": "boom", "retries": 1}],
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: progress)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is False
    assert state["retryable"] == [2]
    assert state["unrecoverable"] == []


def test_is_finalize_ready_failed_then_completed(monkeypatch):
    """批次先失败后重试成功：completed_batches 含该批，failed_batches 残留旧记录 → 应 ready=True。

    回归 Bug 6：mark_batch_failed 写失败记录后重试成功，mark_batch_completed 不清旧记录，
    is_finalize_ready 误判 retryable 导致 finalize 死循环耗尽重试。
    """
    monkeypatch.setattr(ocr_shard.settings, "ocr_batch_max_retries", 3)
    progress = {
        "total_batches": 3,
        "completed_batches": [2, 0, 1],  # 三批都完成（含曾失败的 0、1）
        "failed_batches": [  # 残留旧失败记录（未清除）
            {"index": 0, "error": "old boom", "retries": 1},
            {"index": 1, "error": "old boom", "retries": 2},
        ],
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: progress)
    state = ocr_shard.is_finalize_ready(MATERIAL_ID)
    assert state["ready"] is True
    assert state["missing"] == []
    assert state["retryable"] == []
    assert state["unrecoverable"] == []


# ─── 6. 派发器计划 ─────────────────────────────────────────────────────────

def test_dispatch_plan_fresh(monkeypatch):
    """新派发：返回所有批次，写 progress。"""
    written = {}
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: None)
    monkeypatch.setattr(ocr_shard, "write_progress", lambda mid, **kw: written.update(kw))

    plan = ocr_shard.dispatch_plan(MATERIAL_ID, CASE_ID, "/tmp/x.pdf", 600)
    assert plan["skipped"] is False
    assert plan["reason"] == "fresh"
    assert len(plan["batches"]) == 3  # 600 / 200
    assert written["total_pages"] == 600
    assert written["total_batches"] == 3
    assert written["status"] == ocr_shard.STATUS_SHARDING


def test_dispatch_plan_resume(monkeypatch):
    """续传：已有 status=sharding 的 progress → 只返回 pending 批次。"""
    existing = {
        "status": ocr_shard.STATUS_SHARDING,
        "total_batches": 3,
        "completed_batches": [0, 1],
        "batch_size": 200,
        "total_pages": 600,
    }
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: existing)
    monkeypatch.setattr(ocr_shard, "write_progress", lambda mid, **kw: None)

    plan = ocr_shard.dispatch_plan(MATERIAL_ID, CASE_ID, "/tmp/x.pdf", 600)
    assert plan["reason"] == "resume"
    assert len(plan["batches"]) == 1  # 只剩 batch 2
    assert plan["batches"][0][0] == 2  # batch_index=2


# ─── 7. case 级检查（mock DB） ─────────────────────────────────────────────

def test_case_all_materials_terminal_true(monkeypatch):
    """所有 material 终态 → True。"""
    fake_eng = MagicMock()
    fake_conn = MagicMock()
    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, k: 0
    fake_eng.connect.return_value.__enter__ = lambda self: fake_conn
    fake_eng.connect.return_value.__exit__ = lambda *a: None
    fake_conn.execute.return_value.fetchone.return_value = fake_row
    monkeypatch.setattr(ocr_shard, "_sync_engine", lambda: fake_eng)
    assert ocr_shard.case_all_materials_terminal(CASE_ID) is True


def test_case_all_materials_terminal_false(monkeypatch):
    """有 material 仍在 processing → False。"""
    fake_eng = MagicMock()
    fake_conn = MagicMock()
    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, k: 2
    fake_eng.connect.return_value.__enter__ = lambda self: fake_conn
    fake_eng.connect.return_value.__exit__ = lambda *a: None
    fake_conn.execute.return_value.fetchone.return_value = fake_row
    monkeypatch.setattr(ocr_shard, "_sync_engine", lambda: fake_eng)
    assert ocr_shard.case_all_materials_terminal(CASE_ID) is False


def test_case_already_advanced(monkeypatch):
    fake_eng = MagicMock()
    fake_conn = MagicMock()
    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, k: "catalog_ready"
    fake_eng.connect.return_value.__enter__ = lambda self: fake_conn
    fake_eng.connect.return_value.__exit__ = lambda *a: None
    fake_conn.execute.return_value.fetchone.return_value = fake_row
    monkeypatch.setattr(ocr_shard, "_sync_engine", lambda: fake_eng)
    assert ocr_shard.case_already_advanced(CASE_ID) is True


# ─── 8. 取消 ───────────────────────────────────────────────────────────────

def test_is_material_cancelled(monkeypatch):
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: {"cancelled": True})
    assert ocr_shard.is_material_cancelled(MATERIAL_ID) is True


def test_is_material_cancelled_false(monkeypatch):
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: {"cancelled": False})
    assert ocr_shard.is_material_cancelled(MATERIAL_ID) is False


def test_is_material_cancelled_no_progress(monkeypatch):
    monkeypatch.setattr(ocr_shard, "load_progress", lambda mid: None)
    assert ocr_shard.is_material_cancelled(MATERIAL_ID) is False
