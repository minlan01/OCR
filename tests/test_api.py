"""
API 集成测试
使用 httpx.AsyncClient 覆盖 Health / Admin 端点
Mock 外部依赖 (DB / Redis / MinIO) 以支持无基础设施运行
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import create_app


@pytest.mark.asyncio
async def test_ping_returns_pong():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["ping"] == "pong"
        assert "time" in data
        assert abs(data["time"] - time.time()) < 5
        assert "host" in data


@pytest.mark.asyncio
async def test_health_when_all_services_up():
    with patch("db.session.engine") as mock_engine, \
         patch("api.routes.health.Redis") as mock_redis_cls, \
         patch("services.storage.minio_client.minio_client") as mock_minio:

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis_cls.from_url.return_value = mock_redis

        mock_minio.ping.return_value = True

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["db"] == "ok"
            assert data["redis"] == "ok"
            assert data["minio"] == "ok"


@pytest.mark.asyncio
async def test_health_when_db_fails():
    with patch("db.session.engine") as mock_engine, \
         patch("api.routes.health.Redis") as mock_redis_cls, \
         patch("services.storage.minio_client.minio_client") as mock_minio:

        mock_engine.connect.side_effect = Exception("Connection refused")

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis_cls.from_url.return_value = mock_redis

        mock_minio.ping.return_value = True

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["db"] != "ok"
            assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_when_redis_fails():
    with patch("db.session.engine") as mock_engine, \
         patch("api.routes.health.Redis") as mock_redis_cls, \
         patch("services.storage.minio_client.minio_client") as mock_minio:

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock()

        from redis.exceptions import RedisError as _RedisError
        mock_redis_cls.from_url.side_effect = _RedisError("Redis down")

        mock_minio.ping.return_value = True

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["redis"] != "ok"


@pytest.mark.asyncio
async def test_health_when_minio_fails():
    with patch("db.session.engine") as mock_engine, \
         patch("api.routes.health.Redis") as mock_redis_cls, \
         patch("services.storage.minio_client.minio_client") as mock_minio:

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis_cls.from_url.return_value = mock_redis

        mock_minio.ping.return_value = False

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["minio"] != "ok"


# ── Admin 端点测试 ──

@pytest.mark.asyncio
async def test_admin_stats_returns_expected_schema():
    from api.routes.admin import get_db
    from uuid import uuid4

    mock_session = AsyncMock()
    total_result = MagicMock()
    total_result.scalar.return_value = 42
    status_result = MagicMock()
    status_result.fetchall.return_value = [
        ("completed", 30),
        ("pending", 8),
        ("failed", 4),
    ]
    today_result = MagicMock()
    today_result.scalar.return_value = 5
    avg_result = MagicMock()
    avg_result.scalar.return_value = 0.9345

    mock_session.execute = AsyncMock(side_effect=[total_result, status_result, today_result, avg_result])

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_tasks"] == 42
        assert data["today_tasks"] == 5
        assert data["failed_tasks"] == 4
        assert data["avg_confidence"] == pytest.approx(0.9345, abs=0.001)
        assert data["by_status"] == {"completed": 30, "pending": 8, "failed": 4}


@pytest.mark.asyncio
async def test_admin_stats_no_tasks():
    from api.routes.admin import get_db

    mock_session = AsyncMock()
    total_result = MagicMock()
    total_result.scalar.return_value = 0
    status_result = MagicMock()
    status_result.fetchall.return_value = []
    today_result = MagicMock()
    today_result.scalar.return_value = 0
    avg_result = MagicMock()
    avg_result.scalar.return_value = None

    mock_session.execute = AsyncMock(side_effect=[total_result, status_result, today_result, avg_result])

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_tasks"] == 0
        assert data["today_tasks"] == 0
        assert data["avg_confidence"] is None
        assert data["by_status"] == {}


@pytest.mark.asyncio
async def test_admin_queue_returns_tasks():
    from api.routes.admin import get_db
    from uuid import uuid4
    from datetime import datetime, timezone

    mock_session = AsyncMock()
    task_id1 = uuid4()
    task_id2 = uuid4()
    now = datetime.now(timezone.utc)

    mock_task1 = MagicMock()
    mock_task1.id = task_id1
    mock_task1.filename = "report.pdf"
    mock_task1.status = "pending"
    mock_task1.priority = 0
    mock_task1.created_at = now

    mock_task2 = MagicMock()
    mock_task2.id = task_id2
    mock_task2.filename = "contract.pdf"
    mock_task2.status = "received"
    mock_task2.priority = 5
    mock_task2.created_at = now

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_task1, mock_task2]
    mock_session.execute = AsyncMock(return_value=mock_result)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/queue")
        assert response.status_code == 200
        data = response.json()
        assert data["queue_length"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["filename"] == "report.pdf"
        assert data["items"][1]["filename"] == "contract.pdf"


@pytest.mark.asyncio
async def test_admin_queue_empty():
    from api.routes.admin import get_db

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/queue")
        assert response.status_code == 200
        data = response.json()
        assert data["queue_length"] == 0
        assert data["items"] == []


# ── 应用配置测试 ──

class TestAppConfiguration:

    def test_create_app_returns_fastapi(self):
        from fastapi import FastAPI
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_expected_routes(self):
        app = create_app()
        route_paths = [route.path for route in app.routes if hasattr(route, "path")]
        assert "/api/v1/health" in route_paths
        assert "/api/v1/ping" in route_paths
        assert "/api/v1/admin/stats" in route_paths
        assert "/api/v1/admin/queue" in route_paths
        assert "/api/v1/scans" in route_paths

    def test_app_title_and_version(self):
        app = create_app()
        assert "ScanStruct" in app.title
        assert app.version is not None


# ── API Key 中间件测试 ──

API_KEY = "test-secret-key-12345"


def _set_api_key(key: str):
    """临时设置 api_key 并返回 patch context manager"""
    from pydantic import SecretStr
    from config.settings import settings as _s
    return patch.object(_s, "api_key", SecretStr(key))


@pytest.mark.asyncio
async def test_health_ping_always_public():
    """health 和 ping 即使配置了 API_KEY 也应公开访问"""
    with _set_api_key(API_KEY):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/api/v1/health")
            r2 = await client.get("/api/v1/ping")
            assert r1.status_code == 200
            assert r2.status_code == 200


@pytest.mark.asyncio
async def test_admin_without_key_rejected():
    """无 API Key 访问 /admin/* 应被拒绝"""
    with _set_api_key(API_KEY):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/admin/stats")
            assert r.status_code == 401
            assert "Missing API key" in r.json()["detail"]


@pytest.mark.asyncio
async def test_admin_with_wrong_key_rejected():
    """错误 API Key 应返回 403"""
    with _set_api_key(API_KEY):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/api/v1/admin/stats",
                headers={"X-API-Key": "wrong-key"},
            )
            assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_with_valid_key_accepted():
    """正确 API Key 应放行"""
    from api.routes.admin import get_db

    mock_session = AsyncMock()
    total_result = MagicMock()
    total_result.scalar.return_value = 0
    status_result = MagicMock()
    status_result.fetchall.return_value = []
    today_result = MagicMock()
    today_result.scalar.return_value = 0
    avg_result = MagicMock()
    avg_result.scalar.return_value = None
    mock_session.execute = AsyncMock(side_effect=[total_result, status_result, today_result, avg_result])

    with _set_api_key(API_KEY):
        app = create_app()
        app.dependency_overrides[get_db] = lambda: mock_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/api/v1/admin/stats",
                headers={"X-API-Key": API_KEY},
            )
            assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_with_lowercase_header():
    """小写 x-api-key 头也应被接受"""
    from api.routes.admin import get_db

    mock_session = AsyncMock()
    total_result = MagicMock()
    total_result.scalar.return_value = 0
    status_result = MagicMock()
    status_result.fetchall.return_value = []
    today_result = MagicMock()
    today_result.scalar.return_value = 0
    avg_result = MagicMock()
    avg_result.scalar.return_value = None
    mock_session.execute = AsyncMock(side_effect=[total_result, status_result, today_result, avg_result])

    with _set_api_key(API_KEY):
        app = create_app()
        app.dependency_overrides[get_db] = lambda: mock_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                "/api/v1/admin/stats",
                headers={"x-api-key": API_KEY},
            )
            assert r.status_code == 200
