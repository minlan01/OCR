"""
PDF 文件校验器单元测试
覆盖 ValidationResult dataclass 和 PDFValidator.validate 所有错误/成功路径
"""
from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.scan_in.validator import PDFValidator, ValidationResult, pdf_validator


# ── ValidationResult dataclass ─────────────────────────────

class TestValidationResult:
    def test_defaults(self):
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.error_code is None
        assert result.warnings == []

    def test_with_warnings(self):
        result = ValidationResult(is_valid=True, warnings=["Large file"])
        assert len(result.warnings) == 1

    def test_with_error(self):
        result = ValidationResult(
            is_valid=False,
            error_code="FILE_TOO_LARGE",
            error_message="File exceeds limit",
        )
        assert result.error_code == "FILE_TOO_LARGE"
        assert "File exceeds limit" in result.error_message


# ── Helpers ────────────────────────────────────────────────

def _make_mock_fitz(page_count=5, is_encrypted=False, first_page_text="Some content"):
    """构造 mock fitz 模块"""
    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_count = page_count
    mock_doc.is_encrypted = is_encrypted
    page = MagicMock()
    page.get_text.return_value = first_page_text
    mock_doc.__getitem__.return_value = page
    mock_fitz.open.return_value = mock_doc
    return mock_fitz


# ── PDFValidator.validate — 错误路径 ───────────────────────

class TestPDFValidatorErrors:
    def test_file_not_found(self):
        """文件不存在"""
        result = PDFValidator().validate(Path("/nonexistent/file.pdf"))
        assert not result.is_valid
        assert result.error_code == "FILE_NOT_FOUND"

    def test_invalid_extension(self):
        """非 PDF 扩展名"""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1024
                result = PDFValidator().validate(Path("/fake/test.docx"))

        assert not result.is_valid
        assert result.error_code == "INVALID_EXTENSION"

    def test_empty_file(self):
        """空文件（大小=0）"""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 0
                result = PDFValidator().validate(Path("/fake/empty.pdf"))

        assert not result.is_valid
        assert result.error_code == "EMPTY_FILE"

    def test_file_too_large(self):
        """超过大小限制"""
        validator = PDFValidator()
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = validator.MAX_FILE_SIZE + 1
                result = validator.validate(Path("/fake/huge.pdf"))

        assert not result.is_valid
        assert result.error_code == "FILE_TOO_LARGE"

    def test_encrypted_pdf(self):
        """加密 PDF 应被拒绝"""
        mock_fitz = _make_mock_fitz(is_encrypted=True)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    result = PDFValidator().validate(Path("/fake/encrypted.pdf"))

        assert not result.is_valid
        assert result.error_code == "PDF_ENCRYPTED"

    def test_empty_pdf_zero_pages(self):
        """0 页 PDF"""
        mock_fitz = _make_mock_fitz(page_count=0, is_encrypted=False)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    result = PDFValidator().validate(Path("/fake/empty.pdf"))

        assert not result.is_valid
        assert result.error_code == "EMPTY_PDF"

    def test_too_many_pages(self):
        """超过 500 页限制"""
        mock_fitz = _make_mock_fitz(page_count=501, is_encrypted=False)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    result = PDFValidator().validate(Path("/fake/large.pdf"))

        assert not result.is_valid
        assert result.error_code == "TOO_MANY_PAGES"

    def test_corrupted_pdf(self):
        """损坏的 PDF — 第一页读取异常"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.page_count = 3
        page0 = MagicMock()
        page0.get_text.side_effect = RuntimeError("broken page")
        mock_doc.__getitem__.return_value = page0
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    with patch.object(PDFValidator, "_check_text_pdf", return_value=False):
                        result = PDFValidator().validate(Path("/fake/corrupted.pdf"))

        assert not result.is_valid
        assert result.error_code == "PDF_CORRUPTED"


# ── PDFValidator.validate — 成功路径 ───────────────────────

class TestPDFValidatorSuccess:
    def test_valid_pdf(self):
        mock_fitz = _make_mock_fitz(page_count=5)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 50000
                    with patch.object(PDFValidator, "_check_text_pdf", return_value=False):
                        result = PDFValidator().validate(Path("/fake/valid.pdf"))

        assert result.is_valid
        assert result.page_count == 5
        assert result.file_size == 50000

    def test_valid_text_pdf(self):
        """纯文字 PDF 检测"""
        mock_fitz = _make_mock_fitz(page_count=5)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 50000
                    with patch.object(PDFValidator, "_check_text_pdf", return_value=True):
                        result = PDFValidator().validate(Path("/fake/text.pdf"))

        assert result.is_valid
        assert result.is_text_pdf is True

    def test_large_pdf_generates_warning(self):
        """超过 100 页的 PDF 生成警告"""
        mock_fitz = _make_mock_fitz(page_count=150)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 50000
                    with patch.object(PDFValidator, "_check_text_pdf", return_value=False):
                        result = PDFValidator().validate(Path("/fake/large_but_valid.pdf"))

        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("Large document" in w for w in result.warnings)

    def test_no_fitz_fallback(self):
        """PyMuPDF 不可用时降级校验"""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 50000
                # 让 fitz import 失败
                orig_import = builtins.__import__

                def selective_import(name, *args, **kwargs):
                    if name == "fitz":
                        raise ImportError("no fitz")
                    return orig_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=selective_import):
                    sys.modules.pop("fitz", None)
                    result = PDFValidator().validate(Path("/fake/any.pdf"))

        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("PyMuPDF not available" in w for w in result.warnings)

    def test_validation_exception(self):
        """未知异常统一返回错误结果"""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1
                with patch("builtins.__import__", side_effect=OSError("disk error")):
                    sys.modules.pop("fitz", None)
                    result = PDFValidator().validate(Path("/fake/bad.pdf"))

        assert not result.is_valid
        assert result.error_code == "PDF_VALIDATION_ERROR"


# ── PDFValidator._check_text_pdf ──────────────────────────

class TestCheckTextPDF:
    def test_all_pages_have_text(self):
        mock_doc = MagicMock()
        page = MagicMock()
        page.get_text.return_value = "A" * 500  # 超过 MIN_CHARS_PER_TEXT_PAGE (300)
        mock_doc.__getitem__.return_value = page

        result = PDFValidator()._check_text_pdf(mock_doc, 3)
        assert result is True

    def test_some_pages_empty(self):
        mock_doc = MagicMock()
        pages = []
        for i in range(3):
            page = MagicMock()
            page.get_text.return_value = "A" * 500 if i != 1 else ""  # 阈值 300，有文字页需 >300
            pages.append(page)
        mock_doc.__getitem__.side_effect = pages

        result = PDFValidator()._check_text_pdf(mock_doc, 3)
        assert result is False

    def test_page_error_handled(self):
        """单个页面提取异常不影响其他页"""
        mock_doc = MagicMock()
        pages = []
        for i in range(3):
            page = MagicMock()
            if i == 0:
                page.get_text.side_effect = RuntimeError("bad")
            else:
                page.get_text.return_value = "A" * 500  # 阈值 300
            pages.append(page)
        mock_doc.__getitem__.side_effect = pages

        result = PDFValidator()._check_text_pdf(mock_doc, 3)
        assert result is False  # 只有2页有文字，不是全部3页


# ── 配置覆写 ──────────────────────────────────────────────

class TestPDFValidatorConfig:
    def test_default_allowed_extensions(self):
        assert PDFValidator.ALLOWED_EXTENSIONS == {".pdf"}

    def test_default_max_pages(self):
        assert PDFValidator.MAX_PAGES == 500


# ── 全局单例 ──────────────────────────────────────────────

class TestGlobalSingleton:
    def test_pdf_validator_is_instance(self):
        assert isinstance(pdf_validator, PDFValidator)
