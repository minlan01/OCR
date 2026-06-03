"""OCR 服务层 — 引擎、批量处理"""
from services.ocr.base import BaseOCREngine
from services.ocr.engine import OCREngine, get_ocr_engine, ocr_engine

__all__ = [
    "BaseOCREngine",
    "OCREngine",
    "get_ocr_engine",
    "ocr_engine",
]
