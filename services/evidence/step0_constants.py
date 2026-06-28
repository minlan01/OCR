"""
步骤0 · 原始素材预处理 — 常量定义
================================
10 类费用分类 key 体系 + 置信度阈值 + 校验工具函数
"""
from __future__ import annotations

# ─── 10 类费用分类 ──────────────────────────────────────────────────────────

STEP0_FEE_CATEGORIES: dict[str, str] = {
    "fee_medical": "医疗费",
    "fee_lost_income": "误工费",
    "fee_nursing": "护理费",
    "fee_hospital_food": "住院伙食补助费",
    "fee_nutrition": "营养费",
    "fee_compensation": "赔偿金",
    "fee_dependent": "被扶养人生活费",
    "fee_transport": "交通住宿费",
    "fee_appraisal": "鉴定费",
    "fee_mental": "精神损害抚慰金",
}

# 所有合法的 category key 列表
STEP0_FEE_CATEGORY_KEYS: list[str] = list(STEP0_FEE_CATEGORIES.keys())

# 置信度阈值：低于此值标记 needs_review
STEP0_CONFIDENCE_THRESHOLD: float = 0.6

# 步骤0 状态枚举
STEP0_STATUS_NOT_STARTED = "not_started"
STEP0_STATUS_IN_PROGRESS = "in_progress"
STEP0_STATUS_COMPLETED = "completed"
STEP0_STATUS_SKIPPED = "skipped"

STEP0_VALID_STATUSES = {
    STEP0_STATUS_NOT_STARTED,
    STEP0_STATUS_IN_PROGRESS,
    STEP0_STATUS_COMPLETED,
    STEP0_STATUS_SKIPPED,
}


def validate_fee_category(key: str) -> bool:
    """校验 category key 是否在 10 类费用中"""
    return key in STEP0_FEE_CATEGORIES


def get_fee_cn_name(key: str) -> str:
    """获取费用类别的中文名称，未知 key 返回 '未分类'"""
    return STEP0_FEE_CATEGORIES.get(key, "未分类")
