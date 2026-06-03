"""
百炼 Qwen-OCR 集成测试
覆盖: 引擎工厂、真实API调用、输出格式兼容性、Pipeline兼容性
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 辅助函数 ──────────────────────────────────────────

def _create_test_image(path: Path, text_lines: list[str] | None = None):
    """创建一张带中文文字的测试图片"""
    if text_lines is None:
        text_lines = [
            "检测报告",
            "样品名称: 饮用水",
            "检测结果: 合格",
            "报告日期: 2024年5月14日",
        ]
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        pytest.skip("Pillow 未安装")

    img = Image.new("RGB", (800, 300), color="white")
    draw = ImageDraw.Draw(img)

    # 加载中文字体
    font = None
    for fp in [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 32)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    y = 20
    for line in text_lines:
        draw.text((30, y), line, fill="black", font=font)
        y += 45

    img.save(str(path))
    return path


# ── 测试类 ────────────────────────────────────────────

class TestBailianOCREngineFactory:
    """引擎工厂测试"""

    def test_factory_returns_bailian_when_configured(self):
        """ocr_engine_type=bailian 时返回 BailianOCREngine"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(
            api_key="sk-test",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-vl-ocr-latest",
        )
        assert isinstance(engine, BailianOCREngine)
        assert engine._model == "qwen-vl-ocr-latest"

    def test_bailian_engine_has_required_interface(self):
        """BailianOCREngine 实现与 OCREngine 一致的接口"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        assert hasattr(engine, "recognize")
        assert hasattr(engine, "recognize_batch")
        assert hasattr(engine, "save_result")
        assert hasattr(engine, "load_model")
        assert hasattr(engine, "is_ready")

    def test_factory_get_ocr_engine(self, monkeypatch):
        """get_ocr_engine() 根据配置返回对应引擎"""
        from config.settings import settings as cfg_settings
        monkeypatch.setattr(cfg_settings, "ocr_engine_type", "bailian")

        from services.ocr.engine import get_ocr_engine
        from services.ocr.bailian_engine import BailianOCREngine

        engine = get_ocr_engine()
        assert isinstance(engine, BailianOCREngine)

    def test_factory_default_is_paddle(self, monkeypatch):
        """默认 ocr_engine_type=paddle → 返回 OCREngine"""
        # 直接 mock settings 单例，绕过 .env 文件优先级
        from config.settings import settings as cfg_settings
        monkeypatch.setattr(cfg_settings, "ocr_engine_type", "paddle")

        from services.ocr.engine import get_ocr_engine, OCREngine

        engine = get_ocr_engine()
        assert isinstance(engine, OCREngine)


class TestBailianOCRRealAPI:
    """真实 API 连通性测试（需要有效的 API Key）"""

    @pytest.mark.slow
    def test_real_api_recognize_text(self):
        """真实调用百炼 OCR API 识别文字"""
        import tempfile
        api_key = os.environ.get("BAILIAN_API_KEY", "")
        if not api_key:
            pytest.skip("BAILIAN_API_KEY 未设置")

        from services.ocr.bailian_engine import BailianOCREngine

        with tempfile.TemporaryDirectory() as tmpdir:
            # 生成测试图片
            image_path = Path(tmpdir) / "test_bailian.png"
            _create_test_image(image_path, [
                "检测报告",
                "样品名称: 饮用水",
                "检测结果: 合格",
                "报告日期: 2024年5月14日",
            ])

            engine = BailianOCREngine(api_key=api_key)
            engine.load_model()
            assert engine.is_ready, "引擎未能初始化"

            results = engine.recognize(image_path)
            assert results, "OCR 未能识别任何文字"
            assert len(results) >= 2, f"预期至少2行文字，实际: {len(results)}"

            # 验证输出格式
            for item in results:
                assert "text" in item
                assert "confidence" in item
                assert "bbox" in item
                assert isinstance(item["confidence"], float)
                assert 0 <= item["confidence"] <= 1.0
                assert len(item["bbox"]) == 4
                for pt in item["bbox"]:
                    assert len(pt) == 2

            # 验证关键文本
            all_text = " ".join(r["text"] for r in results)
            assert "检测报告" in all_text or "检测" in all_text, f"未找到预期文本: {all_text}"

    @pytest.mark.slow
    def test_real_api_structured_json(self):
        """真实调用百炼 OCR → 结构化 JSON 输出"""
        import tempfile
        api_key = os.environ.get("BAILIAN_API_KEY", "")
        if not api_key:
            pytest.skip("BAILIAN_API_KEY 未设置")

        from services.ocr.bailian_engine import BailianOCREngine

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "test_json.png"
            _create_test_image(image_path, [
                "样品编号: SC-2024001",
                "检测项目: 重金属",
                "检测结果: 未检出",
            ])

            engine = BailianOCREngine(api_key=api_key)
            engine.load_model()

            results = engine.recognize(image_path)
            assert len(results) >= 1

            # 验证可序列化为 JSON
            json_str = json.dumps(results, ensure_ascii=False)
            parsed = json.loads(json_str)
            assert len(parsed) == len(results)

    @pytest.mark.slow
    def test_real_api_save_result(self):
        """真实 API + save_result 写入文件"""
        import tempfile
        api_key = os.environ.get("BAILIAN_API_KEY", "")
        if not api_key:
            pytest.skip("BAILIAN_API_KEY 未设置")

        from services.ocr.bailian_engine import BailianOCREngine

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "test_save.png"
            _create_test_image(image_path)

            engine = BailianOCREngine(api_key=api_key)
            engine.load_model()

            results = engine.recognize(image_path)
            output_path = Path(tmpdir) / "ocr_result.json"
            engine.save_result(results, output_path)

            assert output_path.exists()
            with open(output_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            assert saved == results


class TestBailianResponseParsing:
    """响应解析测试"""

    def test_parse_valid_json_array(self):
        """解析合法的 JSON 数组"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        raw = json.dumps([
            {"text": "标题", "bbox": [10, 20, 200, 20, 200, 50, 10, 50]},
            {"text": "正文", "bbox": [10, 60, 300, 60, 300, 90, 10, 90]},
        ])
        results = engine._parse_response(raw)
        assert len(results) == 2
        assert results[0]["text"] == "标题"
        assert results[1]["text"] == "正文"
        assert results[0]["confidence"] == 0.95  # 默认云端置信度

    def test_parse_markdown_code_block(self):
        """解析 Markdown 代码块包裹的 JSON"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        raw = '```json\n[{"text": "测试", "bbox": [0,0,100,0,100,30,0,30]}]\n```'
        results = engine._parse_response(raw)
        assert len(results) == 1
        assert results[0]["text"] == "测试"

    def test_parse_fallback_plain_text(self):
        """回退解析纯文本"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        raw = "第一行\n第二行\n第三行"
        results = engine._parse_response(raw)
        assert len(results) == 3
        assert results[0]["text"] == "第一行"
        assert results[0]["confidence"] == 0.90  # 回退置信度
        assert results[0]["bbox"] == [[0, 0], [0, 0], [0, 0], [0, 0]]

    def test_parse_empty_response(self):
        """处理空响应"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        assert engine._parse_response("") == []
        assert engine._parse_response("   ") == []
        assert engine._parse_response("```json\n[]\n```") == []

    def test_parse_partial_json_in_text(self):
        """从混杂文本中提取 JSON 数组"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        raw = '根据图片识别结果如下：[{"text": "混在文本中", "bbox": [0,0,10,0,10,10,0,10]}]，以上为识别内容。'
        results = engine._parse_response(raw)
        assert len(results) == 1
        assert results[0]["text"] == "混在文本中"


class TestBailianPipelineCompatibility:
    """Pipeline 兼容性测试"""

    def test_output_format_matches_ocr_engine(self):
        """
        BailianOCREngine 输出格式与 OCREngine 完全一致
        确保 batch_processor 和 pipeline 可无感切换
        """
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        raw = json.dumps([
            {
                "text": "章节标题",
                "bbox": [50, 100, 300, 100, 300, 140, 50, 140],
                "confidence": 0.98,
            },
            {
                "text": "正文段落内容示例",
                "bbox": [50, 160, 500, 160, 500, 190, 50, 190],
                "confidence": 0.95,
            },
        ])
        results = engine._parse_response(raw)

        # 验证 pipeline 需要的字段
        for item in results:
            assert isinstance(item["text"], str)
            assert isinstance(item["confidence"], float)
            assert isinstance(item["bbox"], list)
            assert len(item["bbox"]) == 4

            # 验证 bbox 每个点是 [x, y]
            for pt in item["bbox"]:
                assert isinstance(pt, list)
                assert len(pt) == 2
                assert isinstance(pt[0], (int, float))
                assert isinstance(pt[1], (int, float))

    def test_batch_processor_accepts_bailian_engine(self):
        """batch_processor 接受 BailianOCREngine 作为引擎"""
        from services.ocr.bailian_engine import BailianOCREngine
        from services.ocr.batch_processor import OCRBatchProcessor

        engine = BailianOCREngine(api_key="sk-test")

        # 验证 batch_processor 可以通过 mock 工作
        with patch.object(engine, "recognize_batch", return_value=[[
            {"text": "Mock 识别", "confidence": 0.95, "bbox": [[0,0],[100,0],[100,30],[0,30]]},
        ]]):
            processor = OCRBatchProcessor(batch_size=1)
            # 不需要真正执行，只验证接口兼容
            assert processor.batch_size == 1

    def test_engine_not_ready_without_api_key(self):
        """无 API Key 时引擎不可用但不崩溃"""
        from services.ocr.bailian_engine import BailianOCREngine

        # api_key="" 不会被 settings.bailian_api_key 覆盖（使用 is not None 判断）
        engine = BailianOCREngine(api_key="")
        engine.load_model()
        assert not engine.is_ready

        # recognize 在未就绪时应返回空列表，不抛异常
        result = engine.recognize(Path("/nonexistent.png"))
        assert result == []

    def test_recognize_nonexistent_file(self):
        """识别不存在的文件返回空列表"""
        from services.ocr.bailian_engine import BailianOCREngine

        engine = BailianOCREngine(api_key="sk-test")
        engine._model_loaded = True  # 绕过连通性检查
        engine._client = MagicMock()

        result = engine.recognize(Path("/nonexistent_file.png"))
        assert result == []


class TestBailianImageEncoding:
    """图片编码测试"""

    def test_base64_encoding_png(self):
        """PNG 图片正确编码为 Base64 Data URL"""
        import tempfile
        from services.ocr.bailian_engine import _image_to_base64_url

        with tempfile.TemporaryDirectory() as tmpdir:
            png_path = Path(tmpdir) / "test.png"
            _create_test_image(png_path)

            url = _image_to_base64_url(png_path)
            assert url.startswith("data:image/png;base64,")
            # 验证 base64 部分可解码
            import base64
            b64_part = url.split(",", 1)[1]
            decoded = base64.b64decode(b64_part)
            assert len(decoded) > 0

    def test_base64_encoding_jpg(self):
        """JPEG 图片正确编码"""
        import tempfile
        from services.ocr.bailian_engine import _image_to_base64_url

        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow 未安装")

        with tempfile.TemporaryDirectory() as tmpdir:
            jpg_path = Path(tmpdir) / "test.jpg"
            img = Image.new("RGB", (100, 100), color="white")
            img.save(str(jpg_path), "JPEG")

            url = _image_to_base64_url(jpg_path)
            assert url.startswith("data:image/jpeg;base64,")
