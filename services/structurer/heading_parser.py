"""
标题层级解析 — 基于字体/位置/编号规则提取文档标题树

支持策略（按优先级）：
1.  正则模式匹配 (中文: 第X章/第X节; Western: Chapter/Section/X.)
2.  字体大小推断 (标题字体 > 1.3x 中位数 → 提升级别)
3.  居中位置启发式 (x 坐标在页面中央 10% 范围内 → H2 候选)
4.  页面顶部位置 (bbox[1] < 页面高度 5% → H1 候选)

标题层级定义（中文格式）：
  第X章 → H1, 第X节 → H2, 一、→ H2, 1. → H3, 1.1 → H4, 1.1.1 → H5
"""
from __future__ import annotations

import re
from statistics import median

from services.constants import (
    CENTER_TOLERANCE,
    DEFAULT_PAGE_HEIGHT,
    DEFAULT_PAGE_WIDTH,
    FONT_SIZE_RATIO_THRESHOLD,
    TOP_PAGE_RATIO,
)


# ================================================================
# 正则模式 — 中文 + Western 混合
# ================================================================

HEADING_PATTERNS: dict[int, list[str]] = {
    1: [
        r"第[一二三四五六七八九十百千\d]+章",
        r"第[一二三四五六七八九十百千\d]+篇",
        r"第[一二三四五六七八九十百千\d]+部",
        r"^Chapter\s+\d+",
        r"^PART\s+[IVX]+",
    ],
    2: [
        r"第[一二三四五六七八九十百千\d]+节",
        r"第[一二三四五六七八九十百千\d]+条",
        r"^[一二三四五六七八九十]、",
        r"^Section\s+\d+(\.\d+)?",
        r"^[A-Z]\.\s",  # A. Title
    ],
    3: [
        r"^\d+[、]",          # 1、标题
        r"^\d+\.(?!\d)",     # 1. 标题 (不匹配 1.1)
        r"^（[一二三四五六七八九十]）",
        r"^\(\d+\)",         # (1)
    ],
    4: [
        r"^（\d+）",
        r"^\d+\.\d+(?!\.\d)",  # 1.1 标题
        r"^\([a-z]\)",        # (a)
    ],
    5: [
        r"^\d+\.\d+\.\d+",
        r"^[ivx]+\.",        # i. Title
    ],
}


# ================================================================
# 字体/位置启发式参数（从 services.constants 导入）
# ================================================================


def _get_font_size(block: dict) -> float:
    """从文本块中提取字体大小"""
    return block.get("font_size", 0.0) or 0.0


def _is_bold(block: dict) -> bool:
    """检查是否为粗体"""
    return block.get("is_bold", False)


def _is_centered(block: dict, page_width: float = DEFAULT_PAGE_WIDTH) -> bool:
    """检查文本块是否在页面中央"""
    bbox = block.get("bbox")
    if not bbox or not isinstance(bbox, list) or len(bbox) < 4:
        return False
    try:
        x_coords = [pt[0] for pt in bbox if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if not x_coords:
            return False
        center_x = (min(x_coords) + max(x_coords)) / 2
        return abs(center_x / page_width - 0.5) < CENTER_TOLERANCE
    except (IndexError, TypeError):
        return False


def _is_top_of_page(block: dict, page_height: float = DEFAULT_PAGE_HEIGHT) -> bool:
    """检查文本块是否在页面顶部"""
    bbox = block.get("bbox")
    if not bbox or not isinstance(bbox, list) or len(bbox) < 2:
        return False
    try:
        y_coords = [pt[1] for pt in bbox if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if not y_coords:
            return False
        top_y = min(y_coords)
        return top_y / page_height < TOP_PAGE_RATIO
    except (IndexError, TypeError):
        return False


# ================================================================
# 公共 API
# ================================================================

def parse_headings(blocks: list[dict]) -> list[dict]:
    """
    解析文本块列表，标注标题层级

    为每个匹配标题模式的文本块添加 heading_level 字段。

    Args:
        blocks: 文本块列表，每块至少含 text 字段，
                可选 font_size, is_bold, bbox 用于启发式推断

    Returns:
        带 heading_level 标注的文本块列表（不改变原有字段）
    """
    results = []
    # 收集所有字体大小以计算中位数
    all_font_sizes = [_get_font_size(b) for b in blocks if _get_font_size(b) > 0]
    median_font = median(all_font_sizes) if all_font_sizes else 0.0

    for block in blocks:
        text = block.get("text", "").strip()
        level = detect_heading_level(
            text,
            font_size=_get_font_size(block),
            median_font=median_font,
            is_bold=_is_bold(block),
            is_centered=_is_centered(block),
            is_top=_is_top_of_page(block),
        )
        if level:
            results.append({**block, "heading_level": level})
        else:
            results.append(block)

    return results


def detect_heading_level(
    text: str,
    font_size: float = 0.0,
    median_font: float = 0.0,
    is_bold: bool = False,
    is_centered: bool = False,
    is_top: bool = False,
) -> int | None:
    """
    检测单行文本的标题层级

    按优先级尝试多种策略：
    1. 正则模式匹配（中文 + Western）
    2. 字体大小启发式（提升潜在标题级别）
    3. 居中/页面顶部启发式

    Args:
        text: 文本内容
        font_size: 当前文本的字体大小
        median_font: 所有文本块字体大小的中位数
        is_bold: 是否粗体
        is_centered: 是否居中
        is_top: 是否位于页面顶部

    Returns:
        标题层级 (1-5)，如果不是标题则返回 None
    """
    if not text or not text.strip():
        return None

    # 策略 1: 正则模式匹配
    for level, patterns in HEADING_PATTERNS.items():
        for pat in patterns:
            if re.match(pat, text):
                return _adjust_level(level, font_size, median_font, is_bold, is_centered, is_top)

    # 策略 2: 字体显著大于中位数且居中/粗体
    if median_font > 0 and font_size > median_font * FONT_SIZE_RATIO_THRESHOLD:
        if is_centered and len(text) < 50:  # 标题通常较短
            return _adjust_level(2, font_size, median_font, is_bold, is_centered, is_top)
        if is_bold:
            return _adjust_level(3, font_size, median_font, is_bold, is_centered, is_top)

    # 策略 3: 页面顶部 + 短文本
    if is_top and len(text) < 30:
        return _adjust_level(1, font_size, median_font, is_bold, is_centered, is_top)

    return None


def _adjust_level(
    level: int,
    font_size: float,
    median_font: float,
    is_bold: bool,
    is_centered: bool,
    is_top: bool,
) -> int:
    """根据启发式特征调整标题级别

    - 页面顶部 + 粗体 → 提升一级
    - 仅字体大但既不居中也不粗体 → 降一级
    - 居中 + 粗体 → 提升一级
    """
    adjusted = level

    # 提升规则
    if is_top and is_bold:
        adjusted = max(1, adjusted - 1)
    if is_centered and is_bold:
        adjusted = max(1, adjusted - 1)

    # 降级规则: 字体不大且无特殊格式
    if median_font > 0 and font_size <= median_font and not is_bold and not is_centered:
        adjusted = min(5, adjusted + 1)

    return max(1, min(5, adjusted))
