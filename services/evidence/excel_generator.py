"""
Excel 费用生成器 — 生成赔偿费用总表和医疗费用汇总表 Excel
========================================================
表1: 赔偿费用清单 — 标准8大赔偿项目 + 计算依据 + 金额
表2: 医疗费用汇总表 — 按医院分组、逐条明细（住院/门诊、报销/自费）
"""
from __future__ import annotations

import io
import uuid
from typing import Any

from loguru import logger
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side, PatternFill
from openpyxl.utils import get_column_letter

MINIO_BUCKET = "scan-result"


def _clean_text(value: str) -> str:
    """清理文本字段：去除LLM返回的JSON标记、代码块标记等噪声"""
    if not value or not isinstance(value, str):
        return ""
    import re
    text = value.strip()
    # 去除代码块标记
    text = re.sub(r'^```(?:json|JSON)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    # 去除JSON对象/数组标记
    if text.startswith('{') and text.endswith('}'):
        return ""  # 整个值是JSON对象，不是有效文本
    if text.startswith('[') and text.endswith(']'):
        return ""  # 整个值是JSON数组
    # 去除多余的换行和空格
    text = re.sub(r'\n{2,}', '\n', text)
    text = text.strip()
    return text


def _get_case_data(case_id: str) -> tuple[dict, dict]:
    """获取案件的清单数据和分析结果"""
    from db.models_evidence import EvidenceCase
    from db.session import get_session_factory, run_in_worker

    async def _fetch():
        from sqlalchemy import select

        case_uuid = uuid.UUID(case_id)
        async with get_session_factory()() as db:
            stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            result = await db.execute(stmt)
            case = result.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")
            return case.catalog_data or {}, case.analysis_result or {}

    return run_in_worker(_fetch())


def _upload_to_minio(case_id: str, excel_bytes: bytes, filename: str) -> str:
    """上传 Excel 到 MinIO"""
    from services.storage.minio_client import minio_client

    minio_key = f"evidence/{case_id}/{uuid.uuid4()}_{filename}"
    minio_client.upload_bytes(
        bucket=MINIO_BUCKET,
        object_key=minio_key,
        data=excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return minio_key


# ─── 样式定义 ────────────────────────────────────────────────────────────────

_HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_CELL_FONT = Font(name="微软雅黑", size=10)
_BOLD_FONT = Font(name="微软雅黑", size=10, bold=True)
_MONEY_FORMAT = '#,##0.00'
_THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center")
_LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
_RIGHT_ALIGN = Alignment(horizontal="right", vertical="center")
_SUBTITLE_FILL = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
_SUBTOTAL_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
_TOTAL_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")


def _apply_header_style(ws, row: int, col_count: int) -> None:
    """应用表头样式"""
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER_ALIGN
        cell.border = _THIN_BORDER


def _apply_cell_style(ws, row: int, col_count: int, money_cols: set[int] | None = None) -> None:
    """应用单元格样式"""
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = _CELL_FONT
        cell.border = _THIN_BORDER
        cell.alignment = _LEFT_ALIGN
        if money_cols and col in money_cols:
            cell.number_format = _MONEY_FORMAT
            cell.alignment = _CENTER_ALIGN


def _apply_row_border(ws, row: int, col_count: int) -> None:
    """给一行所有单元格加边框"""
    for col in range(1, col_count + 1):
        ws.cell(row=row, column=col).border = _THIN_BORDER


# ═══════════════════════════════════════════════════════════════════════════════
# 标准 8 大赔偿项目定义
# ═══════════════════════════════════════════════════════════════════════════════

# 每项: (显示名称, 计算依据模板, fee_summary 中的关键词匹配列表)
_STANDARD_COMPENSATION_ITEMS = [
    ("医疗费", "凭票据实报实销", ["医疗费", "医药费", "门诊费", "住院医疗"]),
    ("护理费", "住院期间护理费 = 护理标准 × 住院天数", ["护理费"]),
    ("住院伙食补助费", "住院伙食补助标准 × 住院天数", ["住院伙食补助费", "伙食补助费", "住院伙食费"]),
    ("营养费", "营养费标准 × 营养期天数（参照鉴定意见）", ["营养费"]),
    ("残疾赔偿金", "受诉法院所在地上年度城镇居民人均可支配收入 × 20年 × 伤残系数", ["残疾赔偿金", "伤残赔偿金"]),
    ("死亡赔偿金", "受诉法院所在地上年度城镇居民人均可支配收入 × 20年", ["死亡赔偿金"]),
    ("丧葬费", "受诉法院所在地上年度职工月平均工资 × 6个月", ["丧葬费"]),
    ("交通费", "凭票据实报实销", ["交通费"]),
    ("精神损害抚慰金", "根据伤残等级/死亡后果酌定", ["精神损害抚慰金", "精神抚慰金", "精神损害"]),
    ("鉴定费", "凭票据实报实销", ["鉴定费"]),
    ("误工费", "误工收入 × 误工天数（参照鉴定意见）", ["误工费"]),
    ("后续治疗费", "参照鉴定意见或后续实际发生费用", ["后续治疗费"]),
    ("被扶养人生活费", "受诉法院所在地上年度城镇居民人均消费支出 × 扶养年限", ["被扶养人生活费"]),
    ("残疾辅助器具费", "凭票据或参照普通适用器具标准", ["残疾辅助器具费", "辅助器具费"]),
    ("住宿费", "凭票据实报实销", ["住宿费"]),
    ("其他费用", "其他合理费用", ["其他费用", "其他"]),
]


def _match_fee_amount(fee_summary: dict, keywords: list[str]) -> float:
    """从 fee_summary 中按关键词匹配金额（最佳匹配而非首次匹配）

    匹配优先级：
    1. 完全匹配（fee_type == keyword）
    2. fee_type 包含 keyword
    3. keyword 包含 fee_type
    """
    best_match = 0.0
    best_score = 0

    for keyword in keywords:
        for fee_type, amount in fee_summary.items():
            if not isinstance(amount, (int, float)) or amount <= 0:
                continue

            # 计算匹配分数
            score = 0
            if fee_type == keyword:
                score = 100  # 完全匹配
            elif keyword in fee_type:
                score = 50   # fee_type 包含 keyword
            elif fee_type in keyword:
                score = 25   # keyword 包含 fee_type

            if score > best_score:
                best_score = score
                best_match = amount

    return best_match


# ═══════════════════════════════════════════════════════════════════════════════
# 旧版兼容函数（直接调 DB + 上传 MinIO）
# ═══════════════════════════════════════════════════════════════════════════════

def generate_compensation_summary(case_id: str) -> str:
    """生成赔偿费用总表 Excel → 返回 MinIO key"""
    catalog_data, analysis_result = _get_case_data(case_id)
    excel_bytes = generate_compensation_inline_data(catalog_data, analysis_result)
    if not excel_bytes:
        raise ValueError("Failed to generate compensation summary")
    minio_key = _upload_to_minio(case_id, excel_bytes, "赔偿费用清单.xlsx")
    logger.info(f"Compensation summary generated: case={case_id} key={minio_key}")
    return minio_key


def generate_fee_type_detail(case_id: str, fee_type: str) -> str:
    """生成单项费用明细 Excel（如医疗费.xlsx） → 返回 MinIO key"""
    catalog_data, analysis_result = _get_case_data(case_id)
    details = generate_fee_details_inline_data(catalog_data, analysis_result)
    if fee_type in details:
        minio_key = _upload_to_minio(case_id, details[fee_type], f"{fee_type}.xlsx")
        logger.info(f"Fee detail generated: case={case_id} type={fee_type} key={minio_key}")
        return minio_key
    raise ValueError(f"No fee detail for type: {fee_type}")


def generate_all_fee_details(case_id: str) -> dict[str, str]:
    """生成所有费用类型的独立 Excel → 返回 {fee_type: minio_key}"""
    catalog_data, analysis_result = _get_case_data(case_id)
    details = generate_fee_details_inline_data(catalog_data, analysis_result)
    results: dict[str, str] = {}
    for fee_type, excel_bytes in details.items():
        try:
            minio_key = _upload_to_minio(case_id, excel_bytes, f"{fee_type}.xlsx")
            results[fee_type] = minio_key
        except Exception as e:
            logger.error(f"Failed to upload fee detail for {fee_type}: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 纯数据驱动生成函数（不调数据库，供路由端直接使用）
# ═══════════════════════════════════════════════════════════════════════════════

def generate_compensation_inline_data(catalog_data: dict, analysis_result: dict) -> bytes | None:
    """赔偿费用清单 Excel（标准法律文书格式）

    表头：序号 | 赔偿项目 | 计算依据 | 金额（元）
    标准 8 大赔偿项目，从 fee_summary 匹配金额，未匹配项目显示为 0
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "赔偿费用清单"

    case_name = analysis_result.get("case_name", "案件")
    case_type = analysis_result.get("case_type", "injury")

    # ── 标题行 ──
    ws.merge_cells("A1:D1")
    title_cell = ws.cell(row=1, column=1, value=f"{case_name} — 赔偿费用清单")
    title_cell.font = Font(name="微软雅黑", size=14, bold=True)
    title_cell.alignment = _CENTER_ALIGN

    # 空行（行2）
    # ── 表头（行3）──
    headers = ["序号", "赔偿项目", "计算依据", "金额（元）"]
    HEADER_ROW = 3
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=HEADER_ROW, column=col_idx, value=header)
    _apply_header_style(ws, HEADER_ROW, len(headers))

    # ── 数据行 ──
    fee_summary = catalog_data.get("fee_summary", {})
    matched_keys = set()  # 记录已匹配的 fee_summary key
    row_idx = HEADER_ROW + 1
    seq = 1
    total_amount = 0.0

    for display_name, calc_basis, keywords in _STANDARD_COMPENSATION_ITEMS:
        # 跳过与案件类型不匹配的项目
        if case_type == "injury" and display_name == "死亡赔偿金":
            continue
        if case_type == "injury" and display_name == "丧葬费":
            continue
        if case_type == "death" and display_name == "残疾赔偿金":
            continue

        amount = _match_fee_amount(fee_summary, keywords)

        # 记录已匹配的 fee_summary key
        for keyword in keywords:
            for fee_type in fee_summary:
                if (keyword in fee_type or fee_type in keyword) and isinstance(fee_summary.get(fee_type), (int, float)):
                    matched_keys.add(fee_type)

        # 即使金额为 0 也列出标准项目（法律文书完整性要求）
        if amount > 0:
            total_amount += amount

        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=display_name)
        ws.cell(row=row_idx, column=3, value=calc_basis)
        ws.cell(row=row_idx, column=4, value=amount)
        _apply_cell_style(ws, row_idx, len(headers), money_cols={4})
        row_idx += 1
        seq += 1

    # 补充 fee_summary 中未匹配到的项目（非标准项目）
    for fee_type, amount in fee_summary.items():
        if fee_type in matched_keys:
            continue
        if not isinstance(amount, (int, float)) or amount <= 0:
            continue
        total_amount += amount
        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=fee_type)
        ws.cell(row=row_idx, column=3, value="凭票据")
        ws.cell(row=row_idx, column=4, value=amount)
        _apply_cell_style(ws, row_idx, len(headers), money_cols={4})
        row_idx += 1
        seq += 1

    # ── 合计行 ──
    ws.cell(row=row_idx, column=2, value="合  计")
    ws.cell(row=row_idx, column=2).font = _BOLD_FONT
    ws.cell(row=row_idx, column=2).alignment = _CENTER_ALIGN
    ws.cell(row=row_idx, column=4, value=total_amount)
    ws.cell(row=row_idx, column=4).font = _BOLD_FONT
    ws.cell(row=row_idx, column=4).number_format = _MONEY_FORMAT
    ws.cell(row=row_idx, column=4).alignment = _CENTER_ALIGN
    # 合计行特殊底色
    for col in range(1, len(headers) + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    # ── 列宽 ──
    col_widths = [8, 22, 55, 18]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # ── 打印设置 ──
    ws.sheet_properties.pageSetUpPr = None  # 使用默认
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def generate_fee_details_inline_data(catalog_data: dict, analysis_result: dict) -> dict[str, bytes]:
    """医疗费用汇总表 Excel（按医院分组，逐条明细）

    从 catalog_data.groups 中提取 fee_receipt 分类的材料，
    按医院名称分组，展示每张票据的日期、金额、报销/自费等信息。

    返回 {"医疗费用汇总表": bytes}
    """
    results: dict[str, bytes] = {}

    # ── 收集所有 fee_receipt 材料 ──
    fee_items = _collect_fee_receipt_items(catalog_data)

    if not fee_items:
        # 没有费用票据数据时，生成空表
        wb = Workbook()
        ws = wb.active
        ws.title = "医疗费用汇总表"
        ws.merge_cells("A1:J1")
        ws.cell(row=1, column=1, value="医疗费用汇总表（无费用票据数据）").font = Font(name="微软雅黑", size=14, bold=True)
        output = io.BytesIO()
        wb.save(output)
        results["医疗费用汇总表"] = output.getvalue()
        return results

    # ── 按医院名称分组 ──
    hospital_groups: dict[str, list[dict]] = {}
    for item in fee_items:
        hospital = item.get("hospital_name", "") or "未知医院"
        if hospital not in hospital_groups:
            hospital_groups[hospital] = []
        hospital_groups[hospital].append(item)

    wb = Workbook()
    ws = wb.active
    ws.title = "医疗费用汇总表"

    case_name = analysis_result.get("case_name", "案件")

    # ── 标题行 ──
    ws.merge_cells("A1:J1")
    title_cell = ws.cell(row=1, column=1, value=f"{case_name} — 医疗费用汇总表")
    title_cell.font = Font(name="微软雅黑", size=14, bold=True)
    title_cell.alignment = _CENTER_ALIGN

    # ── 表头（行3）──
    HEADER_ROW = 3
    headers = [
        "序号", "医院名称", "名称/项目", "日期", "金额（元）",
        "报销金额", "个人自费", "类型", "住院天数", "票据尾号",
    ]
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=HEADER_ROW, column=col_idx, value=header)
    _apply_header_style(ws, HEADER_ROW, len(headers))

    # ── 按医院分组输出 ──
    row_idx = HEADER_ROW + 1
    seq = 1
    grand_total = 0.0
    grand_insurance = 0.0
    grand_out_of_pocket = 0.0

    for hospital_name, items in hospital_groups.items():
        # 医院名子标题行
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(headers))
        hospital_cell = ws.cell(row=row_idx, column=1, value=f"▶ {hospital_name}")
        hospital_cell.font = _BOLD_FONT
        hospital_cell.fill = _SUBTITLE_FILL
        hospital_cell.alignment = _LEFT_ALIGN
        for col in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=col).border = _THIN_BORDER
            ws.cell(row=row_idx, column=col).fill = _SUBTITLE_FILL
        row_idx += 1

        # 该医院下的逐条票据
        sub_total = 0.0
        sub_insurance = 0.0
        sub_out_of_pocket = 0.0

        for item in items:
            amount = item.get("total_amount", 0) or 0
            insurance = item.get("insurance_amount", 0) or 0
            out_of_pocket = item.get("out_of_pocket", 0) or 0
            date_str = item.get("date", "")
            title = item.get("title", "")
            receipt_type = item.get("receipt_type", "门诊")
            stay_days = item.get("stay_days", "")
            receipt_tail = item.get("receipt_tail", "")

            sub_total += amount
            sub_insurance += insurance
            sub_out_of_pocket += out_of_pocket

            ws.cell(row=row_idx, column=1, value=seq)
            ws.cell(row=row_idx, column=2, value="")  # 医院名已在子标题行
            ws.cell(row=row_idx, column=3, value=title)
            ws.cell(row=row_idx, column=4, value=date_str)
            ws.cell(row=row_idx, column=5, value=amount)
            ws.cell(row=row_idx, column=6, value=insurance if insurance else "")
            ws.cell(row=row_idx, column=7, value=out_of_pocket if out_of_pocket else "")
            ws.cell(row=row_idx, column=8, value=receipt_type)
            ws.cell(row=row_idx, column=9, value=stay_days)
            ws.cell(row=row_idx, column=10, value=receipt_tail)
            _apply_cell_style(ws, row_idx, len(headers), money_cols={5, 6, 7})
            row_idx += 1
            seq += 1

        # 小计行
        grand_total += sub_total
        grand_insurance += sub_insurance
        grand_out_of_pocket += sub_out_of_pocket

        ws.cell(row=row_idx, column=3, value=f"{hospital_name} 小计")
        ws.cell(row=row_idx, column=3).font = _BOLD_FONT
        ws.cell(row=row_idx, column=5, value=sub_total)
        ws.cell(row=row_idx, column=5).font = _BOLD_FONT
        ws.cell(row=row_idx, column=5).number_format = _MONEY_FORMAT
        ws.cell(row=row_idx, column=6, value=sub_insurance if sub_insurance else "")
        ws.cell(row=row_idx, column=6).font = _BOLD_FONT
        ws.cell(row=row_idx, column=6).number_format = _MONEY_FORMAT
        ws.cell(row=row_idx, column=7, value=sub_out_of_pocket if sub_out_of_pocket else "")
        ws.cell(row=row_idx, column=7).font = _BOLD_FONT
        ws.cell(row=row_idx, column=7).number_format = _MONEY_FORMAT
        for col in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=col).border = _THIN_BORDER
            ws.cell(row=row_idx, column=col).fill = _SUBTOTAL_FILL
        row_idx += 1

    # ── 总合计行 ──
    ws.cell(row=row_idx, column=3, value="总  计")
    ws.cell(row=row_idx, column=3).font = Font(name="微软雅黑", size=11, bold=True)
    ws.cell(row=row_idx, column=5, value=grand_total)
    ws.cell(row=row_idx, column=5).font = Font(name="微软雅黑", size=11, bold=True)
    ws.cell(row=row_idx, column=5).number_format = _MONEY_FORMAT
    ws.cell(row=row_idx, column=6, value=grand_insurance if grand_insurance else "")
    ws.cell(row=row_idx, column=6).font = Font(name="微软雅黑", size=11, bold=True)
    ws.cell(row=row_idx, column=6).number_format = _MONEY_FORMAT
    ws.cell(row=row_idx, column=7, value=grand_out_of_pocket if grand_out_of_pocket else "")
    ws.cell(row=row_idx, column=7).font = Font(name="微软雅黑", size=11, bold=True)
    ws.cell(row=row_idx, column=7).number_format = _MONEY_FORMAT
    for col in range(1, len(headers) + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    # ── 列宽 ──
    col_widths = [8, 22, 28, 18, 16, 14, 14, 10, 10, 12]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # ── 打印设置 ──
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    results["医疗费用汇总表"] = output.getvalue()

    return results


def _collect_fee_receipt_items(catalog_data: dict) -> list[dict]:
    """从 catalog_data.groups 中提取 fee_receipt 分类的材料明细

    返回列表，每项包含：
      hospital_name, title, date, total_amount,
      insurance_amount, out_of_pocket,
      receipt_type(住院/门诊), stay_days, receipt_tail
    """
    items: list[dict] = []

    for group in catalog_data.get("groups", []):
        category = group.get("category", "")
        if category != "fee_receipt":
            continue

        for mat_item in group.get("items", []):
            fees = mat_item.get("fees", {}) or {}
            identity = mat_item.get("identity", {}) or {}
            evidence_name = mat_item.get("evidence_name", {}) or {}
            raw_extracted = mat_item.get("raw_extracted", {}) or {}
            layer3 = raw_extracted.get("layer_3_treatment", {}) or {}

            # 总额
            total_amount = fees.get("total_amount", 0) or 0

            # 如果 total_amount 为 0，尝试从 items 汇总
            if total_amount <= 0:
                fee_items_list = fees.get("items", []) or []
                for fi in fee_items_list:
                    a = fi.get("amount", 0) or 0
                    # 尝试将字符串转换为数字
                    if isinstance(a, str):
                        try:
                            a = float(a)
                        except (ValueError, TypeError):
                            a = 0
                    if isinstance(a, (int, float)) and a > 0:
                        total_amount += a

            # 医院名
            hospital_name = identity.get("hospital_name", "")

            # 日期
            date_str = evidence_name.get("date", "")
            # 尝试从诊疗经过获取入院-出院日期
            admission = layer3.get("admission_date", "")
            discharge = layer3.get("discharge_date", "")

            # 判断住院/门诊
            stay_days = ""
            receipt_type = "门诊"
            if admission and discharge:
                receipt_type = "住院"
                try:
                    from datetime import datetime
                    d1 = datetime.strptime(admission[:10], "%Y-%m-%d")
                    d2 = datetime.strptime(discharge[:10], "%Y-%m-%d")
                    stay_days = (d2 - d1).days
                    if stay_days < 0:
                        stay_days = ""
                except (ValueError, IndexError):
                    stay_days = ""
                date_str = f"{admission[:10]} ~ {discharge[:10]}"

            # 报销/自费
            insurance_amount = fees.get("insurance_amount") or 0
            if isinstance(insurance_amount, str):
                try:
                    insurance_amount = float(insurance_amount)
                except (ValueError, TypeError):
                    insurance_amount = 0
            out_of_pocket = fees.get("out_of_pocket") or 0
            if isinstance(out_of_pocket, str):
                try:
                    out_of_pocket = float(out_of_pocket)
                except (ValueError, TypeError):
                    out_of_pocket = 0

            # 票据尾号 — 从原始文件名取后4位数字
            original_filename = _clean_text(evidence_name.get("original_filename", "")) or mat_item.get("title", "")
            receipt_tail = _extract_receipt_tail(original_filename)

            # 标题 — 清理JSON污染
            title = _clean_text(evidence_name.get("title", "")) or _clean_text(mat_item.get("title", ""))

            # 医院名 — 清理JSON污染
            hospital_name = _clean_text(hospital_name)

            # 日期 — 清理JSON污染
            date_str = _clean_text(date_str)

            items.append({
                "hospital_name": hospital_name,
                "title": title,
                "date": date_str,
                "total_amount": total_amount,
                "insurance_amount": insurance_amount,
                "out_of_pocket": out_of_pocket,
                "receipt_type": receipt_type,
                "stay_days": stay_days,
                "receipt_tail": receipt_tail,
            })

    return items


def _extract_receipt_tail(filename: str) -> str:
    """从文件名中提取票据尾号（取最后4位数字）"""
    import re
    digits = re.findall(r"\d", filename)
    if len(digits) >= 4:
        return "".join(digits[-4:])
    return ""
