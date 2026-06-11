"""
文档分析器 — 基于 PPT 培训规范的5段结构化民事起诉状生成
=====================================================================
Step 1: 从四层结构化数据提取当事人/诊疗/鉴定/人员等结构化数据
Step 2: 按 template_manager 的 5 段模板逐段调用 LLM 生成法律文本
Step 3: 生成固定结尾段（综上所述...）

遵循规范: 民事起诉状及司法鉴定申请书撰写培训 PPT
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Optional

from loguru import logger
from openai import OpenAI

from config.settings import settings
from services.evidence.classifier import CATEGORY_NAMES
from services.complaint.template_manager import get_template, get_template_key, TEMPLATE_REGISTRY
from services.utils.date_utils import normalize_date as _normalize_date

_analyzer_client: Optional[OpenAI] = None
_flash_client: Optional[OpenAI] = None
_analyzer_lock = threading.Lock()


def _clean_nulls(d: dict) -> None:
    """递归清理 dict 中值为 None 的键（LLM JSON 可能返回 null）"""
    to_delete = [k for k, v in d.items() if v is None]
    for k in to_delete:
        del d[k]
    for v in d.values():
        if isinstance(v, dict):
            _clean_nulls(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _clean_nulls(item)


def _get_analyzer_client() -> OpenAI:
    """获取文本分析客户端

    优先级：DeepSeek → 百炼 → GLM
    DeepSeek V3 质量与 qwen3.5-plus 相当，价格更低。
    """
    global _analyzer_client
    if _analyzer_client is None:
        with _analyzer_lock:
            if _analyzer_client is None:
                # 1. 优先使用 DeepSeek API
                deepseek_key = settings.deepseek_api_key_plain
                if deepseek_key:
                    _analyzer_client = OpenAI(
                        api_key=deepseek_key,
                        base_url=settings.deepseek_base_url,
                    )
                    logger.info("Analyzer client using DeepSeek API")
                else:
                    # 2. 回退到百炼
                    _analyzer_client = OpenAI(
                        api_key=settings.bailian_api_key_plain,
                        base_url=settings.bailian_text_base_url,
                    )
                    logger.info("Analyzer client using Bailian fallback")
    return _analyzer_client


def _get_flash_client() -> OpenAI:
    """获取 flash 客户端（用于段落生成）

    优先级：DeepSeek → GLM（免费） → 百炼
    """
    global _flash_client
    if _flash_client is None:
        with _analyzer_lock:
            if _flash_client is None:
                # 1. 优先使用 DeepSeek API
                deepseek_key = settings.deepseek_api_key_plain
                if deepseek_key:
                    _flash_client = OpenAI(
                        api_key=deepseek_key,
                        base_url=settings.deepseek_base_url,
                    )
                    logger.info("Flash client using DeepSeek API")
                else:
                    # 2. 回退到 GLM（免费）
                    glm_key = settings.glm_api_key_plain
                    if glm_key:
                        _flash_client = OpenAI(
                            api_key=glm_key,
                            base_url=settings.glm_base_url,
                        )
                        logger.info("Flash client using GLM (glm-4v-flash)")
                    else:
                        # 3. 最后回退到百炼
                        _flash_client = OpenAI(
                            api_key=settings.bailian_api_key_plain,
                            base_url=settings.bailian_text_base_url,
                        )
                        logger.info("Flash client using Bailian fallback")
    return _flash_client


def analyze_catalog(case_id: str) -> dict[str, Any]:
    """分析证据清单 → 提取文档生成所需的数据

    Step 1: 结构化数据提取（多原告、入院、诊疗、鉴定、人员）
    Step 2: 按段调用 LLM 生成 5 段事实与理由
    Step 3: 固定结尾段
    """
    import uuid

    from db.models_evidence import EvidenceCase, EvidenceMaterial, EvidenceRequirement
    from db.session import get_session_factory, run_in_worker
    from sqlalchemy import select

    async def _do_analyze():
        case_uuid = uuid.UUID(case_id)
        async with get_session_factory()() as db:
            # 获取案件
            case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            result = await db.execute(case_stmt)
            case = result.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")

            catalog_data = case.catalog_data or {}
            groups = catalog_data.get("groups", [])

            # 收集所有材料
            mat_stmt = select(EvidenceMaterial).where(
                EvidenceMaterial.evidence_case_id == case_uuid
            )
            mat_result = await db.execute(mat_stmt)
            materials = mat_result.scalars().all()

            # ── Step 1: 构建结构化上下文并提取 ──
            structured_context = _build_structured_context(materials)

            if structured_context.strip():
                analysis_result = _extract_document_slots(
                    structured_context, case.case_type, case.is_minor, materials
                )
                # 防御性检查：确保返回有效 dict
                if not isinstance(analysis_result, dict):
                    logger.warning(f"LLM extraction returned non-dict: {type(analysis_result)}, resetting to {{}}")
                    analysis_result = {}
            else:
                analysis_result = {}

            # ── Step 1.2: 校验原告数量 + 关系推断 + is_patient 标记 ──
            plaintiffs = analysis_result.get("plaintiffs", []) or []
            if plaintiffs:
                # 从所有素材 OCR 文本中收集真实身份证号
                import re as _re
                all_ocr_ids: set[str] = set()
                for mat in materials:
                    ocr_text = mat.ocr_text or ""
                    for m_id in _re.findall(r'\d{17}[\dXx]', ocr_text):
                        all_ocr_ids.add(m_id)

                # ── 从文件名提取关系标注 ──
                filename_rels = _extract_filename_relationships(materials)
                
                # ── 从病历/鉴定材料提取患者姓名 ──
                patient_names = _extract_patient_names_from_materials(materials)

                # 过滤 + 关系校验 + is_patient 标记
                valid_plaintiffs = []
                for p in plaintiffs:
                    if not p or not isinstance(p, dict):
                        continue
                    p_id = (p.get("id_number") or "").strip()
                    p_name = (p.get("name") or "").strip()
                    
                    # 身份证号校验
                    if p_id and p_id not in all_ocr_ids:
                        logger.warning(
                            f"过滤原告：{p_name} (id={p_id}) "
                            f"不在素材身份证号集合中，疑似LLM推测"
                        )
                        continue
                    
                    # ── 关系推断优先级 ──
                    
                    # 1. 文件名标注（最高优先级）
                    if filename_rels and p_name in filename_rels:
                        file_rel = filename_rels[p_name]
                        if p.get("relationship") != file_rel:
                            logger.info(
                                f"关系修正（文件名覆盖）: {p_name} "
                                f"LLM={p.get('relationship', '?')} → 文件名={file_rel}"
                            )
                            p["relationship"] = file_rel
                    
                    # 2. 患者姓名交叉比对
                    if patient_names and p_name in patient_names:
                        if p.get("relationship") != "本人":
                            logger.info(
                                f"关系修正（病历交叉）: {p_name} "
                                f"LLM={p.get('relationship', '?')} → 本人（姓名出现在病历患者位置）"
                            )
                            p["relationship"] = "本人"
                        p["is_patient"] = True
                    
                    # 3. 确保 is_patient 与 relationship 一致
                    if p.get("relationship") == "本人":
                        p["is_patient"] = True
                    elif p.get("is_patient") is None:
                        p["is_patient"] = False
                    
                    valid_plaintiffs.append(p)

                if len(valid_plaintiffs) < len(plaintiffs):
                    logger.info(
                        f"原告校验：{len(plaintiffs)} → {len(valid_plaintiffs)} "
                        f"（过滤了 {len(plaintiffs) - len(valid_plaintiffs)} 个无身份证素材的原告）"
                    )
                
                # 日志输出关系推断结果
                for p in valid_plaintiffs:
                    logger.info(
                        f"原告关系确认：{p.get('name', '?')} → "
                        f"relationship={p.get('relationship', 'null')}, "
                        f"is_patient={p.get('is_patient', False)}"
                    )
                
                analysis_result["plaintiffs"] = valid_plaintiffs
                # 更新 plaintiff_name 为第一个有效原告
                if valid_plaintiffs:
                    analysis_result["plaintiff_name"] = valid_plaintiffs[0].get("name", "")

            # ── Step 1.5: 定向提取死亡诊断（直接从OCR原文定位，不依赖LLM） ──
            if case.case_type == "death":
                direct_dd = _direct_extract_death_diagnosis(materials)
                if direct_dd:
                    analysis_result["death_diagnosis"] = direct_dd
                else:
                    # 死亡诊断提取失败，标记缺失
                    logger.warning(
                        f"Death diagnosis direct extraction failed for case {case_id} "
                        f"— will rely on LLM extraction result"
                    )
                    if not analysis_result.get("death_diagnosis"):
                        analysis_result["_death_diagnosis_missing"] = True

            # ── Step 1.6: 定向提取被告信息（从OCR原文中补充法定代表人/信用代码/地址） ──
            direct_def = _direct_extract_defendant_info(materials)
            if direct_def:
                for k, v in direct_def.items():
                    if v and not analysis_result.get(k):
                        analysis_result[k] = v

            # ── Step 1.7: 多家医院被告识别（解决多家医院混淆） ──
            analysis_result = _resolve_defendant_hospital(analysis_result, materials)

            # ── Step 1.7b: 鉴定结论定向提取（补充LLM遗漏的鉴定人/结论原文） ──
            direct_appraisal = _direct_extract_appraisal_conclusion(materials)
            if direct_appraisal:
                appraisal = analysis_result.get("appraisal_details") or {}
                for k, v in direct_appraisal.items():
                    if v and not appraisal.get(k):
                        appraisal[k] = v
                if appraisal:
                    analysis_result["appraisal_details"] = appraisal

            # ── Step 1.7c: 医务人员资质定向提取（补充LLM遗漏的资质问题） ──
            direct_staff = _direct_extract_staff_qualification(materials)
            if direct_staff:
                staff = analysis_result.get("staff_details") or {}
                for k, v in direct_staff.items():
                    if v and not staff.get(k):
                        staff[k] = v
                if staff:
                    analysis_result["staff_details"] = staff
                if direct_staff.get("has_staff_issue") and not analysis_result.get("has_staff_issue"):
                    analysis_result["has_staff_issue"] = True

            # ── Step 1.8: 后验证（校验身份证号、被告名称、日期等） ──
            analysis_result = _validate_extracted_data(analysis_result, case.case_type)

            # ── 要件验证 ──
            req_stmt = select(EvidenceRequirement).where(
                EvidenceRequirement.case_type == case.case_type,
                EvidenceRequirement.is_minor == case.is_minor,
            ).order_by(EvidenceRequirement.sort_order)
            req_result = await db.execute(req_stmt)
            requirements = req_result.scalars().all()

            if not requirements:
                from db.models_evidence import DEFAULT_REQUIREMENTS
                req_data = [
                    r for r in DEFAULT_REQUIREMENTS
                    if r["case_type"] == case.case_type
                    and r["is_minor"] == case.is_minor
                ]
            else:
                req_data = [
                    {
                        "category": r.category,
                        "category_name": r.category_name,
                        "is_required": r.is_required,
                        "check_rules": r.check_rules,
                    }
                    for r in requirements
                ]

            existing_categories: set[str] = set()
            for mat in materials:
                if mat.effective_category:
                    existing_categories.add(mat.effective_category)

            validation_result = []
            missing_items = []
            for req in req_data:
                cat = req["category"]
                has_evidence = cat in existing_categories
                is_ok = has_evidence or not req["is_required"]
                validation_result.append({
                    "category": cat,
                    "category_name": req["category_name"],
                    "is_required": req["is_required"],
                    "has_evidence": has_evidence,
                    "status": "ok" if is_ok else "missing",
                })
                if not is_ok:
                    missing_items.append({
                        "category": cat,
                        "category_name": req["category_name"],
                        "description": req.get("description", ""),
                    })

            # ── 补充案件基本信息 ──
            analysis_result["case_name"] = case.case_name
            analysis_result["case_type"] = case.case_type
            analysis_result["case_type_name"] = (
                "人身损害赔偿" if case.case_type == "injury"
                else "死亡赔偿"
            )
            analysis_result["is_minor"] = case.is_minor

            if case.plaintiff_info:
                analysis_result.update(case.plaintiff_info)
            if case.defendant_info:
                analysis_result.update(case.defendant_info)
                # 手动输入的被告电话映射到 defendant_phone（优先级高于OCR提取）
                if case.defendant_info.get("phone"):
                    analysis_result["defendant_phone"] = case.defendant_info["phone"]

            fee_summary = catalog_data.get("fee_summary", {})
            total_amount = catalog_data.get("total_amount", 0.0)
            analysis_result["fee_summary"] = fee_summary
            analysis_result["total_amount"] = total_amount
            # 诉讼请求总额留空，人工填写
            analysis_result["赔偿总额"] = ""
            analysis_result["claim_total"] = ""

            # 清单数据
            catalog_items = []
            for group in groups:
                for item in group.get("items", []):
                    catalog_items.append(item)
            analysis_result["catalog_items"] = catalog_items
            analysis_result["evidence_list"] = catalog_items

            # ── Step 2: 按段调用 LLM 生成 5 段事实与理由 ──
            template_key = get_template_key(case.case_type, case.is_minor)
            template = get_template(template_key)

            logger.info(f"Generating complaint paragraphs: template={template_key}")

            for section in template["sections"]:
                section_id = section["id"]
                is_optional = section.get("optional", False)

                # 可选段落检查数据是否存在
                if is_optional:
                    if not _has_section_data(section_id, analysis_result):
                        logger.info(f"Skipping optional section: {section_id}")
                        continue

                paragraph_text = _generate_facts_paragraph(
                    section_id, section["prompt"], analysis_result,
                    case.case_type, case.is_minor,
                )
                if paragraph_text:
                    analysis_result[section_id] = paragraph_text
                    logger.info(f"Generated section: {section_id} ({len(paragraph_text)} chars)")

            # ── Step 3: 固定结尾段 ──
            analysis_result["conclusion_text"] = _generate_conclusion(
                analysis_result, case.case_type
            )

            # 兼容旧字段
            _populate_legacy_fields(analysis_result)

            # 保存结果
            case.analysis_result = analysis_result
            case.validation_result = {"items": validation_result}
            case.missing_items = {"items": missing_items}

            await db.commit()

            logger.info(
                f"Analysis completed for case {case_id}: "
                f"{len(analysis_result)} fields extracted, "
                f"paragraphs: {[k for k in analysis_result if k.startswith('paragraph_')]}",
            )
            return {
                "analysis_result": analysis_result,
                "validation_result": {"items": validation_result},
                "missing_items": {"items": missing_items},
            }

    return run_in_worker(_do_analyze())


# ═══════════════════════════════════════════════════════════════════════════════
# 文件名关系提取
# ═══════════════════════════════════════════════════════════════════════════════

# 文件名中常见的关系标注格式：
#   "张三（父亲）正面.jpg"   → name=张三, relationship=父亲
#   "李四-配偶-反面.jpg"     → name=李四, relationship=配偶
#   "王五_本人_正面.png"     → name=王五, relationship=本人
#   "赵六（患者母亲）.jpg"   → name=赵六, relationship=母亲
#   "钱七-死者配偶-正面.pdf" → name=钱七, relationship=配偶
_FILENAME_REL_PATTERN = re.compile(
    r"([^\s（）\(\)\-_.]+)"        # name: 非空白非分隔符
    r"\s*[（(]\s*"                  # 左括号
    r"(?:患者|死者|伤者|患儿)?"     # 可选前缀
    r"([^\s）)]+?)"                 # relationship content
    r"\s*[）)]"                     # 右括号
    r"|"
    r"([^\s（）\(\)\-_.]+)"         # name (alt)
    r"\s*[-_]\s*"                   # 分隔符 - 或 _
    r"(?:患者|死者|伤者|患儿)?"     # 可选前缀
    r"([^\-_.]+?)"                  # relationship (alt)
    r"\s*[-_]\s*"                   # 后续分隔符
)

# 更简洁的关系标注正则：括号标注
_PAREN_REL_PATTERN = re.compile(
    r"([^\s（）\(\)\-_.]+)"         # 姓名
    r"\s*[（(]\s*"                   # 左括号
    r"(?:患者|死者|伤者|患儿)?"      # 可选前缀
    r"([\u4e00-\u9fff]+?)"           # 纯中文关系词
    r"\s*[）)]"                      # 右括号
)

# 连字符标注
_DASH_REL_PATTERN = re.compile(
    r"([^\s（）\(\)\-_.]+)"         # 姓名
    r"\s*[-_]\s*"                    # 分隔符
    r"(?:患者|死者|伤者|患儿)?"      # 可选前缀
    r"([\u4e00-\u9fff]+?)"           # 纯中文关系词
    r"\s*[-_]\s*"                    # 后续分隔
)

# 有效的关系词（用于验证提取结果）
_VALID_RELATIONSHIPS = {
    "本人", "配偶", "父亲", "母亲", "儿子", "女儿",
    "祖父", "祖母", "外祖父", "外祖母",
    "兄弟", "姐妹", "哥哥", "姐姐", "弟弟", "妹妹",
    "伯父", "叔父", "舅舅", "阿姨", "姑姑",
    "养父", "养母", "继父", "继母",
    "岳父", "岳母", "公公", "婆婆",
}


def _extract_filename_relationships(materials: list) -> dict[str, str]:
    """从素材文件名中提取 {姓名: 关系} 映射
    
    支持的文件名格式:
      - "张三（父亲）正面.jpg"
      - "李四-配偶-反面.jpg"  
      - "王五_本人_正面.png"
      - "赵六（患者母亲）.jpg"
    
    Returns:
        dict: {人名: 关系}，如 {"张三": "父亲", "李四": "配偶"}
    """
    name_to_rel: dict[str, str] = {}
    
    for mat in materials:
        filename = mat.original_filename or ""
        if not filename:
            continue
        
        # 去掉扩展名
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        
        # 尝试括号标注: "张三（父亲）正面" → 张三, 父亲
        m = _PAREN_REL_PATTERN.search(stem)
        if m:
            name, rel = m.group(1), m.group(2)
            if rel in _VALID_RELATIONSHIPS or len(rel) <= 4:
                name_to_rel[name] = rel
                logger.debug(f"文件名关系提取（括号）: {name} → {rel} (from {filename})")
                continue
        
        # 尝试连字符标注: "李四-配偶-反面" → 李四, 配偶
        m = _DASH_REL_PATTERN.search(stem)
        if m:
            name, rel = m.group(1), m.group(2)
            if rel in _VALID_RELATIONSHIPS or len(rel) <= 4:
                name_to_rel[name] = rel
                logger.debug(f"文件名关系提取（连字符）: {name} → {rel} (from {filename})")
                continue
    
    if name_to_rel:
        logger.info(f"文件名关系提取结果: {name_to_rel}")
    return name_to_rel


def _extract_patient_names_from_materials(materials: list) -> set[str]:
    """从病历/鉴定材料中提取患者姓名集合
    
    用于交叉比对：如果某个身份证的人名出现在病历患者位置，则该人为患者本人。
    
    Returns:
        set of patient names found in medical/appraisal materials
    """
    patient_names: set[str] = set()
    
    _PATIENT_PATTERNS = [
        re.compile(r"患\s*者[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
        re.compile(r"被鉴定人[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
        re.compile(r"病人[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
        re.compile(r"死\s*者[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
        re.compile(r"伤\s*者[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
        re.compile(r"患儿[：:\s]*([^\s，。、,于因经的\d]{2,4})"),
    ]
    
    for mat in materials:
        cat = mat.effective_category or ""
        # 只从病历/鉴定类材料中提取患者名
        if cat not in ("medical_record", "appraisal", "death_certificate", "identity"):
            continue
        
        ocr_text = mat.ocr_text or ""
        for pattern in _PATIENT_PATTERNS:
            for m in pattern.finditer(ocr_text):
                name = m.group(1).strip()
                # 过滤太长/太短的，以及非姓名字符
                if 2 <= len(name) <= 4 and re.match(r"^[\u4e00-\u9fff]+$", name):
                    patient_names.add(name)
    
    return patient_names


# ═══════════════════════════════════════════════════════════════════════════════
# 结构化上下文构建（保留原有逻辑）
# ═══════════════════════════════════════════════════════════════════════════════

def _append_layer_lines(lines: list, extracted: dict) -> None:
    """将四层结构化数据追加到行列表"""
    # Layer 1: 证据名称
    layer1 = extracted.get("layer_1_evidence_name", {}) or {}
    if layer1:
        lines.append("**证据名称**:")
        if layer1.get("title"):
            lines.append(f"  - 标题: {layer1['title']}")
        if layer1.get("doc_type"):
            lines.append(f"  - 类型: {layer1['doc_type']}")
        if layer1.get("date"):
            lines.append(f"  - 日期: {layer1['date']}")

    # Layer 2: 身份信息
    layer2 = extracted.get("layer_2_identity", {}) or {}
    if layer2:
        lines.append("**身份信息**:")
        for key, label in [
            ("patient_name", "患者姓名"), ("patient_id", "身份证号"),
            ("patient_gender", "性别"), ("patient_birth", "出生日期"),
            ("patient_address", "住址"), ("patient_phone", "电话"),
            ("hospital_name", "医院名称"), ("hospital_code", "统一社会信用代码"),
            ("hospital_address", "医院地址"), ("legal_representative", "法定代表人"),
            ("relationship", "与患者关系"),
        ]:
            val = layer2.get(key)
            if val and val != "":
                lines.append(f"  - {label}: {val}")

    # Layer 3: 诊疗经过
    layer3 = extracted.get("layer_3_treatment", {}) or {}
    if layer3:
        lines.append("**诊疗经过**:")
        for key, label in [
            ("admission_date", "入院日期"), ("discharge_date", "出院日期"),
            ("diagnosis", "诊断结论"), ("symptoms", "主诉/症状"),
            ("treatment_summary", "诊疗经过"), ("operation_records", "手术记录"),
        ]:
            val = layer3.get(key)
            if val and val != "":
                lines.append(f"  - {label}: {val}")

    # Layer 4: 费用明细
    layer4 = extracted.get("layer_4_fees", {}) or {}
    if layer4:
        lines.append("**费用明细**:")
        items = layer4.get("items", []) or []
        for item in items:
            fee_type = item.get("fee_type", "")
            amount = item.get("amount", 0)
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0.0
            if fee_type:
                lines.append(f"  - {fee_type}: {amount:.2f}元")
        ta = layer4.get("total_amount", 0)
        try:
            ta = float(ta)
        except (ValueError, TypeError):
            ta = 0.0
        if ta:
            lines.append(f"  - 合计: {ta:.2f}元")


def _build_structured_context(materials: list) -> str:
    """从材料的 OCR 文本 + 四层结构化数据构建供LLM分析的结构化上下文
    
    核心改进：智能上下文切片，按信息密度排序拼接，确保关键信息不被截断。
    
    排序策略：
    1. 每份材料的OCR原文按段落拆分，给每段打重要性标签
    2. 🔴关键段落（含死亡诊断/鉴定意见/手术/尸检/执业证等）优先拼入
    3. 🟡重要段落（含诊断/治疗/检查/出入院等）次之
    4. ⚪一般段落最后
    5. 同一材料内的段落保持原文顺序（仅调整不同优先级间的顺序）
    
    截断上限通过 settings 配置化。
    """
    if not materials:
        return ""

    # ── 从文件名中提取关系标注 ──
    filename_rels = _extract_filename_relationships(materials)
    
    # ── 从病历/鉴定材料中提取患者姓名 ──
    patient_names = _extract_patient_names_from_materials(materials)

    # ── 重要性关键词库 ──
    _CRITICAL_KEYWORDS = re.compile(
        r'死亡诊断|死因分析|死亡原因|鉴定意见|鉴定结论|尸检诊断|解剖诊断|病理诊断|'
        r'尸检报告|手术记录|执业证|执业范围|身份证号|身份证号码|统一社会信用代码|'
        r'执业医师|鉴定人|鉴定机构|死亡诊断意见|出院诊断|死亡证明|'
        r'尸体检验|尸体解剖|死因鉴定|解剖报告|病理鉴定|毒物鉴定|'
        r'居民身份|户口|户籍|户主|身份号码|出生日期|住址|姓名|性别|民族'
    )
    _IMPORTANT_KEYWORDS = re.compile(
        r'诊断|治疗|检查|入院|出院|医嘱|护理|手术|转院|'
        r'主诉|现病史|既往史|用药|处方|病程|抢救|ICU|'
        r'检验|化验|CT|MRI|B超|血气|心电图|体温|血压|'
        r'伤残等级|过错|因果关系|参与度|不良后果|并发症'
    )

    def _classify_paragraph(text: str) -> int:
        """给段落打重要性标签: 0=关键, 1=重要, 2=一般"""
        if _CRITICAL_KEYWORDS.search(text):
            return 0  # 🔴
        if _IMPORTANT_KEYWORDS.search(text):
            return 1  # 🟡
        return 2  # ⚪

    _DETAIL_CATEGORIES = {"appraisal", "medical_record", "death_certificate", "identity_defendant", "identity"}

    # ── 收集所有材料段落（带优先级和来源标记）──
    material_sections: list[tuple[int, str, str]] = []  # (priority, material_id, section_text)

    for idx, mat in enumerate(materials, 1):
        filename = mat.original_filename or ""
        extracted = mat.extracted_data or {}
        ocr_text = (mat.ocr_text or "").strip()
        cat = mat.effective_category or ""
        cat_name = CATEGORY_NAMES.get(cat, cat or "未分类")
        max_ocr_chars = (
            settings.llm_context_material_detail_limit
            if cat in _DETAIL_CATEGORIES
            else settings.llm_context_material_normal_limit
        )

        # ── 四层结构化提取摘要 ──
        layers_brief = []
        for layer_key, label in [
            ("layer_1_evidence_name", "证据名"),
            ("layer_2_identity", "身份"),
            ("layer_3_treatment", "诊疗"),
            ("layer_4_fees", "费用"),
        ]:
            layer_data = extracted.get(layer_key)
            if layer_data and isinstance(layer_data, dict) and any(v for v in layer_data.values() if v):
                vals = {k: v for k, v in layer_data.items() if v}
                if vals:
                    layers_brief.append(f"  {label}: {json.dumps(vals, ensure_ascii=False)}")
        
        layer_section = ""
        if layers_brief:
            layer_section = "\n**结构化提取**:\n" + "\n".join(layers_brief)

        # ── 构建文件名附加信息（关系标注）──
        filename_extras = []
        if filename_rels:
            # 尝试从文件名中匹配人名
            for name, rel in filename_rels.items():
                if name in filename:
                    filename_extras.append(f"【文件名标注关系：{name}→{rel}】")
        if filename_extras:
            header = f"### 材料{idx} [{cat_name}] 文件:{filename} {' '.join(filename_extras)}"
        else:
            header = f"### 材料{idx} [{cat_name}] 文件:{filename}"

        if not ocr_text:
            # 无 OCR 文本但有结构化数据的，按重要程度处理
            if extracted and any(
                extracted.get(layer)
                for layer in ["layer_1_evidence_name", "layer_2_identity", "layer_3_treatment", "layer_4_fees"]
            ):
                # 构建结构化输出
                lines = [header]
                lines.append(f"**类别**: {cat_name}")
                _append_layer_lines(lines, extracted)
                # 结构化数据通常包含身份/诊疗信息，视为重要
                material_sections.append((1, f"mat{idx}", "\n".join(lines)))
            continue

        # ── 有 OCR 文本：智能切片排序 ──
        # 关键改进：先从全文中提取关键段落（避免被材料级截断丢失），再截取剩余内容
        
        # Step 1: 从整个OCR原文中按段落拆分
        full_paragraphs = re.split(r'\n{2,}|\n(?=[　\s]*[\u4e00-\u9fff①-⑩\d])', ocr_text)
        full_paragraphs = [p.strip() for p in full_paragraphs if p.strip() and len(p.strip()) > 5]
        
        if not full_paragraphs:
            full_paragraphs = [ocr_text[:max_ocr_chars]]

        # Step 2: 分类所有段落
        priority_groups: dict[int, list[str]] = {0: [], 1: [], 2: []}
        for para in full_paragraphs:
            priority = _classify_paragraph(para)
            priority_groups[priority].append(para)

        # Step 3: 按优先级拼接，在 max_ocr_chars 内尽量保留关键内容
        sorted_parts: list[str] = []
        total_chars = 0
        for priority_level in [0, 1, 2]:
            for para in priority_groups[priority_level]:
                if total_chars + len(para) <= max_ocr_chars:
                    sorted_parts.append(para)
                    total_chars += len(para)
                elif total_chars < max_ocr_chars:
                    # 部分截取
                    remaining = max_ocr_chars - total_chars
                    if remaining > 50:
                        sorted_parts.append(para[:remaining])
                        total_chars += remaining
                    break
                else:
                    break
        
        sorted_text = "\n\n".join(sorted_parts)

        section = f"{header}\n**OCR原文**:\n{sorted_text}{layer_section}"
        
        # 材料本身的优先级由包含的最高优先级段落决定（基于全文，不只是截取后的）
        min_priority = 2
        for para in full_paragraphs:
            p = _classify_paragraph(para)
            if p < min_priority:
                min_priority = p
                if p == 0:
                    break

        material_sections.append((min_priority, f"mat{idx}", section))

    # ── 按材料优先级排序（关键材料在前）──
    material_sections.sort(key=lambda x: (x[0], x[1]))

    return "\n\n".join(section for _, _, section in material_sections)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: 结构化数据提取（多原告 + 5大类）
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_document_slots(text: str, case_type: str, is_minor: bool, materials: list = None) -> dict[str, Any]:
    """从结构化上下文中提取文档生成所需的所有结构化数据

    支持多原告、入院/诊疗/转院/鉴定/人员5大类
    """
    client = _get_analyzer_client()

    max_chars = settings.llm_context_merged_limit
    truncated_text = text[:max_chars]
    if len(text) > max_chars:
        truncated_text += "\n...(内容过长已截断)"

    case_type_desc = (
        "人身损害（伤残）" if case_type == "injury"
        else "死亡"
    )
    minor_desc = "（未成年人）" if is_minor else ""

    # ── 根据案件类型定制提取说明 ──
    if case_type == "death":
        case_specific_note = (
            "【死亡案件特别注意】\n"
            "1. 患者已死亡，需要从死亡证明/尸检报告/病历中提取完整死亡诊断\n"
            "2. 死亡诊断必须从住院病历或尸检报告/司法鉴定意见书中提取完整编号列举式诊断\n"
            "3. 不要使用死亡证明书上的简略'死亡原因'，那不是完整的死亡诊断\n"
            "4. adverse_outcome应包含死亡经过及具体时间\n"
        )
        appraisal_note = "cause_of_death(死因), fault_degree"
        death_section = (
            "\n### 九、死亡信息（仅死亡案件）\n"
            "- death_date: 死亡日期\n"
            "- death_diagnosis: 完整死亡诊断（重要：必须从住院病历或尸检报告/司法鉴定意见书中提取完整的'死亡诊断'，"
            "通常是编号列举的多项诊断，如\u2460重度肺动脉高压；\u2461急性右心衰竭；\u2462...格式。"
            "不要使用死亡证明书上的简略'死亡原因'，死亡证明书只有简略死因，不是完整的死亡诊断。必须完整列出所有项，不要遗漏。）\n"
        )
    else:  # injury
        case_specific_note = (
            "【伤残案件特别注意】\n"
            "1. 患者存活，需要从病历中提取入院至今的完整诊疗过程\n"
            "2. 关注损害发生的时间节点和具体经过\n"
            "3. adverse_outcome应描述伤残损害后果\n"
            "4. 如患者截至起诉之日仍在住院，需在admission_condition中注明\n"
        )
        appraisal_note = "disability_level(伤残等级)"
        death_section = ""

    # ── 构建文件名关系提示（如有）──
    filename_rels = _extract_filename_relationships(materials) if materials else {}
    filename_rel_hint = ""
    if filename_rels:
        rel_items = "、".join(f"{name}是{rel}" for name, rel in filename_rels.items())
        filename_rel_hint = (
            f"\n**【文件名标注的关系信息（最高优先级，必须遵守）】**：\n"
            f"根据上传素材的文件名标注，已知：{rel_items}。\n"
            f"请严格按照文件名标注的关系填写每个原告的relationship字段，不得修改。\n"
        )
    
    # ── 构建患者姓名提示 ──
    patient_names = _extract_patient_names_from_materials(materials) if materials else set()
    patient_name_hint = ""
    if patient_names:
        names_str = "、".join(patient_names)
        patient_name_hint = (
            f"\n**【患者姓名识别线索】**：\n"
            f"从病历/鉴定材料中识别到以下患者姓名：{names_str}\n"
            f"如果某位身份证持有人的姓名与患者姓名一致，则其relationship应为\"本人\"，"
            f"is_patient应为true。\n"
        )

    prompt = f"""你是一个医疗损害案件法律文书信息提取助手。请从以下证据材料的OCR原文中提取结构化数据。

## 案件信息
- 案件类型：{case_type_desc}{minor_desc}

## 提取要求
请严格按照以下结构提取，返回 JSON。无法识别的字段填 null。

**关键说明**：
1. 身份证正反面OCR文本可能分散在不同材料中，需要将同一人的正反面信息合并
2. 文件名通常包含姓名和正反面标识（如"赵光远正面.jpg"、"马嘉尉反面.jpg"）
3. 原告数量必须严格等于素材中不同身份证正反面的套数。只有提供了完整身份证正反面素材的人才能作为原告，绝不能从病历中的姓名推测为原告
4. 从身份证OCR原文中提取：姓名、性别、民族、出生日期、住址、身份证号
5. 从户口本OCR原文中提取：户主关系、亲属关系
6. 从被告信息材料中提取：医院全称（不要省略！）、法定代表人、统一社会信用代码
7. 从病历OCR原文中提取：入院日期、主诉、诊断、检查、治疗经过
8. 从鉴定报告OCR原文中提取：鉴定机构、鉴定日期、报告编号、鉴定意见
9. **身份证号必须是18位，前17位纯数字，末位数字或X**，不允许带空格或其他字母
10. **同一人正反面OCR姓名必须一致**，如果发现不一致则标记 name_conflict: true
11. **被告医院名称必须提取完整全称**，不得省略"市/州/县/区"等行政区划词
12. **如有多家医院出现**，需区分哪一家是被诉医院（被告），哪些是转院/首诊/会诊医院
{filename_rel_hint}{patient_name_hint}
**【relationship推断规则】（按优先级从高到低）**：
1. **文件名标注**：如果材料文件名中包含关系标注（如"张三（父亲）正面.jpg"），则直接使用标注的关系
2. **病历/鉴定交叉比对**：如果某人的姓名出现在病历的"患者"/"被鉴定人"位置，则该人relationship="本人"，is_patient=true
3. **户口本关系**：如果有户口本素材，使用"与户主关系"字段推断
4. **无法确定时填null**：如果没有足够的证据确定关系，relationship填null，不要猜测

{case_specific_note}

### 一、原告信息（数组，支持多个原告）
从身份证OCR原文中提取所有原告（每个人正反面信息合并为一条）:
- plaintiffs: 数组，每个元素包含:
  - name: 姓名（从OCR中提取的完整姓名）
  - relationship: 与患者关系（本人/父亲/母亲/配偶/儿子/女儿等，推断规则见上方）
  - is_patient: 是否为患者本人（true/false，必须与relationship一致：relationship="本人"时is_patient=true）
  - gender: 性别（男/女）
  - ethnicity: 民族（如：汉族）
  - birth_date: 出生日期（如：1957年3月10日）
  - address: 住址（完整地址）
  - id_number: 身份证号码（18位）
  - phone: 联系电话（如有）

### 二、患者信息
- patient_name: 患者姓名
- patient_gender: 患者性别
- patient_age: 患者年龄

### 三、被告信息
- defendant_name: 被告医院全称（必须完整，不得省略行政区划词如"市""县""区"）
- legal_representative: 法定代表人姓名
- credit_code: 统一社会信用代码
- defendant_address: 医院地址
- defendant_phone: 医院电话

### 三-B、其他医院（可选，当存在多家医院时）
- other_hospitals: 数组，每项包含：
  - name: 医院全称
  - role: 与本案关系（"首诊医院"/"转入医院"/"会诊医院"/"其他"）
  - visit_date: 就诊日期（如有）

### 四、入院信息（用于第1段事实与理由）
- admission_reason: 入院原因/主诉
- admission_condition: 入院时基本情况（生命体征、症状描述）
- preliminary_diagnosis: 初步诊断
- admission_date: 入院日期

### 五、诊疗经过（用于第2段事实与理由）
- key_examinations: 关键检查（如CT、MRI、心脏彩超、血气分析等）
- key_treatments: 关键治疗（手术、ICU转入、药物治疗等）
- adverse_outcome: 不良后果（并发症、死亡等）
- key_dates: 关键日期节点列表

### 六、转院信息（可选）
- has_transfer: true/false
- transfer_details: {{ transfer_date, transfer_to, new_examinations, new_treatments, discharge_condition, discharge_diagnosis }}

### 七、鉴定信息（可选）
- has_appraisal: true/false
- appraisal_details: {{ appraisal_org, appraisal_org_full_name, appraisal_date, report_no, {appraisal_note}, causation, appraisal_conclusion_original, appraiser_names, appraiser_license_nos }}
  - appraisal_org_full_name: 鉴定机构完整全称（不得简写）
  - appraisal_conclusion_original: 鉴定意见原文（逐字复制，不得改写或概括）
  - appraiser_names: 鉴定人姓名列表（数组）
  - appraiser_license_nos: 鉴定人执业证号列表（数组）

### 八、医务人员资质（可选）
- has_staff_issue: true/false
- staff_details: {{
    staff_name: 涉事医务人员姓名,
    staff_department: 科室,
    staff_license_no: 执业证号,
    staff_scope: 注册执业范围,
    issue_type: 资质问题类型（无证执业/超范围执业/注册过期/未注册/其他）,
    issue_description: 过错描述,
    actual_operation: 实际施行操作（与执业范围对比）
  }}
{death_section}
### 十、结案信息
- court_name: 受理法院名称
- complaint_signer: 具状人签名（多位原告用"、"分隔）
- complaint_year: 起诉年份

## 证据材料（四层结构）
{truncated_text}

请返回JSON格式，只返回JSON，不要额外说明。"""

    try:
        # 根据当前客户端选择合适的模型名
        deepseek_key = settings.deepseek_api_key_plain
        text_model = settings.deepseek_text_model if deepseek_key else settings.bailian_text_model

        response = client.chat.completions.create(
            model=text_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"你是一个专业的{case_type_desc}案件法律文书信息提取助手。"
                        "你必须从OCR原文中仔细提取所有信息，不要遗漏。"
                        "特别注意：\n"
                        "1. 身份证OCR原文中包含姓名、性别、民族、出生、住址、身份证号，必须完整提取\n"
                        "2. 文件名中包含人名和正反面标识，用来关联同一人的正反面信息\n"
                        "2b. **文件名中如果包含关系标注（如\"张三（父亲）\"、\"李四-配偶-\"），必须直接使用该关系作为relationship**\n"
                        "3. 被告医院的完整名称必须完整提取，不能简写为'医院'\n"
                        "4. 病历材料中的入院日期、主诉、诊断必须准确提取\n"
                        "5. 原告数量必须严格等于素材中不同身份证正反面的人数，不要推测或编造没有身份证素材的原告\n"
                        "5b. **如果某人的姓名出现在病历的患者/被鉴定人位置，则其relationship='本人'、is_patient=true**\n"
                        + (
                            "6. 死亡诊断必须从住院病历或尸检报告/司法鉴定意见书中提取完整的编号列举式死亡诊断，"
                            "不要从死亡证明书上提取简略死因\n"
                            if case_type == "death" else
                            ""
                        )
                        + "严格按照要求的JSON结构返回，只输出JSON，不添加任何解释。"
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
            parsed = json.loads(json_match.group())
            # LLM 可能返回 null 值（如 "appraisal_details": null），
            # 但 dict.get(key, default) 在键存在值=null 时返回 None 而非 default，
            # 导致后续 .get() 调用崩溃。这里清理掉 null 值以防御。
            if isinstance(parsed, dict):
                _clean_nulls(parsed)
            return parsed
        else:
            logger.warning(f"LLM did not return valid JSON for analysis: {raw[:200]}")
            return {"raw_response": raw}
    except Exception as e:
        logger.error(f"LLM analysis extraction failed: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: 段落生成
# ═══════════════════════════════════════════════════════════════════════════════

def _has_section_data(section_id: str, data: dict) -> bool:
    """检查可选段落是否有数据支撑"""
    if section_id == "paragraph_3":
        return bool(data.get("has_transfer"))
    elif section_id == "paragraph_4":
        return bool(data.get("has_appraisal"))
    elif section_id == "paragraph_5":
        return bool(data.get("has_staff_issue"))
    return True


def _generate_facts_paragraph(
    section_id: str,
    section_prompt: str,
    extracted_data: dict,
    case_type: str,
    is_minor: bool,
) -> str:
    """根据段落类型和提取数据，调用 LLM 生成段落法律文本"""
    client = _get_flash_client()

    # 构建上下文：将相关的提取数据传入
    context_parts = []

    # 原告信息
    plaintiffs = extracted_data.get("plaintiffs", []) or []
    if plaintiffs:
        context_parts.append("【原告信息】")
        for i, p in enumerate(plaintiffs, 1):
            if not p or not isinstance(p, dict):
                continue  # 跳过 LLM 返回的 null 元素
            is_patient_tag = "（患者本人）" if p.get("is_patient") else ""
            context_parts.append(
                f"  原告{i}：{p.get('name', '')}{is_patient_tag}，"
                f"与患者关系：{p.get('relationship', '未知')}，"
                f"{p.get('gender', '')}，{p.get('ethnicity', '')}，"
                f"{p.get('birth_date', '')}出生，住{p.get('address', '')}，"
                f"身份证号{p.get('id_number', '')}"
            )

    # 患者信息
    patient = {
        "name": extracted_data.get("patient_name", ""),
        "gender": extracted_data.get("patient_gender", ""),
        "age": extracted_data.get("patient_age", ""),
    }
    if patient["name"]:
        context_parts.append(f"【患者信息】{patient['name']}，{patient['gender']}，{patient['age']}岁")

    # 被告信息
    defendant = {
        "name": extracted_data.get("defendant_name", ""),
        "legal_rep": extracted_data.get("legal_representative", ""),
        "address": extracted_data.get("defendant_address", ""),
    }
    if defendant["name"]:
        context_parts.append(f"【被告信息】{defendant['name']}，法定代表人：{defendant['legal_rep']}，地址：{defendant['address']}")

    # 根据段落类型添加特定数据
    if section_id == "paragraph_1":
        admission = {
            "reason": extracted_data.get("admission_reason", ""),
            "condition": extracted_data.get("admission_condition", ""),
            "diagnosis": extracted_data.get("preliminary_diagnosis", ""),
            "date": extracted_data.get("admission_date", ""),
        }
        context_parts.append(f"【入院信息】入院日期：{admission['date']}，入院原因：{admission['reason']}，基本情况：{admission['condition']}，初步诊断：{admission['diagnosis']}")

    elif section_id == "paragraph_2":
        treatment = {
            "examinations": extracted_data.get("key_examinations", ""),
            "treatments": extracted_data.get("key_treatments", ""),
            "outcome": extracted_data.get("adverse_outcome", ""),
            "dates": extracted_data.get("key_dates", ""),
        }
        context_parts.append(f"【诊疗经过】关键检查：{treatment['examinations']}，关键治疗：{treatment['treatments']}，不良后果：{treatment['outcome']}，关键日期：{treatment['dates']}")
        # 死亡案件加死亡信息
        death_date = extracted_data.get("death_date", "")
        death_diag = extracted_data.get("death_diagnosis", "")
        if death_date:
            context_parts.append(f"【死亡信息】死亡日期：{death_date}，死亡诊断：{death_diag}")
        # 鉴定结论原文注入（帮助段落2正确描述鉴定结果，尤其是尸检/死因鉴定）
        appraisal = extracted_data.get("appraisal_details") or {}
        conclusion_original = appraisal.get("appraisal_conclusion_original", "")
        if conclusion_original:
            context_parts.append(f"【鉴定结论原文（请逐字引用，不要改写）】{conclusion_original}")
        # 其他医院信息
        other_hospitals = extracted_data.get("other_hospitals") or []
        if other_hospitals:
            hospitals_text = "；".join(
                f"{h.get('name', '')}（{h.get('role', '其他')}）" for h in other_hospitals
            )
            context_parts.append(f"【其他就诊医院】{hospitals_text}")

    elif section_id == "paragraph_3":
        transfer = extracted_data.get("transfer_details") or {}
        if transfer:
            context_parts.append(f"【转院信息】{json.dumps(transfer, ensure_ascii=False)}")

    elif section_id == "paragraph_4":
        appraisal = extracted_data.get("appraisal_details") or {}
        if appraisal:
            context_parts.append(f"【鉴定信息】{json.dumps(appraisal, ensure_ascii=False)}")

    elif section_id == "paragraph_5":
        staff = extracted_data.get("staff_details") or {}
        if staff:
            context_parts.append(f"【医务人员资质】{json.dumps(staff, ensure_ascii=False)}")

    context = "\n".join(context_parts)

    case_type_desc = "死亡" if case_type == "death" else "伤残"
    minor_note = "（注意：患者为未成年人）" if is_minor else ""

    try:
        # 选择模型：DeepSeek → GLM → 百炼
        deepseek_key = settings.deepseek_api_key_plain
        if deepseek_key:
            model_name = settings.deepseek_flash_model
        elif glm_key:
            model_name = settings.glm_model
        else:
            model_name = settings.bailian_flash_model
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位专业的医疗纠纷律师，擅长撰写民事起诉状。"
                        "请严格按照指令撰写，使用正式的法律文书语言。"
                        "语气客观、正式，用词准确，避免主观推测和情绪化表达。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"{section_prompt}\n\n案件类型：{case_type_desc}{minor_note}\n\n参考信息：\n{context}",
                },
            ],
            temperature=0.3,
            timeout=settings.bailian_text_timeout,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Paragraph generation failed for {section_id}: {e}")
        return f"[段落生成失败: {section_id} — {e}]"


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: 固定结尾段
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_conclusion(extracted_data: dict, case_type: str) -> str:
    """生成固定的结尾段：综上所述..."""
    # 尝试从新的结构化数据获取
    defendant_name = extracted_data.get("defendant_name", "")
    patient_name = extracted_data.get("patient_name", "")

    # 兼容旧字段
    if not defendant_name:
        defendant_name = extracted_data.get("被告医院全称", "被告")
    if not patient_name:
        patient_name = extracted_data.get("原告姓名1", "")

    if case_type == "death":
        return (
            f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
            f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
            f"并由此造成了患者死亡的严重损害后果，"
            f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
            f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
            f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
        )
    elif case_type == "neonatal":
        # 旧 neonatal 兼容：统一走 injury 路径
        return (
            f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
            f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
            f"并由此造成了患者伤残的严重损害后果，"
            f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
            f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
            f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
        )
    else:  # injury
        return (
            f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
            f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
            f"并由此造成了患者伤残的严重损害后果，"
            f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
            f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
            f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 向后兼容：填充旧字段
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_legacy_fields(analysis_result: dict) -> None:
    """将新的结构化数据映射到旧字段，确保旧代码兼容"""
    plaintiffs = analysis_result.get("plaintiffs", []) or []
    if plaintiffs:
        # 过滤掉 None 元素（LLM 可能返回 [null, {...}]）
        valid_plaintiffs = [p for p in plaintiffs if isinstance(p, dict)]
        if valid_plaintiffs:
            p1 = valid_plaintiffs[0]
            analysis_result.setdefault("原告姓名1", p1.get("name", ""))
            analysis_result.setdefault("性别1", p1.get("gender", ""))
            analysis_result.setdefault("民族1", p1.get("ethnicity", ""))
            analysis_result.setdefault("出生年月日1", p1.get("birth_date", ""))
            analysis_result.setdefault("住址1", p1.get("address", ""))
            analysis_result.setdefault("身份证号1", p1.get("id_number", ""))
            analysis_result.setdefault("亲属关系1", p1.get("relationship", ""))
            analysis_result.setdefault("律师电话1", p1.get("phone", ""))
            analysis_result.setdefault("plaintiff_name", p1.get("name", ""))
            analysis_result.setdefault("is_patient1", p1.get("is_patient", False))

            # 多原告: 额外存储 原告姓名2, 原告姓名3...
            for i, p in enumerate(valid_plaintiffs[1:], 2):
                analysis_result[f"原告姓名{i}"] = p.get("name", "")
                analysis_result[f"性别{i}"] = p.get("gender", "")
                analysis_result[f"民族{i}"] = p.get("ethnicity", "")
                analysis_result[f"出生年月日{i}"] = p.get("birth_date", "")
                analysis_result[f"住址{i}"] = p.get("address", "")
                analysis_result[f"身份证号{i}"] = p.get("id_number", "")
                analysis_result[f"亲属关系{i}"] = p.get("relationship", "")
                analysis_result[f"律师电话{i}"] = p.get("phone", "")
                analysis_result[f"is_patient{i}"] = p.get("is_patient", False)

    # 被告
    defendant_name = analysis_result.get("defendant_name", "")
    if defendant_name:
        analysis_result.setdefault("被告医院全称", defendant_name)
    if analysis_result.get("legal_representative"):
        analysis_result.setdefault("法定代表人姓名", analysis_result["legal_representative"])
    if analysis_result.get("credit_code"):
        analysis_result.setdefault("统一社会信用代码", analysis_result["credit_code"])
    if analysis_result.get("defendant_address"):
        analysis_result.setdefault("医院地址", analysis_result["defendant_address"])
    if analysis_result.get("defendant_phone"):
        analysis_result.setdefault("医院电话", analysis_result["defendant_phone"])

    # 患者
    if analysis_result.get("patient_name"):
        analysis_result.setdefault("患者姓名", analysis_result["patient_name"])

    # 法院
    if analysis_result.get("court_name"):
        analysis_result.setdefault("受理法院", analysis_result["court_name"])

    # 具状人
    if analysis_result.get("complaint_signer"):
        analysis_result.setdefault("具状人签名", analysis_result["complaint_signer"])
    if analysis_result.get("complaint_year"):
        analysis_result.setdefault("起诉年份", analysis_result["complaint_year"])

    # 拼接事实与理由（兼容：将5段合并为一个字段）
    paragraphs = []
    for key in ["paragraph_1", "paragraph_2", "paragraph_3", "paragraph_4", "paragraph_5"]:
        text = analysis_result.get(key, "")
        if text:
            paragraphs.append(text)
    if analysis_result.get("conclusion_text"):
        paragraphs.append(analysis_result["conclusion_text"])
    if paragraphs:
        analysis_result.setdefault("事实与理由", "\n\n".join(paragraphs))

    # 司法鉴定兼容字段
    appraisal = analysis_result.get("appraisal_details", {})
    if appraisal:
        analysis_result.setdefault("court_name", analysis_result.get("受理法院", ""))
        analysis_result.setdefault("applicant_name", plaintiffs[0].get("name", "") if plaintiffs else "")
        analysis_result.setdefault("respondent_name", defendant_name)


# ═══════════════════════════════════════════════════════════════════════════════
# 定向提取：死亡诊断（直接从OCR原文定位，不依赖LLM）
# ═══════════════════════════════════════════════════════════════════════════════

# 优先从这些类别的OCR文本中查找死亡诊断（按优先级排序）
_DEATH_DIAG_PRIORITY_CATEGORIES = ["appraisal", "medical_record", "death_certificate"]


def _direct_extract_death_diagnosis(materials: list) -> str | None:
    """直接从OCR原文中定向提取'死亡诊断'文本

    策略：
    1. 按类别优先级（鉴定报告 > 病历 > 死亡证明）查找
    2. 在OCR文本中搜索多种诊断标签
    3. 取标签后的编号列举式诊断原文（如 ①xxx；②xxx；③xxx）
    4. 支持段落式、表格式结论
    5. 处理OCR跨页断裂
    """
    import re as _re

    # 按优先级排序材料
    sorted_mats = sorted(
        materials,
        key=lambda m: _DEATH_DIAG_PRIORITY_CATEGORIES.index(m.effective_category)
        if m.effective_category in _DEATH_DIAG_PRIORITY_CATEGORIES
        else 99,
    )

    _CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
    # 匹配中文医学诊断名：含中文、括号、数字、加号等
    _DIAG_CONTENT = r'[\u4e00-\u9fff\uff08\uff09\(\)0-9a-zA-Z+＋\-－%％Ⅰ-ⅢⅣⅤ]'

    # 扩展的诊断标签匹配模式（按优先级排序）
    _DIAG_LABELS = [
        r'死亡诊断意见[：:]\s*',
        r'死亡诊断[：:]\s*',
        r'尸检诊断[：:]\s*',
        r'解剖诊断[：:]\s*',
        r'病理诊断[：:]\s*',
        r'死因分析[：:]\s*',
        r'死亡原因分析[：:]\s*',
        r'死亡原因[：:]\s*',
        r'鉴定意见[：:]\s*',
        r'鉴定结论[：:]\s*',
        r'检验结果[：:]\s*',
    ]

    # 出院诊断关键词（用于兜底提取，仅匹配含"死亡/衰竭"的条目）
    _DISCHARGE_DIAG_LABEL = r'出院诊断[：:]\s*'
    _DEATH_KEYWORDS = re.compile(
        r'死亡|衰竭|濒死|无效|心跳骤停|呼吸骤停|循环衰竭|多器官功能衰竭|肺栓塞'
    )

    for mat in sorted_mats:
        ocr_text = (mat.ocr_text or "").strip()
        cat = mat.effective_category or ""

        # 只在目标类别中查找
        if cat not in _DEATH_DIAG_PRIORITY_CATEGORIES:
            continue

        # 按优先级搜索多种诊断标签
        match = None
        for label_pattern in _DIAG_LABELS:
            match = _re.search(label_pattern, ocr_text)
            if match:
                break
        if not match:
            continue

        start_pos = match.end()
        # 取标签后最多800字符（足够覆盖跨页断裂的场景）
        tail = ocr_text[start_pos:start_pos + 800]

        # ── 策略：逐项提取，遇到页码污染则跳过并尝试恢复 ──

        # 步骤1：提取所有带圈编号项（包括被污染的）
        raw_items = []
        for m in _re.finditer(r'([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])([^①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮\n]+)', tail):
            num_char = m.group(1)
            content = m.group(2).strip().rstrip('；;，,。．.')
            raw_items.append((num_char, content))

        # 步骤2：判断每项是否被页码/页眉污染
        clean_items = []
        last_good_num = 0  # 上一个有效编号的序号
        for num_char, content in raw_items:
            num_idx = _CIRCLED.index(num_char) + 1  # 序号：①=1, ②=2, ...

            # 判断是否被页码污染：内容包含"页"、"号"、"鉴定"等非诊断文字
            is_contaminated = bool(_re.search(
                r'[第]\d+页|病鉴字|法鉴中心|共\d+页|[A-Z]\d{4,}|报告单', content
            ))

            if is_contaminated:
                # 污染项：直接跳过，不尝试提取前缀（前缀常为机构名等非诊断文字）
                # 真正的诊断内容会在步骤3中从页码后的残留文本恢复
                continue

            # 非污染项：检查是否序号连续
            # 如果序号跳跃（如⑦后跳到①），说明进入了不同段落（如心电图报告），停止
            if num_idx <= last_good_num and last_good_num >= 2:
                break

            clean_items.append(f"{num_char}{content}")
            last_good_num = num_idx

        # 步骤3：如果最后一个有效编号后有跨页残留的诊断文本，尝试恢复
        # 典型模式：⑧被页码截断，页码后出现"凝血功能障碍。"但无编号
        if clean_items and last_good_num > 0:
            # 在tail中找到最后一个有效编号项之后、到下一个大段落（如"四、"）之间的文本
            last_item_text = clean_items[-1]
            last_pos = tail.find(last_item_text) + len(last_item_text)
            remainder = tail[last_pos:last_pos + 300]

            # 去除OCR JSON碎片（```json ... ```）
            remainder = _re.sub(r'```json.*?```', '', remainder, flags=_re.DOTALL)
            # 去除页码行
            remainder = _re.sub(r'第\d+页共\d+页', '', remainder)
            # 去除带圈编号（这些可能是其他段落的，如心电图报告）
            remainder_after_break = remainder

            # 在残留文本中查找无编号的中文诊断短语（2-10字，句号结尾）
            orphan_diags = _re.findall(
                r'([\u4e00-\u9fff]{2,15})[。．\.]', remainder_after_break
            )
            for diag in orphan_diags:
                # 过滤：必须是医学诊断用语，不是通用词
                if _re.search(r'功能|不全|衰竭|障碍|积液|高压|休克|骤停|感染|酸中毒|疾病', diag):
                    next_num = _CIRCLED[last_good_num] if last_good_num < len(_CIRCLED) else ''
                    if next_num:
                        clean_items.append(f"{next_num}{diag}")
                        last_good_num += 1

        if clean_items:
            result = '；'.join(clean_items)
            logger.info(
                f"Direct extracted death_diagnosis from '{mat.original_filename}' "
                f"({cat}): {len(clean_items)} items: {result[:100]}"
            )
            return result

        # 尝试数字编号格式：1.xxx；2.xxx；3.xxx
        num_items = []
        for m in _re.finditer(r'(\d{1,2})[.、．]\s*([^\n；;1-9]+)', tail):
            num = int(m.group(1))
            content = m.group(2).strip().rstrip('；;，,。．.')
            if num > 15:  # 不太可能是诊断编号
                continue
            if _re.search(r'[第]\d+页|病鉴字|法鉴中心|共\d+页|[A-Z]\d{4,}|报告单', content):
                continue
            num_items.append((num, content))
        # 按序号排序并检查连续性
        if num_items:
            num_items.sort(key=lambda x: x[0])
            consecutive = True
            for i in range(1, len(num_items)):
                if num_items[i][0] != num_items[i-1][0] + 1:
                    consecutive = False
                    break
            if consecutive and len(num_items) >= 2:
                result = '；'.join(f"{n}.{c}" for n, c in num_items)
                logger.info(
                    f"Direct extracted death_diagnosis from '{mat.original_filename}' "
                    f"({cat}): numbered format, {len(num_items)} items"
                )
                return result

        # 尝试分号/句号分隔的段落式结论
        # 典型模式：多个诊断用分号连接的一段文字
        paragraph_match = _re.search(
            r'((?:(?:[\u4e00-\u9fff()][\u4e00-\u9fff()0-9a-zA-Z+＋\-－%％Ⅰ-ⅢⅣⅤ]{2,30})[；;]\s*){2,8}'
            r'[\u4e00-\u9fff()][\u4e00-\u9fff()0-9a-zA-Z+＋\-－%％Ⅰ-ⅢⅣⅤ]{2,30})[。．\.]?',
            tail,
        )
        if paragraph_match:
            result = paragraph_match.group(1)
            logger.info(
                f"Direct extracted death_diagnosis from '{mat.original_filename}' "
                f"({cat}): paragraph format"
            )
            return result

        # 最后兜底：取标签后到句号/换行的整段文本
        simple_match = _re.search(r'[^。\n]{5,200}[。．\.]?', tail)
        if simple_match:
            result = simple_match.group().rstrip('。．.')
            logger.info(
                f"Direct extracted death_diagnosis from '{mat.original_filename}' "
                f"({cat}): simple format"
            )
            return result

    # ── 兜底策略：从"出院诊断"中提取含"死亡/衰竭"等关键词的条目 ──
    # 当以上所有标签都没找到死亡诊断时，尝试从出院诊断中筛选
    for mat in sorted_mats:
        ocr_text = (mat.ocr_text or "").strip()
        cat = mat.effective_category or ""
        if cat not in ("medical_record", "death_certificate"):
            continue

        match = _re.search(_DISCHARGE_DIAG_LABEL, ocr_text)
        if not match:
            continue

        start_pos = match.end()
        tail = ocr_text[start_pos:start_pos + 600]

        # 提取带圈/数字编号的诊断条目
        death_items = []
        for m in _re.finditer(r'[①②③④⑤⑥⑦⑧⑨⑩]?([\u4e00-\u9fff()][\u4e00-\u9fff()0-9a-zA-Z+＋\-－%％Ⅰ-ⅢⅣⅤ]{2,40})', tail):
            item_text = m.group(1)
            if _DEATH_KEYWORDS.search(item_text):
                death_items.append(item_text)
            # 最多检查 15 项后停止
            if len(death_items) >= 5:
                break

        if death_items:
            result = '；'.join(death_items)
            logger.info(
                f"Direct extracted death_diagnosis from discharge diagnosis in "
                f"'{mat.original_filename}' ({cat}): {len(death_items)} items: {result[:100]}"
            )
            return result

    logger.warning("Death diagnosis not found in any material — will be marked as missing")
    return None


# ──────────────────────────────────────────────────────────────
# Step 1.6: 被告信息定向提取
# ──────────────────────────────────────────────────────────────
_DEFENDANT_PRIORITY_CATEGORIES = [
    "identity_defendant", "fee_receipt", "medical_record",
    "death_certificate", "appraisal",
]


def _direct_extract_defendant_info(materials: list) -> dict | None:
    """直接从OCR原文中定向提取被告医院信息

    策略：
    1. 严格优先从 identity_defendant 类别提取（被告资质/信息材料）
    2. 搜索 法定代表人、统一社会信用代码、地址 等字段
    3. 搜索被告医院全称（含别名，如"中山市小榄人民医院（中山市第五人民医院）"）
    4. 仅补充 LLM 未提取到的字段
    """
    import re as _re

    result = {}

    # ── 辅助函数：按类别优先级排序 ──
    def _cat_sort_key(m):
        try:
            return _DEFENDANT_PRIORITY_CATEGORIES.index(m.effective_category)
        except (ValueError, TypeError):
            return 99

    # ── 1. 提取被告医院全称（严格从 identity_defendant 优先） ──
    hospital_names = []
    for mat in sorted(materials, key=_cat_sort_key):
        ocr_text = (mat.ocr_text or "").strip()
        if not ocr_text:
            continue
        cat = mat.effective_category or ""
        if cat not in _DEFENDANT_PRIORITY_CATEGORIES:
            continue

        # 匹配 "XXX医院（XXX医院）" 或 "XXX医院(XXX医院)" 形式（含别名完整名）
        # 限制：医院名前缀不得含"与/和/及"等连词（排除"马嘉尉与中山市小榄人民医院"）
        alias_match = _re.search(
            r'([\u4e00-\u9fff]{2,10}医院[（(][\u4e00-\u9fff]+医院[）)])',
            ocr_text,
        )
        if alias_match:
            full_name = alias_match.group(1)
            # 过滤前缀含连词的匹配（如"嘉尉与中山市..."）
            prefix = _re.match(r'([\u4e00-\u9fff]+)医院', full_name)
            if prefix and _re.search(r'[与和及]', prefix.group(1)):
                # 尝试截取连词后的部分
                clean = _re.sub(r'^.*[与和及]', '', full_name)
                if '医院' in clean:
                    full_name = clean
            if full_name not in hospital_names:
                hospital_names.append(full_name)

        # 匹配 "被告XXX医院" 形式
        simple_match = _re.search(
            r'被告([\u4e00-\u9fff]{2,10}医院)',
            ocr_text,
        )
        if simple_match:
            name = simple_match.group(1)
            if name not in hospital_names:
                hospital_names.append(name)

    # 去重后选最长的（含别名的完整版优先）
    if hospital_names:
        best_name = max(hospital_names, key=len)
        result["defendant_name"] = best_name

    # ── 2. 从 identity_defendant 类别优先提取法定代表人/信用代码/地址 ──
    # 先只搜 identity_defendant 类别，确保不被鉴定机构等信息污染
    _CONTRACT_KEYWORDS = ("委托", "合同", "甲方", "乙方", "委托方", "受托方", "律所", "律师事务所")
    for mat in sorted(materials, key=_cat_sort_key):
        ocr_text = (mat.ocr_text or "").strip()
        if not ocr_text:
            continue
        cat = mat.effective_category or ""
        # 跳过委托合同类材料（避免把委托方地址误认为医院地址）
        fname = (mat.original_filename or "").lower()
        is_contract = any(kw in fname or kw in ocr_text[:500] for kw in _CONTRACT_KEYWORDS)

        # 法定代表人：只在 identity_defendant 类别中搜索
        if cat == "identity_defendant" and not result.get("legal_representative"):
            # 格式1: "法定代表人：方明" 或 "法定代表人:方明"
            m = _re.search(r'法定代表人[：:]\s*([\u4e00-\u9fff]{2,4})', ocr_text)
            if not m:
                # 格式2: "法定代表人或负责人姓名\n方明"（企业查询页面格式，值在下一行）
                m = _re.search(
                    r'法定代表人[^\n]*\n\s*([\u4e00-\u9fff]{2,4})\s*\n',
                    ocr_text,
                )
            if m:
                result["legal_representative"] = m.group(1)

        # 统一社会信用代码：只在 identity_defendant 类别中搜索
        if cat == "identity_defendant" and not result.get("credit_code"):
            m = _re.search(
                r'统一社会信用代码[：:\s]*([A-Z0-9]{18})',
                ocr_text,
            )
            if m:
                result["credit_code"] = m.group(1)

        # 地址：只在 identity_defendant 类别中搜索（排除委托合同）
        if cat == "identity_defendant" and not is_contract and not result.get("defendant_address"):
            # 格式1: "地址：/住所：XXX省XXX市XXX路XX号"
            m = _re.search(
                r'(?:地址|住所)[：:]\s*([\u4e00-\u9fff]+省[\u4e00-\u9fff]+[\u4e00-\u9fff]*[路段街道][\u4e00-\u9fff]*\d*号?)',
                ocr_text,
            )
            if not m:
                # 格式2: "注册地址\n云南省保山市龙陵县龙山镇热泉路"（值在下一行，可能没有门牌号）
                m = _re.search(
                    r'(?:注册地址|地址|住所)[^\n]*\n\s*([\u4e00-\u9fff]+[\u4e00-\u9fff]*[路段街道][\u4e00-\u9fff]*\d*号?)',
                    ocr_text,
                )
            if m and len(m.group(1)) >= 4:
                result["defendant_address"] = m.group(1)

    if result:
        logger.info(
            f"Direct extracted defendant_info: {result}"
        )
        return result

    return None


# ──────────────────────────────────────────────────────────────
# Step 1.7: 鉴定结论定向提取
# ──────────────────────────────────────────────────────────────

def _direct_extract_appraisal_conclusion(materials: list) -> dict | None:
    """直接从OCR原文中定向提取鉴定结论原文、鉴定人信息

    策略：
    1. 从 appraisal 类别的材料中提取
    2. 搜索鉴定意见/鉴定结论标签
    3. 提取鉴定人姓名和执业证号
    """
    import re as _re

    result = {}

    for mat in materials:
        if (mat.effective_category or "") != "appraisal":
            continue
        ocr_text = (mat.ocr_text or "").strip()
        if not ocr_text:
            continue

        # ── 提取鉴定意见原文 ──
        # 多种标签匹配
        for label in [
            r'鉴定意见[：:]\s*',
            r'鉴定结论[：:]\s*',
            r'分析说明[：:]\s*',
            r'检验结果[：:]\s*',
        ]:
            match = _re.search(label, ocr_text)
            if match:
                # 取标签后最多1200字符
                tail = ocr_text[match.end():match.end() + 1200]
                # 去除页码污染
                tail = _re.sub(r'第\d+页共\d+页', '', tail)
                # 截取到下一个大段落标记（"四、"、"五、" 等）
                section_match = _re.search(r'[四五六七八九十]+、', tail)
                if section_match:
                    tail = tail[:section_match.start()]
                if len(tail.strip()) > 10:
                    result["appraisal_conclusion_original"] = tail.strip()
                    break

        # ── 提取鉴定人姓名和执业证号 ──
        # 常见格式：鉴定人：张三 李四 / 鉴定人：张三（证号XXXX）李四（证号XXXX）
        appraiser_section = _re.search(
            r'(?:鉴定人|司法鉴定人)[：:]\s*(.*?)(?:\n\n|第\d+页|$)',
            ocr_text,
            _re.DOTALL,
        )
        if appraiser_section:
            section_text = appraiser_section.group(1).strip()
            names = []
            license_nos = []
            # 匹配: 张三（证号XXXX）/ 张三(证号XXXX)
            for m in _re.finditer(
                r'([\u4e00-\u9fff]{2,4})[（(]?\s*(?:证号|执业证号|编号)[：:]*\s*([A-Z0-9]+)[）)]?',
                section_text,
            ):
                names.append(m.group(1))
                license_nos.append(m.group(2))
            # 如果没找到带证号的格式，尝试只有姓名
            if not names:
                for m in _re.finditer(r'([\u4e00-\u9fff]{2,4})', section_text):
                    name = m.group(1)
                    if name not in ("鉴定人", "司法", "执业", "证号") and name not in names:
                        names.append(name)

            if names:
                result["appraiser_names"] = names
            if license_nos:
                result["appraiser_license_nos"] = license_nos

        # ── 提取鉴定机构全称 ──
        org_match = _re.search(
            r'([\u4e00-\u9fff]{2,15}(?:司法鉴定中心|司法鉴定所|法医鉴定中心|鉴定中心|鉴定所))',
            ocr_text,
        )
        if org_match:
            result["appraisal_org_full_name"] = org_match.group(1)

        if result:
            logger.info(f"Direct extracted appraisal_conclusion: {list(result.keys())}")
            return result

    return None


# ──────────────────────────────────────────────────────────────
# Step 1.8: 医务人员资质定向提取
# ──────────────────────────────────────────────────────────────

def _direct_extract_staff_qualification(materials: list) -> dict | None:
    """直接从OCR原文中定向提取医务人员资质问题

    策略：
    1. 从 identity_defendant 和 medical_record 类别中搜索
    2. 匹配执业证/资格证/注册信息/超范围执业等
    """
    import re as _re

    result = {}

    for mat in materials:
        cat = mat.effective_category or ""
        if cat not in ("identity_defendant", "medical_record"):
            continue
        ocr_text = (mat.ocr_text or "").strip()
        if not ocr_text:
            continue

        # 搜索医务人员姓名
        staff_names = []
        for m in _re.finditer(
            r'(?:经治医师|主治医师|住院医师|手术医师|麻醉医师|主刀医师|管床医师|接诊医师)[：:]\s*([\u4e00-\u9fff]{2,4})',
            ocr_text,
        ):
            staff_names.append(m.group(1))

        # 搜索执业资质信息
        has_qualification_issue = False
        issue_type = ""
        if _re.search(r'无证执业|未取得.*执业资格|未注册|执业证.*过期|超范围执业', ocr_text):
            has_qualification_issue = True
            if _re.search(r'无证执业|未取得.*执业资格', ocr_text):
                issue_type = "无证执业"
            elif _re.search(r'未注册', ocr_text):
                issue_type = "未注册"
            elif _re.search(r'执业证.*过期', ocr_text):
                issue_type = "注册过期"
            elif _re.search(r'超范围执业', ocr_text):
                issue_type = "超范围执业"

        # 搜索执业证号
        license_nos = []
        for m in _re.finditer(r'执业证号[：:]\s*(\d{10,20})', ocr_text):
            license_nos.append(m.group(1))

        # 搜索执业范围
        scope_match = _re.search(r'执业范围[：:]\s*([\u4e00-\u9fff]{2,20})', ocr_text)

        if staff_names:
            result["staff_name"] = staff_names[0]  # 取第一个涉事人员
        if has_qualification_issue:
            result["issue_type"] = issue_type
            result["has_staff_issue"] = True
        if license_nos:
            result["staff_license_no"] = license_nos[0]
        if scope_match:
            result["staff_scope"] = scope_match.group(1)

        if result:
            logger.info(f"Direct extracted staff_qualification: {result}")
            return result

    return None

def _validate_extracted_data(data: dict, case_type: str) -> dict:
    """校验并修正 LLM 提取结果，记录问题供后续参考"""
    issues = []

    # ── 1. 身份证号格式校验 ──
    for i, plaintiff in enumerate(data.get("plaintiffs", [])):
        id_num = plaintiff.get("id_number", "")
        if id_num and not re.match(r"^\d{17}[\dXx]$", id_num):
            issues.append(f"原告{i+1}身份证号格式错误: {id_num}")
            plaintiff["id_number"] = None  # 清除无效值

        # 身份证姓名一致性
        if plaintiff.get("name_conflict"):
            issues.append(f"原告{i+1}({plaintiff.get('name', '?')})正反面姓名不一致")

    # ── 2. 被告医院名称完整性校验 ──
    defendant_name = data.get("defendant_name", "")
    if defendant_name:
        if len(defendant_name) < 4:
            issues.append(f"被告名称疑似不完整（过短）: {defendant_name}")
        if not any(kw in defendant_name for kw in [
            "医院", "卫生院", "诊所", "保健院", "中心", "医务室", "门诊", "卫生室",
        ]):
            issues.append(f"被告名称缺少医疗机构关键词: {defendant_name}")
    else:
        issues.append("未提取到被告医院名称")

    # ── 3. 电话号码格式校验 ──
    for phone_field in ["defendant_phone", "phone"]:
        phone = data.get(phone_field, "")
        if phone and not re.match(r"^[\d\-+()]{6,15}$", phone):
            issues.append(f"电话号码格式异常: {phone}")

    # ── 4. 日期格式统一化（覆盖所有日期字段） ──
    _DATE_FIELDS = [
        "admission_date", "death_date", "discharge_date",
        "transfer_date", "surgery_date", "icu_admission_date",
    ]
    for date_field in _DATE_FIELDS:
        val = data.get(date_field, "")
        if val:
            normalized = _normalize_date(val)
            if normalized != val:
                data[date_field] = normalized

    # ── 5. 死亡案件必填校验 ──
    if case_type == "death":
        if not data.get("death_date"):
            issues.append("死亡案件缺少死亡日期")
        if not data.get("death_diagnosis"):
            issues.append("死亡案件缺少死亡诊断")

    # ── 6. neonatal 兼容处理 ──
    if case_type == "neonatal":
        # 旧 neonatal 统一按 injury + is_minor 处理
        data["is_minor"] = True

    # ── 7. 关键日期字段标准化（嵌套对象中的日期） ──
    appraisal = data.get("appraisal_details", {})
    if appraisal:
        for key in ["appraisal_date"]:
            val = appraisal.get(key, "")
            if val:
                appraisal[key] = _normalize_date(val)

    # 诊疗时间线中的日期标准化
    for event_key in ["treatment_events", "timeline_events"]:
        events = data.get(event_key, [])
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict):
                    for dkey in ["date", "start_date", "end_date"]:
                        val = event.get(dkey, "")
                        if val:
                            event[dkey] = _normalize_date(val)

    if issues:
        logger.warning(f"Extracted data validation issues: {issues}")
    data["_validation_issues"] = issues
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# 多家医院被告识别
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_defendant_hospital(data: dict, materials: list) -> dict:
    """从提取结果和材料中确定被告医院，解决多家医院混淆问题

    优先级：
    1. identity_defendant 类别的 OCR 文本中提取的医院名 → 最高优先级
    2. 被告营业执照/执业许可证上的机构名
    3. 所有材料中出现频率最高的医院名
    4. 如果仍然无法确定 → 标记为"待确认"
    """
    defendant_name = data.get("defendant_name", "")
    other_hospitals = data.get("other_hospitals") or []

    # 如果已经有被告名称且看起来完整，直接返回
    if defendant_name and len(defendant_name) >= 4 and "医院" in defendant_name:
        return data

    # 尝试从 identity_defendant 材料中直接提取
    direct_result = _direct_extract_defendant_info(materials)
    if direct_result and direct_result.get("defendant_name"):
        if not defendant_name or len(direct_result["defendant_name"]) > len(defendant_name):
            # 直接提取的更完整，替换
            if defendant_name and defendant_name != direct_result["defendant_name"]:
                # 原来的可能不是被告，移到 other_hospitals
                other_hospitals.append({
                    "name": defendant_name,
                    "role": "待确认",
                })
            data["defendant_name"] = direct_result["defendant_name"]
        # 同时补充法定代表人等信息
        for key in ["legal_representative", "credit_code", "defendant_address"]:
            if direct_result.get(key) and not data.get(key):
                data[key] = direct_result[key]

    # 如果还没有被告名称，统计材料中出现频率最高的医院名
    if not data.get("defendant_name"):
        import collections
        hospital_freq = collections.Counter()
        for mat in materials:
            ocr_text = (mat.ocr_text or "")
            for m in re.finditer(r"([\u4e00-\u9fff]{2,8}(?:医院|卫生院|保健院|中心))", ocr_text):
                name = m.group(1)
                # 跳过常见非被告词
                if name in ("被告医院", "原告医院", "诊疗医院"):
                    continue
                hospital_freq[name] += 1

        if hospital_freq:
            best = hospital_freq.most_common(1)[0]
            data["defendant_name"] = best[0]
            logger.info(f"Defendant resolved by frequency: {best[0]} (appeared {best[1]} times)")

    # 验证被告名称完整性
    if data.get("defendant_name") and len(data["defendant_name"]) < 4:
        data["_defendant_name_needs_confirmation"] = True
        logger.warning(f"Defendant name may be incomplete: {data['defendant_name']}")

    # 保存 other_hospitals
    if other_hospitals:
        data["other_hospitals"] = other_hospitals

    return data
