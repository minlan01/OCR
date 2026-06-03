"""
Scan API 集成测试
覆盖 upload / list / detail / result / retry / delete 全部 6 个端点
使用 httpx.AsyncClient + mock 外部依赖（DB / MinIO / Celery）
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.main import app
from db.models import ScanTask, TaskStep, ScanFile


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_task_id():
    return uuid.uuid4()


@pytest.fixture
def mock_db_session():
    """创建 mock 的 AsyncSession"""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def sample_task(sample_task_id):
    """创建一个示例 ScanTask 用于测试"""
    now = datetime.now(timezone.utc)
    task = ScanTask(
        id=sample_task_id,
        filename="test_document.pdf",
        scanner_id="test_scanner",
        source_type="api_upload",
        status="completed",
        priority=0,
        file_size=102400,
        file_md5="abc123def456",
        page_count=10,
        confidence_avg=0.95,
        structure_score=0.88,
        table_count=3,
        heading_count=12,
        paragraph_count=45,
        callback_url="https://example.com/callback",
        callback_status="success",
        error_code=None,
        error_message=None,
        metadata_={"department": "legal"},
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=now,
    )
    # 模拟 relationship 加载
    task.steps = [
        TaskStep(
            id=1, task_id=sample_task_id, step_name="preprocessing",
            status="completed", duration_ms=1500, retry_count=0,
            error_message=None, started_at=now, completed_at=now,
        ),
        TaskStep(
            id=2, task_id=sample_task_id, step_name="ocr",
            status="completed", duration_ms=8000, retry_count=0,
            error_message=None, started_at=now, completed_at=now,
        ),
    ]
    task.files = [
        ScanFile(
            id=1, task_id=sample_task_id, file_type="raw_pdf",
            page_no=None, bucket="scan-raw",
            object_key=f"raw/2026-05-13/{sample_task_id}_test.pdf",
            size_bytes=102400,
        ),
        ScanFile(
            id=2, task_id=sample_task_id, file_type="ocr_result",
            page_no=None, bucket="scan-result",
            object_key=f"result/{sample_task_id}_result.json",
            size_bytes=20480,
        ),
    ]
    return task


@pytest.fixture
def failed_task(sample_task_id):
    """创建一个失败状态的任务"""
    now = datetime.now(timezone.utc)
    task = ScanTask(
        id=sample_task_id,
        filename="failed_document.pdf",
        scanner_id=None,
        source_type="api_upload",
        status="failed",
        priority=0,
        file_size=51200,
        file_md5="fail123abc",
        page_count=None,
        confidence_avg=None,
        error_code="PIPELINE_ERROR",
        error_message="OCR engine unavailable",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    task.steps = []
    task.files = []
    return task


@pytest.fixture
def pending_task(sample_task_id):
    """创建一个待处理状态的任务"""
    now = datetime.now(timezone.utc)
    task = ScanTask(
        id=sample_task_id,
        filename="pending_document.pdf",
        scanner_id=None,
        source_type="api_upload",
        status="pending",
        file_size=25600,
        file_md5="pend456def",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    task.steps = []
    task.files = []
    return task


# ═══════════════════════════════════════════════════════════
# Override 依赖：替换 DB session 为 mock
# ═══════════════════════════════════════════════════════════

def _mock_get_db(mock_session):
    """生成 mock 的 get_db 依赖"""
    async def _override():
        yield mock_session
    return _override


@pytest.fixture
def client_with_db(mock_db_session):
    """注入 mock DB session 的 AsyncClient"""
    app.dependency_overrides = {}
    from db.session import get_db
    app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
# Tests: Upload
# ═══════════════════════════════════════════════════════════

class TestUpload:
    """POST /api/v1/scans/upload"""

    @pytest.mark.asyncio
    async def test_upload_invalid_extension(self):
        """上传非 PDF 文件应返回 400"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/scans/upload",
                files={"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")},
            )
        assert response.status_code == 400
        assert "Invalid file extension" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_empty_file(self):
        """上传空文件应返回 400"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/scans/upload",
                files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            )
        assert response.status_code == 400
        assert "Empty file" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_pdf_success(self, mock_db_session):
        """正常上传 PDF 应返回 202 + task_id"""
        # Mock: 查重返回 None（无重复）
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio:
            mock_minio.upload_bytes.return_value = 10240

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/scans/upload",
                    files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 mock content"), "application/pdf")},
                    data={"scanner_id": "scanner-01"},
                )

            app.dependency_overrides.clear()

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "received"
        assert data["message"] == "uploaded_pending_process"


# ═══════════════════════════════════════════════════════════
# Tests: List
# ═══════════════════════════════════════════════════════════

class TestList:
    """GET /api/v1/scans"""

    @pytest.mark.asyncio
    async def test_list_empty(self, mock_db_session):
        """空列表返回 page=1, total=0"""
        # Mock: count 返回 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Mock: 查询返回空
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        mock_db_session.execute.side_effect = [count_result, list_result]

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["page"] == 1
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, mock_db_session, sample_task):
        """按 status 筛选"""
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_task]
        mock_db_session.execute.side_effect = [count_result, list_result]

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans?status=completed")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_invalid_sort(self, mock_db_session):
        """非法的 sort_by 字段应返回 400"""
        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans?sort_by=invalid_field")

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "Invalid sort_by" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_with_sort(self, mock_db_session, sample_task):
        """合法 sort_by 参数正常工作"""
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [sample_task]
        mock_db_session.execute.side_effect = [count_result, list_result]

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans?sort_by=page_count&sort_order=asc")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_pagination_edge(self, mock_db_session):
        """越界页码返回空列表"""
        count_result = MagicMock()
        count_result.scalar.return_value = 3
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.side_effect = [count_result, list_result]

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans?page=100&size=20")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 3


# ═══════════════════════════════════════════════════════════
# Tests: Detail
# ═══════════════════════════════════════════════════════════

class TestDetail:
    """GET /api/v1/scans/{task_id}"""

    @pytest.mark.asyncio
    async def test_detail_not_found(self, mock_db_session):
        """不存在的 task_id 返回 404"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        tid = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/scans/{tid}")

        app.dependency_overrides.clear()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_success(self, mock_db_session, sample_task):
        """正常查询返回完整详情"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/scans/{sample_task.id}")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == str(sample_task.id)
        assert data["filename"] == "test_document.pdf"
        assert data["status"] == "completed"
        assert data["page_count"] == 10
        assert len(data["steps"]) == 2
        assert len(data["files"]) == 2
        assert data["steps"][0]["step_name"] == "preprocessing"
        assert data["files"][0]["file_type"] == "raw_pdf"

    @pytest.mark.asyncio
    async def test_detail_invalid_uuid(self):
        """非法 UUID 格式返回 422"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scans/not-a-uuid")

        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════
# Tests: Result
# ═══════════════════════════════════════════════════════════

class TestResult:
    """GET /api/v1/scans/{task_id}/result"""

    @pytest.mark.asyncio
    async def test_result_not_completed(self, mock_db_session, pending_task):
        """未完成的任务返回 400"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pending_task
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/scans/{pending_task.id}/result")

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "not completed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_result_no_file(self, mock_db_session, sample_task):
        """无 result_path 的任务返回 404"""
        sample_task.status = "completed"
        sample_task.result_path = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/scans/{sample_task.id}/result")

        app.dependency_overrides.clear()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_result_success_inline(self, mock_db_session, sample_task):
        """成功获取内联 JSON 结果"""
        sample_task.status = "completed"
        sample_task.result_path = "result/test.json"
        expected_json = {"pages": 10, "headings": 12, "tables": 3}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio:
            mock_minio.download_bytes.return_value = json.dumps(expected_json).encode("utf-8")

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/api/v1/scans/{sample_task.id}/result"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["pages"] == 10
        assert data["tables"] == 3

    @pytest.mark.asyncio
    async def test_result_download_mode(self, mock_db_session, sample_task):
        """download=true 返回 Content-Disposition 头"""
        sample_task.status = "completed"
        sample_task.result_path = "result/test.json"
        expected_json = {"pages": 10}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio:
            mock_minio.download_bytes.return_value = json.dumps(expected_json).encode("utf-8")

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/api/v1/scans/{sample_task.id}/result?download=true"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        # 下载模式下返回的是 Response 而非 JSON dict
        data = json.loads(response.content.decode("utf-8"))
        assert data["pages"] == 10

    @pytest.mark.asyncio
    async def test_result_corrupted_data(self, mock_db_session, sample_task):
        """损坏的 JSON 结果返回 500"""
        sample_task.status = "completed"
        sample_task.result_path = "result/bad.json"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio:
            mock_minio.download_bytes.return_value = b"not valid json!!!"

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/api/v1/scans/{sample_task.id}/result"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 500
        assert "corrupted" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
# Tests: Retry
# ═══════════════════════════════════════════════════════════

class TestRetry:
    """POST /api/v1/scans/{task_id}/retry"""

    @pytest.mark.asyncio
    async def test_retry_not_found(self, mock_db_session):
        """不存在的任务返回 404"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        tid = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/api/v1/scans/{tid}/retry")

        app.dependency_overrides.clear()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_non_failed(self, mock_db_session, pending_task):
        """非 failed 状态的任务重试返回 400"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pending_task
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/scans/{pending_task.id}/retry"
            )

        app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "only failed tasks" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_retry_failed_success(self, mock_db_session, failed_task):
        """failed 状态任务重试成功"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = failed_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.process_scan") as mock_celery:
            mock_celery.delay.return_value = MagicMock(id="celery-task-123")

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/scans/{failed_task.id}/retry"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 202
        data = response.json()
        assert "queued for retry" in data["message"].lower()
        # 验证 Celery 任务被派发
        mock_celery.delay.assert_called_once_with(str(failed_task.id))

    @pytest.mark.asyncio
    async def test_retry_force(self, mock_db_session, pending_task):
        """force=true 允许重试非 failed 任务"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pending_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.process_scan") as mock_celery:
            mock_celery.delay.return_value = MagicMock(id="celery-task-456")

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/scans/{pending_task.id}/retry?force=true"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 202
        mock_celery.delay.assert_called_once_with(str(pending_task.id))

    @pytest.mark.asyncio
    async def test_retry_celery_dispatch_failure(self, mock_db_session, failed_task):
        """Celery 派发失败时任务状态回退为 failed"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = failed_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.process_scan") as mock_celery:
            mock_celery.delay.side_effect = Exception("Redis connection refused")

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/scans/{failed_task.id}/retry"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 500
        assert "dispatch" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
# Tests: Delete
# ═══════════════════════════════════════════════════════════

class TestDelete:
    """DELETE /api/v1/scans/{task_id}"""

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_db_session):
        """不存在的任务返回 404"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        from db.session import get_db
        app.dependency_overrides = {}
        app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

        tid = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/v1/scans/{tid}")

        app.dependency_overrides.clear()

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_db_session, sample_task):
        """正常删除成功"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio, \
             patch("api.routes.scan.celery_app") as mock_celery:
            mock_minio.delete_task_objects.return_value = None

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete(
                    f"/api/v1/scans/{sample_task.id}"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "deleted" in data["message"].lower()
        mock_db_session.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_keep_raw(self, mock_db_session, sample_task):
        """keep_raw=true 保留原始文件"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_task
        mock_db_session.execute.return_value = mock_result

        with patch("api.routes.scan.minio_client") as mock_minio, \
             patch("api.routes.scan.celery_app") as mock_celery:
            # keep_raw 模式下不应该调用 delete_task_objects
            mock_minio.client.list_objects.return_value = []

            from db.session import get_db
            app.dependency_overrides = {}
            app.dependency_overrides[get_db] = _mock_get_db(mock_db_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete(
                    f"/api/v1/scans/{sample_task.id}?keep_raw=true"
                )

            app.dependency_overrides.clear()

        assert response.status_code == 200
        # keep_raw 时不应调用 delete_task_objects
        mock_minio.delete_task_objects.assert_not_called()
