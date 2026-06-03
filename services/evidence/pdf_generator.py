"""
PDF 证据材料导出 — 反向溯源智能选页

核心逻辑：
1. 民事起诉状已生成，包含具体医疗内容（入院、诊疗、鉴定等）
2. 反向分析：从起诉状内容提取关键词 → 匹配病历/鉴定PDF的哪些页包含这些内容
3. 证据材料PDF只包含6大类，且病历/鉴定/资质只放引用到的页

6大类：
  一、原告身份证信息（身份证+户口本）
  二、被告信息（医院）
  三、其他身份证明（结婚证、死亡证明书）
  四、对应内容的病历（反向选页）
  五、对应内容的司法鉴定报告（反向选页）
  六、对应内容的医疗人员资质证明（反向选页）

不包含：fee_receipt、other_evidence
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Any

from loguru import logger

MINIO_BUCKET = "scan-result"

# 中文字体注册标记
_FONT_REGISTERED = False

# 身份证明类别（小图网格，需要身份证配对等特殊处理）
IDENTITY_CATEGORIES_FULL = {
    "identity_id_card",
    "identity_hukou",
    "identity_other",
    "identity_defendant",
}

# 大文档类别（PDF需要反向选页）
DOCUMENT_CATEGORIES = {
    "medical_record",
    "death_certificate",
    "appraisal",
}

# ========== 输出分组定义（6大类） ==========
# 每个分组的标签和是否需要智能选页
OUTPUT_GROUPS = [
    ("plaintiff_id",     "一、原告身份证信息",              False),
    ("defendant",        "二、被告信息（医院）",            False),
    ("other_identity",   "三、其他身份证明（结婚证、死亡证明书）", False),
    ("medical",          "四、对应内容的病历",              True),
    ("appraisal",        "五、对应内容的司法鉴定报告",      True),
    ("staff_qual",       "六、对应内容的医疗人员资质证明",  True),
]


def _get_output_group(cat_code: str, filename: str) -> tuple[str | None, bool]:
    """根据原始分类和文件名，映射到6大输出分组

    Returns:
        (group_id, smart_select) — group_id=None 表示排除（fee_receipt/other_evidence）
    """
    fname = filename or ""

    # 文件名优先覆盖（处理分类器误判和特殊文件）
    if "资质" in fname or "资格" in fname:
        return ("staff_qual", True)
    if "死亡证明" in fname or "死亡医学" in fname:
        return ("other_identity", False)

    # 按分类映射
    if cat_code in ("identity_id_card", "identity_hukou"):
        return ("plaintiff_id", False)
    if cat_code == "identity_defendant":
        return ("defendant", False)
    if cat_code in ("identity_other", "death_certificate"):
        return ("other_identity", False)
    if cat_code == "medical_record":
        return ("medical", True)
    if cat_code == "appraisal":
        return ("appraisal", True)

    # 排除 fee_receipt / other_evidence
    return (None, False)


def _ensure_chinese_font() -> str:
    """确保中文字体已注册，返回字体名称"""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return "ChineseFont"

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_candidates = [
        ("/app/fonts/simhei.ttf", "ChineseFont"),
        ("/app/fonts/NotoSansSC-Regular.ttf", "ChineseFont"),
        ("/app/fonts/SourceHanSansSC-Regular.otf", "ChineseFont"),
        ("C:/Windows/Fonts/msyh.ttc", "ChineseFont"),
        ("C:/Windows/Fonts/simsun.ttc", "ChineseFont"),
        ("C:/Windows/Fonts/simhei.ttf", "ChineseFont"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "ChineseFont"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "ChineseFont"),
        ("/System/Library/Fonts/PingFang.ttc", "ChineseFont"),
    ]

    for fp, name in font_candidates:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont(name, fp))
                _FONT_REGISTERED = True
                logger.info(f"Registered Chinese font: {name} from {fp}")
                return name
            except Exception as e:
                logger.debug(f"Failed to register font {fp}: {e}")
                continue

    logger.warning("No Chinese font found, PDF may not render Chinese correctly")
    _FONT_REGISTERED = True
    return "Helvetica"


# ========== PDF 渲染 ==========

def _render_pdf_pages_to_images(
    pdf_bytes: bytes, dpi: int = 100, max_pages: int = 200
) -> list[tuple[bytes, int, int, bool]]:
    """将 PDF 每页渲染为 JPEG 图片

    Returns:
        list of (jpeg_bytes, width, height, is_naturally_portrait)
    """
    import fitz

    results: list[tuple[bytes, int, int, bool]] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            page_count = min(len(doc), max_pages)
            for page_num in range(page_count):
                page = doc[page_num]
                page_rect = page.rect
                pw_src, ph_src = page_rect.width, page_rect.height
                naturally_portrait = ph_src > pw_src

                pix = page.get_pixmap(matrix=mat)
                pw, ph = pix.width, pix.height
                img_bytes = pix.tobytes("jpeg", jpg_quality=50)
                results.append((img_bytes, pw, ph, naturally_portrait))
            if len(doc) > max_pages:
                logger.warning(f"PDF has {len(doc)} pages, only rendered first {max_pages}")
    except Exception as e:
        logger.error(f"Failed to render PDF pages: {e}")
    return results


# ========== 图片方向检测与回正 ==========

def _detect_needs_rotation(img_bytes: bytes, w: int, h: int, aggressive: bool = False) -> bool:
    """内容梯度分析：判断横版图片是否应旋转为竖版

    策略：
    - aggressive=False（身份证明类）：保守阈值 0.35，避免误转身份证
    - aggressive=True（病历/鉴定/费用类）：放宽阈值 0.7，确保文档正位

    Returns:
        True 表示需要逆时针旋转 90°
    """
    import numpy as np
    from PIL import Image as PILImage

    if w <= h:
        return False

    ratio = h / w

    # 仅处理文档比例范围（A4旋转后≈0.707, Letter≈0.773）
    if not (0.50 <= ratio <= 0.95):
        return False

    # 排除太小的图片
    if w < 400 or h < 200:
        return False

    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        target_w = 300
        target_h = max(80, int(target_w * ratio))
        img_small = img.resize((target_w, target_h), PILImage.LANCZOS).convert("L")

        arr = np.array(img_small, dtype=np.float64)

        row_means = arr.mean(axis=1)
        row_std = np.std(row_means)

        col_means = arr.mean(axis=0)
        col_std = np.std(col_means)

        if row_std < 2.0 or col_std < 2.0:
            return False

        std_ratio = row_std / col_std if col_std > 0 else 0

        # 阈值：aggressive 模式放宽，保守模式严格
        threshold = 0.70 if aggressive else 0.35
        needs_rotation = std_ratio < threshold

        if needs_rotation:
            logger.debug(
                f"Content rotation: row_std/col_std={std_ratio:.3f}, "
                f"threshold={threshold}, aggressive={aggressive}, size=({w},{h})"
            )

        return needs_rotation
    except Exception as e:
        logger.debug(f"Content orientation detection failed: {e}")
        return False


def _auto_orient_image(img_bytes: bytes, aggressive: bool = False) -> tuple[bytes, int, int]:
    """自动回正图片方向：EXIF → 内容分析

    级联策略：
    1. EXIF Orientation 标签（手机拍照）
    2. 内容梯度分析（扫描件，无 EXIF）

    Args:
        aggressive: True = 放宽内容旋转检测阈值（用于非身份证明类文档）

    返回 (oriented_jpeg_bytes, width, height)
    """
    from PIL import Image as PILImage
    from PIL import ImageOps

    img = PILImage.open(io.BytesIO(img_bytes))
    original_size = img.size
    was_exif_rotated = False

    # 方法1: Pillow 内置 EXIF 转置
    try:
        img = ImageOps.exif_transpose(img)
        if img.size != original_size:
            was_exif_rotated = True
    except Exception:
        pass

    # 方法2: 手动 EXIF 方向标签兜底
    if not was_exif_rotated:
        try:
            exif = img.getexif()
            if exif:
                orientation = exif.get(0x0112)
                if orientation is not None and orientation != 1:
                    rotate_map = {
                        3: 180,
                        6: 270,
                        8: 90,
                    }
                    if orientation in rotate_map:
                        img = img.rotate(rotate_map[orientation], expand=True)
                        was_exif_rotated = True
        except Exception:
            pass

    # 方法3: 内容梯度分析（保守/aggressive由参数控制）
    if not was_exif_rotated:
        cw, ch = img.size
        if _detect_needs_rotation(img_bytes, cw, ch, aggressive=aggressive):
            img = img.rotate(90, expand=True)

    w, h = img.size
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), w, h


# ========== 身份证正反面配对 ==========

def _pair_id_card_images(
    id_cards: list[tuple[bytes, int, int, str, str]],
) -> tuple[list[tuple[bytes, int, int, str, str]], list[tuple[bytes, int, int, str, str]]]:
    """将身份证正反面配对并合并为一张图

    配对策略：按文件名中的姓名分组，同一人的正面和反面合并
    正面/反面判断：文件名中包含"正面"或"人像"为正面，"反面"或"国徽"或"背面"为反面

    元组格式: (jpeg_bytes, w, h, title, original_filename)
    title 是 OCR 提取文本（如"中华人民共和国"），original_filename 是原始文件名（如"赵光远正面.jpg"）
    配对时使用 original_filename 判断正反面。

    Returns:
        (paired, remaining) - paired 为合并后的图片列表，remaining 为未配对的
    """
    import re as _re
    from PIL import Image as PILImage

    fronts: dict[str, tuple] = {}  # name → (bytes, w, h, title, filename)
    backs: dict[str, tuple] = {}
    remaining: list[tuple[bytes, int, int, str, str]] = []

    for img_data in id_cards:
        jpeg_bytes, w, h, title, filename = img_data
        # 优先用 original_filename 判断正反面，其次用 title
        name_source = filename if filename else title
        name_lower = name_source.lower()

        # 先去掉正反面关键词，再提取姓名（避免"罗金莲正"和"罗金莲反"不匹配）
        clean_source = _re.sub(r'[正面反面背面国徽人像portraitbacknational]', '', name_source, flags=_re.IGNORECASE)
        name_match = _re.search(r'[\u4e00-\u9fff]{2,4}', clean_source)
        person_name = name_match.group() if name_match else f"unknown_{len(fronts) + len(backs)}"

        is_front = any(kw in name_lower for kw in ["正面", "人像", "portrait"])
        is_back = any(kw in name_lower for kw in ["反面", "背面", "国徽", "back", "national"])

        if is_front:
            fronts[person_name] = img_data
        elif is_back:
            backs[person_name] = img_data
        else:
            # 无法判断正反面，加入 remaining
            remaining.append(img_data)

    # 配对：同名人的正面+反面合并
    paired: list[tuple[bytes, int, int, str, str]] = []
    for name in fronts:
        if name in backs:
            merged = _merge_front_back(fronts[name], backs[name])
            if merged:
                paired.append(merged)
            else:
                remaining.append(fronts[name])
                remaining.append(backs[name])
        else:
            remaining.append(fronts[name])

    # 未配对的反面
    for name in backs:
        if name not in fronts:
            remaining.append(backs[name])

    logger.info(f"ID card pairing: {len(paired)} pairs, {len(remaining)} unpaired")
    return paired, remaining


def _merge_front_back(
    front: tuple[bytes, int, int, str, str],
    back: tuple[bytes, int, int, str, str],
) -> tuple[bytes, int, int, str, str] | None:
    """将身份证正面和反面合并为一张竖版图片（上半=正面，下半=反面）"""
    from PIL import Image as PILImage

    try:
        front_img = PILImage.open(io.BytesIO(front[0]))
        back_img = PILImage.open(io.BytesIO(back[0]))

        # 目标宽度：A4 可用宽度（约 480px）
        target_w = 480
        gap = 20

        # 缩放正面
        ratio_f = target_w / max(front_img.width, 1)
        new_h_f = int(front_img.height * ratio_f)
        front_img = front_img.resize((target_w, new_h_f), PILImage.LANCZOS)

        # 缩放反面
        ratio_b = target_w / max(back_img.width, 1)
        new_h_b = int(back_img.height * ratio_b)
        back_img = back_img.resize((target_w, new_h_b), PILImage.LANCZOS)

        # 合并为一张图
        merged_h = new_h_f + gap + new_h_b
        merged = PILImage.new("RGB", (target_w, merged_h), (255, 255, 255))
        merged.paste(front_img, (0, 0))
        merged.paste(back_img, (0, new_h_f + gap))

        buf = io.BytesIO()
        merged.save(buf, format="JPEG", quality=50)
        return (buf.getvalue(), target_w, merged_h, f"{front[3]}+{back[3]}", f"{front[4]}+{back[4]}")
    except Exception as e:
        logger.error(f"Failed to merge ID card images: {e}")
        return None


def _load_and_resize(
    img_bytes: bytes,
    max_dim: int = 900,
    quality: int = 65,
    skip_rotation: bool = False,
    allow_content_rotation: bool = False,
) -> tuple[bytes, int, int]:
    """统一图片加载：方向修正 + 缩放到 max_dim

    Args:
        img_bytes: 原始图片字节
        max_dim: 最大边长
        quality: JPEG 质量
        skip_rotation: True = 跳过所有方向修正（PDF渲染页已保证方向正确）
        allow_content_rotation: True = 启用内容梯度旋转检测（仅用于大文档扫描件）
    Returns:
        (jpeg_bytes, width, height)
    """
    from PIL import Image as PILImage

    if skip_rotation:
        img = PILImage.open(io.BytesIO(img_bytes))
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        w, h = img.size
    elif allow_content_rotation:
        # 大文档扫描件：EXIF + aggressive 内容检测
        oriented_bytes, w, h = _auto_orient_image(img_bytes, aggressive=True)
        img = PILImage.open(io.BytesIO(oriented_bytes))
    else:
        # 身份证明等小图：仅 EXIF 转置，不做内容检测（防止身份证等格式化文档误判）
        img = PILImage.open(io.BytesIO(img_bytes))
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        w, h = img.size

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    if w > max_dim or h > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
        w, h = img.size

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), w, h


# ========== 反向溯源：提取关键词 & 智能选页 ==========

def _extract_key_phrases(analysis_result: dict[str, Any] | None) -> list[str]:
    """从分析结果中提取关键搜索短语，用于反向匹配病历页

    优先级：
    1. 具体日期（入院、转院、死亡等关键时间节点）
    2. 诊疗措施（具体药物、手术、检查）
    3. 诊断结论（初步诊断、死亡诊断、鉴定结论）
    4. 患者姓名 + 被告医院名
    5. 起诉状段落中的关键短语
    """
    if not analysis_result:
        return []

    phrases: list[str] = []

    # 1. 关键日期（截取日期部分，如"2026-02-02"）
    for d in analysis_result.get("key_dates", []):
        if not isinstance(d, str) or not d.strip():
            continue
        # key_dates 格式: "2026-02-02 13:55 入院"
        parts = d.split()
        if parts:
            phrases.append(parts[0])  # 日期 "2026-02-02"
        if len(parts) >= 2:
            phrases.append(" ".join(parts[:2]))  # "2026-02-02 13:55"

    # 入院日期
    admission_date = analysis_result.get("admission_date", "")
    if admission_date:
        phrases.append(str(admission_date))

    # 死亡日期
    death_date = analysis_result.get("death_date", "")
    if death_date:
        phrases.append(str(death_date))

    # 2. 诊疗措施（每条都是关键短语）
    for t in analysis_result.get("key_treatments", []):
        phrases.append(t)

    # 3. 检查项目
    for e in analysis_result.get("key_examinations", []):
        # 取前20字作为搜索词
        if len(e) > 20:
            phrases.append(e[:20])
        phrases.append(e)

    # 4. 诊断结论
    for field in ("death_diagnosis", "preliminary_diagnosis", "admission_reason",
                  "adverse_outcome", "admission_condition"):
        val = analysis_result.get(field, "")
        if val and isinstance(val, str):
            # 拆分多诊断（用；分隔）
            for part in val.split("；"):
                part = part.strip().lstrip("①②③④⑤⑥⑦⑧⑨⑩")
                if len(part) > 2:
                    phrases.append(part)

    # 5. 鉴定信息
    appraisal = analysis_result.get("appraisal_details", {})
    if isinstance(appraisal, dict):
        for k in ("report_no", "cause_of_death", "appraisal_org"):
            v = appraisal.get(k, "")
            if v:
                phrases.append(str(v))

    # 6. 患者/被告姓名
    patient = analysis_result.get("patient_name", "")
    if patient:
        phrases.append(patient)
    defendant = analysis_result.get("defendant_name", "")
    if defendant:
        phrases.append(defendant)

    # 7. 起诉状段落中提取关键短语（入院段落、诊疗段落等）
    for para_key in ("paragraph_1", "paragraph_2", "paragraph_3", "paragraph_4", "paragraph_5"):
        para_text = analysis_result.get(para_key, "")
        if not para_text or not isinstance(para_text, str):
            continue
        # 按句号拆分，每句作为独立搜索短语
        for sentence in para_text.replace("。", "。\n").split("\n"):
            sentence = sentence.strip()
            if 10 < len(sentence) < 80:
                phrases.append(sentence)

    # 去重并过滤过短的
    seen = set()
    unique = []
    for p in phrases:
        p = p.strip()
        if p and len(p) >= 3 and p not in seen:
            seen.add(p)
            unique.append(p)

    logger.info(f"Extracted {len(unique)} key phrases for reverse page matching")
    return unique


def _find_relevant_pdf_pages(
    pdf_bytes: bytes,
    key_phrases: list[str],
    ocr_text: str | None = None,
    min_matches: int = 1,
) -> list[int]:
    """从PDF中提取每页文本，匹配关键词，返回相关页码

    策略（双通道）：
    通道1: PyMuPDF提取原生文本层 → 精确逐页匹配
    通道2: 如果原生文本为空（扫描件），用数据库OCR文本 + 字符位置估算页码

    保底：如果两个通道都没有匹配，保留首页和末页

    Returns:
        相关页码列表（0-indexed）
    """
    import fitz

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF for text extraction: {e}")
        return list(range(min(5, 200)))

    try:
        total_pages = len(doc)

        # ===== 通道1: 原生文本层 =====
        page_texts: list[str] = []
        for page_num in range(total_pages):
            try:
                text = doc[page_num].get_text()
                page_texts.append(text or "")
            except Exception:
                page_texts.append("")
    finally:
        doc.close()

    has_text = any(t.strip() for t in page_texts)

    if has_text:
        # 原生文本有效 → 逐页精确匹配
        relevant = set()
        for page_num, text in enumerate(page_texts):
            match_count = sum(1 for phrase in key_phrases if phrase in text)
            if match_count >= min_matches:
                relevant.add(page_num)

        if not relevant:
            # 保底：首末页
            relevant = {0}
            if total_pages > 1:
                relevant.add(total_pages - 1)

        logger.info(
            f"PDF page selection (native text): "
            f"{len(relevant)}/{total_pages} pages"
        )
        return sorted(relevant)

    # ===== 通道2: OCR文本 + 位置估算 =====
    if not ocr_text or not ocr_text.strip():
        # 无OCR文本，保底首末页
        logger.info(f"No native text and no OCR text, keeping first+last page")
        result = {0}
        if total_pages > 1:
            result.add(total_pages - 1)
        return sorted(result)

    # 用OCR文本的字符位置估算页码
    # 假设OCR文本按页顺序排列，每页平均字符数 = 总长度 / 总页数
    total_ocr_len = len(ocr_text)
    avg_chars_per_page = max(total_ocr_len / max(total_pages, 1), 100)  # 至少100字/页

    relevant = set()
    for phrase in key_phrases:
        pos = ocr_text.find(phrase)
        if pos >= 0:
            # 估算页码，并前后各扩展1页
            estimated_page = int(pos / avg_chars_per_page)
            for offset in range(-1, 2):  # 前一页 + 当前页 + 后一页
                p = estimated_page + offset
                if 0 <= p < total_pages:
                    relevant.add(p)

    if not relevant:
        # 保底：首末页
        relevant = {0}
        if total_pages > 1:
            relevant.add(total_pages - 1)
        logger.info(
            f"No key phrase matches in OCR text, keeping first+last page"
        )
    else:
        logger.info(
            f"PDF page selection (OCR text estimation): "
            f"{len(relevant)}/{total_pages} pages "
            f"(avg {avg_chars_per_page:.0f} chars/page)"
        )

    return sorted(relevant)

def _calc_batch_size(
    cat_code: str,
    images: list[tuple[bytes, int, int, str, str]],
) -> int:
    """根据分组和图片尺寸计算每页放置的图片数量

    策略：
    - identity_id_card_paired：1张/页
    - identity_hukou / identity_other：4张/页（小证件照）
    - identity_defendant：2张/页
    - medical_record（病历）：1张/页（完整一页，清晰展示）
    - 其他（appraisal/staff_qual 等）：2张/页
    """
    if cat_code == "identity_id_card_paired":
        return 1
    if cat_code in ("identity_hukou", "identity_other"):
        return 4
    if cat_code == "identity_defendant":
        return 2
    # 病历：完整一页展示，保证清晰
    if cat_code == "medical_record":
        return 1
    if not images:
        return 2

    # 其他类型统一2张/页
    return 2


# ========== 排版绘制 ==========

def _draw_images_on_page(
    c,
    images: list[tuple[bytes, int, int]],
    font_name: str,
    page_w: float,
    page_h: float,
    margin: float,
    page_counter: list[int],
    section_title: str = "",
) -> None:
    """智能排版：根据图片数量与方向自适应排列

    - 1张: 居中撑满
    - 2张: 上下排列（竖版）或左右排列（横版）
    - 3张: 2+1 或 1+2
    - 4+张: 2×2 网格
    """
    from reportlab.lib.utils import ImageReader

    if not images:
        return

    page_counter[0] += 1
    n = len(images)

    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin - 20  # 底部留页码
    header_h = 0

    # 分类标题
    if section_title:
        header_h = 18
        c.setFont(font_name, 10)
        c.drawString(margin, page_h - margin - 14, section_title)

    content_top = page_h - margin - header_h - 4
    content_bottom = margin + 15
    content_h = content_top - content_bottom

    if n == 1:
        # 单张图片 — 居中撑满
        img_bytes, iw, ih = images[0]
        ratio = iw / max(ih, 1)

        if ratio >= 1.0:
            dw = usable_w * 0.95
            dh = dw / ratio
            if dh > content_h * 0.95:
                dh = content_h * 0.95
                dw = dh * ratio
        else:
            dh = content_h * 0.95
            dw = dh * ratio
            if dw > usable_w * 0.95:
                dw = usable_w * 0.95
                dh = dw / ratio

        x = (page_w - dw) / 2
        y = content_bottom + (content_h - dh) / 2
        try:
            c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                       preserveAspectRatio=True, anchor="c")
        except Exception as e:
            logger.error(f"Failed to draw image: {e}")

    elif n == 2:
        # 两张图片 — 检查方向
        _, iw1, ih1 = images[0]
        _, iw2, ih2 = images[1]
        avg_ratio = ((iw1 / max(ih1, 1)) + (iw2 / max(ih2, 1))) / 2

        gap = 6
        if avg_ratio > 1.5:
            # 两张横版 → 上下排列
            slot_h = (content_h - gap) / 2
            for idx, (img_bytes, iw, ih) in enumerate(images):
                ratio = iw / max(ih, 1)
                dw = usable_w * 0.9
                dh = dw / ratio
                if dh > slot_h * 0.9:
                    dh = slot_h * 0.9
                    dw = dh * ratio
                x = (page_w - dw) / 2
                y = content_bottom + content_h - (idx + 1) * (slot_h + gap) + gap + (slot_h - dh) / 2
                try:
                    c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                               preserveAspectRatio=True, anchor="c")
                except Exception as e:
                    logger.error(f"Failed to draw image: {e}")
        else:
            # 两张竖版或混合 → 左右排列
            slot_w = (usable_w - gap) / 2
            for idx, (img_bytes, iw, ih) in enumerate(images):
                ratio = iw / max(ih, 1)
                if ratio >= 1.0:
                    dw = slot_w * 0.9
                    dh = dw / ratio
                    if dh > content_h * 0.9:
                        dh = content_h * 0.9
                        dw = dh * ratio
                else:
                    dh = content_h * 0.9
                    dw = dh * ratio
                    if dw > slot_w * 0.9:
                        dw = slot_w * 0.9
                        dh = dw / ratio
                x = margin + idx * (slot_w + gap) + (slot_w - dw) / 2
                y = content_bottom + (content_h - dh) / 2
                try:
                    c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                               preserveAspectRatio=True, anchor="c")
                except Exception as e:
                    logger.error(f"Failed to draw image: {e}")

    elif n == 3:
        # 三张图片 → 三角排列：上2下1 或 上1下2
        # 检查所有图片的平均纵横比
        ratios = [iw / max(ih, 1) for _, iw, ih in images]
        avg_r = sum(ratios) / 3

        gap = 5
        if avg_r > 1.2:
            # 横版为主 → 上2下1
            top_h = content_h * 0.52
            bot_h = content_h * 0.48
            top_slot_w = (usable_w - gap) / 2

            # 上排 2 张
            for idx in range(2):
                img_bytes, iw, ih = images[idx]
                ratio = iw / max(ih, 1)
                dw = top_slot_w * 0.9
                dh = dw / ratio
                if dh > top_h * 0.85:
                    dh = top_h * 0.85
                    dw = dh * ratio
                x = margin + idx * (top_slot_w + gap) + (top_slot_w - dw) / 2
                y = content_bottom + content_h - top_h + (top_h - dh) / 2
                try:
                    c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                               preserveAspectRatio=True, anchor="c")
                except Exception as e:
                    logger.error(f"Failed to draw image: {e}")

            # 下排 1 张
            img_bytes, iw, ih = images[2]
            ratio = iw / max(ih, 1)
            dw = usable_w * 0.6
            dh = dw / ratio
            if dh > bot_h * 0.85:
                dh = bot_h * 0.85
                dw = dh * ratio
            x = (page_w - dw) / 2
            y = content_bottom + (bot_h - dh) / 2
            try:
                c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                           preserveAspectRatio=True, anchor="c")
            except Exception as e:
                logger.error(f"Failed to draw image: {e}")
        else:
            # 竖版为主 → 上1下2
            top_h = content_h * 0.48
            bot_h = content_h * 0.52
            bot_slot_w = (usable_w - gap) / 2

            # 上排 1 张
            img_bytes, iw, ih = images[0]
            ratio = iw / max(ih, 1)
            if ratio >= 1.0:
                dw = usable_w * 0.6
                dh = dw / ratio
                if dh > top_h * 0.85:
                    dh = top_h * 0.85
                    dw = dh * ratio
            else:
                dh = top_h * 0.85
                dw = dh * ratio
            x = (page_w - dw) / 2
            y = content_bottom + content_h - top_h + (top_h - dh) / 2
            try:
                c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                           preserveAspectRatio=True, anchor="c")
            except Exception as e:
                logger.error(f"Failed to draw image: {e}")

            # 下排 2 张
            for idx in range(2):
                img_bytes, iw, ih = images[idx + 1]
                ratio = iw / max(ih, 1)
                if ratio >= 1.0:
                    dw = bot_slot_w * 0.9
                    dh = dw / ratio
                    if dh > bot_h * 0.85:
                        dh = bot_h * 0.85
                        dw = dh * ratio
                else:
                    dh = bot_h * 0.85
                    dw = dh * ratio
                    if dw > bot_slot_w * 0.9:
                        dw = bot_slot_w * 0.9
                        dh = dw / ratio
                x = margin + idx * (bot_slot_w + gap) + (bot_slot_w - dw) / 2
                y = content_bottom + (bot_h - dh) / 2
                try:
                    c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                               preserveAspectRatio=True, anchor="c")
                except Exception as e:
                    logger.error(f"Failed to draw image: {e}")

    else:
        # 4+ 张图片 → 2×2 网格
        cols = 2
        rows = (n + 1) // 2
        gap = 5
        slot_w = (usable_w - gap) / cols
        slot_h = (content_h - (rows - 1) * gap) / rows

        for slot in range(n):
            row = slot // cols
            col = slot % cols
            img_bytes, iw, ih = images[slot]
            ratio = iw / max(ih, 1)

            if ratio >= 1.0:
                dw = slot_w * 0.9
                dh = dw / ratio
                if dh > slot_h * 0.85:
                    dh = slot_h * 0.85
                    dw = dh * ratio
            else:
                dh = slot_h * 0.85
                dw = dh * ratio
                if dw > slot_w * 0.9:
                    dw = slot_w * 0.9
                    dh = dw / ratio

            x = margin + col * (slot_w + gap) + (slot_w - dw) / 2
            y = content_bottom + content_h - (row + 1) * (slot_h + gap) + gap + (slot_h - dh) / 2

            try:
                c.drawImage(ImageReader(io.BytesIO(img_bytes)), x, y, dw, dh,
                           preserveAspectRatio=True, anchor="c")
            except Exception as e:
                logger.error(f"Failed to draw grid image: {e}")

    c.setFont(font_name, 9)
    c.drawCentredString(page_w / 2, 12, str(page_counter[0]))
    c.showPage()


# ========== 主函数 ==========

def generate_catalog_pdf_inline(
    case_id: str,
    case_name: str | None,
    case_type: str | None,
    catalog_data: dict[str, Any],
    material_files: dict[str, tuple[str, str, bytes]] | None = None,
    analysis_result: dict[str, Any] | None = None,
    ocr_texts: dict[str, str] | None = None,
) -> bytes:
    """生成证据材料 PDF — 反向溯源智能选页

    核心逻辑：
    1. 从 analysis_result 提取起诉状关键短语（日期、诊疗、诊断、鉴定结论）
    2. 对病历/鉴定/资质等PDF素材，用双通道匹配：
       - 通道1: PyMuPDF原生文本层（有文本层的PDF）
       - 通道2: 数据库OCR文本 + 字符位置估算（扫描件PDF）
    3. 只包含匹配到的页（无匹配则保留首末页）
    4. 身份证/户口本/结婚证/死亡证明等全部放入
    5. 6大分组输出，排除 fee_receipt/other_evidence
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as cv

    if not material_files:
        material_files = {}
    if not ocr_texts:
        ocr_texts = {}

    font_name = _ensure_chinese_font()

    PAGE_W, PAGE_H = A4  # 595.28 x 841.89
    MARGIN = 0.8 * cm

    # ========== 步骤0: 提取关键词 ==========
    key_phrases = _extract_key_phrases(analysis_result)
    logger.info(f"Key phrases for reverse matching: {len(key_phrases)} phrases")

    # ========== 步骤1: 遍历 catalog_data，映射到6大输出分组 ==========
    # group_images: { group_id: [(jpeg_bytes, w, h, title, original_filename, cat_code), ...] }
    group_images: dict[str, list[tuple[bytes, int, int, str, str, str]]] = {}
    group_order: list[str] = [g[0] for g in OUTPUT_GROUPS]  # 固定顺序

    for group in catalog_data.get("groups", []):
        cat_code = group.get("category", "")
        items = group.get("items", [])

        for item in items:
            material_id = item.get("material_id", "")
            file_info = material_files.get(material_id)
            if not file_info:
                continue

            filename, file_type, file_bytes = file_info
            item_title = item.get("title", "") or filename
            original_filename = (
                item.get("evidence_name", {}).get("original_filename", "")
                or filename
            )

            # 映射到输出分组
            output_group_id, smart_select = _get_output_group(cat_code, original_filename)
            if output_group_id is None:
                logger.debug(f"  Excluded: {original_filename} ({cat_code})")
                continue  # 排除 fee_receipt / other_evidence

            try:
                # 决定旋转策略
                is_identity = cat_code in IDENTITY_CATEGORIES_FULL and output_group_id in (
                    "plaintiff_id", "other_identity"
                )
                rotation_aggressive = not is_identity

                if file_type == "image":
                    # 病历使用更高分辨率和质量
                    is_medical = cat_code == "medical_record"
                    img_max_dim = 1200 if is_medical else 600
                    img_quality = 85 if is_medical else 50

                    if rotation_aggressive:
                        jpeg_bytes, w, h = _auto_orient_image(file_bytes, aggressive=True)
                        jpeg_bytes, w, h = _load_and_resize(
                            jpeg_bytes, max_dim=img_max_dim, quality=img_quality, skip_rotation=True,
                        )
                    else:
                        jpeg_bytes, w, h = _load_and_resize(
                            file_bytes, max_dim=img_max_dim, quality=img_quality,
                            skip_rotation=False, allow_content_rotation=True,
                        )

                    # 身份证强制横版
                    if cat_code == "identity_id_card" and h > w * 1.3:
                        from PIL import Image as PILImage
                        img = PILImage.open(io.BytesIO(jpeg_bytes))
                        img = img.rotate(90, expand=True)
                        w, h = img.size
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=50)
                        jpeg_bytes = buf.getvalue()

                    group_images.setdefault(output_group_id, []).append(
                        (jpeg_bytes, w, h, item_title, original_filename, cat_code)
                    )

                elif file_type == "pdf":
                    # ===== 反向选页：只渲染匹配关键短语的页面 =====
                    # 获取该素材的OCR文本（用于扫描件的位置估算）
                    mat_ocr_text = ocr_texts.get(material_id)

                    if smart_select and key_phrases:
                        relevant_pages = _find_relevant_pdf_pages(
                            file_bytes, key_phrases, ocr_text=mat_ocr_text,
                        )
                        logger.info(
                            f"  Smart select for '{original_filename}': "
                            f"{len(relevant_pages)} relevant pages"
                        )
                    else:
                        # 不需要智能选页，全部渲染
                        relevant_pages = None  # None = all

                    # 渲染选中的页面
                    # 病历使用更高DPI以保证清晰度
                    is_medical = cat_code == "medical_record"
                    render_dpi = 150 if is_medical else 72
                    all_pages = _render_pdf_pages_to_images(
                        file_bytes, dpi=render_dpi, max_pages=200
                    )

                    for pi, (page_bytes, pw, ph, _np) in enumerate(all_pages):
                        if relevant_pages is not None and pi not in relevant_pages:
                            continue  # 跳过不相关的页

                        # 病历：更大max_dim和更高quality以保证清晰
                        if is_medical:
                            jpeg_bytes, w, h = _load_and_resize(
                                page_bytes, max_dim=1200, quality=85, skip_rotation=True
                            )
                        else:
                            jpeg_bytes, w, h = _load_and_resize(
                                page_bytes, max_dim=600, quality=50, skip_rotation=True
                            )
                        page_title = (
                            f"{item_title} (第{pi+1}页)"
                            if len(all_pages) > 1
                            else item_title
                        )

                        group_images.setdefault(output_group_id, []).append(
                            (jpeg_bytes, w, h, page_title, original_filename, cat_code)
                        )

                elif file_type in ("docx", "doc"):
                    pass  # 暂不处理

                else:
                    # 尝试作为图片
                    try:
                        jpeg_bytes, w, h = _load_and_resize(
                            file_bytes, max_dim=600, quality=50, skip_rotation=False
                        )
                        group_images.setdefault(output_group_id, []).append(
                            (jpeg_bytes, w, h, item_title, original_filename, cat_code)
                        )
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Failed to process material {material_id}: {e}")

    # ========== 步骤1.5: 身份证正反面配对合并 ==========
    # 在 plaintiff_id 分组中找 identity_id_card 类型的图片进行配对
    if "plaintiff_id" in group_images:
        pid_images = group_images["plaintiff_id"]
        id_cards = [img for img in pid_images if img[5] == "identity_id_card"]
        non_id_cards = [img for img in pid_images if img[5] != "identity_id_card"]

        if id_cards:
            paired, remaining = _pair_id_card_images(
                [(img[0], img[1], img[2], img[3], img[4]) for img in id_cards]
            )
            # 重建 plaintiff_id: 配对图 + 未配对图 + 非身份证图
            new_images = []
            for p in paired:
                new_images.append((p[0], p[1], p[2], p[3], p[4], "identity_id_card_paired"))
            for r in remaining:
                new_images.append((r[0], r[1], r[2], r[3], r[4], "identity_id_card"))
            new_images.extend(non_id_cards)
            group_images["plaintiff_id"] = new_images

    # 统计
    total_images = sum(len(v) for v in group_images.values())
    logger.info(f"Collected {total_images} images across {len(group_images)} groups")

    if not total_images:
        output = io.BytesIO()
        c = cv.Canvas(output, pagesize=A4)
        c.setFont(font_name, 12)
        c.drawCentredString(PAGE_W / 2, PAGE_H / 2, "（无证据材料图片）")
        c.showPage()
        c.save()
        return output.getvalue()

    # ========== 步骤2: 生成 PDF — 按6大分组输出 ==========
    output = io.BytesIO()
    c = cv.Canvas(output, pagesize=A4)
    c.setTitle(f"证据材料_{case_name or ''}")
    page_counter = [0]

    # 分组标签映射
    GROUP_LABELS = {g[0]: g[1] for g in OUTPUT_GROUPS}

    for group_id in group_order:
        if group_id not in group_images:
            continue
        cat_label = GROUP_LABELS.get(group_id, group_id)
        section_title = cat_label
        batch = group_images[group_id]

        # 用原始cat_code决定batch_size（兼容配对身份证等特殊逻辑）
        cat_code_for_batch = batch[0][5] if batch else group_id
        batch_size = _calc_batch_size(cat_code_for_batch, batch)

        for i in range(0, len(batch), batch_size):
            chunk = batch[i:i + batch_size]
            page_images = [(img[0], img[1], img[2]) for img in chunk]
            _draw_images_on_page(
                c, page_images, font_name,
                PAGE_W, PAGE_H, MARGIN, page_counter,
                section_title=section_title
            )
            section_title = ""  # 仅首页加标题

    # ---------- 签名页 ----------
    page_counter[0] += 1
    c.setFont(font_name, 12)
    c.drawString(2 * cm, PAGE_H * 0.35, "提交人：__________________")
    today = datetime.now()
    c.drawString(2 * cm, PAGE_H * 0.30, f"日期：{today.year} 年 {today.month} 月 {today.day} 日")
    c.setFont(font_name, 9)
    c.drawCentredString(PAGE_W / 2, 0.6 * cm, str(page_counter[0]))
    c.showPage()

    c.save()
    pdf_bytes = output.getvalue()

    logger.info(
        f"Generated evidence PDF: {len(pdf_bytes)/1024:.0f} KB, "
        f"{page_counter[0]} pages, {total_images} images"
    )

    return pdf_bytes


def generate_catalog_table_pdf(
    case_name: str | None,
    case_type: str | None,
    catalog_data: dict[str, Any],
) -> bytes:
    """生成证据清单 PDF — 严格参照参考格式

    格式参考: 立案证据清单（赵小艳）改.doc
    结构: 标题 → 分组表格(编号|证据名称|页码|证明内容) → 费用汇总 → 提交人/日期
    """
    import re
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as cv

    def _clean(value: str) -> str:
        """清理文本字段：去除JSON标记和代码块噪声"""
        if not value or not isinstance(value, str):
            return ""
        text = value.strip()
        text = re.sub(r'^```(?:json|JSON)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        if text.startswith('{') and text.endswith('}'):
            return ""
        if text.startswith('[') and text.endswith(']'):
            return ""
        return text.strip()

    font_name = _ensure_chinese_font()

    PAGE_W, PAGE_H = A4
    MARGIN_LEFT = 2 * cm
    MARGIN_RIGHT = 2 * cm
    MARGIN_TOP = 2.2 * cm
    MARGIN_BOTTOM = 2 * cm
    USABLE_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT

    output = io.BytesIO()
    c = cv.Canvas(output, pagesize=A4)
    c.setTitle(f"证据清单_{case_name or ''}")
    page_num = 0

    # 罗马数字分组编号
    GROUP_NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
                      "十一", "十二", "十三", "十四", "十五"]

    # 列宽设置：编号 | 证据名称 | 页码 | 证明内容
    COL_NO = 1.5 * cm
    COL_NAME = 5.5 * cm
    COL_PAGE = 1.5 * cm
    COL_PURPOSE = USABLE_W - COL_NO - COL_NAME - COL_PAGE
    COL_WIDTHS = [COL_NO, COL_NAME, COL_PAGE, COL_PURPOSE]
    COL_X = [MARGIN_LEFT]
    for w in COL_WIDTHS[:-1]:
        COL_X.append(COL_X[-1] + w)

    ROW_H = 0.65 * cm
    HEADER_H = 0.8 * cm
    FONT_SIZE = 9
    FONT_SIZE_SMALL = 8
    FONT_SIZE_TITLE = 14
    FONT_SIZE_SUBTITLE = 11

    # 计算每个组的页码范围（需要先收集所有组的条目和图片数量）
    # 先统计总页数（近似：每个全页文档类占1页，每个网格类图片页数需要估算）
    # 简化：用 catalog_index 计算页码范围
    # 实际需要跟证据材料PDF对齐，这里用简单的起始-结束页码
    # 先留空，后面再精确计算
    current_page = 1

    # 收集分组数据
    groups_data: list[dict] = []
    for group in catalog_data.get("groups", []):
        cat_code = group.get("category", "")
        cat_name = group.get("category_name", cat_code)
        items = group.get("items", [])

        if not items:
            continue

        # 估算该组占多少页
        # identity类: 约 ceil(n/4) 页（网格排版）
        # 全页类: n 页
        # 其他: 约 ceil(n/3) 页
        n_items = len(items)
        if cat_code in IDENTITY_CATEGORIES_FULL:
            est_pages = max(1, (n_items + 3) // 4)
        elif cat_code in DOCUMENT_CATEGORIES:
            est_pages = n_items
        else:
            est_pages = max(1, (n_items + 2) // 3)

        groups_data.append({
            "cat_code": cat_code,
            "cat_name": cat_name,
            "items": items,
            "page_start": current_page,
            "page_end": current_page + est_pages - 1,
            "est_pages": est_pages,
        })
        current_page += est_pages

    # 收集费用汇总
    fee_summary = catalog_data.get("fee_summary", {})
    total_amount = catalog_data.get("total_amount", 0)
    try:
        total_amount = float(total_amount)
    except (ValueError, TypeError):
        total_amount = 0.0

    # 收集证明目的（按组合并）
    def get_group_proof_purpose(group: dict, case_type_str: str | None) -> str:
        """从组内条目中提取合并的证明目的"""
        purposes = set()
        for item in group["items"]:
            pp = _clean(item.get("proof_purpose", ""))
            if pp:
                purposes.add(pp)
        if purposes:
            return "；".join(sorted(purposes))
        return ""

    # ========== 绘制函数 ==========
    def _new_page(is_first_table_page: bool = False):
        nonlocal page_num, y
        if page_num > 0:
            c.setFont(font_name, 9)
            c.drawCentredString(PAGE_W / 2, 0.8 * cm, str(page_num))
            c.showPage()
        page_num += 1
        y = PAGE_H - MARGIN_TOP

        if is_first_table_page:
            # 绘制表头
            _draw_table_header()

    def _draw_table_header():
        nonlocal y
        # 表头行
        c.setFillColor(colors.Color(0.92, 0.92, 0.92))
        c.rect(MARGIN_LEFT, y - HEADER_H, USABLE_W, HEADER_H, fill=True, stroke=True)
        c.setFillColor(colors.black)
        c.setFont(font_name, FONT_SIZE)

        headers = ["编号", "证据名称", "页码", "证明内容"]
        for i, header in enumerate(headers):
            c.drawCentredString(COL_X[i] + COL_WIDTHS[i] / 2, y - HEADER_H + 0.22 * cm, header)

        y -= HEADER_H

    def _draw_cell_text(text: str, x: float, col_w: float, row_y: float, row_h: float,
                        font_sz: int = FONT_SIZE, center: bool = True):
        """在单元格中绘制文本，支持自动换行"""
        c.setFont(font_name, font_sz)
        max_chars_per_line = int(col_w / cm * 4.2)
        lines = []
        for line_text in text.split('\n'):
            while len(line_text) > max_chars_per_line:
                lines.append(line_text[:max_chars_per_line])
                line_text = line_text[max_chars_per_line:]
            lines.append(line_text)

        line_h = font_sz * 0.04 * cm
        total_text_h = len(lines) * line_h
        start_y = row_y - row_h / 2 + total_text_h / 2 - font_sz * 0.015 * cm

        for li, line in enumerate(lines):
            ly = start_y - li * line_h
            if center:
                c.drawCentredString(x + col_w / 2, ly, line)
            else:
                c.drawString(x + 0.15 * cm, ly, line)

    def _draw_row(no_text: str, name_text: str, page_text: str,
                  purpose_text: str, row_h: float, fill: bool = False):
        nonlocal y
        if y - row_h < MARGIN_BOTTOM:
            _new_page()

        if fill:
            c.setFillColor(colors.Color(0.97, 0.97, 0.97))
            c.rect(MARGIN_LEFT, y - row_h, USABLE_W, row_h, fill=True, stroke=False)
            c.setFillColor(colors.black)

        # 绘制单元格边框
        c.rect(MARGIN_LEFT, y - row_h, USABLE_W, row_h, fill=False, stroke=True)
        # 竖线
        for i in range(1, len(COL_WIDTHS)):
            c.line(COL_X[i], y, COL_X[i], y - row_h)

        # 填充文本
        _draw_cell_text(no_text, COL_X[0], COL_WIDTHS[0], y, row_h)
        _draw_cell_text(name_text, COL_X[1], COL_WIDTHS[1], y, row_h, center=False)
        _draw_cell_text(page_text, COL_X[2], COL_WIDTHS[2], y, row_h)
        _draw_cell_text(purpose_text, COL_X[3], COL_WIDTHS[3], y, row_h, center=False,
                       font_sz=FONT_SIZE_SMALL)

        y -= row_h

    # ========== 页面1：标题 + 表格 ==========
    _new_page()

    # 标题
    case_name_display = _clean(case_name) or "案件"
    c.setFont(font_name, FONT_SIZE_TITLE)
    # 长标题需要分行
    title_text = f"{case_name_display}立案证据清单（原告提供）"
    max_title_chars = int(USABLE_W / cm * 3.5)
    if len(title_text) > max_title_chars:
        # 分两行
        mid = len(case_name_display)
        c.drawCentredString(PAGE_W / 2, y, f"{case_name_display}")
        y -= 0.6 * cm
        c.setFont(font_name, FONT_SIZE_SUBTITLE)
        c.drawCentredString(PAGE_W / 2, y, "立案证据清单（原告提供）")
        y -= 0.8 * cm
    else:
        c.drawCentredString(PAGE_W / 2, y, title_text)
        y -= 1.0 * cm

    # 绘制表头
    _draw_table_header()

    # 逐组绘制
    for gi, group_info in enumerate(groups_data):
        group_numeral = GROUP_NUMERALS[gi] if gi < len(GROUP_NUMERALS) else str(gi + 1)
        items = group_info["items"]
        proof_purpose = get_group_proof_purpose(group_info, case_type)
        page_range = f"{group_info['page_start']}-{group_info['page_end']}" if group_info['est_pages'] > 1 else str(group_info['page_start'])

        n_items = len(items)

        # 第一行：组号 + 第一个证据名称 + 页码 + 证明内容（跨行合并）
        # 计算合并后的行高
        purpose_lines = len(proof_purpose) / int(COL_PURPOSE / cm * 4.2) + 1
        merged_h = max(n_items * ROW_H, int(purpose_lines) * ROW_H, ROW_H)

        # 如果合并行太高，分拆为普通行
        if merged_h > 5 * ROW_H or n_items <= 1:
            # 简单模式：每行一条
            for ii, item in enumerate(items):
                no = f"{group_numeral}" if ii == 0 else ""
                name = _clean(item.get("title", "")) or _clean(item.get("material_filename", ""))
                pg = page_range if ii == 0 else ""
                pp = _clean(proof_purpose) if ii == 0 else ""

                _draw_row(no, f"{ii+1}、{name}", pg, pp, ROW_H * 1.2,
                         fill=(ii % 2 == 1))
        else:
            # 合并模式：组号+页码+证明内容跨行，证据名称逐行
            # 先绘制合并的大框
            start_y = y

            # 逐行绘制证据名称
            for ii, item in enumerate(items):
                name = _clean(item.get("title", "")) or _clean(item.get("material_filename", ""))
                _draw_row(
                    group_numeral if ii == 0 else "",
                    f"{ii+1}、{name}",
                    page_range if ii == 0 else "",
                    "",  # 证明内容单独绘制
                    ROW_H,
                    fill=(ii % 2 == 1)
                )

            # 在右侧证明内容列绘制合并文本
            purpose_y_top = start_y
            purpose_y_bottom = y
            purpose_h = purpose_y_top - purpose_y_bottom

            # 清除证明内容列的竖线
            c.setStrokeColor(colors.white)
            c.line(COL_X[3], purpose_y_top, COL_X[3], purpose_y_bottom)
            c.setStrokeColor(colors.black)
            # 重新画右边框和竖线
            c.rect(COL_X[3], purpose_y_bottom, COL_PURPOSE, purpose_h, fill=False, stroke=True)

            # 绘制证明内容文本
            clean_purpose = _clean(proof_purpose)
            if clean_purpose:
                c.setFont(font_name, FONT_SIZE_SMALL)
                max_chars = int(COL_PURPOSE / cm * 4.5)
                text_lines = []
                for seg in clean_purpose.split('；'):
                    while len(seg) > max_chars:
                        text_lines.append(seg[:max_chars])
                        seg = seg[max_chars:]
                    text_lines.append(seg)

                line_h = FONT_SIZE_SMALL * 0.04 * cm
                total_h = len(text_lines) * line_h
                text_start_y = purpose_y_bottom + purpose_h / 2 + total_h / 2 - FONT_SIZE_SMALL * 0.015 * cm
                for li, line in enumerate(text_lines):
                    ly = text_start_y - li * line_h
                    c.drawString(COL_X[3] + 0.15 * cm, ly, line)

    # ========== 费用汇总行 ==========
    if fee_summary or total_amount > 0:
        fee_text_parts = []
        for name, amount in fee_summary.items():
            try:
                amt = float(amount)
                fee_text_parts.append(f"{name}{amt:.2f}元")
            except (ValueError, TypeError):
                continue

        if fee_text_parts:
            _draw_row("", "赔偿费用汇总", "", "；".join(fee_text_parts), ROW_H * 1.2)

        if total_amount > 0:
            _draw_row("", "合计", "", f"{total_amount:.2f}元", ROW_H * 1.2, fill=True)

    # ========== 结束当前页 ==========
    c.setFont(font_name, 9)
    c.drawCentredString(PAGE_W / 2, 0.8 * cm, str(page_num))
    c.showPage()

    # ========== 签名页（不单独一页，跟在表格后面） ==========
    page_num += 1
    c.setFont(font_name, 12)
    c.drawString(MARGIN_LEFT, PAGE_H * 0.35, "提交人：__________________")
    today = datetime.now()
    c.drawString(MARGIN_LEFT, PAGE_H * 0.30, f"日期：{today.year} 年 {today.month} 月 {today.day} 日")
    c.setFont(font_name, 9)
    c.drawCentredString(PAGE_W / 2, 0.8 * cm, str(page_num))
    c.showPage()

    c.save()
    pdf_bytes = output.getvalue()
    logger.info(f"Generated evidence list PDF: {len(pdf_bytes)/1024:.0f} KB, {page_num} pages")
    return pdf_bytes
