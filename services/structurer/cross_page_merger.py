"""
跨页合并器
检测并合并跨页段落：上一页末行无终止标点 + 下一页首行是继续句
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from services.utils.text_patterns import TERMINAL_PUNCTUATION, PAGE_NUMBER_PATTERN

# 继续句特征：以小写开头、以逗号/分号开始、是括号内续文
CONTINUATION_START = re.compile(
    r'^[a-z\u4e00-\u9fff]|'       # 小写字母或汉字开头（非标题）
    r'^[，,、；;）\)」』】〗]'          # 标点开头 → 明显续文
)

# 章节标题不能合并
CHAPTER_HEADING = re.compile(
    r'^(第[一二三四五六七八九十百千\d]+[章篇节条部])|'
    r'^[一二三四五六七八九十]、|'
    r'^\d+[\.、]'
)


def _get_last_line_text(blocks: list[dict]) -> str:
    """获取上一页最后一个文本块的文字"""
    if not blocks:
        return ""
    return blocks[-1].get("text", "").strip()


def _get_first_line_text(blocks: list[dict]) -> str:
    """获取下一页第一个文本块的文字"""
    if not blocks:
        return ""
    return blocks[0].get("text", "").strip()


def _ends_with_continuation(text: str) -> bool:
    """判断文本是否以"待续"结尾（无终止标点）"""
    text = text.strip()
    if not text:
        return False
    # 排除纯数字页码
    if PAGE_NUMBER_PATTERN.match(text):
        return False
    return not TERMINAL_PUNCTUATION.search(text[-1])


def _starts_as_continuation(text: str) -> bool:
    """判断文本是否以继续句开头"""
    text = text.strip()
    if not text:
        return False

    # 排除章节标题
    if CHAPTER_HEADING.match(text):
        return False

    # 小写字母/汉字开头（非大写标题）
    if text and text[0].islower():
        return True

    # 标点开头（逗号、分号等）→ 明显续文
    if CONTINUATION_START.match(text):
        return True

    return False


def _get_page_bbox(blocks: list[dict], block_index: int | None = None) -> list:
    """获取页面的统一bbox"""
    if block_index is not None and 0 <= block_index < len(blocks):
        bbox = blocks[block_index].get("bbox", [])
        if bbox:
            return bbox

    for b in blocks:
        bbox = b.get("bbox", [])
        if bbox:
            return bbox
    return [0, 0, 0, 0]


def merge_cross_page(
    pages: list[list[dict]],
    page_numbers: list[int] | None = None,
) -> list[list[dict]]:
    """
    检测并合并跨页段落

    Args:
        pages: [[{text, bbox, confidence}, ...], ...] 每页的文本块列表
        page_numbers: 页码列表（可选）

    Returns:
        合并后的文本块列表（如果发生跨页合并，倒数第二页的末块和当前页的首块被合并）
    """
    if not pages or len(pages) < 2:
        return pages

    merged_count = 0
    result = [list(page) for page in pages]  # 深拷贝避免副作用

    for i in range(len(result) - 1):
        prev_page = result[i]
        curr_page = result[i + 1]

        if not prev_page or not curr_page:
            continue

        last_text = _get_last_line_text(prev_page)
        first_text = _get_first_line_text(curr_page)

        if not last_text or not first_text:
            continue

        # 判断是否需要合并
        if _ends_with_continuation(last_text) and _starts_as_continuation(first_text):
            # 执行合并：将当前页第一块的内容合并到上一页最后一块
            prev_last = prev_page[-1]
            curr_first = curr_page[0]

            prev_last["text"] = prev_last.get("text", "") + first_text

            # 合并confidence（取平均）
            prev_conf = prev_last.get("confidence", 0)
            curr_conf = curr_first.get("confidence", 0)
            prev_last["confidence"] = round((prev_conf + curr_conf) / 2, 4)

            # 标记跨页
            prev_last.setdefault("cross_page", []).append(
                page_numbers[i + 1] if page_numbers else i + 2
            )

            # 从当前页移除已合并的块
            curr_page.pop(0)

            merged_count += 1
            logger.debug(
                f"Cross-page merge: page {i+1}→{i+2}: "
                f"'{last_text[-20:]}' + '{first_text[:20]}'"
            )

    if merged_count > 0:
        logger.info(f"Cross-page merge complete: {merged_count} paragraphs merged")

    return result


def merge_cross_page_flat(
    all_blocks: list[dict],
    page_boundaries: list[int],
) -> list[dict]:
    """
    扁平化跨页合并（当所有块在一个列表中时使用）

    Args:
        all_blocks: 所有页的文本块（扁平列表）
        page_boundaries: 每个边界是下一页开始的索引（不含0）

    Returns:
        合并后的文本块列表
    """
    if not all_blocks or not page_boundaries:
        return all_blocks

    result = list(all_blocks)
    offset = 0

    for boundary in page_boundaries:
        actual_boundary = boundary + offset

        if actual_boundary <= 0 or actual_boundary >= len(result):
            continue

        prev_idx = actual_boundary - 1
        curr_idx = actual_boundary

        last_text = result[prev_idx].get("text", "").strip() if prev_idx < len(result) else ""
        first_text = result[curr_idx].get("text", "").strip() if curr_idx < len(result) else ""

        if last_text and first_text:
            if _ends_with_continuation(last_text) and _starts_as_continuation(first_text):
                # 合并
                result[prev_idx]["text"] = result[prev_idx].get("text", "") + first_text
                prev_conf = result[prev_idx].get("confidence", 0)
                curr_conf = result[curr_idx].get("confidence", 0)
                result[prev_idx]["confidence"] = round((prev_conf + curr_conf) / 2, 4)
                result[prev_idx].setdefault("cross_page", []).append(True)
                result.pop(curr_idx)
                offset -= 1

    return result
