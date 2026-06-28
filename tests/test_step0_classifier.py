"""
步骤0 · LLM 费用分类器单元测试
================================
覆盖三层降级（DeepSeek → GLM → 百炼）+ 全部失败兜底

运行:
    cd E:\\OCRScanStruct
    python -m pytest tests/test_step0_classifier.py -v --tb=short
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ─── 确保项目根目录在 sys.path ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.evidence import step0_classifier as clf_module
from services.evidence.step0_classifier import _build_classify_prompt, classify_fee


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: 制造 mock OpenAI 响应
# ═══════════════════════════════════════════════════════════════════════════════

def _make_mock_response(content: str):
    """构造一个 mock 的 OpenAI ChatCompletion 响应"""
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


def _make_json_response(category: str, confidence: float) -> MagicMock:
    """构造返回合法 JSON 的 mock 响应"""
    content = json.dumps({"category": category, "confidence": confidence})
    return _make_mock_response(content)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _build_classify_prompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildPrompt:
    """测试 prompt 构造"""

    def test_prompt_contains_all_10_categories(self):
        """prompt 必须包含全部 10 类"""
        prompt = _build_classify_prompt("test ocr text")
        for cn_name in [
            "医疗费", "误工费", "护理费", "住院伙食补助费", "营养费",
            "赔偿金", "被扶养人生活费", "交通住宿费", "鉴定费", "精神损害抚慰金",
        ]:
            assert cn_name in prompt, f"Prompt should contain '{cn_name}'"

    def test_prompt_contains_ocr_text(self):
        """prompt 必须包含 OCR 文本"""
        ocr_text = "这是一张医疗费发票金额500元"
        prompt = _build_classify_prompt(ocr_text)
        assert ocr_text in prompt

    def test_prompt_contains_json_instruction(self):
        """prompt 必须包含 JSON 返回格式说明"""
        prompt = _build_classify_prompt("test")
        assert "JSON" in prompt or "json" in prompt
        assert "category" in prompt
        assert "confidence" in prompt

    def test_prompt_truncates_long_text(self):
        """超长 OCR 文本应被截断（3000字以内）"""
        long_text = "A" * 5000
        prompt = _build_classify_prompt(long_text)
        # prompt 中不应包含完整 5000 字符
        assert "A" * 4000 not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 2. classify_fee — 三层降级
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyFeeFallback:
    """测试三层降级分类逻辑"""

    def test_deepseek_success_returns_first(self):
        """DeepSeek 成功 → 返回 DeepSeek 结果，不调 GLM/百炼"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", 0.95
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=mock_client),
            patch.object(clf_module, "_get_glm_client") as mock_glm,
            patch.object(clf_module, "_get_bailian_client") as mock_bl,
        ):
            category, confidence = classify_fee("门诊费500元")

        assert category == "fee_medical"
        assert confidence == 0.95
        mock_glm.assert_not_called()
        mock_bl.assert_not_called()

    def test_deepseek_fail_glm_success(self):
        """DeepSeek 失败 → GLM 成功 → 返回 GLM 结果"""
        deepseek_client = MagicMock()
        deepseek_client.chat.completions.create.side_effect = Exception("DeepSeek down")
        glm_client = MagicMock()
        glm_client.chat.completions.create.return_value = _make_json_response(
            "fee_nursing", 0.88
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=deepseek_client),
            patch.object(clf_module, "_get_glm_client", return_value=glm_client),
            patch.object(clf_module, "_get_bailian_client") as mock_bl,
        ):
            category, confidence = classify_fee("护理费收据")

        assert category == "fee_nursing"
        assert confidence == 0.88
        mock_bl.assert_not_called()

    def test_deepseek_glm_fail_bailian_success(self):
        """DeepSeek + GLM 都失败 → 百炼成功 → 返回百炼结果"""
        deepseek_client = MagicMock()
        deepseek_client.chat.completions.create.side_effect = Exception("DS down")
        glm_client = MagicMock()
        glm_client.chat.completions.create.side_effect = Exception("GLM down")
        bailian_client = MagicMock()
        bailian_client.chat.completions.create.return_value = _make_json_response(
            "fee_transport", 0.72
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=deepseek_client),
            patch.object(clf_module, "_get_glm_client", return_value=glm_client),
            patch.object(clf_module, "_get_bailian_client", return_value=bailian_client),
        ):
            category, confidence = classify_fee("交通费票据")

        assert category == "fee_transport"
        assert confidence == 0.72

    def test_all_three_fail_returns_none_zero(self):
        """三层全部失败 → 返回 (None, 0.0)"""
        deepseek_client = MagicMock()
        deepseek_client.chat.completions.create.side_effect = Exception("DS down")
        glm_client = MagicMock()
        glm_client.chat.completions.create.side_effect = Exception("GLM down")
        bailian_client = MagicMock()
        bailian_client.chat.completions.create.side_effect = Exception("BL down")
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=deepseek_client),
            patch.object(clf_module, "_get_glm_client", return_value=glm_client),
            patch.object(clf_module, "_get_bailian_client", return_value=bailian_client),
        ):
            category, confidence = classify_fee("some text")

        assert category is None
        assert confidence == 0.0

    def test_all_clients_none_returns_none_zero(self):
        """所有 client 都为 None（无 API Key）→ 返回 (None, 0.0)"""
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=None),
            patch.object(clf_module, "_get_glm_client", return_value=None),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("some text")

        assert category is None
        assert confidence == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. classify_fee — 边界情况
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyFeeEdgeCases:
    """测试分类器边界情况"""

    def test_empty_ocr_text_returns_none(self):
        """空 OCR 文本 → 返回 (None, 0.0)"""
        category, confidence = classify_fee("")
        assert category is None
        assert confidence == 0.0

    def test_whitespace_only_ocr_text_returns_none(self):
        """纯空白 OCR 文本 → 返回 (None, 0.0)"""
        category, confidence = classify_fee("   \n\t  ")
        assert category is None
        assert confidence == 0.0

    def test_llm_returns_invalid_category_falls_through(self):
        """LLM 返回非法 category → 视为该层失败，降级到下一层"""
        deepseek_client = MagicMock()
        # 返回非法 category
        deepseek_client.chat.completions.create.return_value = _make_json_response(
            "fee_invalid_xyz", 0.9
        )
        glm_client = MagicMock()
        glm_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", 0.8
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=deepseek_client),
            patch.object(clf_module, "_get_glm_client", return_value=glm_client),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("门诊费")

        # DeepSeek 返回非法 category → 降级到 GLM → 返回 fee_medical
        assert category == "fee_medical"
        assert confidence == 0.8

    def test_llm_returns_non_json_response_falls_through(self):
        """LLM 返回非 JSON → 该层失败，降级"""
        deepseek_client = MagicMock()
        deepseek_client.chat.completions.create.return_value = _make_mock_response(
            "这不是JSON格式"
        )
        glm_client = MagicMock()
        glm_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", 0.85
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=deepseek_client),
            patch.object(clf_module, "_get_glm_client", return_value=glm_client),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("门诊费")

        assert category == "fee_medical"
        assert confidence == 0.85

    def test_confidence_clamped_to_range(self):
        """置信度超出 [0, 1] 范围时被 clamp"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", 1.5  # 超过 1.0
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=mock_client),
            patch.object(clf_module, "_get_glm_client", return_value=None),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("门诊费")

        assert category == "fee_medical"
        assert confidence == 1.0

    def test_confidence_negative_clamped_to_zero(self):
        """负置信度 clamp 到 0.0"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", -0.5
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=mock_client),
            patch.object(clf_module, "_get_glm_client", return_value=None),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("门诊费")

        assert category == "fee_medical"
        assert confidence == 0.0

    def test_confidence_rounded_to_2_decimals(self):
        """置信度四舍五入到 2 位小数"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_json_response(
            "fee_medical", 0.856
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=mock_client),
            patch.object(clf_module, "_get_glm_client", return_value=None),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            _, confidence = classify_fee("门诊费")

        assert confidence == 0.86

    def test_json_with_extra_text_still_parsed(self):
        """LLM 返回包含额外文本但内含 JSON → 仍能解析"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            '好的，分类结果如下：{"category": "fee_medical", "confidence": 0.9} 以上是结果。'
        )
        with (
            patch.object(clf_module, "_get_deepseek_client", return_value=mock_client),
            patch.object(clf_module, "_get_glm_client", return_value=None),
            patch.object(clf_module, "_get_bailian_client", return_value=None),
        ):
            category, confidence = classify_fee("门诊费")

        assert category == "fee_medical"
        assert confidence == 0.9
