"""
起诉状模块 OCR 服务
复用现有 bailian_engine 对上传文件做 OCR 识别
支持 docx/xlsx/pptx/pdf/图片 的文本提取
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings
from services.ocr.bailian_engine import BailianOCREngine


_complaint_ocr_engine: Optional[BailianOCREngine] = None


def _get_engine() -> BailianOCREngine:
    global _complaint_ocr_engine
    if _complaint_ocr_engine is None:
        _complaint_ocr_engine = BailianOCREngine()
    return _complaint_ocr_engine


def _extract_docx_text(file_bytes: bytes) -> dict:
    from docx import Document
    import io

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

    tables_text = []
    for table in doc.tables:
        for row in table.rows:
            row_text = [cell.text.strip() for cell in row.cells]
            tables_text.append(" | ".join(row_text))

    full_text = "\n".join(paragraphs)
    if tables_text:
        full_text += "\n\n[表格内容]\n" + "\n".join(tables_text)

    return {
        "full_text": full_text,
        "blocks": [{"text": p, "source": "paragraph"} for p in paragraphs],
        "block_count": len(paragraphs),
        "source_type": "docx",
    }


def _extract_xlsx_text(file_bytes: bytes) -> dict:
    from openpyxl import load_workbook
    import io

    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    all_rows = []
    blocks = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        all_rows.append(f"[工作表: {sheet_name}]")
        for row in ws.iter_rows(values_only=True):
            row_text = [str(cell) if cell is not None else "" for cell in row]
            line = " | ".join(row_text)
            if line.strip().replace("|", "").strip():
                all_rows.append(line)
                blocks.append({"text": line, "source": f"sheet:{sheet_name}"})

    wb.close()

    return {
        "full_text": "\n".join(all_rows),
        "blocks": blocks,
        "block_count": len(blocks),
        "source_type": "xlsx",
    }


def _extract_pptx_text(file_bytes: bytes) -> dict:
    from pptx import Presentation
    import io

    prs = Presentation(io.BytesIO(file_bytes))
    all_text = []
    blocks = []

    for i, slide in enumerate(prs.slides):
        slide_texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        slide_texts.append(para.text.strip())
            if shape.has_table:
                for row in shape.table.rows:
                    row_text = [cell.text.strip() for cell in row.cells]
                    slide_texts.append(" | ".join(row_text))
        if slide_texts:
            all_text.append(f"[幻灯片 {i+1}]")
            all_text.extend(slide_texts)
            for t in slide_texts:
                blocks.append({"text": t, "source": f"slide:{i+1}"})

    return {
        "full_text": "\n".join(all_text),
        "blocks": blocks,
        "block_count": len(blocks),
        "source_type": "pptx",
    }


def ocr_image(image_bytes: bytes, filename: str = "upload.png") -> dict:
    engine = _get_engine()

    suffix = Path(filename).suffix.lower() or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        results = engine.recognize(tmp_path)
        text_lines = []
        for r in results:
            text_lines.append(r.get("text", ""))
        full_text = "\n".join(text_lines)
        return {
            "full_text": full_text,
            "blocks": results,
            "block_count": len(results),
            "source_type": "image_ocr",
        }
    finally:
        tmp_path.unlink(missing_ok=True)


def ocr_pdf(pdf_bytes: bytes, filename: str = "upload.pdf") -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        from services.preprocessor.pdf_splitter import PDFSplitter

        use_cloud_ocr = settings.ocr_engine_type in ("bailian", "dashscope", "qwen")
        split_dpi = 150 if use_cloud_ocr else settings.preprocess_dpi

        with tempfile.TemporaryDirectory() as pages_dir:
            splitter = PDFSplitter(dpi=split_dpi)
            image_paths = splitter.split_to_images(tmp_path, Path(pages_dir))

            if not image_paths:
                return {"full_text": "", "blocks": [], "block_count": 0, "page_count": 0, "source_type": "pdf_ocr"}

            from services.ocr.batch_processor import OCRBatchProcessor
            processor = OCRBatchProcessor()
            ocr_summary = processor.process_pages(image_paths, Path(pages_dir) / "ocr")

        all_text_parts = []
        all_blocks = []
        for page_data in ocr_summary.get("pages", []):
            page_num = page_data.get("page", 0)
            for r in page_data.get("results", []):
                all_blocks.append({
                    "text": r.get("text", ""),
                    "confidence": r.get("confidence", 0),
                    "page": page_num,
                })
                all_text_parts.append(r.get("text", ""))

        return {
            "full_text": "\n".join(all_text_parts),
            "blocks": all_blocks,
            "block_count": len(all_blocks),
            "page_count": ocr_summary.get("total_pages", len(image_paths)),
            "source_type": "pdf_ocr",
        }
    finally:
        tmp_path.unlink(missing_ok=True)


OFFICE_SUFFIXES = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}


def ocr_upload(file_bytes: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        return ocr_pdf(file_bytes, filename)

    if suffix in (".docx", ".doc"):
        return _extract_docx_text(file_bytes)

    if suffix in (".xlsx", ".xls"):
        return _extract_xlsx_text(file_bytes)

    if suffix in (".pptx", ".ppt"):
        return _extract_pptx_text(file_bytes)

    return ocr_image(file_bytes, filename)
