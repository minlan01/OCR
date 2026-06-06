"""
百炼 Qwen-Plus 文本模型信息提取器
从 OCR 识别出的文本中提取结构化信息
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from loguru import logger
from openai import OpenAI

from config.settings import settings


_client: Optional[OpenAI] = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(
                    api_key=settings.bailian_api_key_plain,
                    base_url=settings.bailian_text_base_url,
                )
    return _client


SLOT_PROMPTS = {
    "plaintiff": {
        "name": "原告信息提取",
        "instruction": (
            "请从以下文本中提取原告（患者）信息，返回JSON格式：\n"
            '{"name": "姓名", "id_card": "身份证号", "gender": "性别", '
            '"age": "年龄", "address": "住址", "phone": "联系电话"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "guardian": {
        "name": "法定代理人/监护人信息提取",
        "instruction": (
            "请从以下文本中提取法定代理人/监护人信息，返回JSON格式：\n"
            '{"guardian_name": "姓名", "guardian_id_card": "身份证号", '
            '"guardian_relation": "与患者关系", "guardian_address": "住址", '
            '"guardian_phone": "联系电话"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "defendant": {
        "name": "被告信息提取",
        "instruction": (
            "请从以下文本中提取被告（医院）信息，返回JSON格式：\n"
            '{"hospital_name": "医院全称", "legal_entity": "法定代表人", '
            '"hospital_address": "医院地址", "hospital_phone": "联系电话", '
            '"unified_credit_code": "统一社会信用代码"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "fee": {
        "name": "赔偿费用清单提取",
        "instruction": (
            "请从以下文本中提取赔偿费用清单，返回JSON格式：\n"
            '{"items": [{"name": "费用名称", "amount": 金额数字, "description": "说明"}], '
            '"total_amount": 总金额数字}\n'
            "金额为纯数字（单位：元）。如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "medical": {
        "name": "病历信息提取",
        "instruction": (
            "请从以下病历文本中提取关键信息，返回JSON格式：\n"
            '{"admission_reason": "入院原因", "admission_date": "入院日期", '
            '"diagnosis": "诊断", "treatments": ["治疗1", "治疗2"], '
            '"complications": "并发症/不良后果", "discharge_date": "出院日期", '
            '"discharge_status": "出院情况", "transfer_info": "转院信息(如有)"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "appraisal": {
        "name": "司法鉴定书提取",
        "instruction": (
            "请从以下司法鉴定文本中提取关键信息，返回JSON格式：\n"
            '{"appraisal_org": "鉴定机构", "appraisal_date": "鉴定日期", '
            '"disability_level": "伤残等级", "causality": "因果关系判定", '
            '"medical_error": "医疗过错认定", "error_participation": "过错参与度", '
            '"summary": "鉴定意见摘要"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "staff_error": {
        "name": "医务人员过错核查提取",
        "instruction": (
            "请从以下文本中提取医务人员过错核查信息，返回JSON格式：\n"
            '{"error_type": "过错类型", "error_description": "过错描述", '
            '"involved_staff": "涉事医务人员", "error_evidence": "过错依据", '
            '"summary": "核查结论摘要"}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
    "evidence": {
        "name": "证据材料清单提取",
        "instruction": (
            "请从以下文本中提取证据材料清单，返回JSON格式：\n"
            '{"items": [{"index": 序号, "name": "证据名称", "type": "证据类型", '
            '"source": "来源", "description": "证明内容"}], '
            '"total_count": 证据总数}\n'
            "如果某字段无法识别，填 null。只返回JSON，不要额外说明。"
        ),
    },
}


def extract_slot_info(slot: str, text: str) -> dict[str, Any]:
    prompt_config = SLOT_PROMPTS.get(slot)
    if not prompt_config:
        logger.warning(f"Unknown slot for extraction: {slot}")
        return {}

    if not text or not text.strip():
        logger.info(f"Empty text for slot={slot}, skipping extraction")
        return {}

    client = _get_client()
    max_chars = settings.llm_context_slot_limit
    truncated_text = text[:max_chars]
    if len(text) > max_chars:
        truncated_text += "\n...(文本过长已截断)"

    try:
        response = client.chat.completions.create(
            model=settings.bailian_flash_model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": "你是一个精确的信息提取助手。严格按照用户要求的JSON格式输出，不要添加任何额外内容。"}]},
                {"role": "user", "content": [{"type": "text", "text": f"{prompt_config['instruction']}\n\n文本内容：\n{truncated_text}"}]},
            ],
            temperature=0.1,
            timeout=settings.bailian_text_timeout,
        )
        raw = response.choices[0].message.content.strip()

        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            return json.loads(json_match.group())
        else:
            logger.warning(f"LLM did not return valid JSON for slot={slot}: {raw[:200]}")
            return {"raw_response": raw}
    except Exception as e:
        logger.error(f"LLM extraction failed for slot={slot}: {e}")
        return {"error": str(e)}


def extract_medical_large(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        return {}

    chunk_size = 6000
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])

    if len(chunks) <= 1:
        return extract_slot_info("medical", text)

    client = _get_client()
    chunk_summaries = []

    for idx, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                model=settings.bailian_flash_model,
                messages=[
                    {"role": "system", "content": [{"type": "text", "text": "你是病历信息提取助手。请提取这段病历文本的关键信息，包括入院原因、诊断、治疗、并发症等。用简洁的要点格式输出。"}]},
                    {"role": "user", "content": [{"type": "text", "text": f"病历第{idx+1}部分：\n{chunk}"}]},
                ],
                temperature=0.1,
                timeout=settings.bailian_text_timeout,
            )
            chunk_summaries.append(response.choices[0].message.content.strip())
        except Exception as e:
            logger.warning(f"Medical chunk {idx+1} extraction failed: {e}")

    if not chunk_summaries:
        return {"error": "all_chunks_failed"}

    combined = "\n\n".join(chunk_summaries)
    return extract_slot_info("medical", combined)
