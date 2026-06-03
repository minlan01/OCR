"""
LLM 提取服务 — 按 JSON Schema 从结构化结果中提取字段

调用百炼 Qwen 大模型，将 OCR 结构化结果按模板 Schema 提取为模板所需 JSON 数据。
"""
from __future__ import annotations

import json

from loguru import logger

from config.settings import settings


EXTRACTION_SYSTEM_PROMPT = (
    "你是一个专业的数据提取引擎。你的任务是从给定的结构化数据中，"
    "按照指定的 JSON Schema 提取所需字段。"
    "请严格按 Schema 格式输出 JSON，不要输出任何其他内容。"
    "重要规则：\n"
    "1. 输出的 JSON 必须包含 Schema 中所有 required 字段，即使源数据中没有对应信息。\n"
    "2. 如果某个字段在源数据中找不到，请根据 Schema 中的 description 描述合理推断或构造占位值。\n"
    "3. 字符串字段找不到时用 '[待补充]'，数字用 0，布尔用 false，数组用空数组 []，对象用 {}。\n"
    "4. 绝对不能省略任何 required 字段。"
)


async def extract_with_schema(
    structured_result: dict,
    schema_json: dict,
    rules_md: str | None = None,
) -> dict:
    """调用 LLM 按 Schema 从结构化结果提取数据

    Args:
        structured_result: OCR 结构化结果 JSON
        schema_json: 目标 JSON Schema
        rules_md: 规则手册（可选，提供额外提取指引）

    Returns:
        提取后的 JSON 数据（符合 Schema）
    """
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.bailian_api_key_plain,
        base_url=settings.bailian_ocr_base_url,
        timeout=120,
    )

    user_parts = []

    user_parts.append("## 源数据（病历结构化 OCR 结果）\n")
    source_text = json.dumps(structured_result, ensure_ascii=False, indent=2)
    if len(source_text) > 30000:
        source_text = _truncate_structured(structured_result)
    user_parts.append(f"```json\n{source_text}\n```")

    user_parts.append("\n## 目标 JSON Schema\n")
    user_parts.append(f"```json\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```")

    if rules_md:
        user_parts.append("\n## 提取规则手册\n")
        user_parts.append(rules_md)

    user_parts.append(
        "\n请从源数据中按照上述 JSON Schema 提取数据，"
        "严格输出符合 Schema 的 JSON 对象，不要输出任何其他内容。"
    )

    user_content = "\n".join(user_parts)

    try:
        completion = client.chat.completions.create(
            model="qwen-plus-latest",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        raw = completion.choices[0].message.content or ""
        usage = completion.usage
        logger.info(
            f"LLM extraction done | tokens={usage.total_tokens if usage else '?'} | "
            f"raw_len={len(raw)}"
        )

        return _ensure_required_fields(_parse_llm_json(raw), schema_json)

    except Exception as e:
        logger.error(f"LLM extraction failed: {e}", exc_info=True)
        raise


def _truncate_structured(data: dict, max_chars: int = 30000) -> str:
    """截断过大的结构化结果，保留关键信息"""
    truncated = dict(data)

    pages = truncated.get("pages", [])
    if pages and len(json.dumps(pages, ensure_ascii=False)) > max_chars // 2:
        truncated["pages"] = pages[:5]
        truncated["_note"] = f"仅保留前 5 页（共 {len(pages)} 页）"

    result = json.dumps(truncated, ensure_ascii=False, indent=2)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (truncated)"
    return result


def _parse_llm_json(raw: str) -> dict:
    """解析 LLM 返回的 JSON"""
    text = raw.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    import re
    code_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"LLM output is not valid JSON: {text[:200]}")


_TYPE_DEFAULTS = {
    "string": "[待补充]",
    "number": 0,
    "integer": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _ensure_required_fields(data: dict, schema: dict) -> dict:
    """确保 LLM 输出包含 Schema 中所有 required 字段，缺失的用默认值填充"""
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    filled = []
    for key in required:
        if key not in data:
            prop = properties.get(key, {})
            prop_type = prop.get("type", "string")
            if prop_type == "object":
                data[key] = _ensure_required_fields({}, prop)
            else:
                data[key] = _TYPE_DEFAULTS.get(prop_type, "[待补充]")
            filled.append(key)

    if filled:
        logger.info(f"Schema post-fill: added missing required fields: {filled}")

    return data
