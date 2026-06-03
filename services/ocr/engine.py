"""
OCR 引擎封装（PaddleOCR 3.x 适配版 + 百炼 Qwen-OCR）
支持通过配置 ocr_engine_type 切换引擎:
  - "paddle": 本地 PaddleOCR 3.x（默认）
  - "bailian": 阿里云百炼 Qwen-OCR（云端 API）
模型常驻内存，不重复初始化
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from loguru import logger

from config.settings import settings
from services.ocr.base import BaseOCREngine


class OCREngine(BaseOCREngine):
    """
    OCR 引擎封装
    - PaddleOCR 3.x 作为主引擎（定位 + 识别一体化）
    - EasyOCR 作为后备（PaddleOCR 不可用时）
    - 注意: CPU 模式下须设置 enable_mkldnn=False 避免 oneDNN 兼容性问题
    """

    def __init__(self):
        self._ocr = None
        self._model_loaded = False
        self._use_gpu = settings.ocr_use_gpu

    @property
    def is_ready(self) -> bool:
        return self._model_loaded

    def load_model(self) -> None:
        """加载 OCR 模型（常驻内存）"""
        if self._model_loaded:
            return

        try:
            from paddleocr import PaddleOCR

            kwargs = {
                "lang": settings.ocr_lang,
            }
            # CPU 下禁用 MKLDNN 避免 oneDNN PIR 属性转换错误
            if not self._use_gpu:
                kwargs["enable_mkldnn"] = False

            self._ocr = PaddleOCR(**kwargs)
            self._model_loaded = True
            logger.info(
                f"PaddleOCR 3.x loaded | GPU={self._use_gpu} | lang={settings.ocr_lang} | MKLDNN={'on' if self._use_gpu else 'off'}"
            )
        except ImportError:
            logger.warning("PaddleOCR not installed. Using EasyOCR fallback.")
            self._load_easyocr_fallback()
        except Exception as e:
            logger.error(f"Failed to load PaddleOCR: {e}")
            self._load_easyocr_fallback()

    def _load_easyocr_fallback(self):
        """EasyOCR 后备方案"""
        try:
            import easyocr

            self._ocr = easyocr.Reader(
                ["ch_sim", "en"],
                gpu=self._use_gpu,
            )
            self._model_loaded = True
            logger.info("EasyOCR fallback loaded")
        except ImportError:
            logger.warning("EasyOCR not installed. OCR will be unavailable.")
            self._model_loaded = False

    def recognize(self, image_path: Path) -> list[dict]:
        """
        识别单张图片

        返回:
            [{"text": str, "confidence": float, "bbox": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}, ...]

        PaddleOCR 3.x 输出格式:
            list[OCRResult]（每页一个），每个 OCRResult 包含:
            - rec_texts: list[str]    识别文本
            - rec_scores: list[float] 置信度
            - dt_polys: list[np.ndarray] 检测框 (4x2)
            - rec_polys: list[np.ndarray] 识别框 (4x2)
        """
        if not self._model_loaded:
            self.load_model()

        if not self._model_loaded:
            logger.error("OCR model not loaded, cannot recognize")
            return []

        try:
            results = self._ocr.predict(str(image_path))

            if not results:
                return []

            ocr_results = []
            # 新版 PaddleOCR 3.x 返回 list[OCRResult]（每页一个）
            for page_result in results:
                # OCRResult 实现了 dict-like 接口
                rec_texts = page_result.get("rec_texts", []) or []
                rec_scores = page_result.get("rec_scores", []) or []
                dt_polys = page_result.get("dt_polys", []) or []
                rec_polys = page_result.get("rec_polys", []) or []

                # 优先用识别框 rec_polys（有文本框倾斜校正），回退到检测框 dt_polys
                polys = rec_polys if len(rec_polys) > 0 else dt_polys

                for i, text in enumerate(rec_texts):
                    if not text or not text.strip():
                        continue
                    confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                    if confidence < settings.ocr_confidence_threshold:
                        continue

                    bbox = None
                    if i < len(polys):
                        poly = polys[i]
                        if isinstance(poly, np.ndarray):
                            bbox = [[int(p[0]), int(p[1])] for p in poly.tolist()]
                        elif isinstance(poly, (list, tuple)) and len(poly) == 4:
                            bbox = [[int(p[0]), int(p[1])] for p in poly]

                    ocr_results.append({
                        "text": text.strip(),
                        "confidence": round(confidence, 4),
                        "bbox": bbox or [[0, 0], [0, 0], [0, 0], [0, 0]],
                    })

            return ocr_results

        except Exception as e:
            logger.error(f"OCR failed for {image_path}: {e}")
            return []

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        """批量识别"""
        results = []
        for i, path in enumerate(image_paths):
            logger.debug(f"OCR batch {i+1}/{len(image_paths)}: {path.name}")
            results.append(self.recognize(path))
        return results


# ── 引擎工厂 ────────────────────────────────────────────

def get_ocr_engine():
    """
    根据配置返回 OCR 引擎实例

    settings.ocr_engine_type:
      - "paddle"  → 本地 PaddleOCR (默认)
      - "bailian" → 阿里云百炼 Qwen-OCR (云端)

    Usage:
        from services.ocr.engine import get_ocr_engine
        engine = get_ocr_engine()
        engine.load_model()
        results = engine.recognize(image_path)
    """
    engine_type = settings.ocr_engine_type.lower()

    if engine_type == "bailian":
        from services.ocr.bailian_engine import BailianOCREngine
        logger.info("使用百炼 Qwen-OCR 引擎 (云端)")
        return BailianOCREngine()
    else:
        logger.info("使用 PaddleOCR 引擎 (本地)")
        return OCREngine()


# 全局 OCR 引擎单例（向后兼容）
# 注意：如果在 .env 中设置了 ocr_engine_type=bailian，则此单例为 BailianOCREngine
ocr_engine = get_ocr_engine()
