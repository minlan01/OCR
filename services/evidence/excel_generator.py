"""
Excel 费用生成器 — 生成赔偿费用总表和医疗费用汇总表 Excel
========================================================
表1: 赔偿费用清单 — 标准8大赔偿项目 + 计算依据 + 金额
表2: 医疗费用汇总表 — 按医院分组、逐条明细（住院/门诊、报销/自费）
新增: generate_fee_excel_zip — 10项赔偿明细 ZIP 包
"""
from __future__ import annotations

import io
import uuid
import zipfile
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


def generate_compensation_calculation_excel(compensation_data: dict | None, case_name: str = "",
                                              plaintiff_name: str = "", case_type: str = "injury") -> bytes:
    """生成赔偿费用清单 Excel（标准法律文书格式，参照手工模板）

    格式与手工填写的赔偿费用清单一致：
    - 标题行：赔偿费用清单
    - 表头：序号 | 项目 | 计算依据 | 金额（元）
    - 各项赔偿费用（金额为 0 的项目跳过，不输出空行）
    - 护理费子行：上方金额行含用品发票小计，下方子行写住院天数计算过程
    - 合计行：用 SUM 公式（对金额列所有数据行求和）
    - 备注行

    当 compensation_data 为空或没有 items 时，按案件类型生成模板：
    项目名称和计算依据照出，金额列留白（显示横线）。

    Args:
        compensation_data: calculate_all() 返回的赔偿计算结果字典，可为 None/空
        case_name: 案件名称
        plaintiff_name: 原告姓名
        case_type: 案件类型 injury/death
    """
    compensation_data = compensation_data or {}
    items = compensation_data.get('items', [])
    params = compensation_data.get('params', {})
    has_data = bool(items)

    wb = Workbook()
    ws = wb.active
    ws.title = "赔偿费用清单"

    # 样式
    title_font = Font(name='宋体', size=14, bold=True)
    header_font = Font(name='宋体', size=11, bold=True)
    cell_font = Font(name='宋体', size=11)
    money_fmt = '#,##0.00'
    bold_font = Font(name='宋体', size=11, bold=True)

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin'),
    )

    # 列宽（4列：序号、项目、计算依据、金额）
    col_widths = [8, 20, 55, 18]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── 标题行 ──
    ws.merge_cells('A1:D1')
    ws['A1'] = '赔偿费用清单'
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal='center')

    # ── 表头（行2）──
    headers = ['序号', '项目', '计算依据', '金额（元）']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col, value=header)
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    row_idx = 3
    seq = 1
    # 记录金额列的数据行号，用于合计 SUM 公式
    amount_rows: list[int] = []

    if has_data:
        # ── 有计算数据：只输出金额 > 0 或 manual_amount 不为 null 的项目 ──
        for item in items:
            fee_type = item.get('fee_type', '')
            fee_name = item.get('fee_name', '')
            amount = item.get('manual_amount') or item.get('amount', 0)
            basis = item.get('calculation_basis', '')
            try:
                amount = float(str(amount))
            except (ValueError, TypeError):
                amount = 0.0

            # dependent_living 不在清单中单独列出（已包含在残疾/死亡赔偿金中）
            if fee_type == 'dependent_living':
                continue

            ws.cell(row=row_idx, column=1, value=seq).font = cell_font
            ws.cell(row=row_idx, column=1).border = thin_border
            ws.cell(row=row_idx, column=1).alignment = Alignment(horizontal='center')

            ws.cell(row=row_idx, column=2, value=fee_name).font = cell_font
            ws.cell(row=row_idx, column=2).border = thin_border

            # 护理费主行：basis 写护理用品发票部分，金额用完整金额
            # 非护理费正常写 basis
            if fee_type == 'nursing_fee':
                supplies_basis = _get_nursing_supplies_basis(item)
                ws.cell(row=row_idx, column=3, value=supplies_basis).font = cell_font
            else:
                ws.cell(row=row_idx, column=3, value=basis).font = cell_font
            ws.cell(row=row_idx, column=3).border = thin_border

            cell_amount = ws.cell(row=row_idx, column=4, value=amount)
            cell_amount.number_format = money_fmt
            cell_amount.font = cell_font
            cell_amount.border = thin_border
            cell_amount.alignment = Alignment(horizontal='center')
            amount_rows.append(row_idx)

            row_idx += 1

            # 护理费子行：写住院天数计算过程，序号/项目/金额列合并
            if fee_type == 'nursing_fee':
                sub_detail = _get_nursing_sub_detail(params, plaintiff_name)
                if sub_detail:
                    # 合并序号、项目、金额列
                    ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=1)
                    ws.merge_cells(start_row=row_idx, start_column=2, end_row=row_idx, end_column=2)
                    ws.merge_cells(start_row=row_idx, start_column=4, end_row=row_idx, end_column=4)
                    ws.cell(row=row_idx, column=3, value=sub_detail).font = cell_font
                    for c in range(1, 5):
                        ws.cell(row=row_idx, column=c).border = thin_border
                    row_idx += 1
            else:
                # 非护理费子行详细计算依据
                sub_row = _get_calculation_detail(fee_type, params, plaintiff_name)
                if sub_row:
                    ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=1)
                    ws.merge_cells(start_row=row_idx, start_column=2, end_row=row_idx, end_column=2)
                    ws.merge_cells(start_row=row_idx, start_column=4, end_row=row_idx, end_column=4)
                    ws.cell(row=row_idx, column=3, value=sub_row).font = cell_font
                    for c in range(1, 5):
                        ws.cell(row=row_idx, column=c).border = thin_border
                    row_idx += 1

            seq += 1

        # 合计行：用 SUM 公式
        if amount_rows:
            sum_parts = "+".join(f"D{r}" for r in amount_rows)
            sum_formula = f"={sum_parts}"
        else:
            sum_formula = 0
    else:
        # ── 无计算数据：按案件类型生成模板，金额留白 ──
        template_items = _get_template_items(case_type)
        for fee_name, basis in template_items:
            ws.cell(row=row_idx, column=1, value=seq).font = cell_font
            ws.cell(row=row_idx, column=1).border = thin_border
            ws.cell(row=row_idx, column=1).alignment = Alignment(horizontal='center')

            ws.cell(row=row_idx, column=2, value=fee_name).font = cell_font
            ws.cell(row=row_idx, column=2).border = thin_border

            ws.cell(row=row_idx, column=3, value=basis).font = cell_font
            ws.cell(row=row_idx, column=3).border = thin_border

            # 金额留白（横线占位）
            cell_amount = ws.cell(row=row_idx, column=4, value="——")
            cell_amount.font = cell_font
            cell_amount.border = thin_border
            cell_amount.alignment = Alignment(horizontal='center')

            row_idx += 1
            seq += 1

        sum_formula = "——"

    # ── 合计行 ──
    ws.cell(row=row_idx, column=2, value='总计').font = bold_font
    ws.cell(row=row_idx, column=2).border = thin_border
    ws.cell(row=row_idx, column=2).alignment = Alignment(horizontal='center')
    ws.cell(row=row_idx, column=1).border = thin_border
    ws.cell(row=row_idx, column=3).border = thin_border
    cell_total = ws.cell(row=row_idx, column=4, value=sum_formula)
    if isinstance(sum_formula, str) and sum_formula.startswith('='):
        cell_total.number_format = money_fmt
    cell_total.font = bold_font
    cell_total.border = thin_border
    cell_total.alignment = Alignment(horizontal='center')
    row_idx += 1

    # ── 备注行 ──
    if case_type == "injury":
        note = "备注：因本案尚未鉴定，故上述各项赔偿费用及残疾赔偿金等费用待鉴定后再行补充变更。"
    else:
        note = "备注：因本案尚未鉴定，故上述各项赔偿费用及鉴定费等，待鉴定后再行补充变更。"
    ws.merge_cells(f'A{row_idx}:D{row_idx}')
    ws.cell(row=row_idx, column=1, value=note).font = cell_font

    # ── 打印设置 ──
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _get_nursing_supplies_basis(item: dict) -> str:
    """生成护理费主行的计算依据（护理用品发票部分）"""
    sources = item.get('sources', [])
    if sources:
        filenames = [s.get('filename', '') for s in sources if s.get('filename')]
        if filenames:
            return f"原告方因此次事件支付的医护用品费用合计（见{'、'.join(filenames[:3])}）"
    return "原告方因此次事件支付的医护用品费用"


def _get_nursing_sub_detail(params: dict, plaintiff_name: str = "") -> str:
    """生成护理费子行的详细计算依据（住院天数 × 日护理费）"""
    try:
        hospital_days = int(float(params.get('nursing_days', 0) or params.get('hospital_days', 0)))
        annual_salary = float(params.get('nursing_annual_salary', 0))
        if annual_salary == 0:
            legacy = params.get('nursing_monthly_salary') or params.get('monthly_salary') or 8500
            annual_salary = float(legacy) * 12
        person_count = int(params.get('nursing_person_count', 1) or 1)
        dep_level = str(params.get('nursing_dependency_level') or 'full')
    except (ValueError, TypeError):
        return ""

    if hospital_days <= 0:
        return ""

    name = plaintiff_name or "原告"
    # 使用全精度日费率用于展示（与计算引擎一致）
    daily = annual_salary / 365

    dep_map = {"full": "完全护理依赖(100%)", "mostly": "大部分护理依赖(80%)", "partial": "部分护理依赖(50%)"}
    dep_label = dep_map.get(dep_level, "")

    person_part = f"× {person_count}人" if person_count > 1 else ""
    dep_part = f"× {dep_label}" if dep_level != "full" else ""

    return f"{name}共住院治疗{hospital_days}天，其护理费按上一年度居民服务、修理和其他服务业非私营单位在岗职工年平均工资{annual_salary:.0f}元/年计算：{annual_salary:.0f}元/年÷365天×{hospital_days}天{person_part}{dep_part}"


def _get_template_items(case_type: str) -> list[tuple[str, str]]:
    """按案件类型返回模板赔偿项目（名称 + 计算依据），用于无数据时的空模板生成"""
    if case_type == "death":
        return [
            ("医疗费", "凭票据实报实销"),
            ("误工费", "误工收入 × 误工天数（参照鉴定意见）"),
            ("护理费", "住院期间护理费 = 护理标准 × 住院天数"),
            ("住院伙食补助费", "住院伙食补助标准 × 住院天数"),
            ("营养费", "营养费标准 × 营养期天数（参照鉴定意见）"),
            ("死亡赔偿金", "受诉法院所在地上年度城镇居民人均可支配收入 × 20年（含被扶养人生活费）"),
            ("丧葬费", "受诉法院所在地上年度职工月平均工资 × 6个月"),
            ("交通费", "凭票据实报实销"),
            ("精神损害抚慰金", "根据死亡后果酌定"),
        ]
    else:
        # injury（含新生儿）
        return [
            ("医疗费", "凭票据实报实销"),
            ("误工费", "误工收入 × 误工天数（参照鉴定意见）"),
            ("护理费", "住院期间护理费 = 护理标准 × 住院天数"),
            ("住院伙食补助费", "住院伙食补助标准 × 住院天数"),
            ("营养费", "营养费标准 × 营养期天数（参照鉴定意见）"),
            ("残疾赔偿金", "受诉法院所在地上年度城镇居民人均可支配收入 × 20年 × 伤残系数（含被扶养人生活费）"),
            ("后续治疗费", "参照鉴定意见或后续实际发生费用"),
            ("交通费", "凭票据实报实销"),
            ("精神损害抚慰金", "根据伤残等级酌定"),
        ]


def _get_calculation_detail(fee_type: str, params: dict, plaintiff_name: str = "") -> str:
    """生成子行的详细计算依据说明（参照手工模板格式）

    仅对部分需要详细说明的项目生成子行，其他返回空字符串。
    护理费由 _get_nursing_sub_detail 独立处理，此函数不再处理。
    """
    try:
        hospital_days = int(float(params.get('hospital_days', 0)))
        annual_income = float(params.get('annual_income', 49283))
        monthly_salary = float(params.get('monthly_salary', 8500))
        daily_food = float(params.get('daily_food_subsidy', 100))
        daily_nutrition = float(params.get('daily_nutrition', 50))
        compensation_years = int(float(params.get('compensation_years', 20)))
        disability_coeff = float(params.get('disability_coefficient', 1.0))
        lost_wage_days = int(float(params.get('lost_wage_days', 0)))
        victim_age = int(float(params.get('victim_age', 0)))
    except (ValueError, TypeError):
        return ""

    name = plaintiff_name or "原告"

    if fee_type == 'lost_wages' and lost_wage_days > 0:
        daily = monthly_salary / 30
        return f"{name}的误工费按上一年度职工月平均工资{monthly_salary:.0f}元/月计算：{monthly_salary:.0f}元/月÷30天×{lost_wage_days}天"

    if fee_type == 'food_subsidy' and hospital_days > 0:
        return f"{name}共住院治疗{hospital_days}天，按{daily_food:.0f}元/天计算：{daily_food:.0f}元/天×{hospital_days}天"

    if fee_type == 'nutrition_fee' and hospital_days > 0:
        return f"{name}共住院治疗{hospital_days}天，按{daily_nutrition:.0f}元/天计算：{daily_nutrition:.0f}元/天×{hospital_days}天"

    if fee_type == 'disability_compensation' and compensation_years > 0:
        basis = f"按上一年度城镇居民人均可支配收入{annual_income:.0f}元/年×{compensation_years}年×伤残系数{disability_coeff}"
        # 含被扶养人生活费标注
        annual_consumption = float(params.get('annual_consumption', 0))
        if annual_consumption > 0:
            dep_amt = annual_consumption * compensation_years * disability_coeff
            basis += f"（含被扶养人生活费 ¥{dep_amt:.2f}）"
        return basis

    if fee_type == 'death_compensation':
        # 死亡赔偿金年龄递减
        if victim_age > 0:
            if victim_age >= 75:
                actual_years = 5
            elif victim_age >= 60:
                actual_years = max(20 - (victim_age - 60), 5)
            else:
                actual_years = compensation_years if compensation_years > 0 else 20
        else:
            actual_years = compensation_years
        if actual_years > 0:
            basis = f"按上一年度城镇居民人均可支配收入{annual_income:.0f}元/年×{actual_years}年"
            annual_consumption = float(params.get('annual_consumption', 0))
            if annual_consumption > 0:
                dep_amt = annual_consumption * actual_years
                basis += f"（含被扶养人生活费 ¥{dep_amt:.2f}）"
            return basis

    if fee_type == 'funeral_fee':
        return f"按上一年度职工月平均工资{monthly_salary:.0f}元/月，以六个月总额计算：{monthly_salary:.0f}元/月×6月"

    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 10项赔偿明细 ZIP 包生成
# ═══════════════════════════════════════════════════════════════════════════════

# 10项赔偿明细 ZIP 包中的文件名顺序与 fee_type 映射
ZIP_FEE_ITEMS_ORDER: list[tuple[str, str]] = [
    # (文件名中文名, 对应 compensation_data.items 中的 fee_type)
    ("医疗费", "medical_fee"),
    ("误工费", "lost_wages"),
    ("护理费", "nursing_fee"),
    ("住院伙食补助费", "food_subsidy"),
    ("营养费", "nutrition_fee"),
    ("残疾赔偿金", "disability_compensation"),
    ("死亡赔偿金", "death_compensation"),
    ("交通住宿费", "transport_fee"),
    ("鉴定费", "appraisal_fee"),
    ("精神损害抚慰金", "spiritual_damage"),
    ("被扶养人生活费", "dependent_living"),
]


def _collect_fee_receipt_items_v2(catalog_data: dict) -> list[dict]:
    """从 catalog_data.groups 中提取 fee_receipt 分类材料明细（支持新版带 fee_type 字段的结构）。

    返回列表，每项包含：
      fee_type, hospital_name, title, date, amount, insurance_amount,
      self_pay_amount, receipt_type, stay_days, receipt_tail, evidence_page
    """
    items: list[dict] = []

    for group in catalog_data.get("groups", []):
        if group.get("category") != "fee_receipt":
            continue

        for mat_item in group.get("items", []):
            # 兼容新旧两种数据结构
            fee_type = mat_item.get("fee_type", "") or ""
            fees = mat_item.get("fees", {}) or {}
            identity = mat_item.get("identity", {}) or {}
            evidence_name = mat_item.get("evidence_name", {}) or {}
            raw_extracted = mat_item.get("raw_extracted", {}) or {}
            layer3 = raw_extracted.get("layer_3_treatment", {}) or {}
            layer4 = raw_extracted.get("layer_4_fees", {}) or (fees or {})

            # 金额
            amount = mat_item.get("amount") or fees.get("total_amount", 0) or 0
            if not isinstance(amount, (int, float)):
                try:
                    amount = float(str(amount).replace(",", ""))
                except (ValueError, TypeError):
                    amount = 0.0

            # 如果 amount 为 0，尝试从 items 汇总
            if amount <= 0:
                fee_items_list = layer4.get("items", []) or fees.get("items", []) or []
                for fi in fee_items_list:
                    a = fi.get("amount", 0) or 0
                    if isinstance(a, str):
                        try:
                            a = float(a.replace(",", ""))
                        except (ValueError, TypeError):
                            a = 0
                    if isinstance(a, (int, float)) and a > 0:
                        amount += a

            # 医院名
            hospital_name = _clean_text(identity.get("hospital_name", ""))

            # 日期
            date_str = _clean_text(evidence_name.get("date", "") or mat_item.get("date", ""))
            admission = layer3.get("admission_date", "")
            discharge = layer3.get("discharge_date", "")

            # 住院/门诊
            stay_days: Any = ""
            receipt_type = _clean_text(mat_item.get("fee_subtype", "")) or "门诊"
            if admission and discharge:
                receipt_type = "住院"
                try:
                    from datetime import datetime as _dt
                    d1 = _dt.strptime(admission[:10], "%Y-%m-%d")
                    d2 = _dt.strptime(discharge[:10], "%Y-%m-%d")
                    stay_days = (d2 - d1).days
                    if stay_days < 0:
                        stay_days = ""
                    date_str = f"{admission[:10]} ~ {discharge[:10]}"
                except (ValueError, IndexError):
                    stay_days = ""

            # 报销/自费
            insurance_amount = mat_item.get("insurance_amount") or fees.get("insurance_amount") or 0
            if isinstance(insurance_amount, str):
                try:
                    insurance_amount = float(insurance_amount.replace(",", ""))
                except (ValueError, TypeError):
                    insurance_amount = 0.0
            self_pay_amount = mat_item.get("self_pay_amount") or fees.get("out_of_pocket") or 0
            if isinstance(self_pay_amount, str):
                try:
                    self_pay_amount = float(self_pay_amount.replace(",", ""))
                except (ValueError, TypeError):
                    self_pay_amount = 0.0

            # 票据尾号
            original_filename = _clean_text(evidence_name.get("original_filename", "")) or mat_item.get("title", "")
            receipt_tail = _extract_receipt_tail(original_filename)

            # 标题
            title = _clean_text(evidence_name.get("title", "")) or _clean_text(mat_item.get("title", ""))

            # 证据页码（如存在）
            evidence_page = mat_item.get("evidence_page", "") or ""

            items.append({
                "fee_type": fee_type,
                "hospital_name": hospital_name,
                "title": title,
                "date": date_str,
                "amount": float(amount),
                "insurance_amount": float(insurance_amount),
                "self_pay_amount": float(self_pay_amount),
                "receipt_type": receipt_type,
                "stay_days": stay_days,
                "receipt_tail": receipt_tail,
                "evidence_page": evidence_page,
            })

    return items


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float，处理字符串/Decimal/None。"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return default


def _write_title_row(ws: Any, title: str, col_count: int) -> int:
    """写入标题行（合并第一行），返回下一可用行号。"""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = Font(name="微软雅黑", size=14, bold=True)
    cell.alignment = _CENTER_ALIGN
    return 2


def _write_header_row(ws: Any, headers: list[str], row: int) -> None:
    """写入表头行。"""
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=row, column=col_idx, value=header)
    _apply_header_style(ws, row, len(headers))


# ── 各类 Excel 生成函数 ──────────────────────────────────────────────────────

def _gen_medical_fee_excel(fee_items: list[dict], comp_item: dict | None, case_name: str = "") -> bytes:
    """医疗费用汇总表 — 参考医疗费用汇总表（李明凤）.xls 格式。

    表头：序号 | 名称 | 日期 | 金额 | 报销金额 | 个人自费部分 | 类型 | 住院天数 | 票据尾号 | 证据页码
    数据行：每个费用票据一行
    最后一行：总计行（合并名称列，汇总金额/报销/自费）
    空行填充到约 97 行。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    COL_COUNT = 10
    headers = ["序号", "名称", "日期", "金额", "报销金额", "个人自费部分", "类型", "住院天数", "票据尾号", "证据页码"]

    # 标题行（合并 A1:J1）
    _write_title_row(ws, "医疗费用汇总表", COL_COUNT)
    # 表头（行2）
    HEADER_ROW = 2
    _write_header_row(ws, headers, HEADER_ROW)

    row_idx = HEADER_ROW + 1
    seq = 1
    total_amount = 0.0
    total_insurance = 0.0
    total_self_pay = 0.0

    # 过滤医疗费类项（hospital_fee / outpatient_fee / pharmacy_fee / medical_fee 或空 fee_type 中含医院）
    medical_keywords = {"hospital_fee", "outpatient_fee", "pharmacy_fee", "medical_fee", "", None}
    for item in fee_items:
        ft = item.get("fee_type", "")
        # 只包含医疗类票据（排除护理用品/住宿/交通等）
        if ft and ft not in medical_keywords and "医疗" not in ft and "住院" not in ft and "门诊" not in ft and "药" not in ft:
            continue

        amount = item.get("amount", 0) or 0
        insurance = item.get("insurance_amount", 0) or 0
        self_pay = item.get("self_pay_amount", 0) or 0

        total_amount += amount
        total_insurance += insurance
        total_self_pay += self_pay

        # 名称：优先用医院名，否则用标题
        name = item.get("hospital_name", "") or item.get("title", "")
        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=name)
        ws.cell(row=row_idx, column=3, value=item.get("date", ""))
        ws.cell(row=row_idx, column=4, value=amount if amount else "")
        ws.cell(row=row_idx, column=5, value=insurance if insurance else "")
        ws.cell(row=row_idx, column=6, value=self_pay if self_pay else "")
        ws.cell(row=row_idx, column=7, value=item.get("receipt_type", ""))
        ws.cell(row=row_idx, column=8, value=item.get("stay_days", ""))
        ws.cell(row=row_idx, column=9, value=item.get("receipt_tail", ""))
        ws.cell(row=row_idx, column=10, value=item.get("evidence_page", ""))
        _apply_cell_style(ws, row_idx, COL_COUNT, money_cols={4, 5, 6})
        row_idx += 1
        seq += 1

    # 总计行：合并名称列（B 到 C），写"总计"
    total_row = row_idx
    ws.merge_cells(start_row=total_row, start_column=2, end_row=total_row, end_column=3)
    ws.cell(row=total_row, column=1, value="")
    ws.cell(row=total_row, column=2, value="总计")
    ws.cell(row=total_row, column=2).font = _BOLD_FONT
    ws.cell(row=total_row, column=2).alignment = _CENTER_ALIGN
    ws.cell(row=total_row, column=4, value=total_amount)
    ws.cell(row=total_row, column=4).font = _BOLD_FONT
    ws.cell(row=total_row, column=4).number_format = _MONEY_FORMAT
    ws.cell(row=total_row, column=5, value=total_insurance if total_insurance else "")
    ws.cell(row=total_row, column=5).font = _BOLD_FONT
    ws.cell(row=total_row, column=5).number_format = _MONEY_FORMAT
    ws.cell(row=total_row, column=6, value=total_self_pay if total_self_pay else "")
    ws.cell(row=total_row, column=6).font = _BOLD_FONT
    ws.cell(row=total_row, column=6).number_format = _MONEY_FORMAT
    for col in range(1, COL_COUNT + 1):
        ws.cell(row=total_row, column=col).border = _THIN_BORDER
        ws.cell(row=total_row, column=col).fill = _TOTAL_FILL
    row_idx = total_row + 1

    # 填充空行到约 97 行
    TARGET_ROWS = 97
    while row_idx <= TARGET_ROWS:
        for col in range(1, COL_COUNT + 1):
            ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        row_idx += 1

    # 列宽
    col_widths = [8, 28, 18, 14, 14, 14, 10, 10, 12, 10]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _gen_nursing_supplies_excel(fee_items: list[dict], comp_item: dict | None, case_name: str = "") -> bytes:
    """医护用品费统计表 — 参考护理用品费统计表（李明凤）.xls 格式。

    表头：序号 | 名称 | 日期 | 金额 | 类型 | 票据尾号
    合计行："合计" | | | 总金额 | |
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    COL_COUNT = 6
    headers = ["序号", "名称", "日期", "金额", "类型", "票据尾号"]

    _write_title_row(ws, "医护用品费统计表", COL_COUNT)
    _write_header_row(ws, headers, 2)

    row_idx = 3
    seq = 1
    total = 0.0

    # 筛选护理用品类
    for item in fee_items:
        ft = item.get("fee_type", "")
        if ft != "nursing_supplies" and "护理用品" not in ft and "医护用品" not in ft:
            continue
        amount = item.get("amount", 0) or 0
        total += amount
        name = item.get("title", "") or item.get("hospital_name", "")
        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=name)
        ws.cell(row=row_idx, column=3, value=item.get("date", ""))
        ws.cell(row=row_idx, column=4, value=amount if amount else "")
        ws.cell(row=row_idx, column=5, value=item.get("receipt_type", ""))
        ws.cell(row=row_idx, column=6, value=item.get("receipt_tail", ""))
        _apply_cell_style(ws, row_idx, COL_COUNT, money_cols={4})
        row_idx += 1
        seq += 1

    # 合计行
    ws.cell(row=row_idx, column=1, value="合计")
    ws.cell(row=row_idx, column=1).font = _BOLD_FONT
    ws.cell(row=row_idx, column=1).alignment = _CENTER_ALIGN
    ws.cell(row=row_idx, column=4, value=total)
    ws.cell(row=row_idx, column=4).font = _BOLD_FONT
    ws.cell(row=row_idx, column=4).number_format = _MONEY_FORMAT
    for col in range(1, COL_COUNT + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    col_widths = [8, 30, 18, 14, 10, 14]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _gen_accommodation_excel(fee_items: list[dict], comp_item: dict | None, case_name: str = "") -> bytes:
    """住宿费统计表 — 参考住宿费统计表（李明凤）.xls 格式。

    表头：序号 | 类型 | 住宿人员 | 日期 | 金额 | 备注 | 票据尾号
    总计行
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    COL_COUNT = 7
    headers = ["序号", "类型", "住宿人员", "日期", "金额", "备注", "票据尾号"]

    _write_title_row(ws, "住宿费统计表", COL_COUNT)
    _write_header_row(ws, headers, 2)

    row_idx = 3
    seq = 1
    total = 0.0

    for item in fee_items:
        ft = item.get("fee_type", "")
        if ft and "住宿" not in ft and ft != "accommodation_fee":
            continue
        amount = item.get("amount", 0) or 0
        total += amount
        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=item.get("receipt_type", "") or "住宿费")
        ws.cell(row=row_idx, column=3, value="")
        ws.cell(row=row_idx, column=4, value=item.get("date", ""))
        ws.cell(row=row_idx, column=5, value=amount if amount else "")
        ws.cell(row=row_idx, column=6, value=item.get("title", ""))
        ws.cell(row=row_idx, column=7, value=item.get("receipt_tail", ""))
        _apply_cell_style(ws, row_idx, COL_COUNT, money_cols={5})
        row_idx += 1
        seq += 1

    # 总计行
    ws.cell(row=row_idx, column=2, value="总计")
    ws.cell(row=row_idx, column=2).font = _BOLD_FONT
    ws.cell(row=row_idx, column=2).alignment = _CENTER_ALIGN
    ws.cell(row=row_idx, column=5, value=total)
    ws.cell(row=row_idx, column=5).font = _BOLD_FONT
    ws.cell(row=row_idx, column=5).number_format = _MONEY_FORMAT
    for col in range(1, COL_COUNT + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    col_widths = [8, 12, 14, 18, 14, 20, 14]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _gen_transport_excel(fee_items: list[dict], comp_item: dict | None, case_name: str = "") -> bytes:
    """交通费统计表。

    表头：序号 | 名称 | 日期 | 金额 | 备注 | 票据尾号
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    COL_COUNT = 6
    headers = ["序号", "名称", "日期", "金额", "备注", "票据尾号"]

    _write_title_row(ws, "交通费统计表", COL_COUNT)
    _write_header_row(ws, headers, 2)

    row_idx = 3
    seq = 1
    total = 0.0

    for item in fee_items:
        ft = item.get("fee_type", "")
        if ft and "交通" not in ft and ft != "transport_fee" and ft != "transportation":
            continue
        amount = item.get("amount", 0) or 0
        total += amount
        name = item.get("title", "") or item.get("hospital_name", "")
        ws.cell(row=row_idx, column=1, value=seq)
        ws.cell(row=row_idx, column=2, value=name)
        ws.cell(row=row_idx, column=3, value=item.get("date", ""))
        ws.cell(row=row_idx, column=4, value=amount if amount else "")
        ws.cell(row=row_idx, column=5, value="")
        ws.cell(row=row_idx, column=6, value=item.get("receipt_tail", ""))
        _apply_cell_style(ws, row_idx, COL_COUNT, money_cols={4})
        row_idx += 1
        seq += 1

    # 总计行
    ws.cell(row=row_idx, column=2, value="总计")
    ws.cell(row=row_idx, column=2).font = _BOLD_FONT
    ws.cell(row=row_idx, column=2).alignment = _CENTER_ALIGN
    ws.cell(row=row_idx, column=4, value=total)
    ws.cell(row=row_idx, column=4).font = _BOLD_FONT
    ws.cell(row=row_idx, column=4).number_format = _MONEY_FORMAT
    for col in range(1, COL_COUNT + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    col_widths = [8, 28, 18, 14, 20, 14]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _gen_simple_fee_excel(title: str, comp_item: dict | None, calc_basis: str = "") -> bytes:
    """简单格式 Excel（误工费/护理费/住院伙食补助费/营养费/残疾赔偿金/死亡赔偿金/鉴定费/精神损害抚慰金/被扶养人生活费）。

    表头：序号 | 项目 | 金额 | 计算依据
    数据行 + 合计行
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    COL_COUNT = 4
    headers = ["序号", "项目", "金额", "计算依据"]

    _write_title_row(ws, title, COL_COUNT)
    _write_header_row(ws, headers, 2)

    row_idx = 3

    # 从 comp_item 取金额和计算依据
    amount = 0.0
    basis = calc_basis
    if comp_item:
        amount = _to_float(comp_item.get("manual_amount") or comp_item.get("amount", 0))
        basis = comp_item.get("calculation_basis", "") or calc_basis

    ws.cell(row=row_idx, column=1, value=1)
    ws.cell(row=row_idx, column=2, value=title)
    ws.cell(row=row_idx, column=3, value=amount if amount else "")
    ws.cell(row=row_idx, column=4, value=basis)
    _apply_cell_style(ws, row_idx, COL_COUNT, money_cols={3})
    row_idx += 1

    # 合计行
    ws.cell(row=row_idx, column=2, value="合计")
    ws.cell(row=row_idx, column=2).font = _BOLD_FONT
    ws.cell(row=row_idx, column=2).alignment = _CENTER_ALIGN
    ws.cell(row=row_idx, column=3, value=amount if amount else "")
    ws.cell(row=row_idx, column=3).font = _BOLD_FONT
    ws.cell(row=row_idx, column=3).number_format = _MONEY_FORMAT
    for col in range(1, COL_COUNT + 1):
        ws.cell(row=row_idx, column=col).border = _THIN_BORDER
        ws.cell(row=row_idx, column=col).fill = _TOTAL_FILL

    col_widths = [8, 22, 16, 55]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def generate_fee_excel_zip(
    catalog_data: dict,
    analysis_result: dict,
    compensation_items: list[dict] | None,
) -> bytes:
    """生成 10 项赔偿明细 Excel ZIP 包。

    Args:
        catalog_data: 案件清单数据（含 groups, fee_summary）
        analysis_result: 分析结果
        compensation_items: 前端传来的当前编辑金额列表 [{fee_type, amount/manual_amount, ...}]

    Returns:
        ZIP 字节流，包含 10 个 xlsx 文件
    """
    case_name = analysis_result.get("case_name", "") or ""
    case_type = analysis_result.get("case_type", "injury")

    # 构建 fee_type → comp_item 映射
    comp_map: dict[str, dict] = {}
    if compensation_items:
        for item in compensation_items:
            ft = item.get("fee_type", "")
            if ft:
                comp_map[ft] = item

    # 从 catalog_data 提取费用票据
    fee_items = _collect_fee_receipt_items_v2(catalog_data)

    # 构建 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. 医疗费
        medical_bytes = _gen_medical_fee_excel(
            fee_items, comp_map.get("medical_fee"), case_name
        )
        zf.writestr("01_医疗费.xlsx", medical_bytes)

        # 2. 误工费
        lost_wages_bytes = _gen_simple_fee_excel(
            "误工费", comp_map.get("lost_wages"), "误工收入 × 误工天数（参照鉴定意见）"
        )
        zf.writestr("02_误工费.xlsx", lost_wages_bytes)

        # 3. 护理费 — 包含医护用品统计表
        nursing_main = _gen_simple_fee_excel(
            "护理费", comp_map.get("nursing_fee"), "住院期间护理费 = 护理标准 × 住院天数"
        )
        zf.writestr("03_护理费.xlsx", nursing_main)

        # 护理用品费统计表（作为护理费的补充明细）
        nursing_supplies_bytes = _gen_nursing_supplies_excel(
            fee_items, comp_map.get("nursing_fee"), case_name
        )
        zf.writestr("03_护理费_医护用品费统计表.xlsx", nursing_supplies_bytes)

        # 4. 住院伙食补助费
        food_bytes = _gen_simple_fee_excel(
            "住院伙食补助费", comp_map.get("food_subsidy"), "住院伙食补助标准 × 住院天数"
        )
        zf.writestr("04_住院伙食补助费.xlsx", food_bytes)

        # 5. 营养费
        nutrition_bytes = _gen_simple_fee_excel(
            "营养费", comp_map.get("nutrition_fee"), "营养费标准 × 营养期天数（参照鉴定意见）"
        )
        zf.writestr("05_营养费.xlsx", nutrition_bytes)

        # 6. 残疾赔偿金 / 死亡赔偿金（根据案件类型只生成一个）
        if case_type == "death":
            death_bytes = _gen_simple_fee_excel(
                "死亡赔偿金", comp_map.get("death_compensation"),
                "受诉法院所在地上年度城镇居民人均可支配收入 × 20年",
            )
            zf.writestr("06_死亡赔偿金.xlsx", death_bytes)
        else:
            disability_bytes = _gen_simple_fee_excel(
                "残疾赔偿金", comp_map.get("disability_compensation"),
                "受诉法院所在地上年度城镇居民人均可支配收入 × 20年 × 伤残系数",
            )
            zf.writestr("06_残疾赔偿金.xlsx", disability_bytes)

        # 7. 交通住宿费 — 包含交通费和住宿费两个统计表
        transport_bytes = _gen_transport_excel(
            fee_items, comp_map.get("transport_fee"), case_name
        )
        zf.writestr("07_交通费统计表.xlsx", transport_bytes)

        accommodation_bytes = _gen_accommodation_excel(
            fee_items, comp_map.get("transport_fee"), case_name
        )
        zf.writestr("07_住宿费统计表.xlsx", accommodation_bytes)

        # 8. 鉴定费
        appraisal_bytes = _gen_simple_fee_excel(
            "鉴定费", comp_map.get("appraisal_fee"), "凭票据实报实销"
        )
        zf.writestr("08_鉴定费.xlsx", appraisal_bytes)

        # 9. 精神损害抚慰金
        spiritual_bytes = _gen_simple_fee_excel(
            "精神损害抚慰金", comp_map.get("spiritual_damage"),
            "根据伤残等级/死亡后果酌定",
        )
        zf.writestr("09_精神损害抚慰金.xlsx", spiritual_bytes)

        # 10. 被扶养人生活费（如有）
        dependent_item = comp_map.get("dependent_living")
        dependent_bytes = _gen_simple_fee_excel(
            "被扶养人生活费", dependent_item,
            "受诉法院所在地上年度城镇居民人均消费支出 × 扶养年限",
        )
        zf.writestr("10_被扶养人生活费.xlsx", dependent_bytes)

    return zip_buffer.getvalue()
