"""
步骤0 · LLM 费用分类器（三层降级）
===================================
优先级：DeepSeek → GLM → 百炼（DashScope OpenAI 兼容）
每次调用 classify_fee(ocr_text) 返回 (category_key, confidence)
"""
from __future__ import annotations

import json
import re
import threading
from typing import Optional

from loguru import logger
from openai import OpenAI

from config.settings import settings
from services.evidence.step0_constants import (
    STEP0_FEE_CATEGORIES,
    STEP0_FEE_CATEGORY_KEYS,
    validate_fee_category,
)


# ─── LLM 客户端单例（三层降级） ──────────────────────────────────────────────

_deepseek_client: Optional[OpenAI] = None
_glm_client: Optional[OpenAI] = None
_bailian_client: Optional[OpenAI] = None
_client_lock = threading.Lock()


def _get_deepseek_client() -> Optional[OpenAI]:
    """获取 DeepSeek OpenAI 兼容客户端（仅在配置了 API Key 时可用）"""
    global _deepseek_client
    api_key = settings.deepseek_api_key_plain
    if not api_key:
        return None
    if _deepseek_client is None:
        with _client_lock:
            if _deepseek_client is None:
                _deepseek_client = OpenAI(
                    api_key=api_key,
                    base_url=settings.deepseek_base_url,
                )
    return _deepseek_client


def _get_glm_client() -> Optional[OpenAI]:
    """获取 GLM OpenAI 兼容客户端（仅在配置了 API Key 时可用）"""
    global _glm_client
    api_key = settings.glm_api_key_plain
    if not api_key:
        return None
    if _glm_client is None:
        with _client_lock:
            if _glm_client is None:
                _glm_client = OpenAI(
                    api_key=api_key,
                    base_url=settings.glm_base_url,
                )
    return _glm_client


def _get_bailian_client() -> Optional[OpenAI]:
    """获取百炼 OpenAI 兼容客户端（与 classifier.py 一致）"""
    global _bailian_client
    api_key = settings.bailian_api_key_plain
    if not api_key:
        return None
    if _bailian_client is None:
        with _client_lock:
            if _bailian_client is None:
                _bailian_client = OpenAI(
                    api_key=api_key,
                    base_url=settings.bailian_text_base_url,
                )
    return _bailian_client


# ─── Prompt 构造 ─────────────────────────────────────────────────────────────

def _build_classify_prompt(ocr_text: str) -> str:
    """构造 10 类费用分类 prompt"""
    category_desc = "\n".join(
        f"- {key}: {cn_name}" for key, cn_name in STEP0_FEE_CATEGORIES.items()
    )

    classification_guide = """\
分类判断要点（按主要金额/主要内容归类，强制单分类）：
- fee_medical（医疗费）：门诊/住院发票、费用清单、医保结算单。关键词「门诊费」「住院费」「医药费」「医保统筹」「费用清单」「收费票据」「结算单」
- fee_lost_income（误工费）：工资证明、误工证明、收入减少证明。关键词「误工证明」「工资证明」「收入减少」「停工留薪」
- fee_nursing（护理费）：护理证明、护工费发票、护理依赖鉴定。关键词「护理费」「护理证明」「护工」「陪护」
- fee_hospital_food（住院伙食补助费）：住院天数证明、住院记录。关键词「住院伙食补助」「住院天数」「住院日数」
- fee_nutrition（营养费）：营养证明、医嘱营养建议。关键词「营养费」「营养证明」「医嘱营养」「加强营养」
- fee_compensation（赔偿金）：伤残等级鉴定结论、死亡赔偿金计算依据。关键词「伤残赔偿金」「死亡赔偿金」「伤残等级」
- fee_dependent（被扶养人生活费）：被扶养人身份证明、扶养关系证明。关键词「被扶养人」「生活费」「扶养」「抚养」
- fee_transport（交通住宿费）：交通费/住宿费票据。关键词「交通费」「车票」「机票」「住宿费」
- fee_appraisal（鉴定费）：鉴定费发票、鉴定收据。关键词「鉴定费」「鉴定收费」「司法鉴定费」
- fee_mental（精神损害抚慰金）：精神损害相关证明、心理治疗凭证。关键词「精神损害抚慰金」「精神损害」「心理治疗」
"""

    prompt = (
        f"请仔细阅读以下文档的 OCR 识别文本，判断它属于哪一类费用。\n"
        f"只能从以下 10 个选项中选择一个：\n{category_desc}\n\n"
        f"{classification_guide}\n"
        f"⚠️ 核心规则：\n"
        f"1. 基于文档的**整体内容、主要金额和第一用途**判断，不要仅凭个别关键词\n"
        f"2. 强制单分类，按主要金额/主要内容归类\n"
        f"3. 只能选择上述 10 个 category 之一\n\n"
        f"文档 OCR 文本：\n{ocr_text[:3000]}\n\n"
        f'请返回JSON格式：{{"category": "fee_xxx", "confidence": 0.0-1.0}}\n'
        f"只返回JSON，不要额外说明。"
    )
    return prompt


_SYSTEM_PROMPT = (
    "你是一个医疗损害赔偿案件的费用分类助手。"
    "请基于文档的完整内容、主要金额和用途进行判断，"
    "严格按照指定格式输出JSON。"
)


# ─── 单次 LLM 调用 ────────────────────────────────────────────────────────────

def _call_llm(
    client: OpenAI,
    model: str,
    prompt: str,
    timeout: int,
) -> tuple[str, float]:
    """调用单个 LLM 客户端进行分类，返回 (category, confidence)

    Raises:
        Exception: LLM 调用失败或返回格式无效
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        timeout=timeout,
    )
    raw = response.choices[0].message.content.strip()

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        raise ValueError(f"LLM response is not valid JSON: {raw[:200]}")

    data = json.loads(json_match.group())
    category = data.get("category", "")
    confidence = float(data.get("confidence", 0.5))

    if not validate_fee_category(category):
        raise ValueError(f"LLM returned invalid category: {category}")

    confidence = round(min(1.0, max(0.0, confidence)), 2)
    return (category, confidence)


# ─── 公开接口 ─────────────────────────────────────────────────────────────────

def classify_fee(ocr_text: str) -> tuple[Optional[str], float]:
    """对 OCR 文本进行 10 类费用分类（三层降级）

    优先级：DeepSeek → GLM → 百炼

    Args:
        ocr_text: OCR 识别出的文本

    Returns:
        (category_key, confidence) — 全部 LLM 失败时返回 (None, 0.0)
    """
    if not ocr_text or not ocr_text.strip():
        return (None, 0.0)

    prompt = _build_classify_prompt(ocr_text)

    # ── Layer 1: DeepSeek ──
    try:
        client = _get_deepseek_client()
        if client:
            category, confidence = _call_llm(
                client,
                settings.deepseek_text_model,
                prompt,
                settings.deepseek_timeout,
            )
            logger.info(f"step0 classify_fee [DeepSeek]: category={category}, confidence={confidence}")
            return (category, confidence)
    except Exception as e:
        logger.warning(f"step0 classify_fee DeepSeek failed: {e}")

    # ── Layer 2: GLM ──
    try:
        client = _get_glm_client()
        if client:
            category, confidence = _call_llm(
                client,
                settings.glm_model,
                prompt,
                settings.glm_timeout,
            )
            logger.info(f"step0 classify_fee [GLM]: category={category}, confidence={confidence}")
            return (category, confidence)
    except Exception as e:
        logger.warning(f"step0 classify_fee GLM failed: {e}")

    # ── Layer 3: 百炼（DashScope） ──
    try:
        client = _get_bailian_client()
        if client:
            category, confidence = _call_llm(
                client,
                settings.bailian_flash_model,
                prompt,
                settings.bailian_text_timeout,
            )
            logger.info(f"step0 classify_fee [Bailian]: category={category}, confidence={confidence}")
            return (category, confidence)
    except Exception as e:
        logger.warning(f"step0 classify_fee Bailian failed: {e}")

    # 全部失败
    logger.error("step0 classify_fee: all 3 LLM providers failed")
    return (None, 0.0)
