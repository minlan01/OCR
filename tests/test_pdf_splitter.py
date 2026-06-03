"""
PDF 拆页测试
覆盖 services/preprocessor/pdf_splitter.py — PDFSplitter 类
使用 mock fitz 模块 (方法内部 import fitz，需 patch sys.modules)
"""
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.preprocessor.pdf_splitter import PDFSplitter


def _make_mock_fitz(page_count=5):
    """构建 mock fitz 模块，注入 sys.modules"""
    pix = MagicMock()
    pix.save = MagicMock()
    pix.tobytes = MagicMock(return_value=b"fake_png_data")

    page = MagicMock()
    page.get_pixmap = MagicMock(return_value=pix)

    doc = MagicMock()
    doc.page_count = page_count
    doc.__getitem__ = MagicMock(return_value=page)
    doc.close = MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open.return_value = doc
    mock_fitz.Matrix = MagicMock(return_value="mock_matrix")

    return mock_fitz, doc, page, pix


class TestPDFSplitterInit:
    """构造函数测试"""

    def test_default_dpi(self):
        splitter = PDFSplitter()
        assert splitter.dpi == 300

    def test_custom_dpi(self):
        splitter = PDFSplitter(dpi=150)
        assert splitter.dpi == 150


class TestSplitToImages:
    """split_to_images 方法测试"""

    def test_split_all_pages(self):
        mock_fitz, mock_doc, mock_page, mock_pix = _make_mock_fitz(5)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter(dpi=300)
                result = splitter.split_to_images(Path("/fake/test.pdf"), output_dir)

            assert len(result) == 5
            assert mock_doc.__getitem__.call_count == 5
            assert mock_page.get_pixmap.call_count == 5
            assert mock_pix.save.call_count == 5
            mock_doc.close.assert_called_once()

    def test_split_page_range(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(5)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                result = splitter.split_to_images(
                    Path("/fake/test.pdf"), output_dir,
                    start_page=2, end_page=4,
                )
            assert len(result) == 3

    def test_split_end_page_beyond_total(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(5)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                result = splitter.split_to_images(
                    Path("/fake/test.pdf"), Path(tmpdir), end_page=100,
                )
            assert len(result) == 5

    def test_split_creates_output_dir(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "new_subdir" / "images"
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                splitter.split_to_images(Path("/fake/test.pdf"), output_dir)
            assert output_dir.exists()

    def test_split_output_filenames(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(3)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                result = splitter.split_to_images(
                    Path("/fake/test.pdf"), output_dir, start_page=1, end_page=3,
                )
            assert result[0].name == "page_0001.png"
            assert result[1].name == "page_0002.png"
            assert result[2].name == "page_0003.png"

    def test_split_zero_page_doc(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(0)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                result = splitter.split_to_images(Path("/fake/empty.pdf"), Path(tmpdir))
            assert result == []

    def test_dpi_zoom_calculation(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter(dpi=144)
                splitter.split_to_images(Path("/fake/test.pdf"), Path(tmpdir))
            # zoom = dpi / 72 = 144 / 72 = 2.0
            mock_fitz.Matrix.assert_called_with(2.0, 2.0)


class TestSplitToBytes:
    """split_to_bytes 方法测试"""

    def test_split_to_bytes_all_pages(self):
        mock_fitz, mock_doc, _, mock_pix = _make_mock_fitz(3)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            splitter = PDFSplitter()
            result = splitter.split_to_bytes(b"fake pdf content")
        assert len(result) == 3
        assert all(isinstance(b, bytes) for b in result)
        assert mock_pix.tobytes.call_count == 3

    def test_split_to_bytes_page_range(self):
        mock_fitz, mock_doc, _, _ = _make_mock_fitz(3)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            splitter = PDFSplitter()
            result = splitter.split_to_bytes(b"fake pdf content", start_page=2, end_page=2)
        assert len(result) == 1


class TestPDFSplitterEdgeCases:
    """边界场景"""

    def test_default_dpi_from_settings_when_none_passed(self):
        from config.settings import settings
        splitter = PDFSplitter(dpi=None)
        assert splitter.dpi == settings.preprocess_dpi

    def test_custom_dpi_overrides_settings(self):
        splitter = PDFSplitter(dpi=600)
        assert splitter.dpi == 600
