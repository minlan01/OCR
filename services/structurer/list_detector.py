"""
列表识别器
检测编号列表、项目符号列表、多级嵌套列表
"""
from __future__ import annotations

import re

from loguru import logger

# 列表模式定义
LIST_PATTERNS = {
    "numbered_arabic": [
        r'^\s*(\d+)[\.、)\s]',       # 1. / 1、/ 1) / 1
        r'^\s*（(\d+)）',              # （1）
        r'^\s*\((\d+)\)',              # (1)
    ],
    "numbered_chinese": [
        r'^\s*([一二三四五六七八九十]+)[、\s]',  # 一、
        r'^\s*（([一二三四五六七八九十]+)）',     # （一）
    ],
    "lettered_lower": [
        r'^\s*([a-z])[\.\)、\s]',     # a. / a) / a、
        r'^\s*\(([a-z])\)',           # (a)
    ],
    "lettered_upper": [
        r'^\s*([A-Z])[\.\)、\s]',     # A. / A) / A、
        r'^\s*\(([A-Z])\)',           # (A)
    ],
    "roman": [
        r'^\s*([ivxlcdm]+)[\.\)、\s]',  # i. / ii.
    ],
    "bulleted": [
        r'^\s*[-–—]\s',               # -
        r'^\s*[•·◦○●]\s',            # • · ◦ ○ ●
        r'^\s*[※★☆✓✔✗✘]\s',          # 特殊符号
        r'^\s*[◆◇▶▷►▻]\s',           # 箭头
    ],
    "circled_number": [
        r'^\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]',  # 带圈数字
    ],
}


def _match_list_item(text: str) -> tuple[str, str, str] | None:
    """
    匹配列表项，返回 (列表类型, 编号/符号, 剩余文本)

    Returns:
        (list_type, marker, content) 或 None
    """
    text = text.strip()

    for list_type, patterns in LIST_PATTERNS.items():
        for pattern in patterns:
            m = re.match(pattern, text)
            if m:
                marker = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0).strip()
                content = text[m.end():].strip()
                return (list_type, marker, content)

    return None


def _get_indent_level(bbox: list, base_x: float) -> int:
    """根据bbox的X坐标计算缩进级别"""
    if not bbox:
        return 0

    if isinstance(bbox[0], list):
        x = bbox[0][0]
    elif len(bbox) >= 1:
        x = bbox[0]
    else:
        return 0

    indent = x - base_x
    if indent < 20:
        return 0
    return min(int(indent / 40), 3)  # 每40px一级缩进


def detect_lists(blocks: list[dict], page_base_x: float = 0) -> list[dict]:
    """
    从文本块中检测列表结构

    Args:
        blocks: 文本块 [{text, bbox, confidence}, ...]
        page_base_x: 页面基准X坐标（用于缩进计算）

    Returns:
        [{type, items: [{marker, content, bbox, confidence}], indent_level, bbox}, ...]
    """
    if not blocks:
        return []

    lists = []
    current_list = None
    prev_indent = 0

    # 确定基准X
    if page_base_x == 0 and blocks:
        first_bbox = blocks[0].get("bbox", [])
        if first_bbox:
            if isinstance(first_bbox[0], list):
                page_base_x = first_bbox[0][0]
            else:
                page_base_x = first_bbox[0] if len(first_bbox) > 0 else 0

    # 计算全局平均X作为基准
    all_xs = []
    for b in blocks:
        bbox = b.get("bbox", [])
        if bbox:
            if isinstance(bbox[0], list):
                all_xs.append(bbox[0][0])
            else:
                all_xs.append(bbox[0] if len(bbox) > 0 else 0)
    if all_xs:
        page_base_x = sum(all_xs) / len(all_xs)

    for block in blocks:
        text = block.get("text", "").strip()
        bbox = block.get("bbox", [])

        match = _match_list_item(text)
        if match:
            list_type, marker, content = match
            indent = _get_indent_level(bbox, page_base_x)

            # 判断是否延续当前列表
            if current_list and current_list["type"] == list_type and abs(indent - prev_indent) <= 1:
                # 同类型同缩进 → 延续
                current_list["items"].append({
                    "marker": marker,
                    "content": content,
                    "bbox": bbox,
                    "confidence": block.get("confidence", 0),
                })
                # 扩展列表bbox
                if bbox:
                    _extend_bbox(current_list["bbox"], bbox)
            else:
                # 新列表（只有≥2项才保存旧列表）
                if current_list and len(current_list["items"]) >= 2:
                    lists.append(current_list)
                current_list = {
                    "type": list_type,
                    "items": [{
                        "marker": marker,
                        "content": content,
                        "bbox": bbox,
                        "confidence": block.get("confidence", 0),
                    }],
                    "indent_level": indent,
                    "bbox": list(bbox) if bbox else [0, 0, 0, 0],
                }
                prev_indent = indent
        elif current_list and _is_list_continuation(text, block, current_list):
            # 多行列表项（换行续写）
            last_item = current_list["items"][-1]
            last_item["content"] += " " + text
            if bbox:
                _extend_bbox(current_list["bbox"], bbox)
        else:
            # 非列表项
            if current_list and len(current_list["items"]) >= 2:
                lists.append(current_list)
            current_list = None
            prev_indent = 0

    # 保存最后一个列表
    if current_list and len(current_list["items"]) >= 2:
        lists.append(current_list)

    # 对每个列表计算统计信息
    for lst in lists:
        lst["item_count"] = len(lst["items"])
        lst["confidence_avg"] = round(
            sum(it.get("confidence", 0) for it in lst["items"]) / max(len(lst["items"]), 1),
            4,
        )

    logger.debug(f"List detection complete: {len(lists)} lists found")
    return lists


def _is_list_continuation(text: str, block: dict, current_list: dict) -> bool:
    """判断是否为列表项的多行续写"""
    if not text:
        return False

    # 如果文本以列表标记开头，不是续写
    if _match_list_item(text):
        return False

    # 如果文本以句号/感叹号/问号结尾，是一个完整句子，不是续写
    stripped = text.strip()
    if stripped and stripped[-1] in ('。', '！', '？', '.', '!', '?'):
        return False

    # 续写通常缩进对齐
    bbox = block.get("bbox", [])
    if bbox and current_list.get("items"):
        last_bbox = current_list["items"][-1].get("bbox", [])
        if last_bbox and bbox:
            if isinstance(bbox[0], list) and isinstance(last_bbox[0], list):
                # 续写行的X应该 >= 前一项的X（或略缩进）
                return bbox[0][0] >= last_bbox[0][0] - 10

    return False


def _extend_bbox(list_bbox: list, item_bbox: list) -> None:
    """扩展列表bbox以包含新项"""
    if not list_bbox or not item_bbox:
        return

    if isinstance(item_bbox[0], list) and len(item_bbox) == 4:
        # 四点式bbox
        xs = [p[0] for p in item_bbox]
        ys = [p[1] for p in item_bbox]
        ix, iy = min(xs), min(ys)
        iw, ih = max(xs) - ix, max(ys) - iy
        item_rect = [ix, iy, iw, ih]
    elif len(item_bbox) == 4:
        item_rect = list(item_bbox)
    else:
        return

    if isinstance(list_bbox[0], list):
        # 转换list_bbox为矩形
        xs = [p[0] for p in list_bbox if isinstance(p, list)]
        ys = [p[1] for p in list_bbox if isinstance(p, list)]
        if xs and ys:
            lx, ly = min(xs), min(ys)
            lw, lh = max(xs) - lx, max(ys) - ly
        else:
            lx, ly, lw, lh = 0, 0, 0, 0
    elif len(list_bbox) == 4:
        lx, ly, lw, lh = list_bbox
    else:
        return

    # 合并
    new_x = min(lx, item_rect[0])
    new_y = min(ly, item_rect[1])
    new_w = max(lx + lw, item_rect[0] + item_rect[2]) - new_x
    new_h = max(ly + lh, item_rect[1] + item_rect[3]) - new_y

    list_bbox.clear()
    list_bbox.extend([new_x, new_y, new_w, new_h])
