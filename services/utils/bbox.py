"""
BBox 坐标转换工具

将 OCR 输出的 bbox 格式统一转为矩形 (x, y, w, h)。
"""
from __future__ import annotations


def bbox_to_rect(bbox: list) -> tuple[int, int, int, int]:
    """
    将四点 bbox 或 [x,y,w,h] 转为 (x, y, w, h)

    Args:
        bbox: bbox 数据

    Returns:
        (x, y, w, h) 元组，无效时返回 (0, 0, 0, 0)
    """
    if not bbox:
        return (0, 0, 0, 0)

    if isinstance(bbox[0], (list, tuple)):
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
    elif len(bbox) >= 4:
        x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
    else:
        return (0, 0, 0, 0)

    return (int(x), int(y), int(w), int(h))
