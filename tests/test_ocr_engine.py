"""
OCR 引擎单元测试
覆盖 OCREngine 和 get_ocr_engine 工厂
"""
from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from services.ocr.engine import OCREngine, get_ocr_engine


# ── Helpers ────────────────────────────────────────────────

def _mock_paddle_result(texts, scores, polys):
    """构造 PaddleOCR 3.x OCRResult 风格的 mock"""
    result = MagicMock()
    result.get.side_effect = lambda key, default=None: {
        "rec_texts": texts,
        "rec_scores": scores,
        "dt_polys": polys,
        "rec_polys": polys,
    }.get(key, default)
    return result


def _poly_4x2(y, x, w=80, h=20):
    """生成 4x2 检测框"""
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


# ── OCREngine 基础测试 ─────────────────────────────────────

class TestOCREngineInit:
    def test_default_not_ready(self):
        engine = OCREngine()
        assert not engine.is_ready

    def test_init_respects_gpu_setting(self):
        with patch("services.ocr.engine.settings") as mock_settings:
            mock_settings.ocr_use_gpu = True
            engine = OCREngine()
            assert engine._use_gpu is True


class TestOCREngineLoadModel:
    def test_load_paddleocr_success(self):
        mock_paddle = MagicMock()
        with patch.dict("sys.modules", {"paddleocr": MagicMock(PaddleOCR=mock_paddle)}):
            engine = OCREngine()
            engine.load_model()
            assert engine.is_ready
            mock_paddle.assert_called_once()

    def test_load_easyocr_fallback_when_paddle_missing(self):
        """PaddleOCR 不可用时走 EasyOCR 降级"""
        mock_easy = MagicMock()
        with patch.dict(sys.modules, {"easyocr": mock_easy}):
            # 让 paddleocr 的 import 失败
            orig_import = builtins.__import__

            def selective_import(name, *args, **kwargs):
                if name == "paddleocr":
                    raise ImportError("no paddle")
                return orig_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=selective_import):
                engine = OCREngine()
                engine.load_model()
                assert engine.is_ready is True

    def test_load_is_idempotent(self):
        mock_paddle = MagicMock()
        with patch.dict("sys.modules", {"paddleocr": MagicMock(PaddleOCR=mock_paddle)}):
            engine = OCREngine()
            engine.load_model()
            engine.load_model()
            assert mock_paddle.call_count == 1


# ── OCREngine recognize ────────────────────────────────────

class TestOCREngineRecognize:
    def test_recognize_not_loaded_returns_empty(self):
        with patch.dict("sys.modules", {}):
            with patch("builtins.__import__", side_effect=ImportError):
                engine = OCREngine()
                engine._model_loaded = False
                result = engine.recognize(Path("dummy.png"))
                assert result == []

    def test_recognize_single_page(self):
        """模拟单页 OCR 结果"""
        texts = ["Hello", "World"]
        scores = [0.98, 0.95]
        polys = [_poly_4x2(10, 10), _poly_4x2(40, 10)]
        mock_result = _mock_paddle_result(texts, scores, polys)

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [mock_result]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr

        from config.settings import settings
        with patch.object(settings, "ocr_confidence_threshold", 0.0):
            results = engine.recognize(Path("test.png"))

        assert len(results) == 2
        assert results[0]["text"] == "Hello"
        assert results[0]["confidence"] == 0.98
        assert results[1]["text"] == "World"

    def test_recognize_filters_low_confidence(self):
        """低于置信度阈值的文本应被过滤"""
        texts = ["Keep", "Drop"]
        scores = [0.95, 0.50]
        polys = [_poly_4x2(10, 10), _poly_4x2(40, 10)]
        mock_result = _mock_paddle_result(texts, scores, polys)

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [mock_result]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr

        from config.settings import settings
        with patch.object(settings, "ocr_confidence_threshold", 0.80):
            results = engine.recognize(Path("test.png"))

        assert len(results) == 1
        assert results[0]["text"] == "Keep"

    def test_recognize_empty_page(self):
        """空页返回空列表"""
        mock_result = _mock_paddle_result([], [], [])
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [mock_result]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr
        results = engine.recognize(Path("test.png"))

        assert results == []

    def test_recognize_handles_exception(self):
        """OCR 异常时返回空列表而非崩溃"""
        mock_ocr = MagicMock()
        mock_ocr.predict.side_effect = RuntimeError("GPU OOM")

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr
        results = engine.recognize(Path("test.png"))

        assert results == []

    def test_recognize_uses_rec_polys_fallback_to_dt_polys(self):
        """有 rec_polys 时优先使用，否则回退到 dt_polys"""
        texts = ["Text"]
        scores = [0.99]
        dt_polys = [_poly_4x2(10, 10, w=50)]
        rec_polys = [_poly_4x2(10, 10, w=60)]

        result1 = MagicMock()
        result1.get.side_effect = lambda key, default=None: {
            "rec_texts": texts,
            "rec_scores": scores,
            "dt_polys": dt_polys,
            "rec_polys": rec_polys,
        }.get(key, default)

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [result1]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr
        from config.settings import settings
        with patch.object(settings, "ocr_confidence_threshold", 0.0):
            results = engine.recognize(Path("test.png"))

        # bbox width should be ~60 when rec_polys are used
        bbox = results[0]["bbox"]
        width = bbox[1][0] - bbox[0][0]
        assert width == 60

    def test_recognize_skips_empty_text(self):
        """空白文本行应被跳过"""
        texts = ["", "  ", "Real Text"]
        scores = [0.5, 0.5, 0.99]
        polys = [_poly_4x2(10, 10), _poly_4x2(40, 10), _poly_4x2(70, 10)]
        mock_result = _mock_paddle_result(texts, scores, polys)

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [mock_result]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr
        from config.settings import settings
        with patch.object(settings, "ocr_confidence_threshold", 0.0):
            results = engine.recognize(Path("test.png"))

        assert len(results) == 1
        assert results[0]["text"] == "Real Text"


# ── OCREngine recognize_batch ──────────────────────────────

class TestOCREngineRecognizeBatch:
    def test_batch_returns_per_page_results(self):
        mock_result = _mock_paddle_result(["A"], [0.99], [_poly_4x2(10, 10)])
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [mock_result]

        engine = OCREngine()
        engine._model_loaded = True
        engine._ocr = mock_ocr
        from config.settings import settings
        with patch.object(settings, "ocr_confidence_threshold", 0.0):
            results = engine.recognize_batch([Path("p1.png"), Path("p2.png")])

        assert len(results) == 2
        assert len(results[0]) == 1


# ── OCREngine save_result ──────────────────────────────────

class TestOCREngineSaveResult:
    def test_save_creates_output(self):
        """保存结果到 JSON 文件"""
        import tempfile
        import os
        # 使用项目目录下的临时路径避免 Windows 沙箱权限问题
        output = Path("E:/OCRScanStruct/scan_output/_test_result.json")
        try:
            engine = OCREngine()
            data = [{"text": "Hello", "confidence": 0.99}]
            engine.save_result(data, output)
            assert output.exists()
            loaded = json.loads(output.read_text(encoding="utf-8"))
            assert loaded == data
        finally:
            if output.exists():
                os.remove(output)


# ── get_ocr_engine 工厂 ────────────────────────────────────

class TestGetOCREngineFactory:
    def test_default_is_paddle(self):
        with patch("services.ocr.engine.settings") as mock_settings:
            mock_settings.ocr_engine_type = "paddle"
            engine = get_ocr_engine()
            from services.ocr.engine import OCREngine
            assert isinstance(engine, OCREngine)

    def test_bailian_returns_bailian_engine(self):
        with patch("services.ocr.engine.settings") as mock_settings:
            mock_settings.ocr_engine_type = "bailian"
            from services.ocr.bailian_engine import BailianOCREngine
            engine = get_ocr_engine()
            assert isinstance(engine, BailianOCREngine)
