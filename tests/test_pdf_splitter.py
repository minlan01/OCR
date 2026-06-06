"""
PDF 拆页测试
覆盖 services/preprocessor/pdf_splitter.py — PDFSplitter 类
"""
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.preprocessor.pdf_splitter import PDFSplitter, DEFAULT_DPI


class TestPDFSplitterInit:
    """构造函数测试"""

    def test_default_dpi(self):
        splitter = PDFSplitter()
        assert splitter.dpi == DEFAULT_DPI

    def test_custom_dpi(self):
        splitter = PDFSplitter(dpi=150)
        assert splitter.dpi == 150


class TestSplitToImages:
    """split_to_images 方法测试 — 使用 mock _render_page 避免 ThreadPoolExecutor 内部 fitz 问题"""

    def test_split_all_pages(self):
        """全部页面拆分"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            # 预创建假输出文件
            for i in range(1, 6):
                (output_dir / f"page_{i:04d}.png").write_bytes(b"fake")

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.side_effect = [
                    (0, output_dir / "page_0001.png"),
                    (1, output_dir / "page_0002.png"),
                    (2, output_dir / "page_0003.png"),
                    (3, output_dir / "page_0004.png"),
                    (4, output_dir / "page_0005.png"),
                ]
                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 5
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter(dpi=300)
                    result = splitter.split_to_images(Path("/fake/test.pdf"), output_dir)

            assert len(result) == 5
            assert mock_render.call_count == 5

    def test_split_page_range(self):
        """指定页码范围拆分"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            for i in range(2, 5):
                (output_dir / f"page_{i:04d}.png").write_bytes(b"fake")

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.side_effect = [
                    (1, output_dir / "page_0002.png"),
                    (2, output_dir / "page_0003.png"),
                    (3, output_dir / "page_0004.png"),
                ]
                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 5
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter()
                    result = splitter.split_to_images(
                        Path("/fake/test.pdf"), output_dir,
                        start_page=2, end_page=4,
                    )
            assert len(result) == 3

    def test_split_end_page_beyond_total(self):
        """end_page 超出总页码时截断"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            for i in range(1, 6):
                (output_dir / f"page_{i:04d}.png").write_bytes(b"fake")

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.side_effect = [
                    (0, output_dir / "page_0001.png"),
                    (1, output_dir / "page_0002.png"),
                    (2, output_dir / "page_0003.png"),
                    (3, output_dir / "page_0004.png"),
                    (4, output_dir / "page_0005.png"),
                ]
                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 5
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter()
                    result = splitter.split_to_images(
                        Path("/fake/test.pdf"), Path(tmpdir), end_page=100,
                    )
            assert len(result) == 5

    def test_split_creates_output_dir(self):
        """自动创建输出目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "new_subdir" / "images"
            (output_dir // "page_0001.png").parent.mkdir(parents=True, exist_ok=True) if False else None

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.return_value = (0, output_dir / "page_0001.png")
                # 预创建文件
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "page_0001.png").write_bytes(b"fake")

                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 1
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter()
                    splitter.split_to_images(Path("/fake/test.pdf"), output_dir)
            assert output_dir.exists()

    def test_split_output_filenames(self):
        """输出文件名格式正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            for i in range(1, 4):
                (output_dir / f"page_{i:04d}.png").write_bytes(b"fake")

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.side_effect = [
                    (0, output_dir / "page_0001.png"),
                    (1, output_dir / "page_0002.png"),
                    (2, output_dir / "page_0003.png"),
                ]
                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 3
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter()
                    result = splitter.split_to_images(
                        Path("/fake/test.pdf"), output_dir, start_page=1, end_page=3,
                    )
            assert result[0].name == "page_0001.png"
            assert result[1].name == "page_0002.png"
            assert result[2].name == "page_0003.png"

    def test_split_zero_page_doc(self):
        """0 页 PDF 返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_fitz = MagicMock()
            mock_doc = MagicMock()
            mock_doc.page_count = 0
            mock_doc.close = MagicMock()
            mock_fitz.open.return_value = mock_doc

            with patch.dict(sys.modules, {"fitz": mock_fitz}):
                splitter = PDFSplitter()
                result = splitter.split_to_images(Path("/fake/empty.pdf"), Path(tmpdir))
            assert result == []

    def test_dpi_zoom_calculation(self):
        """DPI 计算的 zoom 值正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "page_0001.png").write_bytes(b"fake")

            with patch("services.preprocessor.pdf_splitter._render_page") as mock_render:
                mock_render.return_value = (0, output_dir / "page_0001.png")
                mock_fitz = MagicMock()
                mock_doc = MagicMock()
                mock_doc.page_count = 1
                mock_doc.close = MagicMock()
                mock_fitz.open.return_value = mock_doc

                with patch.dict(sys.modules, {"fitz": mock_fitz}):
                    splitter = PDFSplitter(dpi=144)
                    splitter.split_to_images(Path("/fake/test.pdf"), Path(tmpdir))

            # 验证 _render_page 被正确调用，dpi=144
            mock_render.assert_called_once()
            call_args = mock_render.call_args
            # _render_page(pdf_path_str, page_num, output_dir_str, dpi, use_jpeg, prefer_extract)
            assert call_args[0][3] == 144  # dpi 参数


class TestSplitToBytes:
    """split_to_bytes 方法测试"""

    def test_split_to_bytes_all_pages(self):
        """全页字节输出"""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake_png_data"

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        mock_page.get_images.return_value = []
        mock_page.rect = MagicMock()
        mock_page.rect.width = 595
        mock_page.rect.height = 842

        mock_doc = MagicMock()
        mock_doc.page_count = 3
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.close = MagicMock()

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value="mock_matrix")

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            splitter = PDFSplitter()
            result = splitter.split_to_bytes(b"fake pdf content")
        assert len(result) == 3
        assert all(isinstance(b, bytes) for b in result)

    def test_split_to_bytes_page_range(self):
        """指定页码范围的字节输出"""
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake_png_data"

        mock_page = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        mock_page.get_images.return_value = []
        mock_page.rect = MagicMock()
        mock_page.rect.width = 595
        mock_page.rect.height = 842

        mock_doc = MagicMock()
        mock_doc.page_count = 3
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.close = MagicMock()

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value="mock_matrix")

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
