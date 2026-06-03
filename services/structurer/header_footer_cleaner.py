"""
页眉页脚清理器
检测并移除每页重复出现的页眉、页脚、页码
基于位置（y坐标）+ 文本相似度
"""
from __future__ import annotations

from difflib import SequenceMatcher

from loguru import logger

from services.constants import DEFAULT_PAGE_HEIGHT
from services.utils.text_patterns import is_page_number


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a_s, b_s = a.strip(), b.strip()
    if a_s == b_s:
        return 1.0
    if abs(len(a_s) - len(b_s)) > max(len(a_s), len(b_s)) * 0.5:
        return 0.0
    return SequenceMatcher(None, a_s, b_s).ratio()


def _is_header_candidate(text: str, y_ratio: float, page_height: float) -> bool:
    if y_ratio < 0.05:
        return True
    if page_height > 0 and y_ratio * page_height < 80:
        return True
    return False


def _is_footer_candidate(text: str, y_ratio: float, page_height: float) -> bool:
    if y_ratio > 0.92:
        return True
    if page_height > 0 and (1 - y_ratio) * page_height < 120:
        return True
    return False


def clean_headers_footers(
    pages: list[list[dict]],
    page_dimensions: list[tuple[int, int]] | None = None,
    similarity_threshold: float = 0.7,
) -> list[list[dict]]:
    """
    清理页眉页脚

    策略：
    1. 收集每页顶部/底部区域的文本
    2. 统计跨页重复出现的文本（≥3页）
    3. 移除这些重复文本

    性能优化：
    - 精确匹配优先，避免 SequenceMatcher 开销
    - 限制候选文本最大数量为 50，超出则跳过模糊匹配
    - 长度差异过大直接跳过
    """
    if not pages:
        return pages

    total_pages = len(pages)
    if total_pages < 3:
        return pages

    default_height = DEFAULT_PAGE_HEIGHT

    header_candidates: dict[str, list[int]] = {}
    footer_candidates: dict[str, list[int]] = {}

    for page_idx, page_blocks in enumerate(pages):
        if page_dimensions and page_idx < len(page_dimensions):
            _, page_h = page_dimensions[page_idx]
        else:
            page_h = default_height

        for block_idx, block in enumerate(page_blocks):
            text = block.get("text", "").strip()
            if not text:
                continue

            bbox = block.get("bbox", [])
            if not bbox:
                continue

            if isinstance(bbox[0], list):
                y = bbox[0][1]
            elif len(bbox) >= 2:
                y = bbox[1]
            else:
                continue

            y_ratio = y / page_h if page_h > 0 else 0

            if is_page_number(text):
                if _is_header_candidate(text, y_ratio, page_h):
                    header_candidates.setdefault(text, []).append(page_idx)
                elif _is_footer_candidate(text, y_ratio, page_h):
                    footer_candidates.setdefault(text, []).append(page_idx)
                continue

            if _is_header_candidate(text, y_ratio, page_h):
                found = False
                if text in header_candidates:
                    header_candidates[text].append(page_idx)
                    found = True
                else:
                    if len(header_candidates) < 50:
                        for candidate in list(header_candidates.keys()):
                            if _text_similarity(text, candidate) >= similarity_threshold:
                                header_candidates[candidate].append(page_idx)
                                found = True
                                break
                if not found:
                    header_candidates[text] = [page_idx]

            elif _is_footer_candidate(text, y_ratio, page_h):
                found = False
                if text in footer_candidates:
                    footer_candidates[text].append(page_idx)
                    found = True
                else:
                    if len(footer_candidates) < 50:
                        for candidate in list(footer_candidates.keys()):
                            if _text_similarity(text, candidate) >= similarity_threshold:
                                footer_candidates[candidate].append(page_idx)
                                found = True
                                break
                if not found:
                    footer_candidates[text] = [page_idx]

    min_pages = max(2, int(total_pages * 0.3))
    headers_to_remove = {
        text for text, pages_list in header_candidates.items()
        if len(pages_list) >= min_pages
    }
    footers_to_remove = {
        text for text, pages_list in footer_candidates.items()
        if len(pages_list) >= min_pages
    }

    if not headers_to_remove and not footers_to_remove:
        return pages

    result = []
    removed_count = 0

    for page_idx, page_blocks in enumerate(pages):
        if page_dimensions and page_idx < len(page_dimensions):
            _, page_h = page_dimensions[page_idx]
        else:
            page_h = default_height

        cleaned_blocks = []
        for block in page_blocks:
            text = block.get("text", "").strip()
            bbox = block.get("bbox", [])

            if not text or not bbox:
                cleaned_blocks.append(block)
                continue

            if isinstance(bbox[0], list):
                y = bbox[0][1]
            elif len(bbox) >= 2:
                y = bbox[1]
            else:
                cleaned_blocks.append(block)
                continue

            y_ratio = y / page_h if page_h > 0 else 0

            should_remove = False

            if is_page_number(text):
                if _is_header_candidate(text, y_ratio, page_h) or _is_footer_candidate(text, y_ratio, page_h):
                    should_remove = True

            if not should_remove and text in headers_to_remove and _is_header_candidate(text, y_ratio, page_h):
                should_remove = True
            elif not should_remove and text in footers_to_remove and _is_footer_candidate(text, y_ratio, page_h):
                should_remove = True

            if not should_remove:
                if _is_header_candidate(text, y_ratio, page_h):
                    for h_text in headers_to_remove:
                        if text != h_text and _text_similarity(text, h_text) >= similarity_threshold:
                            should_remove = True
                            break
                if not should_remove and _is_footer_candidate(text, y_ratio, page_h):
                    for f_text in footers_to_remove:
                        if text != f_text and _text_similarity(text, f_text) >= similarity_threshold:
                            should_remove = True
                            break

            if should_remove:
                removed_count += 1
                continue

            cleaned_blocks.append(block)

        result.append(cleaned_blocks)

    if removed_count > 0:
        logger.info(
            f"Header/Footer cleanup: removed {removed_count} blocks "
            f"({len(headers_to_remove)} header patterns, {len(footers_to_remove)} footer patterns)"
        )

    return result
