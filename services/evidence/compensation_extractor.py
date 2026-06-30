"""
赔偿费用自动提取器
从 fee_receipt 分类的素材 OCR 文本中提取费用数据
"""
import re
import logging
from typing import List, Optional
from decimal import Decimal
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class FeeItem:
    """提取的费用条目"""
    fee_type: str          # medical_fee / hospital_fee / outpatient_fee / pharmacy_fee / nursing_supplies
    amount: Decimal        # 金额
    description: str       # 描述（如"住院发票"、"门诊发票"）
    source_material_id: str  # 来源素材ID
    source_filename: str   # 来源文件名
    ocr_snippet: str = ""  # OCR 关键片段
    hospital_name: str = "" # 医院名称
    date_range: str = ""   # 日期范围


# ─── 文件名 → 费用类型识别规则 ──────────────────────────────────────────────
# 顺序敏感：先匹配优先级高的（如"护理用品"优先于"医保结算"）
FILENAME_FEE_TYPE_RULES: list[tuple[list[str], str, str]] = [
    # (关键词列表, fee_type, description)
    (["日常用品", "护理用品", "生活用品", "护理品", "陪护用品",
      "医疗器械", "医用器械", "康复器械", "辅助器具", "护理器械",
      "轮椅", "拐杖", "助行器", "护理床", "医用耗材"],
     "nursing_supplies", "护理用品/医疗器械"),
    (["住院清单", "住院费用", "住院发票", "住院结算"], "hospital_fee", "住院费用"),
    (["门诊费用", "门诊发票", "门诊清单", "门诊结算"], "outpatient_fee", "门诊费用"),
    (["医保结算", "医保报销", "医保清单"], "medical_fee", "医保结算"),
    (["外购药", "外购", "药店"], "pharmacy_fee", "外购药品费"),
]


def detect_fee_type_by_filename(filename: str) -> tuple[str, str] | tuple[None, None]:
    """根据文件名识别费用类型

    Returns:
        (fee_type, description) 或 (None, None) 表示未识别
    """
    if not filename:
        return (None, None)
    name_lower = filename.lower()
    for keywords, fee_type, desc in FILENAME_FEE_TYPE_RULES:
        for kw in keywords:
            if kw in name_lower:
                return (fee_type, desc)
    return (None, None)

@dataclass
class HospitalStayInfo:
    """住院天数信息"""
    days: int = 0
    source: str = ""  # 来源描述

def extract_from_materials(materials: list) -> tuple[List[FeeItem], HospitalStayInfo]:
    """
    从素材列表中提取费用数据和住院天数

    Args:
        materials: EvidenceMaterial 列表

    Returns:
        (费用列表, 住院天数信息)
    """
    from services.evidence.ocr_storage import get_material_ocr_text

    fee_items: List[FeeItem] = []
    stay_info = HospitalStayInfo()

    for mat in materials:
        cat = getattr(mat, 'effective_category', '') or ''
        ocr_text = get_material_ocr_text(mat)
        filename = getattr(mat, 'original_filename', '') or ''
        mat_id = str(getattr(mat, 'id', ''))

        if not ocr_text:
            continue

        # 从费用类素材提取金额
        if cat in ('fee_receipt', 'invoice', 'receipt'):
            items = parse_fee_receipt(ocr_text, mat_id, filename)
            fee_items.extend(items)

        # 从病历类素材提取住院天数
        if cat in ('medical_record', 'discharge_summary', 'admission_record'):
            days = extract_hospital_days(ocr_text)
            if days > 0:
                stay_info.days = days
                stay_info.source = f"从{filename}提取"

    logger.info(f"费用提取完成: {len(fee_items)}项费用, 住院{stay_info.days}天")
    return fee_items, stay_info

def parse_fee_receipt(ocr_text: str, material_id: str, filename: str) -> List[FeeItem]:
    """从单份费用素材中提取费用"""
    items: List[FeeItem] = []

    # 提取金额的正则模式（优先匹配大金额合计）
    amount_patterns: List[tuple[str, str]] = [
        (r'合\s*计[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'total'),
        (r'总\s*计[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'total'),
        (r'费用合计[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'total'),
        (r'金\s*额[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'item'),
        (r'个人自付[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'personal'),
        (r'个人支付[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'personal'),
        (r'统筹支付[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'insurance'),
        (r'医保支付[：:\s]*[¥￥]?\s*([\d,]+\.?\d*)', 'insurance'),
    ]

    # 判断费用类型 —— 优先使用文件名识别（更精确），其次 OCR 文本回退
    fn_fee_type, fn_desc = detect_fee_type_by_filename(filename)
    if fn_fee_type:
        fee_type = fn_fee_type
        description = fn_desc
    else:
        fee_type = 'medical_fee'
        description = '医疗费用'
        if '住院' in ocr_text or '入院' in ocr_text:
            fee_type = 'hospital_fee'
            description = '住院费用'
        elif '门诊' in ocr_text:
            fee_type = 'outpatient_fee'
            description = '门诊费用'
        elif '医保' in ocr_text and ('结算' in ocr_text or '报销' in ocr_text):
            fee_type = 'medical_fee'
            description = '医保结算'
        elif '外购' in ocr_text or '药店' in ocr_text:
            fee_type = 'pharmacy_fee'
            description = '外购药品费'

    for pattern, amount_type in amount_patterns:
        for m in re.finditer(pattern, ocr_text):
            amount_str = m.group(1).replace(',', '')
            try:
                amount = Decimal(amount_str)
                # 取第一个合计金额作为主金额
                if amount_type == 'total' and amount > 0:
                    snippet = ocr_text[max(0, m.start()-20):m.end()+20]
                    items.append(FeeItem(
                        fee_type=fee_type,
                        amount=amount,
                        description=description,
                        source_material_id=material_id,
                        source_filename=filename,
                        ocr_snippet=snippet.strip(),
                    ))
                    break  # 每份素材只取第一个合计
            except Exception:
                continue
        if items:  # 已找到合计，不再搜索
            break

    return items

def extract_hospital_days(ocr_text: str) -> int:
    """从 OCR 文本中提取住院天数"""
    patterns = [
        r'住院\s*(\d+)\s*天',
        r'实际住院\s*(\d+)\s*天',
        r'共\s*住\s*院\s*(\d+)\s*天',
        r'住院天数[：:\s]*(\d+)',
    ]

    for p in patterns:
        m = re.search(p, ocr_text)
        if m:
            return int(m.group(1))

    # 尝试从入院/出院日期计算
    date_pattern = r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'
    dates = re.findall(date_pattern, ocr_text)
    if len(dates) >= 2:
        try:
            from datetime import date
            d1 = date(int(dates[0][0]), int(dates[0][1]), int(dates[0][2]))
            d2 = date(int(dates[-1][0]), int(dates[-1][1]), int(dates[-1][2]))
            days = abs((d2 - d1).days)
            if 1 <= days <= 365:  # 合理范围
                return days
        except Exception:
            pass

    return 0
