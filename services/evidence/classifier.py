"""
证据分类器 + 四层结构化信息提取
===================================
提取顺序：1.证据名称 → 2.身份信息 → 3.诊疗经过 → 4.费用明细

策略：规则优先（关键词匹配）+ LLM 深度提取兜底
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Optional

from loguru import logger
from openai import OpenAI

from config.settings import settings


# ─── 分类关键词映射 ──────────────────────────────────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # ─── 原告身份信息 ───
    "identity_id_card": [
        "居民身份证", "身份证正面", "身份证反面", "身份证人像",
        "身份证国徽", "签发机关", "有效期限",
        "公民身份号码",
        # 注意：不含单独的"身份证"以避免误匹配（死亡证明中有"身份证件号"）
    ],
    "identity_hukou": [
        "户口本", "户口", "户籍", "常住人口登记",
        "户别", "户号", "户主姓名",
    ],
    "identity_other": [
        "出生证明", "出生医学证明", "出生证", "亲子鉴定",
        "监护证明", "监护权", "收养证明", "领养证",
        "结婚证", "结婚", "婚姻", "离婚证",
    ],
    "identity_defendant": [
        "营业执照", "执业许可证", "信用代码",
        "统一社会信用代码", "法定代表人", "事业单位",
        "医疗机构执业许可证", "医疗机构登记",
        "执业医师", "执业证", "资格证", "医师资格",
        "护士执业", "执业范围", "卫生专业技术", "注册信息",
        "医务人员资质", "医师执业证",
    ],
    # ─── 死亡证明（死亡案件） ───
    "death_certificate": [
        "死亡证明", "居民死亡", "死亡医学证明",
        "死亡诊断", "火化证明",
        "死亡推断", "死亡通知书",
        # 注意：尸检报告/尸体检验 不在此类，归入 appraisal（司法鉴定）
    ],
    # ─── 病历资料 ───
    "medical_record": [
        "病历", "出院记录", "入院记录", "手术记录", "检查报告",
        "门诊病历", "门诊", "住院", "病程", "医嘱", "护理记录", "手术同意书",
        "知情同意书", "CT报告", "MRI报告", "B超报告", "化验单",
        "出院小结", "诊断证明", "死亡记录",
        "长期医嘱", "临时医嘱", "体温单",
    ],
    # ─── 司法鉴定意见书 ───
    "appraisal": [
        "司法鉴定", "鉴定意见书", "伤残等级", "因果关系",
        "参与度", "鉴定意见", "鉴定书", "过错认定", "过错参与度",
        "法医鉴定", "尸体检验", "尸检报告", "尸体解剖",
        "死因鉴定", "解剖报告", "病理鉴定", "毒物鉴定",
    ],
    # ─── 医疗费用及相关票据 ───
    "fee_receipt": [
        "发票", "票据", "收费", "收据", "结算",
        "费用清单", "住院费用", "门诊费用", "医疗费", "药费",
        "挂号费", "检查费", "手术费", "床位费", "护理费",
        "收费票据", "费用明细", "收费项目",
    ],
}

CATEGORY_NAMES: dict[str, str] = {
    "identity_id_card": "原告身份证信息",
    "identity_hukou": "户口本信息",
    "identity_other": "其他身份信息",
    "identity_defendant": "被告身份信息",
    "death_certificate": "死亡医学证明书",
    "medical_record": "病历资料",
    "appraisal": "司法鉴定意见书",
    "fee_receipt": "医疗费用及相关票据",
    "other_evidence": "其他证据",
}

# 排列顺序：严格按法律证据目录惯例
CATEGORY_ORDER: list[str] = [
    "identity_id_card",        # 1. 原告身份证信息（一人一页）
    "identity_hukou",          # 2. 户口本信息（如有）
    "identity_other",          # 3. 其他身份信息（出生证明等）
    "identity_defendant",      # 4. 被告身份信息
    "death_certificate",       # 5. 死亡医学证明书（死亡案件）
    "medical_record",          # 6. 病历资料
    "appraisal",               # 7. 司法鉴定意见书（如有）
    "fee_receipt",             # 8. 医疗费用及相关票据
    "other_evidence",          # 9. 其他证据
]

# 仅死亡案件可见的分类
DEATH_ONLY_CATEGORIES = {"death_certificate"}

# 身份类分组（用于 PDF 排版时判断身份类子类型）
IDENTITY_CATEGORIES = {"identity_id_card", "identity_hukou", "identity_other", "identity_defendant"}

# 分类优先级：当多个类别得分相同时，高优先级优先
# 关键规则：death_certificate > identity_id_card（死亡证明中有"身份证件号"不应误分类）
# appraisal > identity_*（鉴定书可能提到身份证号等）
CATEGORY_PRIORITY: dict[str, int] = {
    "death_certificate": 100,   # 最高，避免被身份证关键词截胡
    "appraisal": 90,            # 司法鉴定优先级高
    "identity_other": 80,       # 结婚证等，高于identity_id_card
    "identity_defendant": 70,
    "identity_hukou": 60,
    "identity_id_card": 50,     # 较低，因为"身份证"关键词容易出现在其他文档中
    "fee_receipt": 40,
    "medical_record": 30,
    "other_evidence": 10,
}

# 文件名→分类映射（当OCR文本为空或低置信时使用）
FILENAME_CLASSIFY_RULES: list[tuple[list[str], str]] = [
    # (关键词列表, 分类)
    (["身份证", "反面", "正面"], "identity_id_card"),
    (["户口本", "户口册", "户籍"], "identity_hukou"),
    (["结婚证", "出生证明", "出生证"], "identity_other"),
    (["被告", "营业执照", "信用代码"], "identity_defendant"),
    (["死亡证明", "死亡记录", "火化"], "death_certificate"),
    (["病历", "出院", "入院", "门诊病历", "手术", "检查报告"], "medical_record"),
    (["鉴定", "法医", "尸检"], "appraisal"),
    # 费用类（含护理用品/日常用品/医疗器械/门诊费用/住院清单/医保结算等命名）
    (["发票", "收据", "票据", "费用", "清单",
      "门诊费用", "住院清单", "住院费用", "医保结算", "医保报销",
      "日常用品", "护理用品", "生活用品", "护理品", "陪护用品",
      "医疗器械", "医用器械", "康复器械", "辅助器具", "护理器械",
      "轮椅", "拐杖", "助行器", "护理床", "医用耗材"], "fee_receipt"),
]

# ─── 四层提取的 keyword match 表（Layer 1 的 category 来自已有分类，这里不做）──

# Layer 2 身份信息关键字段（规则快速提取用）
IDENTITY_PATTERNS: dict[str, str] = {
    "patient_name": r"(患者|病人|姓\s*名)[：:\s]*([^\n，。；]{2,10})",
    "patient_id": r"(身份证号|证件号码|身份证)[：:\s]*([\dXx*]{15,18})",
    "hospital_name": r"([^\n，。；]{2,20}(医院|卫生院|诊所|卫生所|社区卫生服务中心))",
    "hospital_code": r"(统一社会信用代码|信用代码)[：:\s]*([\dA-Z]{18})",
}

# Layer 3 诊疗经过关键字段（规则快速提取用）
TREATMENT_PATTERNS: dict[str, str] = {
    "diagnosis": r"(诊断|入院诊断|出院诊断|主要诊断)[：:\s]*([^\n。]{5,200})",
    "admission_date": r"(入院日期|住院日期)[：:\s]*([\d-]{6,10})",
    "discharge_date": r"(出院日期)[：:\s]*([\d-]{6,10})",
}

# Layer 4 费用关键字段（规则快速提取用）
FEE_PATTERNS: dict[str, str] = {
    "single_amount": r"(合计|总计|金额|费用合计)[：:\s]*[¥￥]?([\d,.]+)",
    "line_item": r"([\u4e00-\u9fff]+费)[：:\s]*[¥￥]?([\d,.]+)",
}

# LLM 客户端单例
_llm_client: Optional[OpenAI] = None
_llm_lock = threading.Lock()


def _get_llm_client() -> OpenAI:
    """获取 OpenAI 兼容客户端（百炼 Qwen）"""
    global _llm_client
    if _llm_client is None:
        with _llm_lock:
            if _llm_client is None:
                _llm_client = OpenAI(
                    api_key=settings.bailian_api_key_plain,
                    base_url=settings.bailian_text_base_url,
                )
    return _llm_client


def _is_death_case(case_type: str) -> bool:
    """判断是否为死亡案件"""
    return case_type in ("death", "death_adult", "death_minor")


def _get_case_type_desc(case_type: str) -> str:
    """获取案件类型描述文字"""
    if case_type in ("death", "death_adult", "death_minor"):
        return "医疗损害（死亡）"
    elif case_type in ("neonatal", "neonatal_adult", "neonatal_minor"):
        return "医疗损害（新生儿）"
    else:
        return "医疗损害（伤残）"


# ═══════════════════════════════════════════════════════════════════════════════
# 原有分类逻辑（保留兼容）
# ═══════════════════════════════════════════════════════════════════════════════

def classify_text(text: str, case_type: str = "injury") -> tuple[str, float]:
    """对文本进行分类，返回 (category, confidence)

    1. 关键词匹配 → 高置信度（2+ 关键词命中）
    2. 同分时按 CATEGORY_PRIORITY 优先级决胜
    3. 单关键词命中 → LLM 内容验证（防止因个别关键词误判）
    4. 关键词未命中 → LLM 分类
    5. death_certificate 仅在 case_type == "death" 时可用
    """
    if not text or not text.strip():
        return ("other_evidence", 0.1)

    text_lower = text.lower()

    # 收集所有类别的得分
    category_scores: list[tuple[str, int]] = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        if category in DEATH_ONLY_CATEGORIES and not _is_death_case(case_type):
            continue

        match_count = 0
        for keyword in keywords:
            if keyword in text_lower:
                match_count += 1

        if match_count > 0:
            category_scores.append((category, match_count))

    # 按得分降序，同分按优先级降序
    category_scores.sort(key=lambda x: (x[1], CATEGORY_PRIORITY.get(x[0], 0)), reverse=True)

    if category_scores:
        best_category, best_score = category_scores[0]
        confidence = min(0.95, 0.6 + best_score * 0.05)

        # ── 规则：仅命中单个关键词 → LLM 内容验证 ──
        # 防止因个别关键词误判（如病历中提到的"身份证号"不应被分类为身份证）
        if best_score == 1:
            try:
                verified_category, verified_confidence = _verify_classification_by_llm(
                    text, best_category, case_type
                )
                # LLM 验证结果置信度更高 → 采纳 LLM 判断
                if verified_confidence > confidence:
                    logger.info(
                        f"LLM verification corrected: {best_category}({confidence}) "
                        f"-> {verified_category}({verified_confidence})"
                    )
                    return (verified_category, verified_confidence)
                # LLM 验证通过 → 保留关键词结果
                logger.info(
                    f"LLM verification confirmed: {best_category}({confidence})"
                )
            except Exception as e:
                logger.warning(f"LLM verification failed, using keyword result: {e}")

        return (best_category, round(confidence, 2))

    try:
        category, confidence = _classify_by_llm(text, case_type)
        return (category, confidence)
    except Exception as e:
        logger.warning(f"LLM classification failed, falling back to other_evidence: {e}")
        return ("other_evidence", 0.3)


def classify_by_filename(filename: str, case_type: str = "injury") -> tuple[str, float]:
    """基于文件名进行分类（OCR文本为空或低置信时的回退）

    优先级低于 OCR 文本分类，仅当 OCR 结果不可用或置信度极低时使用。
    """
    if not filename:
        return ("other_evidence", 0.1)

    name_lower = filename.lower()

    for keywords, category in FILENAME_CLASSIFY_RULES:
        if category in DEATH_ONLY_CATEGORIES and not _is_death_case(case_type):
            continue
        for kw in keywords:
            if kw in name_lower:
                return (category, 0.5)

    return ("other_evidence", 0.1)


def classify_with_filename_fallback(
    text: str, filename: str, case_type: str = "injury"
) -> tuple[str, float]:
    """组合分类：文件名优先（费用类），OCR内容兜底

    分类策略（2026-06-27 修订）：
    1. 文件名匹配到费用类（fee_receipt） → 直接采用，置信度 0.9
       理由：费用/发票/结算/清单类文件，文件名是用户命名的高精度信号
    2. 否则 OCR 文本分类（置信度 >= 0.5 采用）
    3. OCR 不确定时 → 文件名兜底
    """
    # ── Step 1: 文件名优先 — 费用类 ──
    if filename:
        fn_category, fn_confidence = classify_by_filename(filename, case_type)
        if fn_category == "fee_receipt":
            logger.info(
                f"Filename priority (fee_receipt): '{filename}' -> fee_receipt(0.9)"
            )
            return ("fee_receipt", 0.9)

    # ── Step 2: OCR 文本分类 ──
    category, confidence = ("other_evidence", 0.0)
    if text and text.strip():
        category, confidence = classify_text(text, case_type)
        if confidence >= 0.5:
            return (category, confidence)

    # ── Step 3: 文件名兜底（非费用类） ──
    if filename:
        if fn_confidence > confidence:
            logger.info(
                f"Filename fallback: {category}({confidence}) -> {fn_category}({fn_confidence}) "
                f"for '{filename}'"
            )
            return (fn_category, fn_confidence)

    return (category, confidence)


def _classify_by_llm(text: str, case_type: str) -> tuple[str, float]:
    """调用 LLM 基于文档完整内容进行分类"""
    available_categories = list(CATEGORY_ORDER)
    if not _is_death_case(case_type):
        available_categories = [c for c in available_categories if c not in DEATH_ONLY_CATEGORIES]

    category_desc = "\n".join(
        f"- {cat}: {CATEGORY_NAMES.get(cat, cat)}" for cat in available_categories
    )

    # 分类判断指南，帮助 LLM 基于内容精准分类
    classification_guide = """
⚠️ 核心规则：基于文档的**整体内容、结构和用途**来判断，不要仅凭个别关键词！

分类判断要点：
- identity_id_card（原告身份证）: 文档主要内容为"居民身份证"，正面有姓名/性别/民族/出生/住址/身份证号，背面有签发机关/有效期限。注意：仅在文档本身是身份证时才选此项，其他文档中提到"身份证号"不算
- identity_hukou（户口本）: 文档主要内容为"户口""常住人口登记卡"等户口登记信息
- identity_other（其他身份信息）: 出生医学证明、监护证明等非身份证/户口本的身份证明文件
- identity_defendant（被告信息）: 医疗机构的营业执照、执业许可证等主体资格证明文件，以及医务人员执业资质文件
- death_certificate（死亡证明）: 文档主要内容为"死亡医学证明""居民死亡证明""火化证明"等（仅死亡案件）。注意：尸检报告/尸体检验/鉴定意见书不属于此类，归入appraisal
- medical_record（病历资料）: 入院/出院记录、手术记录、检查报告、诊断证明、病程记录等医疗文书
- appraisal（司法鉴定）: 司法鉴定意见书、伤残等级鉴定、因果关系鉴定、尸体检验/尸检报告、死因鉴定等
- fee_receipt（费用票据）: 医疗费发票、费用清单、收费收据、结算单等财务凭证
"""
    # 新生儿案件的分类额外提示
    if case_type == "neonatal":
        classification_guide += (
            "\n【新生儿案件特别提示】\n"
            "- 出生医学证明（含新生儿姓名、出生体重、孕周等）→ identity_other\n"
            "- 分娩记录、产程记录 → medical_record\n"
            "- 新生儿窒息复苏记录 → medical_record\n"
            "- Apgar评分表、新生儿筛查报告 → medical_record\n"
        )
    else:
        classification_guide += (
            "\n【鉴定与资质文件分类提示】\n"
            "- 尸检报告/尸体检验/尸体解剖/死因鉴定 → appraisal（不是death_certificate！）\n"
            "- 执业医师证/资格证/注册信息/执业范围 → identity_defendant\n"
            "- 鉴定意见书中的鉴定人信息 → appraisal（随鉴定书分类）\n"
        )

    prompt = (
        f"请仔细阅读以下文档的完整内容，判断它实际属于哪个证据类别。\n"
        f"只能从以下选项中选择一个：\n{category_desc}\n\n"
        f"{classification_guide}\n"
        f"案件类型：{_get_case_type_desc(case_type)}\n\n"
        f"文档内容：\n{text[:3000]}\n\n"
        f"请返回JSON格式：{{\"category\": \"类别代码\", \"confidence\": 0.0-1.0的置信度}}\n"
        f"只返回JSON，不要额外说明。"
    )

    client = _get_llm_client()
    response = client.chat.completions.create(
        model=settings.bailian_flash_model,
        messages=[
            {"role": "system", "content": "你是一个法律证据分类助手。请基于文档的完整内容、结构和用途进行判断，严格按照指定格式输出。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        timeout=settings.bailian_text_timeout,
    )
    raw = response.choices[0].message.content.strip()

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        data = json.loads(json_match.group())
        category = data.get("category", "other_evidence")
        confidence = float(data.get("confidence", 0.5))
        if category not in available_categories:
            category = "other_evidence"
            confidence = 0.3
        return (category, round(min(1.0, max(0.0, confidence)), 2))

    return ("other_evidence", 0.3)


def _verify_classification_by_llm(
    text: str, suggested_category: str, case_type: str
) -> tuple[str, float]:
    """基于文件完整内容验证/纠正关键词匹配的分类结果

    核心规则：LLM 阅读文件的实际内容，判断这份文档本身是什么类型。
    不依赖个别关键词（如文档中提到的"身份证号"不意味着这是身份证），
    而是根据文档的整体结构、主要内容和第一用途来判断。
    """
    available_categories = list(CATEGORY_ORDER)
    if not _is_death_case(case_type):
        available_categories = [c for c in available_categories if c not in DEATH_ONLY_CATEGORIES]

    category_desc = "\n".join(
        f"- {cat}: {CATEGORY_NAMES.get(cat, cat)}" for cat in available_categories
    )

    suggested_name = CATEGORY_NAMES.get(suggested_category, suggested_category)

    prompt = (
        f"你是一个法律证据分类助手。请仔细阅读以下文档的**完整内容**，"
        f"判断这份文档自身实际属于哪种证据类别。\n\n"
        f"⚠️ 关键规则：\n"
        f"1. 根据文档的**整体结构、主要内容和第一用途**来判断，不要仅凭个别关键词\n"
        f"2. 例如：病历中可能提到'身份证号'，但文档本身是病历，应选 medical_record\n"
        f"3. 例如：费用清单中可能提到'患者姓名'，但文档本身是票据，应选 fee_receipt\n"
        f"4. 判断标准：这份文档**本身是什么文件**？\n\n"
        f"可选类别：\n{category_desc}\n\n"
        f"关键词匹配初步判断为：{suggested_name}\n"
        f"请基于文档实际内容重新独立判断：\n\n"
        f"文档内容：\n{text[:3000]}\n\n"
        f"请返回JSON格式：{{\"category\": \"类别代码\", \"confidence\": 0.0-1.0的置信度}}\n"
        f"只返回JSON，不要额外说明。"
    )

    client = _get_llm_client()
    response = client.chat.completions.create(
        model=settings.bailian_flash_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个法律证据分类助手。请基于文档的完整内容、结构和用途进行独立判断，"
                    "不受外部关键词匹配结果的干扰。严格按照指定格式输出。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        timeout=settings.bailian_text_timeout,
    )
    raw = response.choices[0].message.content.strip()

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        data = json.loads(json_match.group())
        category = data.get("category", suggested_category)
        confidence = float(data.get("confidence", 0.5))
        if category not in available_categories:
            category = suggested_category
            confidence = 0.3
        return (category, round(min(1.0, max(0.0, confidence)), 2))

    return (suggested_category, 0.55)


# ═══════════════════════════════════════════════════════════════════════════════
# 四层结构化信息提取（核心新增）
# ═══════════════════════════════════════════════════════════════════════════════

def extract_structured_info(text: str, case_type: str) -> dict[str, Any]:
    """按照 1.证据名称→2.身份信息→3.诊疗经过→4.费用明细 的顺序提取结构化信息

    先尝试规则快速提取，再LLM补齐缺失字段
    """
    if not text or not text.strip():
        return _empty_extracted_data()

    # Step 1: 规则快速提取
    rule_result = _extract_by_rules(text)

    # Step 2: 如果规则提取结果覆盖率低，用 LLM 补齐
    rule_coverage = _calc_coverage(rule_result)
    if rule_coverage < 0.4:
        logger.info(f"Rule extraction coverage={rule_coverage:.2f}, falling back to LLM")
        try:
            llm_result = _extract_by_llm(text, case_type)
            # 合并：LLM结果填充规则未提取到的字段
            result = _merge_results(rule_result, llm_result)
            return result
        except Exception as e:
            logger.warning(f"LLM extraction failed, using rule result: {e}")
            return rule_result

    return rule_result


def _extract_by_rules(text: str) -> dict[str, Any]:
    """规则快速提取四层信息"""
    result: dict[str, Any] = {
        "layer_1_evidence_name": {},
        "layer_2_identity": {},
        "layer_3_treatment": {},
        "layer_4_fees": {},
    }

    # ── Layer 1: 证据名称 ──
    # 从文件名/标题行提取
    first_line = text.strip().split("\n")[0][:100] if text.strip() else ""
    result["layer_1_evidence_name"] = {
        "title": first_line if first_line else "",
        "doc_type": _infer_doc_type(text),
        "doc_type_confidence": 0.7 if first_line else 0.1,
    }

    # ── Layer 2: 身份信息 ──
    identity: dict[str, Any] = {}
    for field, pattern in IDENTITY_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            identity[field] = match.group(2).strip()

    # 补充提取亲属关系
    rel_match = re.search(r"(法定代理人|监护人|亲属|近亲属)[：:\s]*([^\n，。]{2,10})", text)
    if rel_match:
        identity["legal_representative"] = rel_match.group(2).strip()
        identity["relationship"] = rel_match.group(1).strip()

    result["layer_2_identity"] = identity

    # ── Layer 3: 诊疗经过 ──
    treatment: dict[str, Any] = {}
    for field, pattern in TREATMENT_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            treatment[field] = match.group(2).strip()

    # 提取症状描述
    symptom_match = re.search(
        r"(主诉|症状|因)[：:\s]*([^\n。]{10,200})", text
    )
    if symptom_match:
        treatment["symptoms"] = symptom_match.group(2).strip()

    result["layer_3_treatment"] = treatment

    # ── Layer 4: 费用明细 ──
    fee_data: dict[str, Any] = {"items": [], "total_amount": 0.0}

    # 提取总额
    total_match = re.search(FEE_PATTERNS["single_amount"], text)
    if total_match:
        try:
            raw_amount = total_match.group(2).replace(",", "")
            fee_data["total_amount"] = float(raw_amount)
        except (ValueError, IndexError):
            pass

    # 提取逐项费用
    for match in re.finditer(FEE_PATTERNS["line_item"], text):
        try:
            fee_type = match.group(1).strip()
            amount = float(match.group(2).replace(",", ""))
            fee_data["items"].append({"fee_type": fee_type, "amount": amount})
        except (ValueError, IndexError):
            continue

    result["layer_4_fees"] = fee_data

    return result


def _extract_by_llm(text: str, case_type: str) -> dict[str, Any]:
    """调用 LLM 进行四层结构化提取"""
    client = _get_llm_client()

    case_type_desc = _get_case_type_desc(case_type)

    prompt = (
        f"你是一个医疗损害案件证据分析助手。请严格按照以下四层顺序提取信息。\n"
        f"案件类型：{case_type_desc}\n\n"
        f"## 提取规则\n"
        f"请按 **1层→2层→3层→4层** 的顺序逐层提取，前一层的结果可能帮助后一层的判断。\n"
        f"每层只提取该层相关的字段，不要跨层混淆。\n"
        f"如果某字段无法从文档中识别，填 null。\n\n"
        f"### 第1层：证据名称\n"
        f"- title: 证据文档的标题/名称（如\"XX医院住院病历\"、\"医疗费发票\"）\n"
        f"- doc_type: 文档类型（medical_record/fee_receipt/identity/appraisal/death_certificate/other）\n"
        f"- date: 文档日期\n\n"
        f"### 第2层：身份信息\n"
        f"- patient_name: 患者/受害人姓名\n"
        f"- patient_id: 身份证号\n"
        f"- patient_gender: 性别\n"
        f"- patient_birth: 出生日期\n"
        f"- patient_address: 住址\n"
        f"- patient_phone: 联系电话\n"
        f"- hospital_name: 医院全称\n"
        f"- hospital_code: 统一社会信用代码\n"
        f"- hospital_address: 医院地址\n"
        f"- legal_representative: 法定代理人/亲属姓名（未成年人案件）\n"
        f"- relationship: 与患者的关系\n\n"
        f"### 第3层：诊疗经过\n"
        f"- admission_date: 入院日期\n"
        f"- discharge_date: 出院日期\n"
        f"- diagnosis: 诊断结论\n"
        f"- symptoms: 主诉/症状\n"
        f"- treatment_summary: 诊疗经过摘要（200字以内）\n"
        f"- operation_records: 手术记录（如有）\n\n"
        f"### 第4层：费用明细\n"
        f"- fee_items: 费用项目列表，每项包含 fee_type(费用类型) 和 amount(金额)\n"
        f"- total_amount: 费用合计\n"
        f"- insurance_amount: 医保报销金额（如有）\n"
        f"- out_of_pocket: 自费金额\n\n"
        f"文档内容：\n{text[:5000]}\n\n"
        f"请返回JSON格式（按1-4层组织），key为 layer_1_evidence_name / layer_2_identity / layer_3_treatment / layer_4_fees。"
        f"只返回JSON，不要额外说明。"
    )

    try:
        response = client.chat.completions.create(
            model=settings.bailian_flash_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个专业的医疗损害案件证据分析助手。"
                        "严格按照 证据名称→身份信息→诊疗经过→费用明细 的四层顺序提取信息。"
                        "只输出JSON，不添加任何解释。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            timeout=settings.bailian_text_timeout,
        )
        raw = response.choices[0].message.content.strip()

        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            data = json.loads(json_match.group())
            # 确保四层结构存在
            if "layer_1_evidence_name" not in data:
                data["layer_1_evidence_name"] = {}
            if "layer_2_identity" not in data:
                data["layer_2_identity"] = {}
            if "layer_3_treatment" not in data:
                data["layer_3_treatment"] = {}
            if "layer_4_fees" not in data:
                data["layer_4_fees"] = {"items": [], "total_amount": 0.0}
            return data

        logger.warning(f"LLM did not return valid JSON for extraction: {raw[:200]}")
        return _empty_extracted_data()

    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        raise


def _merge_results(rule_result: dict, llm_result: dict) -> dict[str, Any]:
    """合并规则提取和LLM提取的结果，LLM填补规则未提取到的字段"""
    merged: dict[str, Any] = {
        "layer_1_evidence_name": {},
        "layer_2_identity": {},
        "layer_3_treatment": {},
        "layer_4_fees": {},
    }

    for layer in merged:
        rule_layer = rule_result.get(layer, {}) or {}
        llm_layer = llm_result.get(layer, {}) or {}

        if layer == "layer_4_fees":
            # 费用层特殊合并：保留规则提取的items，LLM补充total
            merged[layer]["items"] = rule_layer.get("items") or llm_layer.get("items") or []
            merged[layer]["total_amount"] = (
                rule_layer.get("total_amount")
                or llm_layer.get("total_amount")
                or 0.0
            )
            merged[layer]["insurance_amount"] = llm_layer.get("insurance_amount")
            merged[layer]["out_of_pocket"] = llm_layer.get("out_of_pocket")
        else:
            # 其他层：LLM补充规则未取到的字段
            for key, value in llm_layer.items():
                if value is not None and value != "":
                    merged[layer][key] = value
            for key, value in rule_layer.items():
                if value is not None and value != "" and key not in merged[layer]:
                    merged[layer][key] = value

    return merged


def _calc_coverage(result: dict) -> float:
    """计算规则提取结果的覆盖率（非空字段比例）"""
    total = 0
    filled = 0
    for layer in ["layer_1_evidence_name", "layer_2_identity", "layer_3_treatment", "layer_4_fees"]:
        layer_data = result.get(layer, {}) or {}
        if layer == "layer_4_fees":
            items = layer_data.get("items", [])
            total += max(1, len(items) + 1)  # items数 + total_amount
            if items:
                filled += len(items)
            if layer_data.get("total_amount"):
                filled += 1
        else:
            for value in layer_data.values():
                total += 1
                if value is not None and value != "":
                    filled += 1

    return filled / max(1, total)


def _infer_doc_type(text: str) -> str:
    """从文本关键词推断文档类型"""
    text_lower = text.lower()
    # 身份证
    if any(kw in text_lower for kw in ["身份证", "居民身份"]):
        return "identity_id_card"
    # 户口本
    if any(kw in text_lower for kw in ["户口本", "户口", "户籍"]):
        return "identity_hukou"
    # 出生证明
    if any(kw in text_lower for kw in ["出生证明", "出生医学证明"]):
        return "identity_other"
    # 被告（医疗机构信息）
    if any(kw in text_lower for kw in ["营业执照", "执业许可证", "信用代码", "统一社会信用代码"]):
        return "identity_defendant"
    # 病历
    if any(kw in text_lower for kw in ["病历", "诊断", "出院", "入院", "手术"]):
        return "medical_record"
    # 费用
    if any(kw in text_lower for kw in ["发票", "费用", "金额", "收费"]):
        return "fee_receipt"
    # 鉴定
    if any(kw in text_lower for kw in ["鉴定", "伤残等级", "因果关系"]):
        return "appraisal"
    # 死亡证明
    if any(kw in text_lower for kw in ["死亡", "尸检", "火化"]):
        return "death_certificate"
    return "other"


def _empty_extracted_data() -> dict[str, Any]:
    """返回空的四层结构"""
    return {
        "layer_1_evidence_name": {},
        "layer_2_identity": {},
        "layer_3_treatment": {},
        "layer_4_fees": {"items": [], "total_amount": 0.0},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 合并分类+提取（优化：一次 LLM 调用同时完成分类和四层提取）
# ═══════════════════════════════════════════════════════════════════════════════

def classify_and_extract(text: str, case_type: str = "injury") -> dict[str, Any]:
    """合并分类+四层提取为一次处理。

    返回: {
        "category": str,
        "confidence": float,
        "extracted": {layer_1:..., layer_2:..., layer_3:..., layer_4:...}
    }

    优化策略：
    1. 先尝试规则分类 + 规则提取（零延迟）
    2. 规则分类命中且覆盖率高 → 直接返回（不走LLM）
    3. 否则一次LLM调用同时完成分类+提取
    """
    if not text or not text.strip():
        return {
            "category": "other_evidence",
            "confidence": 0.1,
            "extracted": _empty_extracted_data(),
        }

    # Step 1: 规则快速分类
    category, confidence = classify_text(text, case_type)

    # Step 2: 规则快速提取
    rule_result = _extract_by_rules(text)
    rule_coverage = _calc_coverage(rule_result)

    # Step 3: 如果规则分类命中（非LLM兜底）且覆盖率高 → 直接返回
    if confidence >= 0.6 and rule_coverage >= 0.4:
        return {
            "category": category,
            "confidence": confidence,
            "extracted": rule_result,
        }

    # Step 4: 需要LLM — 一次调用同时完成分类+提取
    try:
        llm_result = _classify_and_extract_by_llm(text, case_type)
        # 合并：LLM 结果优先（因为包含了分类+提取），规则补充 LLM 未覆盖的字段
        merged_extracted = _merge_results(rule_result, llm_result.get("extracted", {}))

        # LLM 分类结果优先于规则兜底分类
        llm_category = llm_result.get("category", category)
        llm_confidence = llm_result.get("confidence", confidence)

        return {
            "category": llm_category,
            "confidence": llm_confidence,
            "extracted": merged_extracted,
        }
    except Exception as e:
        logger.warning(f"Combined LLM call failed, using rule results: {e}")
        return {
            "category": category,
            "confidence": confidence,
            "extracted": rule_result,
        }


def _classify_and_extract_by_llm(text: str, case_type: str) -> dict[str, Any]:
    """一次LLM调用同时完成分类+四层提取"""
    client = _get_llm_client()

    available_categories = list(CATEGORY_ORDER)
    if case_type not in ("death", "death_adult", "death_minor"):
        available_categories = [c for c in available_categories if c != "death_certificate"]

    category_desc = "\n".join(
        f"- {cat}: {CATEGORY_NAMES.get(cat, cat)}" for cat in available_categories
    )

    case_type_desc = _get_case_type_desc(case_type)

    prompt = (
        f"你是一个医疗损害案件证据分析助手。请同时完成以下两个任务：\n\n"
        f"## 任务1：分类（基于文档完整内容判断）\n"
        f"⚠️ 根据文档的**整体结构、主要内容和第一用途**来判断类别，不要仅凭个别关键词。\n"
        f"例如：病历中提到'身份证号'仍应选 medical_record，费用清单中提到'患者姓名'仍应选 fee_receipt。\n"
        f"从以下类别中选择一个：\n{category_desc}\n\n"
        f"## 任务2：四层结构化信息提取\n"
        f"按 1层→2层→3层→4层 顺序提取：\n"
        f"- layer_1_evidence_name: title(标题), doc_type(文档类型), date(日期)\n"
        f"- layer_2_identity: patient_name, patient_id, hospital_name, hospital_code, legal_representative, relationship 等\n"
        f"- layer_3_treatment: admission_date, discharge_date, diagnosis, symptoms, treatment_summary, operation_records\n"
        f"- layer_4_fees: items(数组，每项含fee_type和amount), total_amount, insurance_amount, out_of_pocket\n\n"
        f"案件类型：{case_type_desc}\n\n"
        f"文档内容：\n{text[:5000]}\n\n"
        f"请返回JSON格式：\n"
        f'{{"category": "类别代码", "confidence": 0.0-1.0, "extracted": {{...四层数据...}}}}\n'
        f"只返回JSON，不要额外说明。"
    )

    response = client.chat.completions.create(
        model=settings.bailian_flash_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个专业的医疗损害案件证据分析助手。"
                    "基于文档的完整内容、结构和用途进行分类判断。"
                    "同时完成分类和四层结构化信息提取。"
                    "只输出JSON，不添加任何解释。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        timeout=settings.bailian_text_timeout,
    )
    raw = response.choices[0].message.content.strip()

    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        data = json.loads(json_match.group())
        category = data.get("category", "other_evidence")
        confidence = float(data.get("confidence", 0.5))
        extracted = data.get("extracted", {})

        # 确保四层结构存在
        if "layer_1_evidence_name" not in extracted:
            extracted["layer_1_evidence_name"] = {}
        if "layer_2_identity" not in extracted:
            extracted["layer_2_identity"] = {}
        if "layer_3_treatment" not in extracted:
            extracted["layer_3_treatment"] = {}
        if "layer_4_fees" not in extracted:
            extracted["layer_4_fees"] = {"items": [], "total_amount": 0.0}

        if category not in available_categories:
            category = "other_evidence"
            confidence = 0.3

        return {
            "category": category,
            "confidence": round(min(1.0, max(0.0, confidence)), 2),
            "extracted": extracted,
        }

    return {"category": "other_evidence", "confidence": 0.3, "extracted": _empty_extracted_data()}


def classify_and_extract_batch(
    items: list[tuple[str, str]],
    case_type: str = "injury",
) -> list[dict[str, Any]]:
    """批量分类+提取：对需要LLM的材料，3-5个拼成一次调用。

    Args:
        items: [(material_id, ocr_text), ...]
        case_type: 案件类型

    Returns:
        [{"material_id": str, "category": str, "confidence": float, "extracted": dict}, ...]
    """
    results: list[dict[str, Any]] = []

    # 先尝试规则路径
    rule_items: list[tuple[int, str, str, dict, float, dict]] = []  # (idx, mid, cat, conf, extracted)
    llm_needed: list[tuple[int, str, str]] = []  # (idx, mid, text)

    for idx, (mid, text) in enumerate(items):
        if not text or not text.strip():
            results.append({
                "material_id": mid,
                "category": "other_evidence",
                "confidence": 0.1,
                "extracted": _empty_extracted_data(),
            })
            continue

        # 规则快速分类
        category, confidence = classify_text(text, case_type)
        # 规则快速提取
        rule_result = _extract_by_rules(text)
        rule_coverage = _calc_coverage(rule_result)

        if confidence >= 0.6 and rule_coverage >= 0.4:
            # 规则路径足够 → 直接用
            results.append({
                "material_id": mid,
                "category": category,
                "confidence": confidence,
                "extracted": rule_result,
            })
        else:
            # 需要LLM
            llm_needed.append((idx, mid, text))
            rule_items.append((idx, mid, category, confidence, rule_result))

    if not llm_needed:
        return results

    # 批量LLM调用：每批最多5个
    BATCH_SIZE = 5
    for batch_start in range(0, len(llm_needed), BATCH_SIZE):
        batch = llm_needed[batch_start:batch_start + BATCH_SIZE]
        batch_rule = rule_items[batch_start:batch_start + BATCH_SIZE]

        try:
            batch_results = _classify_and_extract_batch_by_llm(
                [(mid, text) for _, mid, text in batch],
                case_type,
            )
            for i, (orig_idx, mid, _) in enumerate(batch):
                _, _, rule_cat, rule_conf, rule_extracted = batch_rule[i]
                llm_res = batch_results[i]

                merged_extracted = _merge_results(rule_extracted, llm_res.get("extracted", {}))
                results.append({
                    "material_id": mid,
                    "category": llm_res.get("category", rule_cat),
                    "confidence": llm_res.get("confidence", rule_conf),
                    "extracted": merged_extracted,
                })
        except Exception as e:
            logger.warning(f"Batch LLM call failed, falling back to individual: {e}")
            # 批量失败，回退到逐个
            for i, (orig_idx, mid, text) in enumerate(batch):
                _, _, rule_cat, rule_conf, rule_extracted = batch_rule[i]
                try:
                    single_res = classify_and_extract(text, case_type)
                    results.append({
                        "material_id": mid,
                        "category": single_res["category"],
                        "confidence": single_res["confidence"],
                        "extracted": single_res["extracted"],
                    })
                except Exception as e2:
                    logger.error(f"Individual LLM also failed for {mid}: {e2}")
                    results.append({
                        "material_id": mid,
                        "category": rule_cat,
                        "confidence": rule_conf,
                        "extracted": rule_extracted,
                    })

    return results


def _classify_and_extract_batch_by_llm(
    items: list[tuple[str, str]],
    case_type: str,
) -> list[dict[str, Any]]:
    """批量LLM调用：一次处理多个文档"""
    client = _get_llm_client()

    available_categories = list(CATEGORY_ORDER)
    if case_type not in ("death", "death_adult", "death_minor"):
        available_categories = [c for c in available_categories if c != "death_certificate"]

    category_desc = "\n".join(
        f"- {cat}: {CATEGORY_NAMES.get(cat, cat)}" for cat in available_categories
    )

    case_type_desc = _get_case_type_desc(case_type)

    docs_text = "\n\n---\n\n".join(
        f"[文档{i+1}]:\n{text[:2000]}" for i, (_, text) in enumerate(items)
    )

    prompt = (
        f"你是一个医疗损害案件证据分析助手。请对以下 {len(items)} 个文档分别完成：\n"
        f"1. 分类（基于文档完整内容判断，不要仅凭个别关键词）\n{category_desc}\n"
        f"2. 四层结构化信息提取（证据名称→身份信息→诊疗经过→费用明细）\n\n"
        f"案件类型：{case_type_desc}\n\n"
        f"{docs_text}\n\n"
        f"请返回JSON数组，每个元素包含 category, confidence, extracted(含layer_1_evidence_name/layer_2_identity/layer_3_treatment/layer_4_fees)。\n"
        f"只返回JSON数组，不要额外说明。"
    )

    response = client.chat.completions.create(
        model=settings.bailian_flash_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个专业的医疗损害案件证据分析助手。"
                    "基于文档的完整内容、结构和用途进行分类判断，不要仅凭个别关键词。"
                    "同时完成分类和四层结构化信息提取。"
                    "只输出JSON数组，不添加任何解释。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        timeout=max(60, settings.bailian_text_timeout),
    )
    raw = response.choices[0].message.content.strip()

    json_match = re.search(r"\[[\s\S]*\]", raw)
    if json_match:
        data = json.loads(json_match.group())
        results = []
        for item in data:
            category = item.get("category", "other_evidence")
            confidence = float(item.get("confidence", 0.5))
            extracted = item.get("extracted", {})

            if "layer_4_fees" not in extracted:
                extracted["layer_4_fees"] = {"items": [], "total_amount": 0.0}
            for layer in ["layer_1_evidence_name", "layer_2_identity", "layer_3_treatment"]:
                if layer not in extracted:
                    extracted[layer] = {}

            if category not in available_categories:
                category = "other_evidence"
                confidence = 0.3

            results.append({
                "category": category,
                "confidence": round(min(1.0, max(0.0, confidence)), 2),
                "extracted": extracted,
            })

        # 确保结果数量匹配
        while len(results) < len(items):
            results.append({
                "category": "other_evidence",
                "confidence": 0.3,
                "extracted": _empty_extracted_data(),
            })

        return results[:len(items)]

    # JSON解析失败，返回默认结果
    return [
        {"category": "other_evidence", "confidence": 0.3, "extracted": _empty_extracted_data()}
        for _ in items
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 材料处理入口（分类 + 四层提取）
# ═══════════════════════════════════════════════════════════════════════════════

def classify_material(material_id: str) -> None:
    """对单个材料执行分类 + 四层结构化信息提取，更新数据库"""
    import uuid

    from db.models_evidence import EvidenceMaterial, EvidenceCase
    from db.session import get_session_factory, run_in_worker
    from sqlalchemy import select

    material_uuid = uuid.UUID(material_id)

    async def _do_process():
        async with get_session_factory()() as db:
            stmt = select(EvidenceMaterial).where(EvidenceMaterial.id == material_uuid)
            result = await db.execute(stmt)
            material = result.scalar_one_or_none()
            if not material:
                logger.warning(f"Material not found: {material_id}")
                return

            # 无OCR文本 → 跳过
            if not material.ocr_text or not material.ocr_text.strip():
                material.auto_category = "other_evidence"
                material.category_confidence = 0.1
                material.effective_category = "other_evidence"
                material.extracted_data = _empty_extracted_data()
                await db.commit()
                return

            # 获取案件类型
            case_stmt = select(EvidenceCase).where(EvidenceCase.id == material.evidence_case_id)
            case_result = await db.execute(case_stmt)
            case = case_result.scalar_one_or_none()
            case_type = case.case_type if case else "injury"

            # ── Step A: 分类（OCR文本优先，文件名兜底） ──
            category, confidence = classify_with_filename_fallback(
                material.ocr_text, material.original_filename, case_type
            )

            material.auto_category = category
            material.category_confidence = confidence
            if not material.manual_category:
                material.effective_category = category
            else:
                material.effective_category = material.manual_category

            # ── Step B: 四层结构化提取 ──
            extracted = extract_structured_info(material.ocr_text, case_type)
            material.extracted_data = extracted

            # ── Step C: 从四层数据生成清单标题和证明目的 ──
            material.catalog_title = _generate_title_v2(category, extracted, material)
            material.proof_purpose = _generate_proof_purpose_v2(category, extracted, case_type)

            # ── Step D: 从第4层填充 fee_detail ──
            fees = extracted.get("layer_4_fees", {})
            if fees.get("items") or fees.get("total_amount"):
                material.fee_detail = {
                    "items": fees.get("items", []),
                    "total_amount": fees.get("total_amount", 0.0),
                    "insurance_amount": fees.get("insurance_amount"),
                    "out_of_pocket": fees.get("out_of_pocket"),
                }

            await db.commit()
            logger.info(
                f"Material processed: {material_id} -> category={category} "
                f"(conf={confidence}), extraction_layers="
                f"L1={bool(extracted.get('layer_1_evidence_name'))}/"
                f"L2={bool(extracted.get('layer_2_identity'))}/"
                f"L3={bool(extracted.get('layer_3_treatment'))}/"
                f"L4={bool(extracted.get('layer_4_fees',{}).get('items'))}"
            )

    run_in_worker(_do_process())


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_title_v2(category: str, extracted: dict, material) -> str:
    """基于四层数据生成更精准的清单标题"""
    filename = material.original_filename or "未命名文件"

    # 优先使用第1层提取的标题
    layer1 = extracted.get("layer_1_evidence_name", {}) or {}
    extracted_title = layer1.get("title", "")
    doc_type = layer1.get("doc_type", category)

    if extracted_title and extracted_title != filename:
        return extracted_title

    # 回退：分类名 + 文件名
    cat_name = CATEGORY_NAMES.get(category, "其他证据")
    if doc_type and doc_type in CATEGORY_NAMES:
        cat_name = CATEGORY_NAMES[doc_type]

    # 如果有患者名，加入标题
    identity = extracted.get("layer_2_identity", {}) or {}
    patient = identity.get("patient_name", "")
    if patient:
        return f"{patient} - {cat_name}（{filename}）"

    return f"{cat_name}（{filename}）"


def _generate_proof_purpose_v2(category: str, extracted: dict, case_type: str) -> str:
    """基于四层数据生成更精准的证明目的"""
    layer2 = extracted.get("layer_2_identity", {}) or {}
    layer3 = extracted.get("layer_3_treatment", {}) or {}
    layer4 = extracted.get("layer_4_fees", {}) or {}

    purposes = {
        "identity_id_card": "证明{}的原告主体身份".format(
            layer2.get("patient_name") or "原告"
        ),
        "identity_hukou": "证明{}的户籍信息及家庭关系".format(
            layer2.get("patient_name") or "原告"
        ),
        "identity_other": "证明{}的身份关系".format(
            layer2.get("patient_name") or "原告"
        ),
        "identity_defendant": "证明被告的主体资格及医疗机构执业信息",
        "medical_record": "证明{}的诊疗经过及损害后果".format(
            layer2.get("patient_name") or "患者"
        ),
        "fee_receipt": "证明因医疗损害造成的经济损失{}{}".format(
            f"，合计{layer4.get('total_amount', 0)}元" if layer4.get("total_amount") else "",
            "" if not _is_death_case(case_type) else "（含死亡相关费用）"
        ),
        "appraisal": "证明医疗过错、因果关系及过错参与度",
        "death_certificate": "证明患者死亡的事实",
        "other_evidence": "证明案件相关事实",
    }
    return purposes.get(category, "证明案件相关事实")


def _generate_title(category: str, material) -> str:
    """旧版兼容：根据分类和材料信息自动生成清单标题"""
    filename = material.original_filename or "未命名文件"
    cat_name = CATEGORY_NAMES.get(category, "其他证据")
    return f"{cat_name}（{filename}）"


def _generate_proof_purpose(category: str, case_type: str) -> str:
    """旧版兼容：根据分类自动生成证明目的"""
    purposes: dict[str, str] = {
        "identity_id_card": "证明原告的主体身份",
        "identity_hukou": "证明原告的户籍信息及家庭关系",
        "identity_other": "证明原告的身份关系",
        "identity_defendant": "证明被告的主体资格及医疗机构执业信息",
        "medical_record": "证明患者的诊疗经过及损害后果",
        "fee_receipt": "证明因医疗损害造成的经济损失",
        "appraisal": "证明医疗过错、因果关系及过错参与度",
        "death_certificate": "证明患者死亡的事实",
        "other_evidence": "证明案件相关事实",
    }
    return purposes.get(category, "证明案件相关事实")
