"""
Layout 版面检测器
基于 OCR 结果的纯算法版面分析：文本块合并、分栏检测、表格区域识别、图片区域推断
不依赖 PPStructure，保证环境兼容性
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from services.constants import DEFAULT_PAGE_HEIGHT, DEFAULT_PAGE_WIDTH
from services.utils.bbox import (
    bbox_to_rect,
)


@dataclass
class LayoutRegion:
    """版面区域"""
    type: str  # "text" | "table" | "image" | "title"
    bbox: list[int]  # [x, y, w, h]
    confidence: float
    text_lines: list[dict] = field(default_factory=list)
    reading_order: int = 0


def _detect_columns(blocks: list[dict], page_width: int) -> int:
    """检测分栏数（基于文本块X坐标分布）"""
    if len(blocks) < 3:
        return 1

    # blocks 可能是内部格式 (items/rect) 或外部格式 (bbox)
    rects = []
    for b in blocks:
        if "rect" in b:
            rects.append(b["rect"])
        elif "bbox" in b:
            rects.append(bbox_to_rect(b["bbox"]))
    if len(rects) < 3:
        return 1
    centers = [r[0] + r[2] / 2 for r in rects]

    # 按X排序
    centers_sorted = sorted(centers)
    gaps = [centers_sorted[i + 1] - centers_sorted[i] for i in range(len(centers_sorted) - 1)]

    if not gaps:
        return 1

    mean_gap = sum(gaps) / len(gaps)

    # 如果存在明显大于平均的间隙，可能是分栏
    large_gaps = [g for g in gaps if g > mean_gap * 2.5 and g > page_width * 0.08]
    return min(len(large_gaps) + 1, 3)  # 最多3栏


def _is_table_row(text: str) -> bool:
    """判断单行文本是否可能是表格行（数字/符号密集）"""
    if not text:
        return False
    # 统计数字和分隔符占比
    digits_symbols = len(re.findall(r'[\d.,;:()（）\-\+%/℃㎡]', text))
    return digits_symbols / max(len(text), 1) > 0.25


class LayoutDetector:
    """版面检测器 — 基于OCR结果的纯算法实现"""

    def __init__(
        self,
        line_merge_threshold: float = 1.5,  # 行合并阈值（行高倍数）
        column_gap_ratio: float = 0.08,       # 分栏间隙占页宽比
        table_density_threshold: float = 0.25, # 表格数字密度阈值
    ):
        self.line_merge_threshold = line_merge_threshold
        self.column_gap_ratio = column_gap_ratio
        self.table_density_threshold = table_density_threshold

    def detect(
        self,
        ocr_results: list[dict],
        page_width: int = DEFAULT_PAGE_WIDTH,
        page_height: int = DEFAULT_PAGE_HEIGHT,
    ) -> list[dict]:
        """
        检测单页版面区域
        Args:
            ocr_results: OCR识别结果 [{text, confidence, bbox}, ...]
            page_width: 页面宽度（像素）
            page_height: 页面高度（像素）
        Returns:
            [{type, bbox: [x,y,w,h], confidence, text_lines, reading_order}, ...]
        """
        if not ocr_results:
            return []

        # 1. 计算每个OCR结果的矩形和行高
        items = []
        for r in ocr_results:
            rect = bbox_to_rect(r["bbox"])
            _, _, _, h = rect
            items.append({
                "text": r["text"],
                "confidence": r["confidence"],
                "bbox": r["bbox"],
                "rect": rect,
                "line_height": h,
            })

        if not items:
            return []

        # 平均行高
        avg_line_height = sum(it["line_height"] for it in items) / len(items)
        merge_threshold = avg_line_height * self.line_merge_threshold

        # 2. 按Y坐标排序
        items.sort(key=lambda it: (it["rect"][1], it["rect"][0]))

        # 3. 合并相邻文本行为文本块
        blocks: list[dict] = []
        current_block = {
            "items": [items[0]],
            "rect": items[0]["rect"],
            "confidence_sum": items[0]["confidence"],
        }

        for item in items[1:]:
            prev_bottom = current_block["rect"][1] + current_block["rect"][3]
            curr_top = item["rect"][1]
            gap = curr_top - prev_bottom

            # 同行（Y 重叠）→ 合并为同一文本块
            # 或临近行（小间隙）→ 合并
            if gap <= merge_threshold:
                # 合并（同行或紧密排列的行）
                x = min(current_block["rect"][0], item["rect"][0])
                y = min(current_block["rect"][1], item["rect"][1])
                r = max(
                    current_block["rect"][0] + current_block["rect"][2],
                    item["rect"][0] + item["rect"][2],
                )
                b = max(
                    current_block["rect"][1] + current_block["rect"][3],
                    item["rect"][1] + item["rect"][3],
                )
                current_block["rect"] = (x, y, r - x, b - y)
                current_block["items"].append(item)
                current_block["confidence_sum"] += item["confidence"]
            else:
                # 保存当前块，开始新块
                blocks.append(current_block)
                current_block = {
                    "items": [item],
                    "rect": item["rect"],
                    "confidence_sum": item["confidence"],
                }
        blocks.append(current_block)

        # 4. 检测分栏
        num_columns = _detect_columns(blocks, page_width)

        # 5. 分类每个块
        regions: list[LayoutRegion] = []
        for block in blocks:
            rect = block["rect"]
            texts = [it["text"] for it in block["items"]]
            full_text = " ".join(texts)
            avg_conf = block["confidence_sum"] / len(block["items"])

            # 表格判断：块中多行为表格特征行
            table_row_count = sum(1 for t in texts if _is_table_row(t))
            table_ratio = table_row_count / len(texts) if texts else 0

            if table_ratio >= self.table_density_threshold:
                region_type = "table"
            else:
                region_type = "text"

            regions.append(LayoutRegion(
                type=region_type,
                bbox=[rect[0], rect[1], rect[2], rect[3]],
                confidence=round(avg_conf, 4),
                text_lines=[
                    {"text": it["text"], "confidence": it["confidence"], "bbox": it["bbox"]}
                    for it in block["items"]
                ],
            ))

        # 6. 检测图片区域（文本块之间的大间隙）
        image_regions = self._detect_image_gaps(regions, page_width, page_height, avg_line_height)

        # 7. 标注标题（块中字体较大或居中、加粗特征 → 这里从OCR结果推断）
        regions = self._mark_titles(regions, page_width)

        # 8. 合并所有区域
        all_regions = regions + image_regions

        # 9. 按阅读顺序排序（Y优先，同Y按X）
        all_regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))

        # 10. 分配阅读顺序号
        for i, region in enumerate(all_regions):
            region.reading_order = i

        return [
            {
                "type": r.type,
                "bbox": r.bbox,
                "confidence": r.confidence,
                "text_lines": r.text_lines,
                "reading_order": r.reading_order,
            }
            for r in all_regions
        ]

    def _detect_image_gaps(
        self,
        text_regions: list[LayoutRegion],
        page_width: int,
        page_height: int,
        avg_line_height: float,
    ) -> list[LayoutRegion]:
        """检测文本块之间的大间隙 → 可能的图片区域"""
        if len(text_regions) < 2:
            return []

        image_regions = []
        gap_threshold = avg_line_height * 4  # 4倍行高以上视为显著间隙

        for i in range(len(text_regions) - 1):
            curr = text_regions[i]
            next_r = text_regions[i + 1]

            curr_bottom = curr.bbox[1] + curr.bbox[3]
            next_top = next_r.bbox[1]
            gap = next_top - curr_bottom

            if gap > gap_threshold and gap < page_height * 0.5:
                # 间隙足够大，标记为可能的图片区域
                region_height = min(gap, page_height * 0.4)
                image_regions.append(LayoutRegion(
                    type="image",
                    bbox=[
                        max(0, int(page_width * 0.05)),
                        curr_bottom + int(gap * 0.1),
                        int(page_width * 0.9),
                        int(region_height * 0.8),
                    ],
                    confidence=0.5,
                ))

        return image_regions

    def _mark_titles(
        self,
        regions: list[LayoutRegion],
        page_width: int,
    ) -> list[LayoutRegion]:
        """标注标题区域（基于文本特征）"""
        for region in regions:
            if region.type != "text" or not region.text_lines:
                continue

            first_text = region.text_lines[0]["text"]

            # 标题特征：短文本 + 居中/编号模式
            is_short = len(first_text) < 50
            has_numbering = bool(re.match(
                r'^(第[一二三四五六七八九十百千\d]+[章篇节条部])|'
                r'^[一二三四五六七八九十]、|'
                r'^\d+[、.]|'
                r'^（[一二三四五六七八九十\d]）',
                first_text,
            ))

            # 居中检查
            x, _, w, _ = region.bbox
            center_x = x + w / 2
            is_centered = abs(center_x - page_width / 2) < page_width * 0.15

            if is_short and (has_numbering or is_centered):
                region.type = "title"

        return regions

    def detect_all_pages(
        self,
        pages_ocr: list[dict],
        page_dimensions: list[tuple[int, int]] | None = None,
    ) -> list[list[dict]]:
        """
        批量检测多页版面
        Args:
            pages_ocr: [[{text, confidence, bbox}, ...], ...] 每页的OCR结果
            page_dimensions: [(w, h), ...] 每页尺寸
        Returns:
            [[{type, bbox, confidence, ...}, ...], ...]
        """
        results = []
        for i, page_ocr in enumerate(pages_ocr):
            if page_dimensions and i < len(page_dimensions):
                w, h = page_dimensions[i]
            else:
                w, h = DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT  # A4 @ 300 DPI
            results.append(self.detect(page_ocr, w, h))
        logger.info(f"Layout detection complete: {len(results)} pages")
        return results


# 全局单例（保持向后兼容）
layout_detector = LayoutDetector()
