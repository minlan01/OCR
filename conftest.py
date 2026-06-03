"""
pytest 全局配置与共享 fixtures
为所有测试文件提供 mock DB session、任务实例、API 客户端等
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.main import app
from db.models import ScanTask, TaskStep, ScanFile


# ═══════════════════════════════════════════════════════════
# 全局 — 测试环境禁限流
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """所有测试禁用 slowapi 限流"""
    from api.rate_limit import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


# ═══════════════════════════════════════════════════════════
# Fixtures — 基础 mock 对象
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_task_id() -> uuid.UUID:
    """提供一个随机 UUID 作为任务 ID"""
    return uuid.uuid4()


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """创建 mock 的 AsyncSession，方法均可 chain"""
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
def now() -> datetime:
    """统一的当前时间"""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════
# Fixtures — 任务实例（三种状态）
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_task(sample_task_id: uuid.UUID, now: datetime) -> ScanTask:
    """完成状态的完整任务，含 steps、files"""
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
        TaskStep(
            id=3, task_id=sample_task_id, step_name="layout_analysis",
            status="completed", duration_ms=2500, retry_count=0,
            error_message=None, started_at=now, completed_at=now,
        ),
    ]
    task.files = [
        ScanFile(
            id=1, task_id=sample_task_id, file_type="raw_pdf",
            page_no=None, bucket="scan-raw",
            object_key=f"raw/2026-05/{sample_task_id}_test.pdf",
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
def failed_task(sample_task_id: uuid.UUID, now: datetime) -> ScanTask:
    """失败状态的任务"""
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
def pending_task(sample_task_id: uuid.UUID, now: datetime) -> ScanTask:
    """待处理状态的任务"""
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


@pytest.fixture
def processing_task(sample_task_id: uuid.UUID, now: datetime) -> ScanTask:
    """处理中状态的任务"""
    task = ScanTask(
        id=sample_task_id,
        filename="processing.pdf",
        scanner_id="scanner-02",
        source_type="api_upload",
        status="processing",
        priority=5,
        file_size=88000,
        file_md5="proc789ghi",
        metadata_={},
        created_at=now,
        updated_at=now,
        started_at=now,
    )
    task.steps = [
        TaskStep(
            id=1, task_id=sample_task_id, step_name="preprocessing",
            status="completed", duration_ms=1200, retry_count=0,
            started_at=now, completed_at=now,
        ),
        TaskStep(
            id=2, task_id=sample_task_id, step_name="ocr",
            status="processing", retry_count=0,
            started_at=now,
        ),
    ]
    task.files = [
        ScanFile(
            id=1, task_id=sample_task_id, file_type="raw_pdf",
            bucket="scan-raw",
            object_key=f"raw/2026-05/{sample_task_id}_proc.pdf",
            size_bytes=88000,
        ),
    ]
    return task


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _mock_get_db(mock_session: AsyncMock):
    """生成 mock 的 get_db FastAPI 依赖覆盖"""
    async def _override() -> AsyncGenerator:
        yield mock_session
    return _override


def setup_db_override(mock_session: AsyncMock) -> None:
    """注入 mock DB session 到 FastAPI 依赖覆盖"""
    from db.session import get_db
    app.dependency_overrides[get_db] = _mock_get_db(mock_session)


def teardown_db_override() -> None:
    """清理 DB 依赖覆盖"""
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
# Fixtures — API 客户端
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def raw_client() -> AsyncClient:
    """无任何 mock 注入的裸客户端"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def client_with_db(mock_db_session: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    """注入 mock DB session 的 AsyncClient"""
    setup_db_override(mock_db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    teardown_db_override()


# ═══════════════════════════════════════════════════════════
# Fixtures — Mock 工具组合
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_minio_upload():
    """Mock MinIO 上传成功"""
    with patch("api.routes.scan.minio_client") as mock_minio:
        mock_minio.upload_bytes.return_value = 10240
        yield mock_minio


@pytest.fixture
def mock_minio_download():
    """Mock MinIO 下载成功"""
    with patch("api.routes.scan.minio_client") as mock_minio:
        mock_minio.download_bytes.return_value = json.dumps({
            "pages": 10, "headings": 12, "tables": 3
        }).encode("utf-8")
        yield mock_minio


@pytest.fixture
def mock_celery_dispatch():
    """Mock Celery 任务派发"""
    with patch("api.routes.scan.process_scan") as mock_celery:
        mock_celery.delay.return_value = MagicMock(id="celery-task-123")
        yield mock_celery


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """模拟的有效 PDF 内容"""
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF"


# ═══════════════════════════════════════════════════════════
# Fixtures — 多任务列表
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def multi_status_tasks(now: datetime) -> list[ScanTask]:
    """不同状态的多任务列表，用于分页/筛选测试"""
    tasks = []
    statuses = [
        ("completed", 0.95, 10),
        ("completed", 0.88, 5),
        ("completed", 0.92, 8),
        ("failed", None, None),
        ("failed", None, None),
        ("pending", None, None),
        ("pending", None, None),
        ("pending", None, None),
        ("processing", None, None),
        ("received", None, None),
    ]
    for i, (status, conf, pages) in enumerate(statuses):
        tid = uuid.uuid4()
        task = ScanTask(
            id=tid,
            filename=f"doc_{i:03d}.pdf",
            scanner_id=f"scanner-{i % 3}",
            source_type="api_upload",
            status=status,
            priority=i % 5,
            file_size=10000 * (i + 1),
            file_md5=f"md5_{i:03d}",
            page_count=pages,
            confidence_avg=conf,
            metadata_={},
            created_at=now,
            updated_at=now,
        )
        task.steps = []
        task.files = []
        tasks.append(task)
    return tasks
