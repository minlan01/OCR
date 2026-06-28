"""
步骤0 · API 路由集成测试
========================
使用 httpx AsyncClient + ASGITransport，mock service 层

覆盖 8 个 REST 端点 + 错误 case

运行:
    cd E:\\OCRScanStruct
    python -m pytest tests/test_step0_api.py -v --tb=short
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ─── 确保项目根目录在 sys.path ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pydantic import SecretStr

from api.main import app, create_app
from api.dependencies import get_tenant_filter
from config.settings import settings
from db.models_evidence import EvidenceCase, EvidenceMaterial


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def client():
    """构建 AsyncClient，依赖覆盖：get_tenant_filter + 跳过认证"""

    async def _override_tenant():
        return None

    app.dependency_overrides[get_tenant_filter] = _override_tenant

    # Temporarily disable auth: clear jwt_secret_key and api_key so
    # AuthMiddleware enters dev-mode bypass (line 117 of middleware.py)
    original_jwt = settings.jwt_secret_key
    original_api_key = settings.api_key
    settings.jwt_secret_key = ""
    settings.api_key = SecretStr("")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    # Restore
    settings.jwt_secret_key = original_jwt
    settings.api_key = original_api_key
    app.dependency_overrides.clear()


def _make_material(
    case_id: uuid.UUID | None = None,
    metadata_: dict[str, Any] | None = None,
) -> EvidenceMaterial:
    """构造 EvidenceMaterial"""
    now = datetime.now(timezone.utc)
    m = EvidenceMaterial(
        id=uuid.uuid4(),
        evidence_case_id=case_id or uuid.uuid4(),
        original_filename="test.jpg",
        file_type="image",
        minio_bucket="scan-result",
        minio_key="evidence/raw/test.jpg",
        file_size=1024,
        ocr_status="pending",
        metadata_=metadata_ or {"source": "step0_preprocess"},
    )
    # Set timestamps manually (normally set by DB server_default)
    m.created_at = now
    m.updated_at = now
    return m


def _make_case(case_id: uuid.UUID | None = None) -> EvidenceCase:
    return EvidenceCase(
        id=case_id or uuid.uuid4(),
        case_name="Test",
        case_type="injury",
        metadata_={"step0_status": "not_started"},
    )


def _mock_db_with_case(case: EvidenceCase | None = None):
    """构造 mock 返回 case 存在的 db result"""
    result = MagicMock()
    result.scalar_one_or_none.return_value = case or _make_case()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. POST /step0/upload
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Upload:
    """测试上传端点"""

    async def test_upload_success(self, client: AsyncClient):
        """上传成功 → 201 + Step0UploadResponse"""
        case_id = uuid.uuid4()
        mat = _make_material(case_id=case_id)

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.upload_raw_materials", new_callable=AsyncMock, return_value=[mat]),
        ):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/upload",
                files=[
                    ("files", ("test1.jpg", b"img1", "image/jpeg")),
                    ("files", ("test2.jpg", b"img2", "image/jpeg")),
                ],
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["case_id"] == str(case_id)
        assert data["uploaded_count"] == 1
        assert len(data["materials"]) == 1

    async def test_upload_case_not_found(self, client: AsyncClient):
        """case 不存在 → 404"""
        case_id = uuid.uuid4()
        from fastapi import HTTPException

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock,
                    side_effect=HTTPException(status_code=404, detail="Not found")):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/upload",
                files=[("files", ("test.jpg", b"img", "image/jpeg"))],
            )

        assert resp.status_code == 404

    async def test_upload_no_files(self, client: AsyncClient):
        """未选择文件 → 400"""
        case_id = uuid.uuid4()

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/upload",
                files=[],
            )

        assert resp.status_code == 400 or resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST /step0/preprocess
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Preprocess:
    """测试启动预处理"""

    async def test_preprocess_returns_task_id(self, client: AsyncClient):
        """预处理 → 返回 task_id"""
        case_id = uuid.uuid4()

        mock_task = MagicMock()
        mock_task.id = "celery-task-abc123"

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("worker.step0_tasks.process_step0_preprocess") as mock_celery,
        ):
            mock_celery.delay.return_value = mock_task
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/preprocess",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "celery-task-abc123"
        assert "message" in data

    async def test_preprocess_case_not_found(self, client: AsyncClient):
        """case 不存在 → 404"""
        case_id = uuid.uuid4()
        from fastapi import HTTPException

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock,
                    side_effect=HTTPException(status_code=404, detail="Not found")):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/preprocess",
            )

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GET /step0/progress
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Progress:
    """测试获取进度"""

    async def test_progress_success(self, client: AsyncClient):
        """获取进度成功"""
        case_id = uuid.uuid4()
        progress_data = {
            "total": 10,
            "processed": 5,
            "failed": 1,
            "pending": 4,
            "progress_percent": 50.0,
            "step0_status": "in_progress",
            "category_summary": {"fee_medical": 3, "fee_nursing": 2},
        }

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_preprocess_progress", new_callable=AsyncMock,
                  return_value=progress_data),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/progress",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert data["processed"] == 5
        assert data["failed"] == 1
        assert data["pending"] == 4
        assert data["progress_percent"] == 50.0
        assert data["step0_status"] == "in_progress"

    async def test_progress_case_not_found(self, client: AsyncClient):
        """case 不存在 → 404"""
        case_id = uuid.uuid4()
        from fastapi import HTTPException

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock,
                    side_effect=HTTPException(status_code=404, detail="Not found")):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/progress",
            )

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GET /step0/materials
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Materials:
    """测试获取素材列表"""

    async def test_materials_returns_list(self, client: AsyncClient):
        """返回素材列表"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(case_id=case_id, metadata_={
                "source": "step0_preprocess", "step0_fee_category": "fee_medical"
            }),
            _make_material(case_id=case_id, metadata_={
                "source": "step0_preprocess", "step0_fee_category": "fee_nursing"
            }),
        ]

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_step0_materials", new_callable=AsyncMock,
                  return_value=mats),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/materials",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_materials_empty_list(self, client: AsyncClient):
        """无素材 → 空列表"""
        case_id = uuid.uuid4()

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_step0_materials", new_callable=AsyncMock,
                  return_value=[]),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/materials",
            )

        assert resp.status_code == 200
        assert resp.json() == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PUT /step0/materials/{id}/category
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0CorrectCategory:
    """测试手动纠正分类"""

    async def test_correct_returns_updated_material(self, client: AsyncClient):
        """纠正成功 → 返回更新后 material"""
        case_id = uuid.uuid4()
        mat_id = uuid.uuid4()
        mat = _make_material(case_id=case_id, metadata_={
            "source": "step0_preprocess",
            "step0_fee_category": "fee_nursing",
            "step0_corrected": True,
        })

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.correct_category", new_callable=AsyncMock,
                  return_value=mat),
        ):
            resp = await client.put(
                f"/api/v1/evidence/cases/{case_id}/step0/materials/{mat_id}/category",
                json={"new_category": "fee_nursing"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["step0_corrected"] is True

    async def test_correct_invalid_category_returns_400(self, client: AsyncClient):
        """非法 category → 400"""
        case_id = uuid.uuid4()
        mat_id = uuid.uuid4()

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock):
            resp = await client.put(
                f"/api/v1/evidence/cases/{case_id}/step0/materials/{mat_id}/category",
                json={"new_category": "fee_invalid_xyz"},
            )

        assert resp.status_code == 400

    async def test_correct_material_not_found(self, client: AsyncClient):
        """material 不存在 → 404"""
        case_id = uuid.uuid4()
        mat_id = uuid.uuid4()

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.correct_category", new_callable=AsyncMock,
                  side_effect=ValueError("Material not found")),
        ):
            resp = await client.put(
                f"/api/v1/evidence/cases/{case_id}/step0/materials/{mat_id}/category",
                json={"new_category": "fee_medical"},
            )

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 6. POST /step0/skip
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Skip:
    """测试跳过步骤0"""

    async def test_skip_success(self, client: AsyncClient):
        """跳过成功"""
        case_id = uuid.uuid4()

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.skip_step0", new_callable=AsyncMock),
        ):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/skip",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == str(case_id)
        assert "message" in data

    async def test_skip_case_not_found(self, client: AsyncClient):
        """case 不存在 → 404"""
        case_id = uuid.uuid4()
        from fastapi import HTTPException

        with patch("api.routes.step0._check_case_exists", new_callable=AsyncMock,
                    side_effect=HTTPException(status_code=404, detail="Not found")):
            resp = await client.post(
                f"/api/v1/evidence/cases/{case_id}/step0/skip",
            )

        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GET /step0/summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestStep0Summary:
    """测试分类汇总"""

    async def test_summary_success(self, client: AsyncClient):
        """获取汇总成功"""
        case_id = uuid.uuid4()
        summary = {"fee_medical": 3, "fee_nursing": 2}

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_category_summary", new_callable=AsyncMock,
                  return_value=summary),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/summary",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["category_summary"] == summary
        assert len(data["category_detail"]) == 2
        # category_detail 应包含 category_cn
        detail_cats = {d["category"] for d in data["category_detail"]}
        assert "fee_medical" in detail_cats
        assert "fee_nursing" in detail_cats

    async def test_summary_empty(self, client: AsyncClient):
        """无数据 → 空汇总"""
        case_id = uuid.uuid4()

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_category_summary", new_callable=AsyncMock,
                  return_value={}),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/summary",
            )

        assert resp.status_code == 200
        assert resp.json()["category_summary"] == {}

    async def test_summary_includes_cn_name(self, client: AsyncClient):
        """category_detail 包含中文名"""
        case_id = uuid.uuid4()
        summary = {"fee_medical": 1}

        with (
            patch("api.routes.step0._check_case_exists", new_callable=AsyncMock),
            patch("api.routes.step0.get_category_summary", new_callable=AsyncMock,
                  return_value=summary),
        ):
            resp = await client.get(
                f"/api/v1/evidence/cases/{case_id}/step0/summary",
            )

        data = resp.json()
        med_detail = [d for d in data["category_detail"] if d["category"] == "fee_medical"][0]
        assert med_detail["category_cn"] == "医疗费"
