"""
证据材料清单生成器
===================
将分类好的材料按 1.证据名称→2.身份信息→3.诊疗经过→4.费用明细 的四层结构生成清单。

每个材料项的展示严格遵循此顺序：
  - 证据名称（Layer 1）
  - 身份信息（Layer 2）
  - 诊疗经过（Layer 3）
  - 费用明细（Layer 4）
"""
from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from services.evidence.classifier import CATEGORY_ORDER, CATEGORY_NAMES


def generate_catalog(case_id: str) -> dict[str, Any]:
    """生成证据材料清单 catalog_data

    流程：
    1. 获取案件信息
    2. 获取所有已分类+已提取的材料
    3. 按 CATEGORY_ORDER 排序
    4. 组内按上传时间排序
    5. 每个材料按四层结构展示
    6. 生成编号、计算费用汇总
    7. 更新 case.catalog_data
    """
    from db.models_evidence import EvidenceCase, EvidenceMaterial
    from db.session import get_session_factory, run_in_worker
    from sqlalchemy import select

    async def _do_generate():
        case_uuid = uuid.UUID(case_id)
        async with get_session_factory()() as db:
            # 获取案件
            case_stmt = select(EvidenceCase).where(EvidenceCase.id == case_uuid)
            result = await db.execute(case_stmt)
            case = result.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")

            # 获取所有已分类的材料
            mat_stmt = (
                select(EvidenceMaterial)
                .where(
                    EvidenceMaterial.evidence_case_id == case_uuid,
                    EvidenceMaterial.effective_category.isnot(None),
                )
                .order_by(EvidenceMaterial.created_at.asc())
            )
            mat_result = await db.execute(mat_stmt)
            materials = mat_result.scalars().all()

            if not materials:
                catalog_data = {
                    "groups": [],
                    "fee_summary": {},
                    "total_amount": 0.0,
                    "total_items": 0,
                    "empty_reason": "no_materials",  # 区分空目录原因
                }
                case.catalog_data = catalog_data
                await db.commit()
                return catalog_data

            # 检查是否所有材料都处理失败
            all_failed = all(
                mat.ocr_status in ("failed", "pending")
                for mat in materials
            )
            if all_failed:
                catalog_data = {
                    "groups": [],
                    "fee_summary": {},
                    "total_amount": 0.0,
                    "total_items": 0,
                    "empty_reason": "all_failed",  # 所有材料处理失败
                    "material_count": len(materials),
                }
                case.catalog_data = catalog_data
                await db.commit()
                return catalog_data

            # 按 effective_category 分组
            groups: dict[str, list[EvidenceMaterial]] = {}
            for mat in materials:
                cat = mat.effective_category or "other_evidence"
                if cat not in groups:
                    groups[cat] = []
                groups[cat].append(mat)

            # 按 CATEGORY_ORDER 排序各组，生成四层结构目录
            sorted_groups: list[dict[str, Any]] = []
            index_counter = 1

            for category in CATEGORY_ORDER:
                if category not in groups:
                    continue

                cat_materials = groups[category]
                items = []
                for mat in cat_materials:
                    mat.catalog_index = index_counter

                    # 构建四层结构项
                    item_data = _build_four_layer_item(
                        index_counter=index_counter,
                        material=mat,
                        category=category,
                    )
                    items.append(item_data)
                    index_counter += 1

                sorted_groups.append({
                    "category": category,
                    "category_name": CATEGORY_NAMES.get(category, category),
                    "sort_order": _get_category_sort_order(category),
                    "items": items,
                })

            # 处理未在 CATEGORY_ORDER 中的分类
            for category, cat_materials in groups.items():
                if category in CATEGORY_ORDER:
                    continue
                items = []
                for mat in cat_materials:
                    mat.catalog_index = index_counter
                    item_data = _build_four_layer_item(
                        index_counter=index_counter,
                        material=mat,
                        category=category,
                    )
                    items.append(item_data)
                    index_counter += 1
                sorted_groups.append({
                    "category": category,
                    "category_name": CATEGORY_NAMES.get(category, category),
                    "sort_order": 99,
                    "items": items,
                })

            # 费用汇总
            fee_summary = _calculate_fee_summary(materials)
            total_amount = sum(
                v for v in fee_summary.values() if isinstance(v, (int, float))
            )

            catalog_data = {
                "groups": sorted_groups,
                "fee_summary": fee_summary,
                "total_amount": round(total_amount, 2),
                "total_items": index_counter - 1,
            }

            case.catalog_data = catalog_data
            await db.commit()

            logger.info(
                f"Catalog generated for case {case_id}: "
                f"{index_counter - 1} items, {len(sorted_groups)} groups, "
                f"total_amount={total_amount}"
            )
            return catalog_data

    return run_in_worker(_do_generate())


def _build_four_layer_item(
    index_counter: int,
    material,
    category: str,
) -> dict[str, Any]:
    """构建单个材料的四层结构目录项

    输出结构严格遵循: 证椐名称(L1) → 身份信息(L2) → 诊疗经过(L3) → 费用明细(L4)
    """
    extracted = material.extracted_data or {}

    # 各层数据
    layer1 = extracted.get("layer_1_evidence_name", {}) or {}
    layer2 = extracted.get("layer_2_identity", {}) or {}
    layer3 = extracted.get("layer_3_treatment", {}) or {}
    layer4 = extracted.get("layer_4_fees", {}) or {}

    # ── Layer 1: 证据名称 ──
    evidence_name = {
        "title": (
            material.catalog_title
            or layer1.get("title")
            or material.original_filename
            or f"证据{index_counter}"
        ),
        "doc_type": layer1.get("doc_type", category),
        "doc_type_name": CATEGORY_NAMES.get(layer1.get("doc_type", category), "其他证据"),
        "date": layer1.get("date", ""),
        "original_filename": material.original_filename,
        "file_type": material.file_type,
    }

    # ── Layer 2: 身份信息 ──
    identity = {
        "patient_name": layer2.get("patient_name", ""),
        "patient_id": _mask_id(layer2.get("patient_id", "")),
        "patient_gender": layer2.get("patient_gender", ""),
        "patient_birth": layer2.get("patient_birth", ""),
        "patient_address": layer2.get("patient_address", ""),
        "patient_phone": layer2.get("patient_phone", ""),
        "hospital_name": layer2.get("hospital_name", ""),
        "hospital_code": layer2.get("hospital_code", ""),
        "legal_representative": layer2.get("legal_representative", ""),
        "relationship": layer2.get("relationship", ""),
    }

    # ── Layer 3: 诊疗经过 ──
    treatment = {
        "admission_date": layer3.get("admission_date", ""),
        "discharge_date": layer3.get("discharge_date", ""),
        "diagnosis": layer3.get("diagnosis", ""),
        "symptoms": layer3.get("symptoms", ""),
        "treatment_summary": layer3.get("treatment_summary", ""),
        "operation_records": layer3.get("operation_records", ""),
    }

    # ── Layer 4: 费用明细 ──
    fee_items = layer4.get("items", []) or []
    fees = {
        "items": fee_items,
        "total_amount": layer4.get("total_amount", 0.0),
        "insurance_amount": layer4.get("insurance_amount"),
        "out_of_pocket": layer4.get("out_of_pocket"),
        "fee_summary_text": _format_fee_summary(fee_items, layer4.get("total_amount", 0)),
    }

    return {
        "index": index_counter,
        "material_id": str(material.id),
        "category": category,
        "category_name": CATEGORY_NAMES.get(category, category),
        "proof_purpose": material.proof_purpose or "",
        # ═══ 四层结构（核心） ═══
        "evidence_name": evidence_name,     # Layer 1
        "identity": identity,                # Layer 2
        "treatment": treatment,              # Layer 3
        "fees": fees,                        # Layer 4
        # 原始数据保留（兼容）
        "title": evidence_name["title"],
        "description": layer3.get("treatment_summary", material.catalog_description or ""),
        "fee_detail": material.fee_detail,
        "raw_extracted": extracted,
        # OCR 原文（用于 word_generator 的正则补充提取）
        "ocr_text": material.ocr_text or "",
    }


def _get_category_sort_order(category: str) -> int:
    """获取分类的排序权重"""
    order_map = {
        "identity_id_card": 1,
        "identity_hukou": 2,
        "identity_other": 3,
        "identity_defendant": 4,
        "death_certificate": 5,
        "medical_record": 6,
        "appraisal": 7,
        "fee_receipt": 8,
        "other_evidence": 9,
    }
    return order_map.get(category, 9)


def _mask_id(id_number: str) -> str:
    """身份证号脱敏：保留前6后4"""
    if not id_number or len(id_number) < 10:
        return id_number
    return id_number[:6] + "****" + id_number[-4:]


def _format_fee_summary(fee_items: list, total) -> str:
    """格式化费用摘要文本"""
    def _safe_float(v, default=0.0):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    total = _safe_float(total)
    if not fee_items:
        return f"合计：{total:.2f}元" if total else ""
    parts = [f"{item.get('fee_type', '')} {_safe_float(item.get('amount', 0)):.2f}元" for item in fee_items[:5]]
    text = "；".join(parts)
    if len(fee_items) > 5:
        text += f" 等共{len(fee_items)}项"
    if total:
        text += f"，合计：{total:.2f}元"
    return text


def _calculate_fee_summary(materials: list) -> dict[str, Any]:
    """从材料的四层提取数据中汇总费用（使用Decimal避免浮点精度问题）"""
    from decimal import Decimal, ROUND_HALF_UP

    fee_summary: dict[str, Decimal] = {}

    for mat in materials:
        extracted = mat.extracted_data or {}
        layer4 = extracted.get("layer_4_fees", {}) or {}

        # 优先从 fee_detail 汇总
        fee_detail = mat.fee_detail or {}
        items = fee_detail.get("items") or layer4.get("items") or []

        for item in items:
            fee_type = item.get("fee_type", "")
            amount = item.get("amount", 0)
            if fee_type and isinstance(amount, (int, float)) and amount > 0:
                amount_dec = Decimal(str(amount))
                if fee_type in fee_summary:
                    fee_summary[fee_type] += amount_dec
                else:
                    fee_summary[fee_type] = amount_dec

    return {k: float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) for k, v in fee_summary.items()}
