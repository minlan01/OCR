"""
段落归属分组器
基于 heading_parser 结果，将文本块归属到对应标题下，构建层级文档树
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from services.utils.text_patterns import is_page_number


def _is_heading_block(block: dict) -> bool:
    return block.get("heading_level") is not None


def _is_empty_block(block: dict) -> bool:
    text = block.get("text", "").strip()
    return len(text) == 0


def _bbox_y(block: dict) -> float:
    bbox = block.get("bbox")
    if not bbox:
        return 0.0
    if isinstance(bbox[0], list):
        return bbox[0][1]
    return bbox[1] if len(bbox) > 1 else 0.0


def _bbox_x(block: dict) -> float:
    bbox = block.get("bbox")
    if not bbox:
        return 0.0
    if isinstance(bbox[0], list):
        return bbox[0][0]
    return bbox[0] if len(bbox) > 0 else 0.0


def _split_into_paragraphs(blocks: list[dict]) -> list[dict]:
    """
    将文本块列表合并为段落
    相邻且Y坐标接近的文本合并为一个段落
    """
    if not blocks:
        return []

    # 按Y排序
    sorted_blocks = sorted(blocks, key=lambda b: (_bbox_y(b), _bbox_x(b)))

    paragraphs = []
    current_para = None

    for block in sorted_blocks:
        text = block.get("text", "").strip()
        if is_page_number(text):
            continue

        bbox = block.get("bbox", [])
        if not bbox:
            continue

        # 获取当前块顶部Y坐标
        if isinstance(bbox[0], list):
            curr_top = bbox[0][1]
        else:
            curr_top = bbox[1] if len(bbox) > 1 else 0

        if current_para is None:
            current_para = {
                "text": text,
                "bbox": bbox,
                "confidence": block.get("confidence", 0),
                "confidence_count": 1,
                "lines": [text],
            }
        else:
            # 计算与上一段落的间距
            prev_bbox = current_para["bbox"]
            if isinstance(prev_bbox[0], list):
                prev_bottom = max(p[1] for p in prev_bbox)
            else:
                prev_bottom = prev_bbox[1] + prev_bbox[3] if len(prev_bbox) > 3 else 0

            gap = curr_top - prev_bottom

            # 如果间距合理（< 2倍估计行高），合并为同一段落
            if gap <= 80:  # 300dpi下约2行
                current_para["text"] += " " + text
                current_para["lines"].append(text)
                # 扩展bbox
                if isinstance(prev_bbox[0], list):
                    all_xs = [p[0] for p in prev_bbox] + [p[0] for p in bbox]
                    all_ys = [p[1] for p in prev_bbox] + [p[1] for p in bbox]
                    current_para["bbox"] = [
                        [min(all_xs), min(all_ys)],
                        [max(all_xs), min(all_ys)],
                        [max(all_xs), max(all_ys)],
                        [min(all_xs), max(all_ys)],
                    ]
                current_para["confidence"] += block.get("confidence", 0)
                current_para["confidence_count"] += 1
            else:
                # 新段落
                current_para["confidence"] /= max(current_para["confidence_count"], 1)
                del current_para["confidence_count"]
                paragraphs.append(current_para)
                current_para = {
                    "text": text,
                    "bbox": bbox,
                    "confidence": block.get("confidence", 0),
                    "confidence_count": 1,
                    "lines": [text],
                }

    if current_para is not None:
        current_para["confidence"] /= max(current_para["confidence_count"], 1)
        del current_para["confidence_count"]
        paragraphs.append(current_para)

    return paragraphs


def group_paragraphs(blocks: list[dict], headings: list[dict] | None = None) -> dict:
    """
    将文本块按标题层级分组为结构化文档树

    Args:
        blocks: 文本块列表 [{text, confidence, bbox, heading_level?}, ...]
        headings: 已标注的标题列表（可选，如果blocks已含heading_level则不需传）

    Returns:
        {
            "sections": [{level, title, paragraphs: [...], subsections: [...]}, ...],
            "orphan_paragraphs": [{text, bbox, confidence}, ...],
            "total_sections": int,
            "total_paragraphs": int,
        }
    """
    # 合并headings标注（如果传入）
    if headings:
        heading_map = {}
        for h in headings:
            text = h.get("text", "").strip()
            if text:
                heading_map[text] = h.get("heading_level")
        for block in blocks:
            text = block.get("text", "").strip()
            if text in heading_map and not _is_heading_block(block):
                block["heading_level"] = heading_map[text]

    # 过滤空块和页码
    filtered = [b for b in blocks if not _is_empty_block(b) and not is_page_number(b.get("text", ""))]

    if not filtered:
        return {
            "sections": [],
            "orphan_paragraphs": [],
            "total_sections": 0,
            "total_paragraphs": 0,
        }

    # 第一遍：找出所有标题，构建段落组
    sections = []
    orphan_blocks = []

    # 临时：收集第一个标题之前的内容
    pre_heading_blocks = []
    current_heading = None
    current_body_blocks = []

    for block in filtered:
        if _is_heading_block(block):
            # 保存之前的段落
            if current_heading is not None and current_body_blocks:
                paras = _split_into_paragraphs(current_body_blocks)
                current_heading["paragraphs"] = paras
            elif not current_heading and pre_heading_blocks:
                # 第一个标题之前的段落 → 后续归入 orphan_blocks（见下方 orphan_blocks.extend）
                pass

            # 开始新标题段落
            level = block.get("heading_level", 1)
            current_heading = {
                "level": level,
                "title": block.get("text", ""),
                "heading_bbox": block.get("bbox", []),
                "heading_confidence": block.get("confidence", 0),
                "paragraphs": [],
                "subsections": [],
            }
            sections.append(current_heading)
            current_body_blocks = []

            if not sections or len(sections) == 1:
                # 第一个标题之前的内容
                if pre_heading_blocks:
                    orphan_blocks.extend(pre_heading_blocks)
                pre_heading_blocks = []
        else:
            if current_heading is not None:
                current_body_blocks.append(block)
            else:
                pre_heading_blocks.append(block)

    # 处理最后一个标题的段落
    if current_heading is not None and current_body_blocks:
        paras = _split_into_paragraphs(current_body_blocks)
        current_heading["paragraphs"] = paras

    # 处理孤儿段落
    if pre_heading_blocks:
        orphan_blocks.extend(pre_heading_blocks)

    # 第二遍：构建层级树（将子标题嵌套到父标题下）
    structured_sections = _build_hierarchy(sections)

    orphan_paragraphs = _split_into_paragraphs(orphan_blocks) if orphan_blocks else []

    total_sections = sum(1 + _count_subsections(s) for s in structured_sections)
    total_paragraphs = sum(
        len(s.get("paragraphs", [])) + _count_paragraphs_in_subsections(s)
        for s in structured_sections
    ) + len(orphan_paragraphs)

    logger.info(
        f"Paragraph grouping complete: {total_sections} sections, {total_paragraphs} paragraphs"
    )

    return {
        "sections": structured_sections,
        "orphan_paragraphs": orphan_paragraphs,
        "total_sections": total_sections,
        "total_paragraphs": total_paragraphs,
    }


def _build_hierarchy(sections: list[dict]) -> list[dict]:
    """将扁平标题列表构建为层级树"""
    if not sections:
        return []

    result = []
    stack: list[dict] = []  # 当前嵌套栈

    for section in sections:
        level = section.get("level", 1)

        # 找到正确的父级
        while stack and stack[-1].get("level", 1) >= level:
            stack.pop()

        if stack:
            stack[-1].setdefault("subsections", []).append(section)
        else:
            result.append(section)

        stack.append(section)

    return result


def _count_subsections(section: dict) -> int:
    """递归计算子节数"""
    count = 0
    for sub in section.get("subsections", []):
        count += 1 + _count_subsections(sub)
    return count


def _count_paragraphs_in_subsections(section: dict) -> int:
    """递归计算子节中的段落数"""
    count = 0
    for sub in section.get("subsections", []):
        count += len(sub.get("paragraphs", []))
        count += _count_paragraphs_in_subsections(sub)
    return count
