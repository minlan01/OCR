"""
步骤0 · 常量模块单元测试
========================
覆盖：
- 10 类费用分类 key 完整性 + 中文名正确性
- validate_fee_category 合法/非法 key
- get_fee_cn_name 正确返回
- 置信度阈值常量
- 状态枚举完整性

运行:
    cd E:\\OCRScanStruct
    python -m pytest tests/test_step0_constants.py -v --tb=short
"""
from __future__ import annotations

import os
import sys

import pytest

# ─── 确保项目根目录在 sys.path ──────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.evidence.step0_constants import (
    STEP0_CONFIDENCE_THRESHOLD,
    STEP0_FEE_CATEGORIES,
    STEP0_FEE_CATEGORY_KEYS,
    STEP0_STATUS_COMPLETED,
    STEP0_STATUS_IN_PROGRESS,
    STEP0_STATUS_NOT_STARTED,
    STEP0_STATUS_SKIPPED,
    STEP0_VALID_STATUSES,
    get_fee_cn_name,
    validate_fee_category,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 10 类费用分类
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeeCategories:
    """测试 10 类费用分类常量"""

    def test_category_count_is_10(self):
        """必须正好 10 个分类"""
        assert len(STEP0_FEE_CATEGORIES) == 10

    def test_category_keys_list_matches_dict(self):
        """STEP0_FEE_CATEGORY_KEYS 应与 dict keys 一致"""
        assert set(STEP0_FEE_CATEGORY_KEYS) == set(STEP0_FEE_CATEGORIES.keys())

    @pytest.mark.parametrize(
        "key,cn_name",
        [
            ("fee_medical", "医疗费"),
            ("fee_lost_income", "误工费"),
            ("fee_nursing", "护理费"),
            ("fee_hospital_food", "住院伙食补助费"),
            ("fee_nutrition", "营养费"),
            ("fee_compensation", "赔偿金"),
            ("fee_dependent", "被扶养人生活费"),
            ("fee_transport", "交通住宿费"),
            ("fee_appraisal", "鉴定费"),
            ("fee_mental", "精神损害抚慰金"),
        ],
    )
    def test_category_cn_name_correct(self, key: str, cn_name: str):
        """每个 key 对应正确的中文名"""
        assert STEP0_FEE_CATEGORIES[key] == cn_name

    def test_all_keys_start_with_fee_prefix(self):
        """所有 key 必须以 fee_ 开头"""
        for key in STEP0_FEE_CATEGORIES:
            assert key.startswith("fee_"), f"Key '{key}' should start with 'fee_'"

    def test_all_keys_unique(self):
        """所有 key 必须唯一"""
        keys = list(STEP0_FEE_CATEGORIES.keys())
        assert len(keys) == len(set(keys))

    def test_all_cn_names_unique(self):
        """所有中文名必须唯一"""
        cn_names = list(STEP0_FEE_CATEGORIES.values())
        assert len(cn_names) == len(set(cn_names))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. validate_fee_category
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateFeeCategory:
    """测试 validate_fee_category 校验函数"""

    @pytest.mark.parametrize(
        "key",
        [
            "fee_medical",
            "fee_lost_income",
            "fee_nursing",
            "fee_hospital_food",
            "fee_nutrition",
            "fee_compensation",
            "fee_dependent",
            "fee_transport",
            "fee_appraisal",
            "fee_mental",
        ],
    )
    def test_valid_keys_return_true(self, key: str):
        """所有合法 key 返回 True"""
        assert validate_fee_category(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "",
            "medical",
            "fee_other",
            "fee_",
            "not_a_category",
            "FEE_MEDICAL",
            "fee_medical ",  # trailing space
            " fee_medical",  # leading space
            "identity_id_card",
            "null",
        ],
    )
    def test_invalid_keys_return_false(self, key: str):
        """非法 key 返回 False"""
        assert validate_fee_category(key) is False

    def test_none_returns_false(self):
        """None 返回 False"""
        assert validate_fee_category(None) is False  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. get_fee_cn_name
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetFeeCnName:
    """测试 get_fee_cn_name 获取中文名函数"""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("fee_medical", "医疗费"),
            ("fee_lost_income", "误工费"),
            ("fee_nursing", "护理费"),
            ("fee_hospital_food", "住院伙食补助费"),
            ("fee_nutrition", "营养费"),
            ("fee_compensation", "赔偿金"),
            ("fee_dependent", "被扶养人生活费"),
            ("fee_transport", "交通住宿费"),
            ("fee_appraisal", "鉴定费"),
            ("fee_mental", "精神损害抚慰金"),
        ],
    )
    def test_known_key_returns_cn_name(self, key: str, expected: str):
        """已知 key 返回对应中文名"""
        assert get_fee_cn_name(key) == expected

    def test_unknown_key_returns_default(self):
        """未知 key 返回 '未分类'"""
        assert get_fee_cn_name("fee_unknown") == "未分类"

    def test_empty_string_returns_default(self):
        """空字符串返回 '未分类'"""
        assert get_fee_cn_name("") == "未分类"

    def test_none_returns_default(self):
        """None 返回 '未分类'"""
        assert get_fee_cn_name(None) == "未分类"  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 置信度阈值 + 状态枚举
# ═══════════════════════════════════════════════════════════════════════════════

class TestThresholdAndStatus:
    """测试置信度阈值和状态枚举"""

    def test_confidence_threshold_is_0_6(self):
        """置信度阈值 = 0.6"""
        assert STEP0_CONFIDENCE_THRESHOLD == 0.6

    def test_confidence_threshold_is_float(self):
        """置信度阈值是 float 类型"""
        assert isinstance(STEP0_CONFIDENCE_THRESHOLD, float)

    def test_valid_statuses_contains_4_states(self):
        """状态枚举包含 4 个状态"""
        assert len(STEP0_VALID_STATUSES) == 4

    def test_valid_statuses_values(self):
        """4 个状态值正确"""
        assert STEP0_STATUS_NOT_STARTED == "not_started"
        assert STEP0_STATUS_IN_PROGRESS == "in_progress"
        assert STEP0_STATUS_COMPLETED == "completed"
        assert STEP0_STATUS_SKIPPED == "skipped"
        assert STEP0_VALID_STATUSES == {
            "not_started", "in_progress", "completed", "skipped"
        }
