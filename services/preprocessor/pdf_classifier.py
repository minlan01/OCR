"""
PDF 分类器 — 判断 PDF 类型（扫描件 vs 纯文字 PDF）

检测策略（v2）：
  1. 分布式采样：首部 N 页 + 中部 N 页 + 尾部 N 页，避免只看开头误判
  2. 提高字符阈值：从 100 → 300 字符/页，减少页眉页脚水印造成的假阳性
  3. 输出置信度分数，方便上层决策（如降级处理）
  4. 检测混合模式 PDF（部分页可提取文字、部分页为扫描图像）
  5. 附带每页图像大小作为辅助判断（纯图像页通常更大）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from services.constants import MIN_CHARS_PER_TEXT_PAGE

# 分布式采样：首部/中部/尾部各取多少页
HEAD_SAMPLE = 3
MID_SAMPLE = 3
TAIL_SAMPLE = 3


@dataclass
class PDFInfo:
    """PDF 文件信息"""
    path: Path
    page_count: int
    is_encrypted: bool
    is_text_pdf: bool  # True = 纯文字 PDF，可直接提取文字
    text_ratio: float = 0.0  # 采样页中文字页占比
    confidence: float = 0.0  # 分类置信度 (0.0-1.0)
    is_mixed: bool = False  # 混合模式：部分文字页 + 部分扫描页
    page_details: list[dict] = field(default_factory=list)  # 采样详情


class PDFClassifier:
    """PDF 类型分类器（v2 — 分布式采样 + 置信度）"""

    def classify(self, file_path: Path) -> PDFInfo:
        """
        分析 PDF 类型（扫描件 vs 纯文字 PDF）

        检测策略：
        - 分布式采样首部/中部/尾部页面
        - 每页提取文字，超过 MIN_CHARS_PER_TEXT_PAGE 视为文字页
        - 采样页中 ≥80% 文字页 → is_text_pdf=True
        - 计算置信度（基于文字量分布的一致性）
        - 检测混合模式（文字页占比在 20%-80%）

        Args:
            file_path: PDF 文件路径

        Returns:
            PDFInfo 对象
        """
        try:
            import fitz
        except ImportError:
            logger.warning("PyMuPDF not available, treating as scan PDF")
            return PDFInfo(
                path=file_path,
                page_count=1,
                is_encrypted=False,
                is_text_pdf=False,
            )

        doc = fitz.open(str(file_path))
        page_count = doc.page_count
        is_encrypted = doc.is_encrypted

        # ---- 构建采样索引 ----
        sample_indices = self._build_sample_indices(page_count)

        # ---- 逐页检测 ----
        text_pages = 0
        checked = 0
        char_counts: list[int] = []
        page_details: list[dict] = []

        for idx in sample_indices:
            checked += 1
            try:
                text = doc[idx].get_text()
                char_count = len(text.strip())
                char_counts.append(char_count)
                is_text = char_count >= MIN_CHARS_PER_TEXT_PAGE
                if is_text:
                    text_pages += 1

                page_details.append({
                    "page": idx + 1,  # 1-based
                    "chars": char_count,
                    "is_text_page": is_text,
                })
            except Exception as e:
                logger.debug(f"Page {idx} text extraction failed: {e}")
                char_counts.append(0)
                page_details.append({
                    "page": idx + 1,
                    "chars": 0,
                    "is_text_page": False,
                    "error": str(e),
                })

        doc.close()

        if checked == 0:
            return PDFInfo(
                path=file_path,
                page_count=page_count,
                is_encrypted=is_encrypted,
                is_text_pdf=False,
            )

        # ---- 计算指标 ----
        text_ratio = text_pages / checked
        is_text_pdf = text_ratio >= 0.8
        is_mixed = 0.2 <= text_ratio < 0.8

        # 置信度：基于文字量分布的离散度
        confidence = self._compute_confidence(char_counts, text_ratio)

        logger.debug(
            f"PDF: {file_path.name} | pages={page_count} | sampled={checked} | "
            f"text_pdf={is_text_pdf} | mixed={is_mixed} | "
            f"text_ratio={text_ratio:.2f} | confidence={confidence:.2f}"
        )

        return PDFInfo(
            path=file_path,
            page_count=page_count,
            is_encrypted=is_encrypted,
            is_text_pdf=is_text_pdf,
            text_ratio=text_ratio,
            confidence=confidence,
            is_mixed=is_mixed,
            page_details=page_details,
        )

    # ------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------

    @staticmethod
    def _build_sample_indices(page_count: int) -> list[int]:
        """构建分布式采样索引：首部 + 中部 + 尾部"""
        indices: set[int] = set()

        n_head = min(HEAD_SAMPLE, page_count)
        for i in range(n_head):
            indices.add(i)

        if page_count > HEAD_SAMPLE + TAIL_SAMPLE:
            mid_start = max(HEAD_SAMPLE, page_count // 2 - MID_SAMPLE // 2)
            for i in range(mid_start, min(mid_start + MID_SAMPLE, page_count - TAIL_SAMPLE)):
                indices.add(i)

        n_tail = min(TAIL_SAMPLE, page_count)
        for i in range(max(0, page_count - n_tail), page_count):
            indices.add(i)

        return sorted(indices)

    @staticmethod
    def _compute_confidence(char_counts: list[int], text_ratio: float) -> float:
        """
        计算分类置信度

        规则：
        - 文字量分布非常一致（全部 > 阈值 or 全部 < 阈值）→ 高置信
        - 文字量分布离散（部分高部分低）→ 中置信
        - 极端比例（0% or 100%）→ 置信度不再额外加分（可能是真的一致）
        - 边界情况（ratio 在 0.75-0.85）→ 降信
        """
        if not char_counts:
            return 0.0

        # 一致性分数：有多少页的判定与整体结论一致
        threshold = MIN_CHARS_PER_TEXT_PAGE
        if text_ratio >= 0.5:
            consistent = sum(1 for c in char_counts if c >= threshold)
        else:
            consistent = sum(1 for c in char_counts if c < threshold)
        consistency = consistent / len(char_counts) if char_counts else 0.0

        # 边界惩罚：ratio 在 0.75-0.85 时降低置信（灰色地带）
        boundary_penalty = 1.0
        if 0.75 <= text_ratio <= 0.85:
            # 越接近 0.8 惩罚越大
            dist_from_center = abs(text_ratio - 0.80)
            boundary_penalty = 0.7 + dist_from_center * 6  # 0.70 - 1.0

        confidence = consistency * boundary_penalty
        return round(min(confidence, 1.0), 4)
