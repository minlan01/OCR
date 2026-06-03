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

_analyzer_client: Optional[OpenAI] = None
_flash_client: Optional[OpenAI] = None
_analyzer_lock = threading.Lock()


def _get_analyzer_client() -> OpenAI:
    """获取文本分析客户端（qwen3.5-plus）"""
    global _analyzer_client
    if _analyzer_client is None:
        with _analyzer_lock:
            if _analyzer_client is None:
                _analyzer_client = OpenAI(
                    api_key=settings.bailian_api_key_plain,
                    base_url=settings.bailian_text_base_url,
                )
    return _analyzer_client


def _get_flash_client() -> OpenAI:
    """获取 flash 客户端（deepseek-v4-flash，用于段落生成）"""
    global _flash_client
    if _flash_client is None:
        with _analyzer_lock:
            if _flash_client is None:
                _flash_client = OpenAI(
                    api_key=settings.bailian_api_key_plain,
                    base_url=settings.bailian_text_base_url,
                )
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
                    structured_context, case.case_type, case.is_minor
                )
            else:
                analysis_result = {}

            # ── Step 1.5: 定向提取死亡诊断（直接从OCR原文定位，不依赖LLM） ──
            if case.case_type == "death":
                direct_dd = _direct_extract_death_diagnosis(materials)
                if direct_dd:
                    analysis_result["death_diagnosis"] = direct_dd

            # ── Step 1.6: 定向提取被告信息（从OCR原文中补充法定代表人/信用代码/地址） ──
            direct_def = _direct_extract_defendant_info(materials)
            if direct_def:
                for k, v in direct_def.items():
                    if v and not analysis_result.get(k):
                        analysis_result[k] = v

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
                "人身损害赔偿" if case.case_type == "injury" else "死亡赔偿"
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
# 结构化上下文构建（保留原有逻辑）
# ═══════════════════════════════════════════════════════════════════════════════

def _build_structured_context(materials: list) -> str:
    """从材料的 OCR 文本 + 四层结构化数据构建供LLM分析的结构化上下文
    
    关键改进：始终传递 OCR 原文，确保 LLM 能提取到身份证等原始信息。
    四层结构化数据作为补充参考。
    鉴定报告和病历材料允许更多OCR原文（最多5000字），其他材料最多2000字。
    """
    if not materials:
        return ""

    parts: list[str] = []

    for idx, mat in enumerate(materials, 1):
        filename = mat.original_filename or ""
        extracted = mat.extracted_data or {}
        ocr_text = (mat.ocr_text or "").strip()
        cat = mat.effective_category or ""
        cat_name = CATEGORY_NAMES.get(cat, cat or "未分类")

        # ── 始终以 OCR 原文为主体（鉴定报告/病历最多 5000 字，其他最多 2000 字） ──
        if ocr_text:
            # 关键类别允许更多OCR原文，避免死亡诊断等关键信息被截断
            _DETAIL_CATEGORIES = {"appraisal", "medical_record", "death_certificate"}
            max_ocr_chars = 5000 if cat in _DETAIL_CATEGORIES else 2000
            header = f"### 材料{idx} [{cat_name}] 文件:{filename}"
            
            # 同时输出四层提取结果（如果有）作为辅助
            layers_brief = []
            for layer_key, label in [
                ("layer_1_evidence_name", "证据名"),
                ("layer_2_identity", "身份"),
                ("layer_3_treatment", "诊疗"),
                ("layer_4_fees", "费用"),
            ]:
                layer_data = extracted.get(layer_key)
                if layer_data and isinstance(layer_data, dict) and any(v for v in layer_data.values() if v):
                    # 只输出有值的字段
                    vals = {k: v for k, v in layer_data.items() if v}
                    if vals:
                        layers_brief.append(f"  {label}: {json.dumps(vals, ensure_ascii=False)}")
            
            layer_section = ""
            if layers_brief:
                layer_section = "\n**结构化提取**:\n" + "\n".join(layers_brief)
            
            parts.append(f"{header}\n**OCR原文**:\n{ocr_text[:max_ocr_chars]}{layer_section}")
            continue

        # 无 OCR 文本，跳过
        if not extracted or not any(
            extracted.get(layer)
            for layer in ["layer_1_evidence_name", "layer_2_identity", "layer_3_treatment", "layer_4_fees"]
        ):
            continue

        # 四层结构化输出
        lines = [f"### 材料{idx}"]
        lines.append(f"**类别**: {CATEGORY_NAMES.get(mat.effective_category or '', '未分类')}")

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
                ("patient_name", "患者姓名"),
                ("patient_id", "身份证号"),
                ("patient_gender", "性别"),
                ("patient_birth", "出生日期"),
                ("patient_address", "住址"),
                ("patient_phone", "电话"),
                ("hospital_name", "医院名称"),
                ("hospital_code", "统一社会信用代码"),
                ("hospital_address", "医院地址"),
                ("legal_representative", "法定代表人"),
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
                ("admission_date", "入院日期"),
                ("discharge_date", "出院日期"),
                ("diagnosis", "诊断结论"),
                ("symptoms", "主诉/症状"),
                ("treatment_summary", "诊疗经过"),
                ("operation_records", "手术记录"),
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

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: 结构化数据提取（多原告 + 5大类）
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_document_slots(text: str, case_type: str, is_minor: bool) -> dict[str, Any]:
    """从结构化上下文中提取文档生成所需的所有结构化数据

    支持多原告、入院/诊疗/转院/鉴定/人员5大类
    """
    client = _get_analyzer_client()

    max_chars = 30000
    truncated_text = text[:max_chars]
    if len(text) > max_chars:
        truncated_text += "\n...(内容过长已截断)"

    case_type_desc = "人身损害（伤残）" if case_type == "injury" else "死亡"
    minor_desc = "（未成年人）" if is_minor else ""

    prompt = f"""你是一个医疗损害案件法律文书信息提取助手。请从以下证据材料的OCR原文中提取结构化数据。

## 案件信息
- 案件类型：{case_type_desc}{minor_desc}

## 提取要求
请严格按照以下结构提取，返回 JSON。无法识别的字段填 null。

**关键说明**：
1. 身份证正反面OCR文本可能分散在不同材料中，需要将同一人的正反面信息合并
2. 文件名通常包含姓名和正反面标识（如"赵光远正面.jpg"、"马嘉尉反面.jpg"）
3. 原告通常包括：患者本人、患者的配偶、父母、子女等近亲属
4. 从身份证OCR原文中提取：姓名、性别、民族、出生日期、住址、身份证号
5. 从户口本OCR原文中提取：户主关系、亲属关系
6. 从被告信息材料中提取：医院全称（不要省略！）、法定代表人、统一社会信用代码
7. 从病历OCR原文中提取：入院日期、主诉、诊断、检查、治疗经过、死亡诊断等
8. 从鉴定报告OCR原文中提取：鉴定机构、鉴定日期、报告编号、鉴定意见

### 一、原告信息（数组，支持多个原告）
从身份证OCR原文中提取所有原告（每个人正反面信息合并为一条）:
- plaintiffs: 数组，每个元素包含:
  - name: 姓名（从OCR中提取的完整姓名）
  - relationship: 与患者关系（本人/父亲/母亲/配偶/儿子/女儿等）
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
- defendant_name: 被告医院全称
- legal_representative: 法定代表人姓名
- credit_code: 统一社会信用代码
- defendant_address: 医院地址
- defendant_phone: 医院电话

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
- appraisal_details: {{ appraisal_org, appraisal_date, report_no, cause_of_death(死亡案件), disability_level(伤残案件), causation, fault_degree }}

### 八、医务人员资质（可选）
- has_staff_issue: true/false
- staff_details: {{ staff_name, issue_type, issue_description }}

### 九、死亡信息（仅死亡案件）
- death_date: 死亡日期
- death_diagnosis: 完整死亡诊断（重要：必须从住院病历或尸检报告/司法鉴定意见书中提取完整的"死亡诊断"，通常是编号列举的多项诊断，如"①重度肺动脉高压；②急性右心衰竭；③..."格式。不要使用死亡证明书上的简略"死亡原因"，死亡证明书只有简略死因，不是完整的死亡诊断。必须完整列出所有项，不要遗漏。）

### 十、结案信息
- court_name: 受理法院名称
- complaint_signer: 具状人签名（多位原告用"、"分隔）
- complaint_year: 起诉年份

## 证据材料（四层结构）
{truncated_text}

请返回JSON格式，只返回JSON，不要额外说明。"""

    try:
        response = client.chat.completions.create(
            model=settings.bailian_text_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个专业的医疗损害案件法律文书信息提取助手。"
                        "你必须从OCR原文中仔细提取所有信息，不要遗漏。"
                        "特别注意：\n"
                        "1. 身份证OCR原文中包含姓名、性别、民族、出生、住址、身份证号，必须完整提取\n"
                        "2. 文件名中包含人名和正反面标识，用来关联同一人的正反面信息\n"
                        "3. 被告医院的完整名称必须完整提取，不能简写为'医院'\n"
                        "4. 病历材料中的入院日期、主诉、诊断必须准确提取\n"
                        "5. 提取所有出现的原告（通常4人左右），不要遗漏\n"
                        "6. 死亡诊断必须从住院病历或尸检报告/司法鉴定意见书中提取完整的编号列举式死亡诊断，"
                        "不要从死亡证明书上提取简略死因\n"
                        "严格按照要求的JSON结构返回，只输出JSON，不添加任何解释。"
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
            return json.loads(json_match.group())
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
    plaintiffs = extracted_data.get("plaintiffs", [])
    if plaintiffs:
        context_parts.append("【原告信息】")
        for i, p in enumerate(plaintiffs, 1):
            context_parts.append(
                f"  原告{i}：{p.get('name', '')}，{p.get('relationship', '')}，"
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

    elif section_id == "paragraph_3":
        transfer = extracted_data.get("transfer_details", {})
        if transfer:
            context_parts.append(f"【转院信息】{json.dumps(transfer, ensure_ascii=False)}")

    elif section_id == "paragraph_4":
        appraisal = extracted_data.get("appraisal_details", {})
        if appraisal:
            context_parts.append(f"【鉴定信息】{json.dumps(appraisal, ensure_ascii=False)}")

    elif section_id == "paragraph_5":
        staff = extracted_data.get("staff_details", {})
        if staff:
            context_parts.append(f"【医务人员资质】{json.dumps(staff, ensure_ascii=False)}")

    context = "\n".join(context_parts)

    case_type_desc = "死亡" if case_type == "death" else "伤残"
    minor_note = "（注意：患者为未成年人）" if is_minor else ""

    try:
        response = client.chat.completions.create(
            model=settings.bailian_flash_model,
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
    else:
        return (
            f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
            f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
            f"并由此造成了严重的损害后果，"
            f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
            f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
            f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 向后兼容：填充旧字段
# ═══════════════════════════════════════════════════════════════════════════════

def _populate_legacy_fields(analysis_result: dict) -> None:
    """将新的结构化数据映射到旧字段，确保旧代码兼容"""
    plaintiffs = analysis_result.get("plaintiffs", [])
    if plaintiffs:
        # 旧字段：取第一个原告
        p1 = plaintiffs[0]
        analysis_result.setdefault("原告姓名1", p1.get("name", ""))
        analysis_result.setdefault("性别1", p1.get("gender", ""))
        analysis_result.setdefault("民族1", p1.get("ethnicity", ""))
        analysis_result.setdefault("出生年月日1", p1.get("birth_date", ""))
        analysis_result.setdefault("住址1", p1.get("address", ""))
        analysis_result.setdefault("身份证号1", p1.get("id_number", ""))
        analysis_result.setdefault("亲属关系1", p1.get("relationship", ""))
        analysis_result.setdefault("律师电话1", p1.get("phone", ""))
        analysis_result.setdefault("plaintiff_name", p1.get("name", ""))

        # 多原告: 额外存储 原告姓名2, 原告姓名3...
        for i, p in enumerate(plaintiffs[1:], 2):
            analysis_result[f"原告姓名{i}"] = p.get("name", "")
            analysis_result[f"性别{i}"] = p.get("gender", "")
            analysis_result[f"民族{i}"] = p.get("ethnicity", "")
            analysis_result[f"出生年月日{i}"] = p.get("birth_date", "")
            analysis_result[f"住址{i}"] = p.get("address", "")
            analysis_result[f"身份证号{i}"] = p.get("id_number", "")
            analysis_result[f"亲属关系{i}"] = p.get("relationship", "")
            analysis_result[f"律师电话{i}"] = p.get("phone", "")

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
    2. 在OCR文本中搜索"死亡诊断"或"死亡原因"标签
    3. 取标签后的编号列举式诊断原文（如 ①xxx；②xxx；③xxx）
    4. 处理OCR跨页断裂：页码/页眉混入编号项时，丢弃污染部分，
       并在页码后面查找残留的诊断项文本（如"凝血功能障碍"）
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

    for mat in sorted_mats:
        ocr_text = (mat.ocr_text or "").strip()
        cat = mat.effective_category or ""

        # 只在目标类别中查找
        if cat not in _DEATH_DIAG_PRIORITY_CATEGORIES:
            continue

        # 搜索"死亡诊断"标签
        match = _re.search(r'死亡诊断[：:]\s*', ocr_text)
        if not match:
            # 退而搜索"死亡原因"（死亡证明书上用的标签）
            match = _re.search(r'死亡原因[：:]\s*', ocr_text)
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

        # 如果没有编号格式，取标签后到句号/换行的整段文本
        simple_match = _re.search(r'[^。\n]{5,200}[。．\.]?', tail)
        if simple_match:
            result = simple_match.group().rstrip('。．.')
            logger.info(
                f"Direct extracted death_diagnosis from '{mat.original_filename}' "
                f"({cat}): simple format"
            )
            return result

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
    for mat in sorted(materials, key=_cat_sort_key):
        ocr_text = (mat.ocr_text or "").strip()
        if not ocr_text:
            continue
        cat = mat.effective_category or ""

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

        # 地址：只在 identity_defendant 类别中搜索
        if cat == "identity_defendant" and not result.get("defendant_address"):
            # 格式1: "地址：/住所：XXX省XXX市XXX路XX号"
            m = _re.search(
                r'(?:地址|住所)[：:]\s*([\u4e00-\u9fff]+省[\u4e00-\u9fff]+[\u4e00-\u9fff]*[路段街道][\u4e00-\u9fff]*\d+号)',
                ocr_text,
            )
            if not m:
                # 格式2: "注册地址\n中山市小榄镇菊城大道中65号"（值在下一行，可能不含省）
                m = _re.search(
                    r'(?:注册地址|地址|住所)[^\n]*\n\s*([\u4e00-\u9fff]+[\u4e00-\u9fff]*[路段街道][\u4e00-\u9fff]*\d+号)',
                    ocr_text,
                )
            if m:
                result["defendant_address"] = m.group(1)

    if result:
        logger.info(
            f"Direct extracted defendant_info: {result}"
        )
        return result

    return None
