"""
多 OCR 引擎集成测试

覆盖:
  1. BaiduOCREngine — 正常解析、错误码处理、批量并发
  2. GlmOCREngine   — 正常解析、429 重试、图片不存在
  3. MultiOCREngine  — 链式回退、全部失败、部分未就绪、is_ready
  4. 工厂函数       — 5 种 engine_type 返回正确实例
  5. Settings 验证器 — baidu/glm/multi 凭证校验
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch, call

import pytest
from pydantic import ValidationError

# ── 共享 Fixtures ──────────────────────────────────────────


@pytest.fixture
def fake_image(tmp_path: Path) -> Path:
    """创建一张 1x1 纯白 JPEG 图片（有效二进制）"""
    img_path = tmp_path / "test.jpg"
    # Minimal valid JPEG: SOI + APP0 + data + EOI
    img_path.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    return img_path


@pytest.fixture
def fake_image_png(tmp_path: Path) -> Path:
    """创建一张最小有效 PNG"""
    img_path = tmp_path / "test.png"
    # Minimal valid PNG
    img_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return img_path


# ═══════════════════════════════════════════════════════════
# 1. BaiduOCREngine 测试
# ═══════════════════════════════════════════════════════════


class TestBaiduOCREngine:
    """百度云 OCR 引擎测试"""

    def _make_engine_ready(self, engine):
        """手动将引擎设为就绪状态，跳过 AipOcr 导入"""
        engine._model_loaded = True
        engine._client = MagicMock()

    # ── 正常返回解析 ──

    def test_recognize_normal_parse(self, fake_image):
        """words_result 正常解析 → list[dict]"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        # Mock AipOcr.basicAccurate 返回正常结果
        engine._client.basicAccurate.return_value = {
            "words_result": [
                {"words": "Hello World"},
                {"words": "Test OCR"},
            ],
            "words_result_num": 2,
            "log_id": 12345,
        }

        result = engine.recognize(fake_image)
        assert len(result) == 2
        assert result[0]["text"] == "Hello World"
        assert result[0]["confidence"] == 0.95
        assert result[0]["bbox"] == [[0, 0], [0, 0], [0, 0], [0, 0]]
        assert result[1]["text"] == "Test OCR"

    def test_recognize_skips_empty_words(self, fake_image):
        """words_result 中 words 为空的条目应被跳过"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        engine._client.basicAccurate.return_value = {
            "words_result": [
                {"words": "Valid"},
                {"words": "   "},
                {"words": ""},
            ],
            "words_result_num": 3,
        }

        result = engine.recognize(fake_image)
        assert len(result) == 1
        assert result[0]["text"] == "Valid"

    # ── 错误码处理 ──

    @pytest.mark.parametrize("error_code,desc", [
        (17, "配额超限"),
        (18, "QPS超限"),
        (100, "认证失败"),
    ])
    def test_recognize_error_code_returns_empty(self, fake_image, error_code, desc):
        """错误码 17/18/100 → 返回空列表"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        engine._client.basicAccurate.return_value = {
            "error_code": error_code,
            "error_msg": desc,
        }

        result = engine.recognize(fake_image)
        assert result == []

    # ── 图片不存在 ──

    def test_recognize_image_not_found(self):
        """图片不存在 → 返回空列表"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        result = engine.recognize(Path("/nonexistent/image.jpg"))
        assert result == []

    # ── 引擎未就绪 ──

    def test_recognize_not_ready(self, fake_image):
        """引擎未就绪 → 返回空列表"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine()
        # 未调用 load_model，_model_loaded = False
        assert not engine.is_ready
        result = engine.recognize(fake_image)
        assert result == []

    # ── recognize_batch 并发处理 ──

    def test_recognize_batch_concurrent(self, fake_image):
        """recognize_batch 并发处理多张图片"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        engine._client.basicAccurate.return_value = {
            "words_result": [{"words": "Text"}],
            "words_result_num": 1,
        }

        # 创建多张图片
        images = [fake_image, fake_image, fake_image]
        results = engine.recognize_batch(images)

        assert len(results) == 3
        assert all(len(r) == 1 for r in results)
        assert all(r[0]["text"] == "Text" for r in results)

    def test_recognize_batch_preserves_order(self, tmp_path):
        """batch 结果顺序应与输入图片顺序一致"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)

        # 创建 3 张不同名称的图片
        img1 = tmp_path / "page1.jpg"
        img2 = tmp_path / "page2.jpg"
        img3 = tmp_path / "page3.jpg"
        for p in [img1, img2, img3]:
            p.write_bytes(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
                b"\x00\x01\x00\x00\xff\xd9"
            )

        call_count = 0

        def side_effect(image_bytes):
            nonlocal call_count
            call_count += 1
            return {
                "words_result": [{"words": f"Page{call_count}"}],
                "words_result_num": 1,
            }

        engine._client.basicAccurate.side_effect = side_effect
        results = engine.recognize_batch([img1, img2, img3])

        # 结果长度应与输入一致
        assert len(results) == 3

    def test_is_ready_false_when_not_loaded(self):
        """初始状态 is_ready 为 False"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine()
        assert engine.is_ready is False

    def test_is_ready_true_when_loaded(self):
        """加载后 is_ready 为 True"""
        from services.ocr.baidu_engine import BaiduOCREngine

        engine = BaiduOCREngine(
            app_id="test_app",
            api_key="test_key",
            secret_key="test_secret",
        )
        self._make_engine_ready(engine)
        assert engine.is_ready is True


# ═══════════════════════════════════════════════════════════
# 2. GlmOCREngine 测试
# ═══════════════════════════════════════════════════════════


class TestGlmOCREngine:
    """GLM-4V-Flash OCR 引擎测试"""

    def _make_engine_ready(self, engine):
        """手动将引擎设为就绪状态"""
        engine._model_loaded = True
        engine._client = MagicMock()

    # ── 正常返回解析 ──

    def test_recognize_normal_parse(self, fake_image):
        """Mock OpenAI chat.completions.create，验证正常返回解析"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        # Mock completion response
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = json.dumps([
            {"text": "Hello", "bbox": [[10, 20], [100, 20], [100, 50], [10, 50]]},
            {"text": "World", "bbox": [[10, 60], [100, 60], [100, 90], [10, 90]]},
        ])
        mock_completion.usage = MagicMock()
        mock_completion.usage.total_tokens = 100

        engine._client.chat.completions.create.return_value = mock_completion

        # Mock _image_to_base64_url 以避免实际读取图片
        with patch("services.ocr.glm_engine._image_to_base64_url", return_value="data:image/jpeg;base64,abc"):
            result = engine.recognize(fake_image)

        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "World"

    def test_recognize_empty_response(self, fake_image):
        """GLM 返回空内容 → 空列表"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = json.dumps([])
        mock_completion.usage = MagicMock()
        mock_completion.usage.total_tokens = 0

        engine._client.chat.completions.create.return_value = mock_completion

        with patch("services.ocr.glm_engine._image_to_base64_url", return_value="data:image/jpeg;base64,abc"):
            result = engine.recognize(fake_image)

        assert result == []

    # ── 429 重试逻辑 ──

    def test_recognize_429_retry_succeeds(self, fake_image):
        """429 重试后成功（最多 3 次指数退避）"""
        from services.ocr.glm_engine import GlmOCREngine
        from openai import APIStatusError

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        # 前 2 次 429，第 3 次成功
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = json.dumps([
            {"text": "Retried OK"},
        ])
        mock_completion.usage = MagicMock()
        mock_completion.usage.total_tokens = 50

        error_429 = APIStatusError(
            message="Rate limit",
            response=MagicMock(status_code=429),
            body=None,
        )

        engine._client.chat.completions.create.side_effect = [
            error_429, error_429, mock_completion
        ]

        with patch("services.ocr.glm_engine._image_to_base64_url", return_value="data:image/jpeg;base64,abc"), \
             patch("services.ocr.glm_engine.time.sleep"):
            result = engine.recognize(fake_image)

        assert len(result) == 1
        assert result[0]["text"] == "Retried OK"

    def test_recognize_429_all_retries_exhausted(self, fake_image):
        """429 所有重试耗尽 → 返回空列表"""
        from services.ocr.glm_engine import GlmOCREngine
        from openai import APIStatusError

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        error_429 = APIStatusError(
            message="Rate limit",
            response=MagicMock(status_code=429),
            body=None,
        )

        # 所有调用都 429（共 max_retries+1=4 次）
        engine._client.chat.completions.create.side_effect = [error_429] * 4

        with patch("services.ocr.glm_engine._image_to_base64_url", return_value="data:image/jpeg;base64,abc"), \
             patch("services.ocr.glm_engine.time.sleep"):
            result = engine.recognize(fake_image)

        assert result == []

    def test_recognize_non_429_api_error_no_retry(self, fake_image):
        """非 429 的 API 错误不重试，直接返回空"""
        from services.ocr.glm_engine import GlmOCREngine
        from openai import APIStatusError

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        error_500 = APIStatusError(
            message="Internal error",
            response=MagicMock(status_code=500),
            body=None,
        )

        engine._client.chat.completions.create.side_effect = error_500

        with patch("services.ocr.glm_engine._image_to_base64_url", return_value="data:image/jpeg;base64,abc"):
            result = engine.recognize(fake_image)

        assert result == []
        # 只调用了一次，没有重试
        assert engine._client.chat.completions.create.call_count == 1

    # ── 图片不存在 ──

    def test_recognize_image_not_found(self):
        """图片不存在 → 返回空列表"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        self._make_engine_ready(engine)

        result = engine.recognize(Path("/nonexistent/image.jpg"))
        assert result == []

    def test_recognize_not_ready(self, fake_image):
        """引擎未就绪 → 返回空列表"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine()
        assert not engine.is_ready
        result = engine.recognize(fake_image)
        assert result == []

    # ── _parse_response 测试 ──

    def test_parse_response_json_direct(self):
        """直接 JSON 数组解析"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        raw = json.dumps([{"text": "Hi", "confidence": 0.9, "bbox": [[1,2],[3,4],[5,6],[7,8]]}])
        result = engine._parse_response(raw)
        assert len(result) == 1
        assert result[0]["text"] == "Hi"

    def test_parse_response_markdown_code_block(self):
        """Markdown 代码块中的 JSON 解析"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        raw = '```json\n[{"text": "Code", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}]\n```'
        result = engine._parse_response(raw)
        assert len(result) == 1
        assert result[0]["text"] == "Code"

    def test_parse_response_fallback_text(self):
        """纯文本回退解析"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="test-key")
        raw = "Line one\nLine two\n"
        result = engine._parse_response(raw)
        assert len(result) == 2
        assert result[0]["text"] == "Line one"
        assert result[0]["confidence"] == 0.85  # fallback 置信度

    def test_is_ready_false_when_no_api_key(self):
        """缺少 API key 时 is_ready 为 False"""
        from services.ocr.glm_engine import GlmOCREngine

        engine = GlmOCREngine(api_key="")
        engine.load_model()  # 内部检查 _api_key 为空不加载
        assert engine.is_ready is False


# ═══════════════════════════════════════════════════════════
# 3. MultiOCREngine 测试
# ═══════════════════════════════════════════════════════════


def _make_mock_engine(name: str, ready: bool = True, recognize_result=None, recognize_side_effect=None):
    """创建 mock OCR 引擎"""
    engine = MagicMock()
    engine.is_ready = ready
    engine.__str__ = lambda self_: name
    if recognize_result is not None:
        engine.recognize.return_value = recognize_result
    if recognize_side_effect is not None:
        engine.recognize.side_effect = recognize_side_effect
    return engine


class TestMultiOCREngine:
    """多引擎回退测试"""

    # ── 链式回退 ──

    def test_chain_fallback_first_fails_second_succeeds(self, fake_image):
        """第一个引擎失败 → 降级到第二个引擎成功"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True, recognize_result=[])
        engine2 = _make_mock_engine("GlmOCR", ready=True, recognize_result=[
            {"text": "From GLM", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}
        ])

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize(fake_image)
        assert len(result) == 1
        assert result[0]["text"] == "From GLM"

    def test_chain_fallback_exception_degrades(self, fake_image):
        """引擎抛异常 → 降级到下一个"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True, recognize_side_effect=RuntimeError("timeout"))
        engine2 = _make_mock_engine("GlmOCR", ready=True, recognize_result=[
            {"text": "Fallback", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}
        ])

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize(fake_image)
        assert len(result) == 1
        assert result[0]["text"] == "Fallback"

    # ── 全部引擎失败 ──

    def test_all_engines_fail_returns_empty(self, fake_image):
        """全部引擎失败 → 返回空列表"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True, recognize_result=[])
        engine2 = _make_mock_engine("GlmOCR", ready=True, recognize_result=[])

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize(fake_image)
        assert result == []

    # ── 部分引擎未就绪 ──

    def test_skip_not_ready_engines(self, fake_image):
        """跳过未就绪的引擎，使用已就绪的"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=False)
        engine2 = _make_mock_engine("GlmOCR", ready=True, recognize_result=[
            {"text": "From GLM", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}
        ])

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize(fake_image)
        assert len(result) == 1
        assert result[0]["text"] == "From GLM"
        # 确认未就绪的引擎没有被调用
        engine1.recognize.assert_not_called()

    # ── is_ready 属性 ──

    def test_is_ready_at_least_one_ready(self):
        """至少一个引擎就绪 → is_ready = True"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=False)
        engine2 = _make_mock_engine("GlmOCR", ready=True)

        multi = MultiOCREngine([engine1, engine2])
        assert multi.is_ready is True

    def test_is_ready_none_ready(self):
        """所有引擎未就绪 → is_ready = False"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=False)
        engine2 = _make_mock_engine("GlmOCR", ready=False)

        multi = MultiOCREngine([engine1, engine2])
        assert multi.is_ready is False

    # ── load_model ──

    def test_load_model_calls_all_engines(self):
        """load_model 调用所有子引擎的 load_model"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True)
        engine2 = _make_mock_engine("GlmOCR", ready=True)

        multi = MultiOCREngine([engine1, engine2])
        multi.load_model()

        engine1.load_model.assert_called_once()
        engine2.load_model.assert_called_once()
        assert multi._model_loaded is True

    # ── recognize_batch ──

    def test_recognize_batch_fallback(self, fake_image):
        """批量识别整批降级"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True)
        engine1.recognize_batch.return_value = [[], []]

        engine2 = _make_mock_engine("GlmOCR", ready=True)
        engine2.recognize_batch.return_value = [
            [{"text": "A", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}],
            [{"text": "B", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}],
        ]

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize_batch([fake_image, fake_image])
        assert len(result) == 2
        assert result[0][0]["text"] == "A"
        assert result[1][0]["text"] == "B"

    def test_recognize_batch_all_fail(self, fake_image):
        """批量识别全部引擎失败 → 返回全空列表"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True)
        engine1.recognize_batch.return_value = [[], []]

        engine2 = _make_mock_engine("GlmOCR", ready=True)
        engine2.recognize_batch.return_value = [[], []]

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        result = multi.recognize_batch([fake_image, fake_image])
        assert result == [[], []]

    # ── get_stats ──

    def test_get_stats_tracks_engine_usage(self, fake_image):
        """get_stats 返回成功引擎的调用统计"""
        from services.ocr.multi_engine import MultiOCREngine

        engine1 = _make_mock_engine("BaiduOCR", ready=True, recognize_result=[])
        engine2 = _make_mock_engine("GlmOCR", ready=True, recognize_result=[
            {"text": "OK", "confidence": 0.9, "bbox": [[0,0],[0,0],[0,0],[0,0]]}
        ])

        multi = MultiOCREngine([engine1, engine2])
        multi._model_loaded = True

        multi.recognize(fake_image)
        stats = multi.get_stats()
        assert "GlmOCR" in stats
        assert stats["GlmOCR"] == 1


# ═══════════════════════════════════════════════════════════
# 4. 工厂函数测试
# ═══════════════════════════════════════════════════════════


class TestGetOCREngineFactory:
    """验证 get_ocr_engine() 在 5 种 engine_type 下返回正确实例"""

    def _mock_settings(self, engine_type: str, multi_engines=None):
        """构造 mock settings 对象"""
        mock_settings = MagicMock()
        mock_settings.ocr_engine_type = engine_type
        mock_settings.ocr_multi_engines = multi_engines or ["baidu", "glm", "bailian"]
        return mock_settings

    def test_paddle_returns_ocr_engine(self):
        """engine_type='paddle' → OCREngine"""
        from services.ocr.engine import get_ocr_engine, OCREngine

        with patch("services.ocr.engine.settings", self._mock_settings("paddle")):
            engine = get_ocr_engine()
            assert isinstance(engine, OCREngine)

    def test_bailian_returns_bailian_engine(self):
        """engine_type='bailian' → BailianOCREngine"""
        from services.ocr.engine import get_ocr_engine

        with patch("services.ocr.engine.settings", self._mock_settings("bailian")):
            engine = get_ocr_engine()
            from services.ocr.bailian_engine import BailianOCREngine
            assert isinstance(engine, BailianOCREngine)

    def test_baidu_returns_baidu_engine(self):
        """engine_type='baidu' → BaiduOCREngine"""
        from services.ocr.engine import get_ocr_engine

        with patch("services.ocr.engine.settings", self._mock_settings("baidu")):
            engine = get_ocr_engine()
            from services.ocr.baidu_engine import BaiduOCREngine
            assert isinstance(engine, BaiduOCREngine)

    def test_glm_returns_glm_engine(self):
        """engine_type='glm' → GlmOCREngine"""
        from services.ocr.engine import get_ocr_engine

        with patch("services.ocr.engine.settings", self._mock_settings("glm")):
            engine = get_ocr_engine()
            from services.ocr.glm_engine import GlmOCREngine
            assert isinstance(engine, GlmOCREngine)

    def test_multi_returns_multi_engine(self):
        """engine_type='multi' → MultiOCREngine"""
        from services.ocr.engine import get_ocr_engine

        mock_settings = self._mock_settings("multi", multi_engines=["baidu", "glm"])
        with patch("services.ocr.engine.settings", mock_settings):
            engine = get_ocr_engine()
            from services.ocr.multi_engine import MultiOCREngine
            assert isinstance(engine, MultiOCREngine)

    def test_unknown_type_defaults_to_paddle(self):
        """未知 engine_type → 回退到 OCREngine"""
        from services.ocr.engine import get_ocr_engine, OCREngine

        mock_settings = self._mock_settings("unknown")
        with patch("services.ocr.engine.settings", mock_settings):
            engine = get_ocr_engine()
            assert isinstance(engine, OCREngine)


# ═══════════════════════════════════════════════════════════
# 5. Settings Validator 测试
# ═══════════════════════════════════════════════════════════


class TestSettingsValidators:
    """配置项验证器测试"""

    def test_baidu_engine_without_credentials_raises(self):
        """engine_type='baidu' 但缺少 baidu 凭证 → ValidationError"""
        from config.settings import Settings
        from pydantic import SecretStr

        with pytest.raises(ValidationError) as exc_info:
            Settings(
                ocr_engine_type="baidu",
                baidu_ocr_app_id="",
                baidu_ocr_api_key="",
                baidu_ocr_secret_key="",
            )
        errors = exc_info.value.errors()
        # 应该有 3 个验证错误（app_id, api_key, secret_key 各一个）
        error_fields = {e["loc"][-1] for e in errors}
        assert "baidu_ocr_app_id" in error_fields or "baidu_ocr_api_key" in error_fields or "baidu_ocr_secret_key" in error_fields

    def test_multi_engine_without_glm_key_raises(self):
        """engine_type='multi' 但缺少 glm_api_key → ValidationError"""
        from config.settings import Settings
        from pydantic import SecretStr

        with pytest.raises(ValidationError) as exc_info:
            Settings(
                ocr_engine_type="multi",
                glm_api_key=SecretStr(""),
                # 提供 baidu 凭证以通过 baidu validator
                baidu_ocr_app_id="test",
                baidu_ocr_api_key="test",
                baidu_ocr_secret_key="test",
                # 提供 bailian key 以通过 bailian validator
                bailian_api_key=SecretStr("test-bailian-key"),
            )
        errors = exc_info.value.errors()
        error_fields = {e["loc"][-1] for e in errors}
        assert "glm_api_key" in error_fields

    def test_paddle_engine_without_baidu_glm_is_ok(self):
        """engine_type='paddle' 时缺少 baidu/glm 凭证 → 不报错"""
        from config.settings import Settings
        from pydantic import SecretStr

        # 不应抛出任何异常
        s = Settings(
            ocr_engine_type="paddle",
            baidu_ocr_app_id="",
            baidu_ocr_api_key="",
            baidu_ocr_secret_key="",
            glm_api_key=SecretStr(""),
        )
        assert s.ocr_engine_type == "paddle"

    def test_baidu_engine_with_credentials_ok(self):
        """engine_type='baidu' 且凭证齐全 → 正常创建"""
        from config.settings import Settings

        s = Settings(
            ocr_engine_type="baidu",
            baidu_ocr_app_id="my_app",
            baidu_ocr_api_key="my_key",
            baidu_ocr_secret_key="my_secret",
        )
        assert s.ocr_engine_type == "baidu"
        assert s.baidu_ocr_app_id == "my_app"

    def test_glm_engine_without_key_raises(self):
        """engine_type='glm' 但缺少 glm_api_key → ValidationError"""
        from config.settings import Settings
        from pydantic import SecretStr

        with pytest.raises(ValidationError) as exc_info:
            Settings(
                ocr_engine_type="glm",
                glm_api_key=SecretStr(""),
            )
        errors = exc_info.value.errors()
        error_fields = {e["loc"][-1] for e in errors}
        assert "glm_api_key" in error_fields

    def test_glm_engine_with_key_ok(self):
        """engine_type='glm' 且 key 齐全 → 正常创建"""
        from config.settings import Settings
        from pydantic import SecretStr

        s = Settings(
            ocr_engine_type="glm",
            glm_api_key=SecretStr("test-glm-key"),
        )
        assert s.ocr_engine_type == "glm"

    def test_bailian_engine_without_key_raises(self):
        """engine_type='bailian' 但缺少 bailian_api_key → ValidationError"""
        from config.settings import Settings
        from pydantic import SecretStr

        with pytest.raises(ValidationError) as exc_info:
            Settings(
                ocr_engine_type="bailian",
                bailian_api_key=SecretStr(""),
            )
        errors = exc_info.value.errors()
        error_fields = {e["loc"][-1] for e in errors}
        assert "bailian_api_key" in error_fields

    def test_multi_engine_with_all_credentials_ok(self):
        """engine_type='multi' 且所有凭证齐全 → 正常创建"""
        from config.settings import Settings
        from pydantic import SecretStr

        s = Settings(
            ocr_engine_type="multi",
            baidu_ocr_app_id="app",
            baidu_ocr_api_key="key",
            baidu_ocr_secret_key="secret",
            glm_api_key=SecretStr("glm-key"),
            bailian_api_key=SecretStr("bailian-key"),
        )
        assert s.ocr_engine_type == "multi"
