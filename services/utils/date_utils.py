"""
日期处理工具 — 统一各种日期格式
===============================
处理 OCR 结果中常见的各种日期格式，统一为"XXXX年X月X日"格式
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


def normalize_date(date_str: str) -> str:
    """将各种日期格式统一为'XXXX年X月X日'格式

    支持格式：
    - 2024年1月1日 / 2024年01月01日
    - 2024/1/1 / 2024-1-1 / 2024.1.1
    - 20240101
    - 2024年3月 (仅年月)
    - 2024年 (仅年份)
    - OCR常见错误: 2O24年 (字母O替代0) / 2O24年1月O1日
    """
    if not date_str:
        return date_str

    s = date_str.strip()

    # 修正 OCR 常见错误：字母O替代数字0
    s = s.replace("O", "0").replace("ｏ", "0").replace("Ｏ", "0")

    # 已经是标准中文格式: 2024年1月1日
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    # 斜线/短横/点分隔: 2024/1/1, 2024-1-1, 2024.1.1
    m = re.match(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    # 纯数字: 20240101
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    # 仅年月: 2024年3月
    m = re.match(r"(\d{4})年(\d{1,2})月$", s)
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月"

    # 仅年份
    m = re.match(r"^(\d{4})年?$", s)
    if m:
        return f"{m.group(1)}年"

    return s


def parse_date(date_str: str) -> Optional[datetime]:
    """将日期字符串解析为 datetime 对象

    返回 None 如果无法解析
    """
    if not date_str:
        return None

    s = normalize_date(date_str)

    # 尝试各种格式
    for fmt in ["%Y年%m月%d日", "%Y年%m月", "%Y年"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    return None


def sort_events_by_date(events: list[dict], date_key: str = "date") -> list[dict]:
    """按日期字段对事件列表排序

    Args:
        events: 事件列表，每个事件需包含 date_key 指定的日期字段
        date_key: 日期字段名（默认 "date"）

    Returns:
        按日期升序排列的事件列表（无法解析日期的排到最后）
    """
    def _sort_key(event):
        date_str = event.get(date_key, "")
        dt = parse_date(date_str)
        if dt:
            return (0, dt)
        return (1, datetime.max)

    return sorted(events, key=_sort_key)


def format_date_chinese(date_str: str) -> str:
    """确保日期字符串使用中文格式"""
    return normalize_date(date_str)
