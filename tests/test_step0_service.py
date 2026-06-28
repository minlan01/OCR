"""
步骤0 · Service 层单元测试
==========================
覆盖 11 个核心方法，使用 mock AsyncSession + mock MinIO client。

关键断言：
- 所有修改 metadata_ 的方法必须调用 copy.deepcopy
- flush() 后必须 commit()
- MinIO 路径格式正确
- 序号策略：追加不重排

运行:
    cd E:\\OCRScanStruct
    python -m pytest tests/test_step0_service.py -v --tb=short
"""
from __future__ import annotations

import copy
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 确保项目根目录在 sys.path ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db.models_evidence import EvidenceCase, EvidenceMaterial
from services.evidence import step0_service as svc
from services.evidence.step0_constants import (
    STEP0_CONFIDENCE_THRESHOLD,
    STEP0_FEE_CATEGORIES,
    STEP0_STATUS_SKIPPED,
)
from services.evidence.step0_service import (
    ALLOWED_EXTENSIONS,
    EVIDENCE_MINIO_BUCKET,
    MAX_FILE_SIZE,
    _build_archive_key,
    _generate_seq,
    _get_extension,
    _archive_material,
    _split_pdf_and_archive,
    correct_category,
    get_category_summary,
    get_preprocess_progress,
    get_step0_materials,
    skip_step0,
    upload_raw_materials,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures & Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_mock_upload_file(
    filename: str = "test.jpg",
    content: bytes = b"fake image bytes",
    content_type: str = "image/jpeg",
) -> MagicMock:
    """构造 mock UploadFile"""
    f = MagicMock()
    f.filename = filename
    f.content_type = content_type
    f.size = len(content)
    f.read = AsyncMock(return_value=content)
    return f


def _make_material(
    case_id: uuid.UUID | None = None,
    original_filename: str = "test.jpg",
    file_type: str = "image",
    minio_key: str | None = None,
    ocr_status: str = "pending",
    metadata_: dict[str, Any] | None = None,
) -> EvidenceMaterial:
    """构造 EvidenceMaterial 实例（不依赖 DB）"""
    return EvidenceMaterial(
        id=uuid.uuid4(),
        evidence_case_id=case_id or uuid.uuid4(),
        original_filename=original_filename,
        file_type=file_type,
        minio_bucket=EVIDENCE_MINIO_BUCKET,
        minio_key=minio_key or f"evidence/raw/test.jpg",
        file_size=1024,
        ocr_status=ocr_status,
        metadata_=metadata_ or {},
    )


def _make_case(
    case_id: uuid.UUID | None = None,
    metadata_: dict[str, Any] | None = None,
) -> EvidenceCase:
    """构造 EvidenceCase 实例"""
    return EvidenceCase(
        id=case_id or uuid.uuid4(),
        case_name="Test Case",
        case_type="injury",
        metadata_=metadata_ or {},
    )


def _make_mock_db(materials_return: list | None = None, case_return: Any = None):
    """构造 mock AsyncSession，可配置 execute 返回链"""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.close = AsyncMock()

    # execute 返回的 result 对象
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = materials_return or []
    result.scalars.return_value = scalars_mock
    result.scalar_one_or_none.return_value = case_return
    result.scalar.return_value = 0
    db.execute = AsyncMock(return_value=result)

    return db, result


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _get_extension
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetExtension:
    """测试 _get_extension 工具函数"""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("photo.jpg", ".jpg"),
            ("photo.JPEG", ".jpeg"),
            ("photo.PNG", ".png"),
            ("doc.pdf", ".pdf"),
            ("archive.tar.gz", ".gz"),
            ("noext", ""),
            ("path/to/file.PDF", ".pdf"),
        ],
    )
    def test_get_extension(self, filename: str, expected: str):
        assert _get_extension(filename) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _build_archive_key
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildArchiveKey:
    """测试归档路径构建"""

    def test_image_key_format(self):
        """图片归档路径：evidence/{cid}/preprocess/{类别名}/{类别名}{序号}.{ext}"""
        case_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        key = _build_archive_key(case_id, "医疗费", 1, ".jpg")
        assert key == f"evidence/{case_id}/preprocess/医疗费/医疗费1.jpg"

    def test_pdf_page_key_format(self):
        """PDF 拆分路径：evidence/{cid}/preprocess/{类别名}/{类别名}{序号}_{页码}.jpg"""
        case_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        key = _build_archive_key(case_id, "医疗费", 1, ".pdf", page=2)
        assert key == f"evidence/{case_id}/preprocess/医疗费/医疗费1_2.jpg"

    def test_different_seq(self):
        """不同序号生成不同路径"""
        case_id = uuid.uuid4()
        key1 = _build_archive_key(case_id, "护理费", 1, ".jpg")
        key3 = _build_archive_key(case_id, "护理费", 3, ".jpg")
        assert "护理费1" in key1
        assert "护理费3" in key3

    def test_none_page_for_image(self):
        """page=None 时走图片路径格式"""
        case_id = uuid.uuid4()
        key = _build_archive_key(case_id, "鉴定费", 5, ".png", page=None)
        assert "_5" not in key
        assert "鉴定费5.png" in key


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _generate_seq
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateSeq:
    """测试序号生成（追加不重排）"""

    async def test_seq_with_existing_2_returns_3(self):
        """已有 2 个归档 → 返回 3"""
        case_id = uuid.uuid4()
        # 构造 2 个已归档材料
        archived_mats = [
            _make_material(
                case_id=case_id,
                metadata_={
                    "source": "step0_preprocess",
                    "step0_fee_category": "fee_medical",
                    "step0_archived_key": "evidence/.../医疗费1.jpg",
                },
            ),
            _make_material(
                case_id=case_id,
                metadata_={
                    "source": "step0_preprocess",
                    "step0_fee_category": "fee_medical",
                    "step0_archived_key": "evidence/.../医疗费2.jpg",
                },
            ),
        ]

        db, result = _make_mock_db(materials_return=archived_mats)
        seq = await _generate_seq(case_id, "医疗费", db)

        assert seq == 3

    async def test_seq_with_zero_existing_returns_1(self):
        """没有已归档材料 → 返回 1"""
        case_id = uuid.uuid4()
        db, result = _make_mock_db(materials_return=[])

        seq = await _generate_seq(case_id, "医疗费", db)
        assert seq == 1

    async def test_seq_ignores_non_step0_materials(self):
        """非 step0_preprocess 来源的材料不计入序号"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(
                case_id=case_id,
                metadata_={
                    "source": "other_source",  # 非 step0
                    "step0_fee_category": "fee_medical",
                    "step0_archived_key": "some_key",
                },
            ),
        ]
        db, _ = _make_mock_db(materials_return=mats)

        seq = await _generate_seq(case_id, "医疗费", db)
        assert seq == 1

    async def test_seq_ignores_unarchived_materials(self):
        """未归档（无 step0_archived_key）的材料不计入序号"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(
                case_id=case_id,
                metadata_={
                    "source": "step0_preprocess",
                    "step0_fee_category": "fee_medical",
                    "step0_archived_key": None,  # 未归档
                },
            ),
        ]
        db, _ = _make_mock_db(materials_return=mats)

        seq = await _generate_seq(case_id, "医疗费", db)
        assert seq == 1

    async def test_seq_ignores_different_category(self):
        """不同类别的材料不计入当前类别序号"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(
                case_id=case_id,
                metadata_={
                    "source": "step0_preprocess",
                    "step0_fee_category": "fee_nursing",  # 不同类别
                    "step0_archived_key": "evidence/.../护理费1.jpg",
                },
            ),
        ]
        db, _ = _make_mock_db(materials_return=mats)

        seq = await _generate_seq(case_id, "医疗费", db)
        assert seq == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. upload_raw_materials
# ═══════════════════════════════════════════════════════════════════════════════

class TestUploadRawMaterials:
    """测试上传原始素材"""

    async def test_upload_2_files_creates_2_materials(self):
        """上传 2 个文件 → 创建 2 个 material"""
        case_id = uuid.uuid4()
        files = [
            _make_mock_upload_file("photo1.jpg", b"img1"),
            _make_mock_upload_file("photo2.jpg", b"img2"),
        ]

        db, _ = _make_mock_db()

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            materials = await upload_raw_materials(case_id, files, None, db)

        assert len(materials) == 2
        assert db.add.call_count == 2
        # flush called per file + final commit
        assert db.flush.await_count >= 2
        assert db.commit.await_count >= 1

    async def test_uploaded_material_has_correct_status(self):
        """上传后 ocr_status='pending'"""
        case_id = uuid.uuid4()
        files = [_make_mock_upload_file("test.jpg", b"image")]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            materials = await upload_raw_materials(case_id, files, None, db)

        assert materials[0].ocr_status == "pending"

    async def test_uploaded_material_metadata_source(self):
        """metadata_.source='step0_preprocess'"""
        case_id = uuid.uuid4()
        files = [_make_mock_upload_file("test.jpg", b"image")]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            materials = await upload_raw_materials(case_id, files, None, db)

        md = materials[0].metadata_
        assert md["source"] == "step0_preprocess"
        assert md["step0_raw_key"] is not None
        assert md["step0_corrected"] is False
        assert md["step0_needs_review"] is False

    async def test_raw_key_path_format(self):
        """raw key 路径格式: evidence/{case_id}/preprocess/raw/{uuid}_{原名}"""
        case_id = uuid.uuid4()
        files = [_make_mock_upload_file("发票.jpg", b"image")]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            materials = await upload_raw_materials(case_id, files, None, db)

        raw_key = materials[0].metadata_["step0_raw_key"]
        assert raw_key.startswith(f"evidence/{case_id}/preprocess/raw/")
        assert "发票" in raw_key or "%E5%8F%91%E7%A5%A8" in raw_key

    async def test_unsupported_extension_raises(self):
        """不支持的文件类型 → ValueError"""
        case_id = uuid.uuid4()
        files = [_make_mock_upload_file("doc.txt", b"text")]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client"),
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="不支持的文件类型"):
                await upload_raw_materials(case_id, files, None, db)

    async def test_file_too_large_raises(self):
        """超大文件 → ValueError"""
        case_id = uuid.uuid4()
        big_content = b"x" * (MAX_FILE_SIZE + 1)
        files = [_make_mock_upload_file("big.jpg", big_content)]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client"),
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="文件过大"):
                await upload_raw_materials(case_id, files, None, db)

    async def test_minio_upload_called_with_correct_bucket(self):
        """MinIO upload_bytes 使用正确的 bucket"""
        case_id = uuid.uuid4()
        files = [_make_mock_upload_file("test.jpg", b"image")]

        db, _ = _make_mock_db()
        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await upload_raw_materials(case_id, files, None, db)

        mock_minio.upload_bytes.assert_called_once()
        call_kwargs = mock_minio.upload_bytes.call_args
        assert call_kwargs.kwargs.get("bucket") == EVIDENCE_MINIO_BUCKET or \
               call_kwargs[1].get("bucket") == EVIDENCE_MINIO_BUCKET


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _archive_material
# ═══════════════════════════════════════════════════════════════════════════════

class TestArchiveMaterial:
    """测试归档单个素材"""

    async def test_archive_updates_material_fields(self):
        """归档后 material 字段正确更新"""
        case_id = uuid.uuid4()
        material = _make_material(
            case_id=case_id,
            original_filename="发票.jpg",
            metadata_={
                "source": "step0_preprocess",
                "step0_raw_key": "evidence/raw/test.jpg",
            },
        )

        db, _ = _make_mock_db(materials_return=[])

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.download_bytes = MagicMock(return_value=b"image data")

            await _archive_material(
                material=material,
                category="fee_medical",
                confidence=0.9,
                db=db,
            )

        assert material.auto_category == "fee_medical"
        assert material.effective_category == "fee_medical"
        assert material.category_confidence == 0.9
        assert material.ocr_status == "completed"
        md = material.metadata_
        assert md["step0_fee_category"] == "fee_medical"
        assert md["step0_archived_key"] is not None

    async def test_archive_uses_deepcopy(self):
        """归档必须使用 copy.deepcopy 修改 metadata_"""
        case_id = uuid.uuid4()
        original_md = {
            "source": "step0_preprocess",
            "step0_raw_key": "evidence/raw/test.jpg",
        }
        material = _make_material(
            case_id=case_id,
            metadata_=original_md,
        )

        db, _ = _make_mock_db(materials_return=[])

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch("services.evidence.step0_service.copy.deepcopy", wraps=copy.deepcopy) as mock_dc,
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.download_bytes = MagicMock(return_value=b"data")

            await _archive_material(
                material=material,
                category="fee_medical",
                confidence=0.9,
                db=db,
            )

        mock_dc.assert_called()

    async def test_archive_low_confidence_marks_review(self):
        """置信度 < 0.6 → step0_needs_review=True"""
        case_id = uuid.uuid4()
        material = _make_material(case_id=case_id)

        db, _ = _make_mock_db(materials_return=[])

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.download_bytes = MagicMock(return_value=b"data")

            await _archive_material(
                material=material,
                category="fee_medical",
                confidence=0.4,  # < 0.6
                db=db,
            )

        assert material.metadata_["step0_needs_review"] is True

    async def test_archive_high_confidence_no_review(self):
        """置信度 >= 0.6 → step0_needs_review=False"""
        case_id = uuid.uuid4()
        material = _make_material(case_id=case_id)

        db, _ = _make_mock_db(materials_return=[])

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.download_bytes = MagicMock(return_value=b"data")

            await _archive_material(
                material=material,
                category="fee_medical",
                confidence=0.8,
                db=db,
            )

        assert material.metadata_["step0_needs_review"] is False

    async def test_archive_calls_flush(self):
        """归档后调用 flush"""
        case_id = uuid.uuid4()
        material = _make_material(case_id=case_id)
        db, _ = _make_mock_db(materials_return=[])

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.download_bytes = MagicMock(return_value=b"data")

            await _archive_material(material, "fee_medical", 0.9, db)

        db.flush.assert_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _split_pdf_and_archive
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitPdfAndArchive:
    """测试 PDF 拆分归档"""

    async def test_split_3_pages_creates_3_children(self):
        """3 页 PDF → 创建 3 个子 material"""
        case_id = uuid.uuid4()
        parent = _make_material(
            case_id=case_id,
            original_filename="report.pdf",
            file_type="pdf",
            metadata_={"source": "step0_preprocess", "step0_raw_key": "raw/key.pdf"},
        )

        db, _ = _make_mock_db(materials_return=[])

        # Mock fitz
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=3)

        mock_pixmaps = []
        for i in range(3):
            mock_pix = MagicMock()
            mock_pix.tobytes.return_value = f"page{i+1}".encode()
            mock_pixmaps.append(mock_pix)

        mock_pages = []
        for i in range(3):
            mock_page = MagicMock()
            mock_page.get_pixmap.return_value = mock_pixmaps[i]
            mock_pages.append(mock_page)

        mock_doc.__getitem__ = MagicMock(side_effect=mock_pages)

        # Track added children
        added_materials: list = []
        original_add = db.add

        def track_add(obj):
            added_materials.append(obj)
            original_add(obj)

        db.add = track_add

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        # 3 子 material 被添加 + _archive_material 被调 3 次
        assert len(added_materials) == 3

    async def test_parent_minio_key_unchanged(self):
        """母 material 的 minio_key 保持指向 raw（不变）"""
        case_id = uuid.uuid4()
        original_raw_key = "evidence/raw/report.pdf"
        parent = _make_material(
            case_id=case_id,
            original_filename="report.pdf",
            file_type="pdf",
            minio_key=original_raw_key,
            metadata_={"source": "step0_preprocess", "step0_raw_key": original_raw_key},
        )

        db, _ = _make_mock_db(materials_return=[])

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"page"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        # 母 material minio_key 不变
        assert parent.minio_key == original_raw_key

    async def test_parent_ocr_status_completed(self):
        """母 material ocr_status='completed'"""
        case_id = uuid.uuid4()
        parent = _make_material(
            case_id=case_id,
            file_type="pdf",
            metadata_={"source": "step0_preprocess", "step0_raw_key": "raw.pdf"},
        )

        db, _ = _make_mock_db(materials_return=[])

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"page"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        assert parent.ocr_status == "completed"

    async def test_child_metadata_has_page_number(self):
        """子 material metadata_.step0_page_number 正确"""
        case_id = uuid.uuid4()
        parent = _make_material(
            case_id=case_id,
            file_type="pdf",
            metadata_={"source": "step0_preprocess", "step0_raw_key": "raw.pdf"},
        )

        db, _ = _make_mock_db(materials_return=[])
        added_materials: list = []
        original_add = db.add
        db.add = lambda obj: added_materials.append(obj) or original_add(obj)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=3)

        pages_pix = []
        for i in range(3):
            mp = MagicMock()
            mpix = MagicMock()
            mpix.tobytes.return_value = b"page"
            mp.get_pixmap.return_value = mpix
            pages_pix.append(mp)
        mock_doc.__getitem__ = MagicMock(side_effect=pages_pix)

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        page_numbers = [m.metadata_["step0_page_number"] for m in added_materials]
        assert page_numbers == [1, 2, 3]

    async def test_child_metadata_has_parent_id(self):
        """子 material metadata_.step0_parent_material_id = 母 id"""
        case_id = uuid.uuid4()
        parent = _make_material(
            case_id=case_id,
            file_type="pdf",
            metadata_={"source": "step0_preprocess", "step0_raw_key": "raw.pdf"},
        )
        parent_id_str = str(parent.id)

        db, _ = _make_mock_db(materials_return=[])
        added_materials: list = []
        original_add = db.add
        db.add = lambda obj: added_materials.append(obj) or original_add(obj)

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"page"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        assert added_materials[0].metadata_["step0_parent_material_id"] == parent_id_str

    async def test_split_uses_deepcopy_for_parent(self):
        """拆分后母 material metadata_ 使用 deepcopy"""
        case_id = uuid.uuid4()
        parent = _make_material(
            case_id=case_id,
            file_type="pdf",
            metadata_={"source": "step0_preprocess", "step0_raw_key": "raw.pdf"},
        )

        db, _ = _make_mock_db(materials_return=[])

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"page"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        with (
            patch("fitz.open", return_value=mock_doc),
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch.object(svc, "_archive_material", new_callable=AsyncMock),
            patch("services.evidence.step0_service.copy.deepcopy", wraps=copy.deepcopy) as mock_dc,
        ):
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            await _split_pdf_and_archive(parent, b"pdf bytes", "fee_medical", 0.9, db)

        mock_dc.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. correct_category
# ═══════════════════════════════════════════════════════════════════════════════

class TestCorrectCategory:
    """测试手动纠正分类"""

    async def test_correct_updates_category_fields(self):
        """纠正后字段正确更新"""
        material_id = uuid.uuid4()
        case_id = uuid.uuid4()
        material = _make_material(
            case_id=case_id,
            original_filename="发票.jpg",
            metadata_={
                "source": "step0_preprocess",
                "step0_fee_category": "fee_medical",
                "step0_archived_key": "evidence/old/医疗费1.jpg",
                "step0_raw_key": "evidence/raw/test.jpg",
            },
        )

        db, result = _make_mock_db(materials_return=[], case_return=material)
        # correct_category queries material by id
        result.scalar_one_or_none.return_value = material

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=2),
        ):
            mock_minio.download_bytes = MagicMock(return_value=b"image")
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.delete_object = MagicMock()

            updated = await correct_category(material_id, "fee_nursing", db)

        assert updated.manual_category == "fee_nursing"
        assert updated.effective_category == "fee_nursing"
        assert updated.metadata_["step0_fee_category"] == "fee_nursing"
        assert updated.metadata_["step0_corrected"] is True
        assert updated.metadata_["step0_needs_review"] is False

    async def test_correct_invalid_category_raises(self):
        """非法 category → ValueError"""
        material_id = uuid.uuid4()
        db, _ = _make_mock_db()

        with pytest.raises(ValueError, match="无效的费用类别"):
            await correct_category(material_id, "fee_invalid", db)

    async def test_correct_material_not_found_raises(self):
        """material 不存在 → ValueError"""
        material_id = uuid.uuid4()
        db, result = _make_mock_db()
        result.scalar_one_or_none.return_value = None

        with pytest.raises(ValueError, match="Material not found"):
            await correct_category(material_id, "fee_medical", db)

    async def test_correct_deletes_old_archive_key(self):
        """纠正后删除旧归档文件"""
        material_id = uuid.uuid4()
        case_id = uuid.uuid4()
        old_key = "evidence/old/医疗费1.jpg"
        material = _make_material(
            case_id=case_id,
            metadata_={
                "source": "step0_preprocess",
                "step0_archived_key": old_key,
                "step0_raw_key": "raw.jpg",
            },
        )

        db, result = _make_mock_db(case_return=material)

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.download_bytes = MagicMock(return_value=b"image")
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.delete_object = MagicMock()

            await correct_category(material_id, "fee_nursing", db)

        # delete_object 应被调用（删除旧 key）
        mock_minio.delete_object.assert_called()

    async def test_correct_uses_deepcopy(self):
        """纠正必须使用 deepcopy"""
        material_id = uuid.uuid4()
        case_id = uuid.uuid4()
        material = _make_material(
            case_id=case_id,
            metadata_={
                "source": "step0_preprocess",
                "step0_archived_key": "old.jpg",
                "step0_raw_key": "raw.jpg",
            },
        )

        db, result = _make_mock_db(case_return=material)

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
            patch("services.evidence.step0_service.copy.deepcopy", wraps=copy.deepcopy) as mock_dc,
        ):
            mock_minio.download_bytes = MagicMock(return_value=b"image")
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.delete_object = MagicMock()

            await correct_category(material_id, "fee_nursing", db)

        mock_dc.assert_called()

    async def test_correct_calls_commit(self):
        """纠正后调用 commit"""
        material_id = uuid.uuid4()
        case_id = uuid.uuid4()
        material = _make_material(
            case_id=case_id,
            metadata_={
                "source": "step0_preprocess",
                "step0_archived_key": "old.jpg",
                "step0_raw_key": "raw.jpg",
            },
        )

        db, result = _make_mock_db(case_return=material)

        with (
            patch("services.storage.minio_client.minio_client") as mock_minio,
            patch.object(svc, "_generate_seq", new_callable=AsyncMock, return_value=1),
        ):
            mock_minio.download_bytes = MagicMock(return_value=b"image")
            mock_minio.upload_bytes = MagicMock(return_value=1024)
            mock_minio.delete_object = MagicMock()

            await correct_category(material_id, "fee_nursing", db)

        db.commit.assert_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. skip_step0
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkipStep0:
    """测试跳过步骤0"""

    async def test_skip_calls_update_status(self):
        """skip_step0 调用 _update_case_step0_status with 'skipped'"""
        case_id = uuid.uuid4()
        db, _ = _make_mock_db()

        with patch.object(svc, "_update_case_step0_status", new_callable=AsyncMock) as mock_update:
            await skip_step0(case_id, db)

        mock_update.assert_awaited_once()
        args = mock_update.call_args
        # 第二个位置参数应为 status
        assert args.args[1] == STEP0_STATUS_SKIPPED or args.kwargs.get("status") == STEP0_STATUS_SKIPPED


# ═══════════════════════════════════════════════════════════════════════════════
# 9. get_step0_materials
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetStep0Materials:
    """测试查询步骤0素材"""

    async def test_filters_step0_source_only(self):
        """只返回 source='step0_preprocess' 的素材"""
        case_id = uuid.uuid4()
        step0_mat = _make_material(
            case_id=case_id,
            metadata_={"source": "step0_preprocess"},
        )
        other_mat = _make_material(
            case_id=case_id,
            metadata_={"source": "other"},
        )
        all_mats = [step0_mat, other_mat]

        db, result = _make_mock_db(materials_return=all_mats)

        materials = await get_step0_materials(case_id, db)

        assert len(materials) == 1
        assert materials[0] == step0_mat

    async def test_empty_list_when_no_step0(self):
        """无 step0 素材 → 返回空列表"""
        case_id = uuid.uuid4()
        db, result = _make_mock_db(materials_return=[])

        materials = await get_step0_materials(case_id, db)
        assert materials == []

    async def test_handles_none_metadata(self):
        """metadata_ 为 None 时不报错"""
        case_id = uuid.uuid4()
        mat = _make_material(case_id=case_id, metadata_={})
        mat.metadata_ = None

        db, result = _make_mock_db(materials_return=[mat])

        materials = await get_step0_materials(case_id, db)
        assert len(materials) == 0  # None metadata → not step0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. get_category_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetCategorySummary:
    """测试分类汇总"""

    async def test_summary_groups_by_category(self):
        """按 step0_fee_category 分组 COUNT"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(case_id=case_id, metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_medical"}),
            _make_material(case_id=case_id, metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_medical"}),
            _make_material(case_id=case_id, metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_nursing"}),
        ]

        db, result = _make_mock_db(materials_return=mats)

        summary = await get_category_summary(case_id, db)

        assert summary["fee_medical"] == 2
        assert summary["fee_nursing"] == 1

    async def test_summary_empty_when_no_materials(self):
        """无素材 → 空 dict"""
        case_id = uuid.uuid4()
        db, result = _make_mock_db(materials_return=[])

        summary = await get_category_summary(case_id, db)
        assert summary == {}

    async def test_summary_skips_none_category(self):
        """step0_fee_category=None 不计入"""
        case_id = uuid.uuid4()
        mats = [
            _make_material(case_id=case_id, metadata_={"source": "step0_preprocess", "step0_fee_category": None}),
            _make_material(case_id=case_id, metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_medical"}),
        ]

        db, result = _make_mock_db(materials_return=mats)

        summary = await get_category_summary(case_id, db)
        assert summary == {"fee_medical": 1}


# ═══════════════════════════════════════════════════════════════════════════════
# 11. get_preprocess_progress
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetPreprocessProgress:
    """测试预处理进度统计"""

    async def test_progress_counts_correctly(self):
        """统计 total/processed/failed/pending 正确"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"step0_status": "in_progress"})
        mats = [
            _make_material(case_id=case_id, ocr_status="completed",
                           metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_medical"}),
            _make_material(case_id=case_id, ocr_status="completed",
                           metadata_={"source": "step0_preprocess", "step0_fee_category": "fee_medical"}),
            _make_material(case_id=case_id, ocr_status="failed",
                           metadata_={"source": "step0_preprocess"}),
            _make_material(case_id=case_id, ocr_status="pending",
                           metadata_={"source": "step0_preprocess"}),
        ]

        db, result = _make_mock_db(materials_return=mats, case_return=case)

        progress = await get_preprocess_progress(case_id, db)

        assert progress["total"] == 4
        assert progress["processed"] == 2
        assert progress["failed"] == 1
        assert progress["pending"] == 1

    async def test_progress_percent_calculation(self):
        """进度百分比正确计算"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"step0_status": "in_progress"})
        mats = [
            _make_material(case_id=case_id, ocr_status="completed", metadata_={"source": "step0_preprocess"}),
            _make_material(case_id=case_id, ocr_status="pending", metadata_={"source": "step0_preprocess"}),
        ]

        db, result = _make_mock_db(materials_return=mats, case_return=case)

        progress = await get_preprocess_progress(case_id, db)
        assert progress["progress_percent"] == 50.0

    async def test_progress_zero_total(self):
        """total=0 → progress_percent=0.0"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"step0_status": "not_started"})
        db, result = _make_mock_db(materials_return=[], case_return=case)

        progress = await get_preprocess_progress(case_id, db)
        assert progress["total"] == 0
        assert progress["progress_percent"] == 0.0

    async def test_progress_includes_step0_status(self):
        """返回 step0_status"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"step0_status": "completed"})
        db, result = _make_mock_db(materials_return=[], case_return=case)

        progress = await get_preprocess_progress(case_id, db)
        assert progress["step0_status"] == "completed"

    async def test_progress_processing_counts_as_pending(self):
        """ocr_status='processing' 算作 pending"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"step0_status": "in_progress"})
        mats = [
            _make_material(case_id=case_id, ocr_status="processing", metadata_={"source": "step0_preprocess"}),
        ]

        db, result = _make_mock_db(materials_return=mats, case_return=case)

        progress = await get_preprocess_progress(case_id, db)
        assert progress["pending"] == 1
        assert progress["processed"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 12. _update_case_step0_status
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateCaseStep0Status:
    """测试更新 case step0 状态"""

    async def test_update_status_uses_deepcopy(self):
        """更新状态必须用 deepcopy"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={"old": "data"})
        db, result = _make_mock_db(case_return=case)

        with patch("services.evidence.step0_service.copy.deepcopy", wraps=copy.deepcopy) as mock_dc:
            from services.evidence.step0_service import _update_case_step0_status
            from services.evidence.step0_constants import STEP0_STATUS_COMPLETED
            await _update_case_step0_status(case_id, STEP0_STATUS_COMPLETED, db)

        mock_dc.assert_called()

    async def test_update_status_calls_flush_and_commit(self):
        """更新后调用 flush + commit"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={})
        db, result = _make_mock_db(case_return=case)

        from services.evidence.step0_service import _update_case_step0_status
        from services.evidence.step0_constants import STEP0_STATUS_COMPLETED
        await _update_case_step0_status(case_id, STEP0_STATUS_COMPLETED, db)

        db.flush.assert_awaited()
        db.commit.assert_awaited()

    async def test_update_status_sets_correct_value(self):
        """metadata_.step0_status 被正确设置"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={})
        db, result = _make_mock_db(case_return=case)

        from services.evidence.step0_service import _update_case_step0_status
        await _update_case_step0_status(case_id, "completed", db)

        assert case.metadata_["step0_status"] == "completed"

    async def test_update_status_case_not_found_no_error(self):
        """case 不存在 → 不报错"""
        case_id = uuid.uuid4()
        db, result = _make_mock_db()
        result.scalar_one_or_none.return_value = None

        from services.evidence.step0_service import _update_case_step0_status
        # 不应抛异常
        await _update_case_step0_status(case_id, "completed", db)

    async def test_update_completed_sets_completed_at(self):
        """status='completed' 时设置 step0_completed_at"""
        case_id = uuid.uuid4()
        case = _make_case(case_id=case_id, metadata_={})
        db, result = _make_mock_db(case_return=case)

        from services.evidence.step0_service import _update_case_step0_status
        from services.evidence.step0_constants import STEP0_STATUS_COMPLETED
        await _update_case_step0_status(case_id, STEP0_STATUS_COMPLETED, db)

        assert "step0_completed_at" in case.metadata_
