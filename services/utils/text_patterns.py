"""
文本模式匹配工具

提供页码检测、终止标点判断、跨页续文检测等正则表达式和工具函数。
"""
from __future__ import annotations

import re

# 终止标点：句号、问号、感叹号、省略号、冒号（章节标题）、右括号结束
TERMINAL_PUNCTUATION = re.compile(r'[。？！…\.\!\?\)」』】〗]$')

# 页码模式：纯数字（1-4位），不应被当作正文
PAGE_NUMBER_PATTERN = re.compile(r'^\d{1,4}$')

# 装饰页码模式：- 1 - 或 — 2 — 等形式
DECORATED_PAGE_PATTERN = re.compile(r'^[-–—]\s*\d{1,4}\s*[-–—]$')

# 罗马数字页码：i, ii, iii, iv, v, vi, vii, viii, ix, x, l, c, d, m 组合
ROMAN_PAGE_PATTERN = re.compile(r'^[ivxlcdm]{1,5}$', re.IGNORECASE)

# 第X页 / Page X / P. X 格式
LABELED_PAGE_PATTERN = re.compile(
    r'^(第\s*\d+\s*页|Page\s+\d+|P\.?\s*\d+)$',
    re.IGNORECASE,
)

# X / Y 页码格式（如 "3 / 15"）
SLASH_PAGE_PATTERN = re.compile(r'^\d{1,4}\s*/\s*\d{1,4}$')


def is_page_number(text: str) -> bool:
    """
    判断文本是否为独立页码

    支持格式：
    - 纯数字（1-4位）："123"
    - 罗马数字："iv", "XII"
    - 装饰页码："- 1 -", "— 2 —"
    - 标签页码："第5页", "Page 10", "P.3"
    - 分数页码："3 / 15"

    Args:
        text: 待检测文本

    Returns:
        是否为页码
    """
    text = text.strip()
    if not text:
        return False
    if PAGE_NUMBER_PATTERN.match(text):
        return True
    if ROMAN_PAGE_PATTERN.match(text):
        return True
    if DECORATED_PAGE_PATTERN.match(text):
        return True
    if LABELED_PAGE_PATTERN.match(text):
        return True
    if SLASH_PAGE_PATTERN.match(text):
        return True
    return False


