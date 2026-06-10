"""
OCR 引擎共享工具

包含:
  - OCR_SYSTEM_PROMPT: 统一 OCR 提示词
  - 图片压缩/转换工具: _compress_jpeg, _compress_png_to_jpeg, _image_to_base64_url
"""
from __future__ import annotations

import base64
from pathlib import Path


OCR_SYSTEM_PROMPT = (
    "你是一个精确的OCR文字识别引擎。请逐行识别图片中的所有文字，"
    "以JSON数组格式返回每个文本块。每个元素的格式为：\n"
    '{"text": "文字内容", "bbox": [x1, y1, x2, y2, x3, y3, x4, y4]}\n'
    "bbox为顺时针四个顶点的像素坐标。只返回JSON数组，不要任何额外说明。"
    "对于表格，将每个单元格作为独立的文本块。"
)


def _compress_jpeg(
    image_path: Path,
    quality: int = 75,
    max_long_side: int = 1800,
) -> bytes:
    """压缩 JPEG 图片，长边超过 max_long_side 时缩放"""
    try:
        import io
        from PIL import Image

        with Image.open(str(image_path)) as img:
            w, h = img.size
            if max(w, h) > max_long_side:
                ratio = max_long_side / max(w, h)
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue()

    except Exception:
        with open(image_path, "rb") as f:
            return f.read()


def _compress_png_to_jpeg(
    image_path: Path,
    quality: int = 75,
    max_long_side: int = 1800,
) -> bytes:
    """将 PNG 转换为 JPEG 并压缩，长边超过 max_long_side 时缩放"""
    try:
        import io
        from PIL import Image

        with Image.open(str(image_path)) as img:
            if img.mode == "RGBA":
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            if max(w, h) > max_long_side:
                ratio = max_long_side / max(w, h)
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    except Exception:
        with open(image_path, "rb") as f:
            return f.read()


def _image_to_base64_url(image_path: Path) -> str:
    """将图片转为 Base64 data URL（自动压缩大图）"""
    suffix = image_path.suffix.lower()

    img_bytes: bytes
    if suffix == ".png":
        img_bytes = _compress_png_to_jpeg(image_path)
        mime = "image/jpeg"
    elif suffix in (".jpg", ".jpeg"):
        img_bytes = _compress_jpeg(image_path)
        mime = "image/jpeg"
    else:
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        mime_map = {
            ".webp": "image/webp",
        }
        mime = mime_map.get(suffix, "image/jpeg")

    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"
