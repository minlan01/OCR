"""
PDF 拆页服务
- 扫描 PDF：直接提取嵌入图片（极快，无需重新渲染）
- 文字 PDF：并行渲染为指定 DPI 的图片
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings
from services.constants import DEFAULT_DPI


def _render_page(
    pdf_path_str: str,
    page_num: int,
    output_dir_str: str,
    dpi: float,
    use_jpeg: bool,
    prefer_extract: bool,
) -> tuple[int, Optional[Path]]:
    """线程内渲染单个页面"""
    import fitz

    doc = fitz.open(pdf_path_str)
    page = doc[page_num]
    output_path = Path(output_dir_str) / f"page_{page_num + 1:04d}"

    try:
        if prefer_extract:
            extracted = _try_extract_image_static(doc, page, output_path)
            if extracted:
                logger.debug(f"Page {page_num + 1}: extracted embedded image (skipped render)")
                doc.close()
                return (page_num, extracted)

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        if use_jpeg:
            out = output_path.with_suffix(".jpg")
            pix.save(str(out), output="JPEG", jpg_quality=80)
        else:
            out = output_path.with_suffix(".png")
            pix.save(str(out))
        doc.close()
        return (page_num, out)
    except Exception:
        doc.close()
        raise


def _try_extract_image_static(doc, page, output_path: Path, min_dpi: int = 150) -> Optional[Path]:
    """静态版本：线程内提取嵌入图片

    仅在嵌入图的有效 DPI >= min_dpi 时才直提（避免低分辨率图影响 OCR）。
    有效 DPI = 图片像素宽度 / (页面宽度(inch))，页面默认 72pt = 1 inch。
    """
    import fitz

    image_list = page.get_images(full=True)
    if not image_list:
        return None

    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return None

    best_img_info = None
    best_coverage = 0.0

    for img_info in image_list:
        xref = img_info[0]
        try:
            img_rects = page.get_image_rects(xref)
        except Exception:
            continue
        if not img_rects:
            continue
        total_img_area = sum(r.width * r.height for r in img_rects)
        coverage = total_img_area / page_area
        if coverage > best_coverage:
            best_coverage = coverage
            best_img_info = img_info

    if best_img_info is None or best_coverage < 0.85:
        return None

    # 检查嵌入图的有效 DPI
    xref = best_img_info[0]
    try:
        base_image = doc.extract_image(xref)
    except Exception:
        return None
    if not base_image:
        return None

    img_width = base_image.get("width", 0)
    page_width_inches = page_rect.width / 72.0
    if page_width_inches > 0 and img_width > 0:
        effective_dpi = img_width / page_width_inches
        if effective_dpi < min_dpi:
            logger.debug(
                f"Page {page.number + 1}: embedded image DPI={effective_dpi:.0f} < {min_dpi}, "
                f"will render instead"
            )
            return None

    smask = best_img_info[1] if len(best_img_info) > 1 else 0

    img_ext = base_image.get("ext", "png")
    img_bytes = base_image.get("image")
    if not img_bytes:
        return None

    if smask:
        try:
            img_bytes = _apply_smask_static(doc, img_bytes, smask)
            if img_bytes:
                img_ext = "png"
        except Exception:
            pass

    out = output_path.with_suffix(f".{img_ext}")
    out.write_bytes(img_bytes)
    return out


def _apply_smask_static(doc, img_bytes: bytes, smask_xref: int) -> Optional[bytes]:
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        smask_data = doc.extract_image(smask_xref)
        if not smask_data or not smask_data.get("image"):
            return None
        mask = Image.open(io.BytesIO(smask_data["image"]))
        if mask.size != img.size:
            mask = mask.resize(img.size, Image.LANCZOS)
        if img.mode == "RGB":
            img = img.convert("RGBA")
        elif img.mode != "RGBA":
            img = img.convert("RGBA")
        img.putalpha(mask.convert("L"))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return None


class PDFSplitter:
    """PDF 拆页器 — 使用 PyMuPDF，自动检测并优先提取嵌入图片"""

    def __init__(self, dpi: int = DEFAULT_DPI, output_format: str = "auto"):
        self.dpi = dpi or settings.preprocess_dpi
        self.output_format = output_format

    def split_to_images(
        self,
        pdf_path: Path,
        output_dir: Path,
        start_page: int = 1,
        end_page: Optional[int] = None,
        prefer_extract: bool = True,
    ) -> list[Path]:
        """
        将 PDF 拆分为图片，并行渲染 4 页
        """
        import fitz

        output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        total_pages = doc.page_count
        doc.close()

        if end_page is None:
            end_page = total_pages
        end_page = min(end_page, total_pages)

        use_jpeg = self.output_format in ("jpeg", "jpg") or (
            self.output_format == "auto" and settings.ocr_engine_type in ("bailian", "dashscope", "qwen")
        )

        total_to_process = end_page - (start_page - 1)
        image_paths: list[Optional[Path]] = [None] * total_to_process

        with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as pool:
            futures = {}
            for page_idx, page_num in enumerate(range(start_page - 1, end_page)):
                f = pool.submit(
                    _render_page,
                    str(pdf_path),
                    page_num,
                    str(output_dir),
                    self.dpi,
                    use_jpeg,
                    prefer_extract,
                )
                futures[f] = page_idx

            for future in as_completed(futures):
                page_idx = futures[future]
                try:
                    _, out_path = future.result()
                    image_paths[page_idx] = out_path
                except Exception as e:
                    logger.warning(f"Split page {start_page + page_idx} failed: {e}")

        result = [p for p in image_paths if p is not None]
        extracted_count = sum(1 for p in image_paths if p is not None and "extracted" in str(getattr(p, '_extracted', '')))
        logger.info(
            f"PDF split: {pdf_path.name} -> {len(result)} pages "
            f"(parallel {min(os.cpu_count() or 4, 8)} workers, dpi={self.dpi}, "
            f"prefer_extract={prefer_extract})"
        )
        return result

    def split_to_bytes(
        self,
        pdf_data: bytes,
        start_page: int = 1,
        end_page: Optional[int] = None,
    ) -> list[bytes]:
        """
        从 PDF 字节流拆页，返回每页图片字节
        """
        import fitz

        doc = fitz.open(stream=pdf_data, filetype="pdf")
        total_pages = doc.page_count

        if end_page is None:
            end_page = total_pages

        zoom = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        images = []

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            images.append(pix.tobytes("png"))

        doc.close()
        return images
