"""
纯文字 PDF 快速提取
检测到纯文字 PDF 时走此路径，跳过 OCR
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger


class TextPDFExtractor:
    """纯文字 PDF 文本提取器"""

    def extract(self, pdf_path: Path) -> dict:
        """
        从纯文字 PDF 中提取所有文本
        返回按页组织的文字内容
        """
        import fitz

        doc = fitz.open(str(pdf_path))
        pages_data = []

        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text("text")  # 纯文本
            text_blocks = page.get_text("blocks")  # 按块提取（含坐标）

            blocks = []
            for block in text_blocks:
                if block[6] == 0:  # type 0 = text
                    blocks.append({
                        "bbox": list(block[:4]),
                        "text": block[4].strip(),
                    })

            pages_data.append({
                "page": page_num + 1,
                "width": int(page.rect.width),
                "height": int(page.rect.height),
                "text": text.strip(),
                "blocks": blocks,
            })

        doc.close()
        logger.info(f"Text PDF extracted: {pdf_path.name} -> {len(pages_data)} pages")
        return {"page_count": len(pages_data), "pages": pages_data}

    def extract_structured(self, pdf_path: Path) -> dict:
        """
        从纯文字 PDF 提取文本并做初步结构化

        基于字体大小和粗体标识推断标题候选，输出结构化数据供 heading_parser 使用。

        Args:
            pdf_path: PDF 文件路径

        Returns:
            字典包含:
            - page_count: 总页数
            - pages: 按页组织的文本块列表 [{page, width, height, blocks}]
            - font_size_distribution: 字体大小分布统计
            - heading_candidates: 推断的标题候选列表 [{text, font_size, page, is_bold}]
        """
        import fitz

        doc = fitz.open(str(pdf_path))
        pages_data = []
        all_text = []

        for page_num in range(doc.page_count):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]

            page_blocks = []
            for block in blocks:
                if block["type"] != 0:  # 非文本块跳过
                    continue

                for line in block["lines"]:
                    text = "".join([span["text"] for span in line["spans"]])
                    if not text.strip():
                        continue

                    # 取第一个 span 的字体信息
                    span = line["spans"][0]
                    font_size = span.get("size", 12)
                    font_name = span.get("font", "")
                    is_bold = "bold" in font_name.lower() or "black" in font_name.lower()

                    page_blocks.append({
                        "bbox": list(line["bbox"]),
                        "text": text.strip(),
                        "font_size": round(font_size, 1),
                        "is_bold": is_bold,
                        "page": page_num + 1,
                    })

            # 按 y 坐标排序（阅读顺序）
            page_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

            pages_data.append({
                "page": page_num + 1,
                "width": int(page.rect.width),
                "height": int(page.rect.height),
                "blocks": page_blocks,
            })

            all_text.extend(page_blocks)

        doc.close()

        # 基于字体大小推断标题层级
        font_sizes = sorted(set(b["font_size"] for b in all_text), reverse=True)
        title_candidates = self._infer_headings(all_text, font_sizes)

        return {
            "page_count": len(pages_data),
            "pages": pages_data,
            "font_size_distribution": [{"size": s, "count": sum(1 for b in all_text if b["font_size"] == s)} for s in font_sizes[:10]],
            "heading_candidates": title_candidates,
        }

    def _infer_headings(self, blocks: list, font_sizes: list[float]) -> list[dict]:
        """根据字体大小推断标题"""
        if len(font_sizes) < 2:
            return []

        # 最大的字体可能是标题
        max_size = font_sizes[0]
        heading_threshold = max_size * 0.8  # 80% 以上最大字体视为标题

        headings = []
        for b in blocks:
            if b["font_size"] >= heading_threshold or b["is_bold"]:
                headings.append({
                    "text": b["text"],
                    "font_size": b["font_size"],
                    "page": b["page"],
                    "is_bold": b["is_bold"],
                })

        return headings


text_extractor = TextPDFExtractor()
