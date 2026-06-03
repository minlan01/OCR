"""
表格识别器
基于 OCR 结果的纯算法表格结构识别
通过 x/y 坐标聚类推断行列结构，输出 HTML + 结构化 cells
"""
from __future__ import annotations

from collections import defaultdict

from loguru import logger


def _cluster_1d(values: list[float], threshold: float) -> list[float]:
    """
    一维聚类：将相近的值合并为组中心
    Args:
        values: 待聚类的值列表
        threshold: 合并阈值（同一组内最大间距）
    Returns:
        排序后的组中心列表
    """
    if not values:
        return []

    sorted_vals = sorted(set(values))
    clusters = []
    current_cluster = [sorted_vals[0]]

    for v in sorted_vals[1:]:
        if v - current_cluster[-1] <= threshold:
            current_cluster.append(v)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [v]

    if current_cluster:
        clusters.append(sum(current_cluster) / len(current_cluster))

    return clusters


def _estimate_font_height(items: list[dict]) -> float:
    """从OCR结果估算字体高度"""
    heights = []
    for item in items:
        bbox = item.get("bbox", [])
        if bbox and isinstance(bbox[0], list) and len(bbox) == 4:
            heights.append(bbox[2][1] - bbox[0][1])  # bottom_y - top_y
        elif isinstance(bbox, list) and len(bbox) == 4:
            heights.append(bbox[3])  # h

    if not heights:
        return 20  # 默认20px

    return sum(heights) / len(heights)


def _get_cell_rect(item: dict) -> tuple[float, float, float, float]:
    """获取OCR结果的矩形 (center_x, center_y, top, bottom)"""
    bbox = item.get("bbox", [])

    if isinstance(bbox[0], list) and len(bbox) == 4:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        top = min(ys)
        bottom = max(ys)
        left = min(xs)
        return (cx, cy, top, bottom, left)
    elif isinstance(bbox, list) and len(bbox) == 4:
        x, y, w, h = bbox
        return (x + w / 2, y + h / 2, y, y + h, x)
    else:
        return (0, 0, 0, 0, 0)


def _build_html_table(
    cells: list[list[str]],
    merge_info: list[dict] | None = None,
    table_class: str = "scanstruct-table",
) -> str:
    """
    构建语义化 HTML 表格

    Args:
        cells: 二维单元格文本
        merge_info: 合并信息列表 [{"row": 0, "col": 0, "rowspan": 2, "colspan": 3}, ...]
        table_class: CSS 类名，默认 "scanstruct-table"

    Returns:
        HTML 表格字符串，含 <thead>/<tbody> 语义标签
    """
    if not cells:
        return f'<table class="{table_class}"></table>'

    # 构建合并索引
    merge_map: dict[tuple[int, int], dict] = {}
    if merge_info:
        for m in merge_info:
            key = (m.get("row", 0), m.get("col", 0))
            merge_map[key] = {
                "rowspan": m.get("rowspan", 1),
                "colspan": m.get("colspan", 1),
            }

    # 追踪已合并覆盖的单元格
    covered: set[tuple[int, int]] = set()
    for (r, c), info in merge_map.items():
        for dr in range(info["rowspan"]):
            for dc in range(info["colspan"]):
                if dr != 0 or dc != 0:
                    covered.add((r + dr, c + dc))

    html_parts = [f'<table class="{table_class}">']

    # 第一行作为表头
    has_header = len(cells) >= 2

    if has_header:
        html_parts.append("<thead>")
        html_parts.extend(_render_row(cells[0], 0, merge_map, covered))
        html_parts.append("</thead>")
        html_parts.append("<tbody>")
        body_start = 1
    else:
        html_parts.append("<tbody>")
        body_start = 0

    for ri in range(body_start, len(cells)):
        html_parts.extend(_render_row(cells[ri], ri, merge_map, covered))

    html_parts.append("</tbody>")
    html_parts.append("</table>")
    return "\n".join(html_parts)


def _render_row(
    row: list[str],
    row_idx: int,
    merge_map: dict[tuple[int, int], dict],
    covered: set[tuple[int, int]],
) -> list[str]:
    """
    渲染单行 HTML，处理合并单元格

    Args:
        row: 行数据
        row_idx: 行索引
        merge_map: {(row, col): {rowspan, colspan}}
        covered: 被合并覆盖的单元格坐标集合

    Returns:
        HTML 行片段列表
    """
    parts = ["<tr>"]
    col_idx = 0
    while col_idx < len(row):
        if (row_idx, col_idx) in covered:
            col_idx += 1
            continue

        cell_text = row[col_idx]
        display = cell_text[:200]
        if len(cell_text) > 200:
            display += "..."

        # 合并属性
        attrs = ""
        merge_key = (row_idx, col_idx)
        if merge_key in merge_map:
            info = merge_map[merge_key]
            rs, cs = info["rowspan"], info["colspan"]
            if rs > 1:
                attrs += f' rowspan="{rs}"'
            if cs > 1:
                attrs += f' colspan="{cs}"'

        parts.append(f"<td{attrs}>{display}</td>")
        col_idx += 1

    parts.append("</tr>")
    return parts


def recognize_table(
    ocr_items: list[dict],
    region_bbox: list[int] | None = None,
) -> dict:
    """
    识别表格结构

    算法：
    1. 对 OCR 结果按 Y 坐标聚类 → 行
    2. 对每行内的文本按 X 坐标聚类 → 列
    3. 构建 cell 网格
    4. 生成 HTML 输出

    Args:
        ocr_items: 表格区域内的 OCR 结果 [{text, confidence, bbox}, ...]
        region_bbox: 表格区域 bbox [x, y, w, h]（可选）

    Returns:
        {
            "html": str,       # HTML表格
            "rows": int,        # 行数
            "cols": int,        # 列数
            "cells": [[str]],   # 二维网格
            "cell_details": [[{text, confidence, bbox}]],  # 详细单元格
            "confidence_avg": float,
        }
    """
    if not ocr_items or len(ocr_items) < 2:
        return {"html": "", "rows": 0, "cols": 0, "cells": [], "cell_details": [], "confidence_avg": 0.0}

    # 估算字体高度用于阈值
    font_height = _estimate_font_height(ocr_items)
    row_threshold = font_height * 1.2   # 行聚类阈值
    col_threshold = font_height * 0.8   # 列聚类阈值（列间距通常比行间距小）

    # 1. 获取每个item的中心Y → 行聚类
    items_with_pos = []
    for item in ocr_items:
        cx, cy, top, bottom, left = _get_cell_rect(item)
        items_with_pos.append({
            "text": item.get("text", ""),
            "confidence": item.get("confidence", 0),
            "bbox": item.get("bbox", []),
            "cx": cx, "cy": cy, "top": top, "bottom": bottom, "left": left,
        })

    # 按Y排序
    items_with_pos.sort(key=lambda x: x["top"])

    # 行聚类
    row_ys = _cluster_1d([it["cy"] for it in items_with_pos], row_threshold)

    # 2. 分配每个item到行
    rows_items: list[list[dict]] = [[] for _ in row_ys]
    for item in items_with_pos:
        # 找最近的行中心
        best_row = min(range(len(row_ys)), key=lambda i: abs(item["cy"] - row_ys[i]))
        rows_items[best_row].append(item)

    # 3. 对每行进行列聚类
    all_col_xs = []
    for row in rows_items:
        if row:
            col_xs = _cluster_1d([it["cx"] for it in row], col_threshold)
            all_col_xs.extend(col_xs)

    # 全局列（合并所有行的列X中心）
    if all_col_xs:
        global_cols = _cluster_1d(all_col_xs, col_threshold * 1.5)
    else:
        global_cols = []

    # 4. 构建网格
    num_rows = len(rows_items)
    num_cols = len(global_cols)

    cells: list[list[str]] = []
    cell_details: list[list[dict]] = []

    for row_idx, row in enumerate(rows_items):
        row_cells = [""] * max(num_cols, 1)
        row_details: list[list[dict]] = [[] for _ in range(max(num_cols, 1))]

        for item in row:
            if not global_cols:
                col_idx = 0
            else:
                col_idx = min(range(len(global_cols)), key=lambda i: abs(item["cx"] - global_cols[i]))

            # 合并同单元格文本
            existing = row_cells[col_idx]
            if existing:
                row_cells[col_idx] = existing + " " + item["text"]
            else:
                row_cells[col_idx] = item["text"]
            row_details[col_idx].append({
                "text": item["text"],
                "confidence": item["confidence"],
                "bbox": item["bbox"],
            })

        cells.append(row_cells)
        cell_details.append(row_details)

    # 5. 清理空行/空列
    cells = _trim_empty_rows_cols(cells)

    # 6. 生成HTML
    html = _build_html_table(cells)

    # 7. 计算平均置信度
    all_confs = [it["confidence"] for it in items_with_pos]
    confidence_avg = round(sum(all_confs) / len(all_confs), 4) if all_confs else 0.0

    rows = len(cells)
    cols = max(len(row) for row in cells) if cells else 0

    logger.debug(f"Table recognized: {rows}x{cols}, confidence={confidence_avg:.3f}")

    return {
        "html": html,
        "rows": rows,
        "cols": cols,
        "cells": cells,
        "cell_details": cell_details[:rows] if cell_details else [],
        "confidence_avg": confidence_avg,
    }


def _trim_empty_rows_cols(cells: list[list[str]]) -> list[list[str]]:
    """移除空行和空列"""
    if not cells:
        return cells

    # 移除空行
    cells = [row for row in cells if any(cell.strip() for cell in row)]

    if not cells:
        return cells

    # 移除空列
    max_cols = max(len(row) for row in cells)
    non_empty_cols = []
    for ci in range(max_cols):
        has_content = any(
            ci < len(row) and row[ci].strip()
            for row in cells
        )
        if has_content:
            non_empty_cols.append(ci)

    if not non_empty_cols:
        return cells

    trimmed = []
    for row in cells:
        new_row = []
        for ci in non_empty_cols:
            if ci < len(row):
                new_row.append(row[ci])
            else:
                new_row.append("")
        trimmed.append(new_row)

    return trimmed
