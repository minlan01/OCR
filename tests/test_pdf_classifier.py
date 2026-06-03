"""
PDF 分类器单元测试（v2 — 分布式采样 + 300字符阈值）
覆盖 PDFInfo dataclass 和 PDFClassifier.classify
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.preprocessor.pdf_classifier import PDFInfo, PDFClassifier, MIN_CHARS_PER_TEXT_PAGE


# ── Helpers ────────────────────────────────────────────────

def _make_mock_fitz(page_count=5, is_encrypted=False, page_texts=None):
    """构造 mock fitz 模块和 doc

    page_texts 的长度应与 page_count 一致（分布式采样可能访问中部/尾部页面）
    """
    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_count = page_count
    mock_doc.is_encrypted = is_encrypted

    if page_texts is None:
        page_texts = ["A" * MIN_CHARS_PER_TEXT_PAGE] * page_count

    # 补齐到 page_count 长度
    if len(page_texts) < page_count:
        page_texts = list(page_texts) + [""] * (page_count - len(page_texts))

    mock_pages = []
    for text in page_texts:
        page = MagicMock()
        page.get_text.return_value = text
        mock_pages.append(page)
    # 超出范围的页码返回空白
    mock_doc.__getitem__.side_effect = lambda i: mock_pages[i] if i < len(mock_pages) else MagicMock(get_text=MagicMock(return_value=""))
    mock_fitz.open.return_value = mock_doc
    return mock_fitz, mock_doc


# ── PDFInfo dataclass ──────────────────────────────────────

class TestPDFInfo:
    def test_defaults(self):
        info = PDFInfo(path=Path("test.pdf"), page_count=1, is_encrypted=False, is_text_pdf=False)
        assert info.path == Path("test.pdf")
        assert info.page_count == 1
        assert info.text_ratio == 0.0
        assert info.is_text_pdf is False
        assert info.confidence == 0.0
        assert info.is_mixed is False
        assert info.page_details == []

    def test_all_fields(self):
        info = PDFInfo(
            path=Path("doc.pdf"),
            page_count=10,
            is_encrypted=True,
            is_text_pdf=True,
            text_ratio=0.9,
            confidence=0.95,
            is_mixed=False,
        )
        assert info.is_encrypted is True
        assert info.is_text_pdf is True
        assert info.text_ratio == 0.9
        assert info.confidence == 0.95


# ── PDFClassifier.classify ─────────────────────────────────

class TestPDFClassifierClassify:
    def test_classify_text_pdf(self):
        """所有采样页文字量 >= 300 → 纯文字 PDF（v2 阈值）"""
        mock_fitz, _ = _make_mock_fitz(page_count=5, page_texts=["A" * MIN_CHARS_PER_TEXT_PAGE] * 5)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("text_heavy.pdf"))

        assert info.is_text_pdf is True
        assert info.text_ratio == 1.0
        assert info.page_count == 5
        assert info.confidence >= 0.9
        assert info.is_mixed is False

    def test_classify_scan_pdf(self):
        """文字量不足 → 扫描件"""
        texts = ["", "", "", "", "A" * 50] + [""] * 95  # 补齐到100页
        mock_fitz, _ = _make_mock_fitz(page_count=100, page_texts=texts)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("scan.pdf"))

        assert info.is_text_pdf is False
        assert info.text_ratio < 0.8

    def test_classify_empty_pdf(self):
        """空 PDF（0 页）"""
        mock_fitz, _ = _make_mock_fitz(page_count=0, page_texts=[])
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("empty.pdf"))

        assert info.page_count == 0
        assert info.text_ratio == 0.0

    def test_classify_encrypted_pdf(self):
        """加密 PDF 仍能返回 is_encrypted=True"""
        mock_fitz, _ = _make_mock_fitz(page_count=3, is_encrypted=True,
                                        page_texts=["encrypted_not_enough"] * 3)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("encrypted.pdf"))

        assert info.is_encrypted is True

    def test_classify_large_pdf_distributed_sampling(self):
        """超过 9 页的 PDF 使用分布式采样（首+中+尾）"""
        # 100 页全部是文字页
        mock_fitz, _ = _make_mock_fitz(page_count=100, page_texts=["A" * MIN_CHARS_PER_TEXT_PAGE] * 100)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("large.pdf"))

        assert info.is_text_pdf is True
        assert info.text_ratio == 1.0
        # 分布式采样最多 9 页（3+3+3）
        assert len(info.page_details) <= 9

    def test_classify_no_fitz_fallback(self):
        """PyMuPDF 不可用时的降级逻辑"""
        orig_import = builtins.__import__

        def selective_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("no fitz")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=selective_import):
            sys.modules.pop("fitz", None)
            classifier = PDFClassifier()
            info = classifier.classify(Path("any.pdf"))

        assert info.is_text_pdf is False
        assert info.is_encrypted is False

    def test_classify_page_extraction_error_handled(self):
        """单页文字提取异常不影响整体分类"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_count = 5
        mock_doc.is_encrypted = False
        mock_pages = []
        for i in range(5):
            page = MagicMock()
            if i == 2:
                page.get_text.side_effect = RuntimeError("bad page")
            else:
                page.get_text.return_value = "A" * MIN_CHARS_PER_TEXT_PAGE
            mock_pages.append(page)
        mock_doc.__getitem__.side_effect = mock_pages
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("partial.pdf"))

        assert info.is_text_pdf is True

    def test_classify_mixed_pdf(self):
        """混合模式 PDF：部分文字页 + 部分扫描页"""
        # 前3页文字，后续扫描
        texts = ["A" * MIN_CHARS_PER_TEXT_PAGE] * 3 + [""] * 97
        mock_fitz, _ = _make_mock_fitz(page_count=100, page_texts=texts)
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("mixed.pdf"))

        assert info.is_text_pdf is False
        assert info.is_mixed is True  # 20%-80% 范围
        assert info.confidence < 1.0

    def test_classify_below_threshold_200_chars(self):
        """200 字符页面 < 300 阈值 → 归为扫描页"""
        mock_fitz, _ = _make_mock_fitz(page_count=5,
                                        page_texts=["A" * 200, "A" * 200, "A" * 200, "A" * 200, "A" * 200])
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            classifier = PDFClassifier()
            info = classifier.classify(Path("borderline.pdf"))

        # 200 < 300，所有页都算非文字页
        assert info.is_text_pdf is False
        assert info.text_ratio == 0.0
