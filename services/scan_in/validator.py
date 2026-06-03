"""
PDF 文件校验器
校验后缀、大小、页数、是否损坏、是否加密
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from services.constants import MIN_CHARS_PER_TEXT_PAGE
from config.settings import settings


@dataclass
class ValidationResult:
    """校验结果"""
    is_valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    page_count: Optional[int] = None
    is_encrypted: bool = False
    is_text_pdf: bool = False  # 是否纯文字 PDF（可直接提取文本）
    file_size: int = 0
    warnings: list[str] = field(default_factory=list)


class PDFValidator:
    """PDF 文件校验器"""

    ALLOWED_EXTENSIONS = set(settings.allowed_extensions)
    MAX_FILE_SIZE = settings.max_upload_size
    MAX_PAGES = 2000

    def validate(self, file_path: str | Path) -> ValidationResult:
        """校验 PDF 文件"""
        file_path = Path(file_path)

        # 1. 检查文件存在
        if not file_path.exists():
            return ValidationResult(
                is_valid=False,
                error_code="FILE_NOT_FOUND",
                error_message=f"File not found: {file_path}",
            )

        # 2. 检查后缀
        if file_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return ValidationResult(
                is_valid=False,
                error_code="INVALID_EXTENSION",
                error_message=f"Invalid file extension: {file_path.suffix}",
            )

        # 3. 检查文件大小
        file_size = file_path.stat().st_size
        if file_size == 0:
            return ValidationResult(
                is_valid=False,
                error_code="EMPTY_FILE",
                error_message="File is empty",
            )
        if file_size > self.MAX_FILE_SIZE:
            return ValidationResult(
                is_valid=False,
                error_code="FILE_TOO_LARGE",
                error_message=f"File too large: {file_size} bytes (max {self.MAX_FILE_SIZE})",
            )

        # 4. 使用 PyMuPDF 打开并校验
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(file_path))

            # 检查加密
            is_encrypted = doc.is_encrypted
            if is_encrypted:
                doc.close()
                return ValidationResult(
                    is_valid=False,
                    error_code="PDF_ENCRYPTED",
                    error_message="PDF is encrypted and cannot be processed",
                    is_encrypted=True,
                )

            # 检查页数
            page_count = doc.page_count
            if page_count == 0:
                doc.close()
                return ValidationResult(
                    is_valid=False,
                    error_code="EMPTY_PDF",
                    error_message="PDF has no pages",
                )
            if page_count > self.MAX_PAGES:
                doc.close()
                return ValidationResult(
                    is_valid=False,
                    error_code="TOO_MANY_PAGES",
                    error_message=f"PDF has {page_count} pages (max {self.MAX_PAGES})",
                )

            # 检查是否纯文字 PDF（每页可提取文字）
            is_text_pdf = self._check_text_pdf(doc, page_count)

            # 检查是否损坏：尝试读取第一页
            try:
                _ = doc[0].get_text()
            except Exception:
                doc.close()
                return ValidationResult(
                    is_valid=False,
                    error_code="PDF_CORRUPTED",
                    error_message="PDF appears to be corrupted",
                )

            doc.close()

            warnings = []
            if page_count > 100:
                warnings.append(f"Large document: {page_count} pages, processing may take time")

            return ValidationResult(
                is_valid=True,
                page_count=page_count,
                is_encrypted=False,
                is_text_pdf=is_text_pdf,
                file_size=file_size,
                warnings=warnings,
            )

        except ImportError:
            # PyMuPDF 未安装时的降级校验
            logger.warning("PyMuPDF not installed, skipping deep PDF validation")
            return ValidationResult(
                is_valid=True,
                file_size=file_size,
                warnings=["PyMuPDF not available, skipping content validation"],
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_code="PDF_VALIDATION_ERROR",
                error_message=f"Failed to validate PDF: {e}",
            )

    def _check_text_pdf(self, doc, page_count: int) -> bool:
        """检查是否为纯文字 PDF（前 3 页可提取足够字符）"""
        text_pages = 0
        check_pages = min(3, page_count)
        for i in range(check_pages):
            try:
                text = doc[i].get_text()
                if len(text.strip()) >= MIN_CHARS_PER_TEXT_PAGE:
                    text_pages += 1
            except Exception as e:
                logger.debug(f"Page {i} text extraction failed during validation: {e}")
        return text_pages == check_pages


# 全局校验器
pdf_validator = PDFValidator()
