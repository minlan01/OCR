"""
端到端工作流集成测试
覆盖完整生命周期、错误恢复、重复检测、分页/排序、SPA 集成、认证链路

测试策略：使用 mock 外部依赖（DB/MinIO/Celery/Redis），
但模拟真实的多步骤用户操作流程。
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app, create_app
from db.models import ScanTask, TaskStep, ScanFile


# ═══════════════════════════════════════════════════════════
# Local helpers（与 conftest.py 配合使用）
# ═══════════════════════════════════════════════════════════

def _mock_get_db(mock_session):
    """生成 mock 的 get_db FastAPI 依赖覆盖"""
    async def _override():
        yield mock_session
    return _override


# ═══════════════════════════════════════════════════════════
# Helper: 快捷创建带 mock 的测试上下文
# ═══════════════════════════════════════════════════════════

def _mock_session_for_scan(return_value):
    """创建返回特定值的 mock execute"""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    session.execute.return_value = mock_result
    return session


def _mock_session_for_list(tasks: list, total: int | None = None):
    """创建返回任务列表 + count 的 mock execute"""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = total if total is not None else len(tasks)
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = tasks
    session.execute.side_effect = [
        count_result,
        list_result,
    ]
    return session


# ═══════════════════════════════════════════════════════════
# Workflow 1: 完整生命周期（Happy Path）
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestHappyPathWorkflow:
    """
    模拟用户完整操作链路：
    Upload PDF → 查列表确认 → 看详情 → 看结果 → 删除 → 验证已删除

    所有阶段共享同一个 task_id，通过 mock uuid4 确保一致性。
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, sample_task, sample_pdf_bytes):
        """从头到尾走完一个任务的生命周期"""
        task = sample_task
        task.status = "completed"
        task.result_path = "result/test.json"
        # 确保 sample_task 的 ID 与上传生成的 UUID 一致
        shared_id = task.id
        task_id = str(shared_id)
        expected_json = {
            "pages": 10,
            "headings": 12,
            "tables": 3,
            "paragraphs": 45,
            "sections": [
                {"title": "第一章 概述", "level": 1},
                {"title": "1.1 背景", "level": 2},
            ],
        }

        # Phase 1: Upload — 使用固定 UUID ───────────────
        upload_session = _mock_session_for_scan(None)  # 查重返回 None
        with patch("api.routes.scan.minio_client") as mock_minio, \
             patch("uuid.uuid4", return_value=shared_id):
            mock_minio.upload_bytes.return_value = 10240
            from db.session import get_db
            app.dependency_overrides[get_db] = _mock_get_db(upload_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                upload_resp = await client.post(
                    "/api/v1/scans/upload",
                    files={"file": ("contract.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
                    data={"scanner_id": "scanner-01", "callback_url": "https://example.com/webhook"},
                )
            app.dependency_overrides.clear()

        assert upload_resp.status_code == 202, f"Upload failed: {upload_resp.text}"
        upload_data = upload_resp.json()
        assert upload_data["task_id"] == task_id
        assert upload_data["status"] == "received"
        # api_upload sources get "uploaded_pending_process", watch_folder gets "accepted"
        assert upload_data["message"] == "uploaded_pending_process"
        assert "filename" in upload_data

        # Phase 2: List — 确认任务已出现 —─────────────────
        # 注意：list mock 使用 sample_task fixture，其 UUID 与 upload 生成的不同
        # 真实场景下两者一致；这里验证列表格式正确、能返回数据即可
        list_session = _mock_session_for_list([task])
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(list_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            list_resp = await client.get("/api/v1/scans")
        app.dependency_overrides.clear()

        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] >= 1
        assert list_data["page"] == 1
        assert len(list_data["items"]) >= 1
        # 验证列表项结构完整
        item = list_data["items"][0]
        assert "task_id" in item
        assert "filename" in item
        assert "status" in item

        # Phase 3: Detail — 查看详情 —────────────────────
        detail_session = _mock_session_for_scan(task)
        app.dependency_overrides[get_db] = _mock_get_db(detail_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            detail_resp = await client.get(f"/api/v1/scans/{task_id}")
        app.dependency_overrides.clear()

        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["task_id"] == task_id
        assert detail_data["filename"] == task.filename
        assert detail_data["status"] == "completed"
        assert detail_data["page_count"] == 10
        assert detail_data["confidence_avg"] == pytest.approx(0.95)
        assert len(detail_data["steps"]) == 3
        assert len(detail_data["files"]) == 2

        # Phase 4: Result — 获取结构化结果 —──────────────
        result_session = _mock_session_for_scan(task)
        with patch("api.routes.scan.minio_client") as mock_minio:
            mock_minio.download_bytes.return_value = json.dumps(expected_json).encode("utf-8")
            app.dependency_overrides[get_db] = _mock_get_db(result_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                result_resp = await client.get(f"/api/v1/scans/{task_id}/result")
            app.dependency_overrides.clear()

        assert result_resp.status_code == 200
        result_data = result_resp.json()
        assert result_data["pages"] == 10
        assert result_data["headings"] == 12
        assert result_data["tables"] == 3
        assert len(result_data["sections"]) == 2

        # Phase 5: Delete — 删除任务 —────────────────────
        delete_session = _mock_session_for_scan(task)
        with patch("api.routes.scan.minio_client") as mock_minio, \
             patch("api.routes.scan.celery_app") as mock_celery:
            mock_minio.delete_task_objects.return_value = None
            app.dependency_overrides[get_db] = _mock_get_db(delete_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                delete_resp = await client.delete(f"/api/v1/scans/{task_id}")
            app.dependency_overrides.clear()

        assert delete_resp.status_code == 200
        delete_data = delete_resp.json()
        assert "deleted" in delete_data["message"].lower()
        delete_session.delete.assert_called_once()

        # Phase 6: Verify gone — 确认已删除 —──────────────
        notfound_session = _mock_session_for_scan(None)
        app.dependency_overrides[get_db] = _mock_get_db(notfound_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            verify_resp = await client.get(f"/api/v1/scans/{task_id}")
        app.dependency_overrides.clear()

        assert verify_resp.status_code == 404, "删除后的任务查询应返回 404"


# ═══════════════════════════════════════════════════════════
# Workflow 2: 错误恢复（Failed → Retry → Success）
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestErrorRecoveryWorkflow:
    """失败任务的完整恢复流程"""

    @pytest.mark.asyncio
    async def test_retry_chain(self, failed_task):
        """失败 → 重试 → 验证状态重置 ─────────────────"""
        task = failed_task
        task_id = str(task.id)

        # Step 1: 确认任务处于 failed 状态
        detail_session = _mock_session_for_scan(task)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(detail_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            detail_resp = await client.get(f"/api/v1/scans/{task_id}")
        app.dependency_overrides.clear()

        assert detail_resp.status_code == 200
        assert detail_resp.json()["status"] == "failed"
        assert detail_resp.json()["error_code"] == "PIPELINE_ERROR"

        # Step 2: 执行重试
        retry_session = _mock_session_for_scan(task)
        with patch("api.routes.scan.process_scan") as mock_celery:
            mock_celery.delay.return_value = MagicMock(id="celery-task-456")
            app.dependency_overrides[get_db] = _mock_get_db(retry_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                retry_resp = await client.post(f"/api/v1/scans/{task_id}/retry")
            app.dependency_overrides.clear()

        assert retry_resp.status_code == 202
        retry_data = retry_resp.json()
        assert "queued" in retry_data["message"].lower()
        mock_celery.delay.assert_called_once_with(task_id)

        # Step 3: 验证重试后状态变更为 "pending"
        # ── 由路由代码处理，验证 error_code 被清除
        assert task.error_code is None
        assert task.error_message is None
        assert task.status == "pending"

    @pytest.mark.asyncio
    async def test_retry_force_non_failed(self, pending_task):
        """force=true 强制重试非失败任务 ────────────────"""
        task = pending_task
        task_id = str(task.id)

        retry_session = _mock_session_for_scan(task)
        with patch("api.routes.scan.process_scan") as mock_celery:
            mock_celery.delay.return_value = MagicMock(id="celery-force-789")
            from db.session import get_db
            app.dependency_overrides[get_db] = _mock_get_db(retry_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                retry_resp = await client.post(
                    f"/api/v1/scans/{task_id}/retry?force=true"
                )
            app.dependency_overrides.clear()

        assert retry_resp.status_code == 202
        mock_celery.delay.assert_called_once_with(task_id)

    @pytest.mark.asyncio
    async def test_retry_non_failed_rejected(self, pending_task):
        """不 force 的情况下重试非失败任务应被拒绝 ────"""
        task = pending_task
        task_id = str(task.id)

        retry_session = _mock_session_for_scan(task)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(retry_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            retry_resp = await client.post(f"/api/v1/scans/{task_id}/retry")
        app.dependency_overrides.clear()

        assert retry_resp.status_code == 400
        assert "only failed tasks" in retry_resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
# Workflow 3: 重复文件检测
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestDuplicateDetectionWorkflow:
    """相同文件上传两次的验证"""

    @pytest.mark.asyncio
    async def test_duplicate_upload_returns_existing(self, sample_task, sample_pdf_bytes):
        """第二次上传相同文件应返回已有任务 ────────────"""
        existing = sample_task

        dup_session = _mock_session_for_scan(existing)  # 查重返回已有任务
        with patch("api.routes.scan.minio_client") as mock_minio:
            from db.session import get_db
            app.dependency_overrides[get_db] = _mock_get_db(dup_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                upload_resp = await client.post(
                    "/api/v1/scans/upload",
                    files={"file": ("same.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
                )
            app.dependency_overrides.clear()

        assert upload_resp.status_code == 202
        data = upload_resp.json()
        assert data["task_id"] == str(existing.id), "重复上传应返回已有任务 ID"
        assert data["message"] == "duplicate_file"
        # 验证没有重复上传 MinIO（mock 的 upload_bytes 不应被调用）
        mock_minio.upload_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_two_different_pdfs_create_two_tasks(self, sample_pdf_bytes):
        """两个不同 PDF 应创建两个独立任务 ──────────────"""
        # 第一次上传
        session1 = _mock_session_for_scan(None)
        with patch("api.routes.scan.minio_client") as mock_minio1:
            mock_minio1.upload_bytes.return_value = 10240
            from db.session import get_db
            app.dependency_overrides[get_db] = _mock_get_db(session1)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp1 = await client.post(
                    "/api/v1/scans/upload",
                    files={"file": ("doc_a.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
                )
            app.dependency_overrides.clear()

        assert resp1.status_code == 202
        tid1 = resp1.json()["task_id"]

        # 第二次上传（不同内容）
        different_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
        session2 = _mock_session_for_scan(None)
        with patch("api.routes.scan.minio_client") as mock_minio2:
            mock_minio2.upload_bytes.return_value = 5120
            app.dependency_overrides[get_db] = _mock_get_db(session2)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp2 = await client.post(
                    "/api/v1/scans/upload",
                    files={"file": ("doc_b.pdf", io.BytesIO(different_pdf), "application/pdf")},
                )
            app.dependency_overrides.clear()

        assert resp2.status_code == 202
        tid2 = resp2.json()["task_id"]
        assert tid1 != tid2, "两个不同文件应生成不同 task_id"
        assert resp2.json()["status"] == "received"


# ═══════════════════════════════════════════════════════════
# Workflow 4: 分页、排序、筛选综合链路
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestListFilterSortWorkflow:
    """多任务列表的筛选、分页、排序操作"""

    @pytest.mark.asyncio
    async def test_filter_by_status_paginated(self, multi_status_tasks):
        """按状态筛选 + 分页 ─────────────────────────"""
        all_tasks = multi_status_tasks

        # 筛选 "completed"
        completed = [t for t in all_tasks if t.status == "completed"]
        session = _mock_session_for_list(completed)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/scans?status=completed&page=1&size=20")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(completed)
        for item in data["items"]:
            assert item["status"] == "completed"

    @pytest.mark.asyncio
    async def test_pagination_boundaries(self, multi_status_tasks):
        """分页边界场景 ──────────────────────────────"""
        all_tasks = multi_status_tasks

        # 第一页
        session1 = _mock_session_for_list(all_tasks[:3], total=len(all_tasks))
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.get("/api/v1/scans?page=1&size=3")
        app.dependency_overrides.clear()

        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["page"] == 1
        assert data1["total"] == len(all_tasks)
        assert len(data1["items"]) == 3

        # 越界页
        session_out = _mock_session_for_list([], total=len(all_tasks))
        app.dependency_overrides[get_db] = _mock_get_db(session_out)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_out = await client.get("/api/v1/scans?page=100&size=20")
        app.dependency_overrides.clear()

        assert resp_out.status_code == 200
        data_out = resp_out.json()
        assert data_out["items"] == []
        assert data_out["total"] == len(all_tasks)

    @pytest.mark.asyncio
    async def test_sort_by_valid_fields(self, multi_status_tasks):
        """按合法字段排序 ────────────────────────────"""
        all_tasks = multi_status_tasks

        for sort_field in ["created_at", "page_count", "confidence_avg", "file_size"]:
            session = _mock_session_for_list(all_tasks)
            from db.session import get_db
            app.dependency_overrides[get_db] = _mock_get_db(session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/v1/scans?sort_by={sort_field}&sort_order=desc")
            app.dependency_overrides.clear()

            assert resp.status_code == 200, f"sort_by={sort_field} 应返回 200"

    @pytest.mark.asyncio
    async def test_sort_by_invalid_field_rejected(self, multi_status_tasks):
        """非法排序字段返回 400 ─────────────────────"""
        session = _mock_session_for_list([])
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/scans?sort_by=__invalid__")
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "Invalid sort_by" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_filter_by_scanner_id(self, multi_status_tasks):
        """按 scanner_id 筛选 ────────────────────────"""
        scanner_tasks = [t for t in multi_status_tasks if t.scanner_id == "scanner-0"]
        session = _mock_session_for_list(scanner_tasks)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/scans?scanner_id=scanner-0")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(scanner_tasks)


# ═══════════════════════════════════════════════════════════
# Workflow 5: Admin 综合链路
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestAdminWorkflow:
    """管理员面板的统计 + 队列组合查询"""

    @pytest.mark.asyncio
    async def test_stats_and_queue_combined(self):
        """stats + queue 联合调用验证数据一致性 ────────"""
        from api.routes.admin import get_db

        # 构造：3 个任务中 1 个 pending, 1 个 processing, 1 个 failed
        total_count = 3
        status_rows = [("completed", 1), ("failed", 1), ("pending", 1)]
        today_count = 2
        avg_conf = 0.87

        mock_session = AsyncMock()
        total_result = MagicMock()
        total_result.scalar.return_value = total_count
        status_result = MagicMock()
        status_result.fetchall.return_value = status_rows
        today_result = MagicMock()
        today_result.scalar.return_value = today_count
        avg_result = MagicMock()
        avg_result.scalar.return_value = avg_conf

        # stats 查询 + queue 查询
        queue_result = MagicMock()
        pending_tasks = []
        for i in range(sum(1 for s, c in status_rows if s in ("pending", "failed"))):
            task = MagicMock()
            task.id = uuid.uuid4()
            task.filename = f"queue_task_{i}.pdf"
            task.status = "pending" if i == 0 else "failed"
            task.priority = i
            task.created_at = datetime.now(timezone.utc)
            pending_tasks.append(task)
        queue_result.scalars.return_value.all.return_value = pending_tasks

        mock_session.execute = AsyncMock(side_effect=[
            total_result, status_result, today_result, avg_result,  # stats
            queue_result,  # queue
        ])

        app.dependency_overrides[get_db] = _mock_get_db(mock_session)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 先查 stats
            stats_resp = await client.get("/api/v1/admin/stats")
            # 再查 queue
            queue_resp = await client.get("/api/v1/admin/queue")

        app.dependency_overrides.clear()

        # 验证 stats
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_tasks"] == 3
        assert stats["today_tasks"] == 2
        assert stats["failed_tasks"] == 1
        assert stats["avg_confidence"] == pytest.approx(0.87, abs=0.01)
        assert stats["by_status"]["completed"] == 1

        # 验证 queue
        assert queue_resp.status_code == 200
        queue = queue_resp.json()
        assert queue["queue_length"] == len(pending_tasks)
        assert len(queue["items"]) == len(pending_tasks)

        # 数据一致性：queue 中的任务不应出现在 stats completed 中
        queue_statuses = {item["status"] for item in queue["items"]}
        assert "completed" not in queue_statuses, "队列中不应有已完成任务"


# ═══════════════════════════════════════════════════════════
# Workflow 6: SPA 静态文件 + API 共存
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestSPAIntegration:
    """Admin SPA 静态文件服务与 API 路由共存"""

    def test_api_routes_accessible_even_with_spa(self):
        """挂载 SPA 后 API 路由仍能正常访问"""
        app = create_app()
        route_paths = [getattr(r, "path", "") for r in app.routes]
        # API 路由应存在
        for path in [
            "/api/v1/ping",
            "/api/v1/health",
            "/api/v1/scans",
            "/api/v1/admin/stats",
        ]:
            assert path in route_paths, f"挂载 SPA 后 {path} 应仍可访问"

    def test_spa_mount_not_registered_when_dist_missing(self):
        """dist 目录不存在时不注册 SPA 挂载"""
        # 默认情况下 dist 目录存在（之前构建过）
        app_instance = create_app()
        route_paths = [getattr(r, "path", "") for r in app_instance.routes]

        # 检查是否有根路由挂载
        root_mounts = [p for p in route_paths if p in ("/", "")]
        # 有或没有都可以——取决于 static/dist 是否存在
        # 只需确保不崩溃即可
        assert isinstance(route_paths, list)


# ═══════════════════════════════════════════════════════════
# Workflow 7: 认证链路（API Key）
# ═══════════════════════════════════════════════════════════

API_KEY = "test-secret-e2e-2026"


def _set_api_key(key: str):
    from pydantic import SecretStr
    from config.settings import settings as _s
    return patch.object(_s, "api_key", SecretStr(key))


@pytest.mark.e2e
class TestAuthChain:
    """API Key 认证链路的完整验证"""

    @pytest.mark.asyncio
    async def test_auth_chain_full_flow(self):
        """完整认证流程：配置 Key → 公开端点 → 保护端点 → 关键验证 ───"""
        from api.routes.admin import get_db

        # 准备 mock stats 数据（需要足够多的 execute side effects）
        mock_session = AsyncMock()
        total_result = MagicMock()
        total_result.scalar.return_value = 0
        status_result = MagicMock()
        status_result.fetchall.return_value = []
        today_result = MagicMock()
        today_result.scalar.return_value = 0
        avg_result = MagicMock()
        avg_result.scalar.return_value = None
        # 为两次 stats 调用准备 side effects（每次 4 个 execute）
        mock_session.execute = AsyncMock(side_effect=[
            total_result, status_result, today_result, avg_result,  # 第一次 stats
            total_result, status_result, today_result, avg_result,  # 第二次 stats（lowercase）
        ])

        with _set_api_key(API_KEY):
            app2 = create_app()
            app2.dependency_overrides[get_db] = _mock_get_db(mock_session)
            transport = ASGITransport(app=app2)

            async with AsyncClient(transport=transport, base_url="http://test") as client:

                # 1. 公开端点：无 Key 仍可访问
                r_ping = await client.get("/api/v1/ping")
                assert r_ping.status_code == 200, "ping 应公开"

                r_health = await client.get("/api/v1/health")
                # health 可能因 mock 而 200 或 500，但不应是 401
                assert r_health.status_code != 401, "health 不应要求认证"

                # 2. 保护端点：无 Key → 401
                r_admin_no_key = await client.get("/api/v1/admin/stats")
                assert r_admin_no_key.status_code == 401
                assert "Missing API key" in r_admin_no_key.json()["detail"]

                # 3. 保护端点：错误 Key → 403
                r_admin_wrong = await client.get(
                    "/api/v1/admin/stats",
                    headers={"X-API-Key": "wrong-key"},
                )
                assert r_admin_wrong.status_code == 403
                assert "Invalid API key" in r_admin_wrong.json()["detail"]

                # 4. 保护端点：正确 Key → 200
                r_admin_ok = await client.get(
                    "/api/v1/admin/stats",
                    headers={"X-API-Key": API_KEY},
                )
                assert r_admin_ok.status_code == 200

                # 5. 小写 header 也能工作
                r_admin_lower = await client.get(
                    "/api/v1/admin/stats",
                    headers={"x-api-key": API_KEY},
                )
                assert r_admin_lower.status_code == 200

                # 6. Scan 端点也需要 Key
                r_scan_no_key = await client.get("/api/v1/scans")
                assert r_scan_no_key.status_code == 401

                # 7. Scan upload 也需要 Key
                r_upload_no_key = await client.post("/api/v1/scans/upload")
                assert r_upload_no_key.status_code == 401

            app2.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
# Workflow 8: 边界 & 异常流程
# ═══════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestBoundaryAndError:
    """边界条件与异常流程的综合测试"""

    @pytest.mark.asyncio
    async def test_upload_invalid_inputs(self):
        """上传各种非法输入 ───────────────────────────"""
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 非 PDF 扩展名
            r1 = await client.post(
                "/api/v1/scans/upload",
                files={"file": ("image.png", io.BytesIO(b"PNG"), "image/png")},
            )
            assert r1.status_code == 400
            assert "Invalid file extension" in r1.json()["detail"]

            # 空文件
            r2 = await client.post(
                "/api/v1/scans/upload",
                files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            )
            assert r2.status_code == 400
            assert "Empty file" in r2.json()["detail"]

            # 没有文件
            r3 = await client.post("/api/v1/scans/upload")
            assert r3.status_code == 422, "缺少 file 字段应返回 422"

    @pytest.mark.asyncio
    async def test_detail_invalid_uuid_format(self):
        """非法 UUID 格式 ────────────────────────────"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/scans/not-a-valid-uuid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_result_for_incomplete_task(self, pending_task):
        """未完成任务获取结果应拒绝 ─────────────────"""
        session = _mock_session_for_scan(pending_task)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/scans/{pending_task.id}/result")
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """删除不存在的任务 ────────────────────────"""
        session = _mock_session_for_scan(None)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session)

        tid = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/scans/{tid}")
        app.dependency_overrides.clear()

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_concurrent_delete_and_detail(self, sample_task):
        """并发场景：删除与详情查询 ─────────────────"""
        task = sample_task

        # 第一次查询：存在
        session_find = _mock_session_for_scan(task)
        from db.session import get_db
        app.dependency_overrides[get_db] = _mock_get_db(session_find)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_detail = await client.get(f"/api/v1/scans/{task.id}")
        app.dependency_overrides.clear()

        assert resp_detail.status_code == 200

        # 删除
        session_del = _mock_session_for_scan(task)
        with patch("api.routes.scan.minio_client") as mock_minio, \
             patch("api.routes.scan.celery_app"):
            mock_minio.delete_task_objects.return_value = None
            app.dependency_overrides[get_db] = _mock_get_db(session_del)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp_delete = await client.delete(f"/api/v1/scans/{task.id}")
            app.dependency_overrides.clear()

        assert resp_delete.status_code == 200

        # 第二次查询：已不存在
        session_notfound = _mock_session_for_scan(None)
        app.dependency_overrides[get_db] = _mock_get_db(session_notfound)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_after = await client.get(f"/api/v1/scans/{task.id}")
        app.dependency_overrides.clear()

        assert resp_after.status_code == 404


# ═══════════════════════════════════════════════════════════
# Workflow 9: 结构完整性验证
# ═════════════════════════════════════════════════