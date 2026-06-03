"""
结构化质量评分器
多维度评分：OCR置信度、结构完整性、标题层级合理性、异常检测
"""
from __future__ import annotations

import statistics

from loguru import logger


def _score_ocr_confidence(ocr_summary: dict) -> tuple[float, dict]:
    """
    评分维度1：OCR识别质量（权重 0.35）
    基于整体和分页置信度
    """
    avg_conf = ocr_summary.get("confidence_avg", 0)
    total_pages = ocr_summary.get("total_pages", 0)
    confidence_by_page = [
        p.get("confidence_avg", 0)
        for p in ocr_summary.get("pages", [])
    ]

    # 置信度直接作为分数
    score = min(avg_conf, 1.0)

    # 低置信度页面惩罚
    low_conf_pages = sum(1 for c in confidence_by_page if c < 0.6)
    if low_conf_pages > 0 and total_pages > 0:
        penalty = (low_conf_pages / total_pages) * 0.2
        score = max(0, score - penalty)

    detail = {
        "confidence_avg": round(avg_conf, 4),
        "low_confidence_pages": low_conf_pages,
        "page_count": total_pages,
    }

    return score, detail


def _score_structure_completeness(structure: dict) -> tuple[float, dict]:
    """
    评分维度2：结构完整性（权重 0.25）
    检查是否有标题、段落、层级结构
    """
    sections = structure.get("sections", [])
    orphan = structure.get("orphan_paragraphs", [])
    total_paragraphs = structure.get("total_paragraphs", 0)
    total_sections = structure.get("total_sections", 0)

    score = 0.0
    factors = []

    # 是否有标题层级（最重要）
    if total_sections > 0:
        score += 0.4
        factors.append("has_sections")

        # 检查层级深度
        max_depth = _max_heading_depth(sections)
        if max_depth >= 3:
            score += 0.3
            factors.append("deep_hierarchy")
        elif max_depth >= 2:
            score += 0.2
            factors.append("moderate_hierarchy")
        else:
            score += 0.1
            factors.append("shallow_hierarchy")
    else:
        factors.append("no_sections")

    # 是否有正文段落
    if total_paragraphs > 0:
        score += 0.2
        factors.append("has_paragraphs")

        # 段落数合理性
        if total_paragraphs >= 5:
            score += 0.1
            factors.append("sufficient_paragraphs")
    else:
        factors.append("no_paragraphs")

    # 孤儿段落比例（孤儿太多说明结构差）
    orphan_ratio = len(orphan) / max(total_paragraphs, 1)
    if orphan_ratio < 0.2:
        score = min(score, 1.0)
    elif orphan_ratio < 0.5:
        score *= 0.8
    else:
        score *= 0.6
        factors.append("high_orphan_ratio")

    detail = {
        "total_sections": total_sections,
        "total_paragraphs": total_paragraphs,
        "max_heading_depth": _max_heading_depth(sections),
        "orphan_ratio": round(orphan_ratio, 3),
        "factors": factors,
    }

    return min(score, 1.0), detail


def _score_heading_quality(sections: list[dict]) -> tuple[float, dict]:
    """
    评分维度3：标题层级合理性（权重 0.20）
    检查标题层级是否合理（不过跳、不过密）
    """
    if not sections:
        return 0.0, {"error": "no_sections"}

    score = 0.7  # 基础分
    issues = []

    # 遍历检查层级跳跃
    def check_levels(secs, parent_level=0):
        nonlocal score, issues
        prev_level = parent_level
        for s in secs:
            level = s.get("level", 1)

            # 检查层级跳跃（不能跳 > 1 级）
            if prev_level > 0 and level > prev_level + 1:
                issues.append(f"level_skip: {prev_level}→{level}")
                score -= 0.05
            prev_level = level

            # 递归检查子节（传递当前 level 作为子节的前驱）
            subs = s.get("subsections", [])
            if subs:
                check_levels(subs, level)

    check_levels(sections)

    # 层级均匀性
    all_levels = []
    def collect_levels(secs):
        for s in secs:
            all_levels.append(s.get("level", 1))
            subs = s.get("subsections", [])
            if subs:
                collect_levels(subs)

    collect_levels(sections)

    if all_levels:
        # 标题密度检查（如果标题太密说明可能有误判）
        unique_levels = set(all_levels)
        if len(unique_levels) < 2 and len(all_levels) > 5:
            issues.append("uniform_level")
            score -= 0.1

    detail = {
        "issues": issues,
        "heading_count": len(all_levels),
        "unique_levels": len(unique_levels) if all_levels else 0,
    }

    return max(0.0, min(1.0, score)), detail


def _score_data_quality(structure: dict, lists: list[dict], tables: list[dict]) -> tuple[float, dict]:
    """
    评分维度4：数据质量（权重 0.10）
    检查表格/列表等结构化数据的完整性
    """
    score = 0.5  # 基础分
    factors = []

    # 列表质量
    if lists:
        score += 0.15
        factors.append("has_lists")
        # 平均列表项数
        avg_items = sum(len(lst.get("items", [])) for lst in lists) / max(len(lists), 1)
        if avg_items >= 3:
            score += 0.1
            factors.append("rich_lists")
    else:
        factors.append("no_lists")

    # 表格质量
    if tables:
        score += 0.15
        factors.append("has_tables")
        # 检查表格是否非空
        valid_tables = sum(
            1 for t in tables
            if t.get("rows", 0) > 0 and t.get("cols", 0) > 0
        )
        if valid_tables > 0:
            score += 0.1
            factors.append("valid_tables")
    else:
        factors.append("no_tables")

    detail = {
        "list_count": len(lists),
        "table_count": len(tables),
        "valid_table_count": sum(
            1 for t in tables if t.get("rows", 0) > 0 and t.get("cols", 0) > 0
        ),
        "factors": factors,
    }

    return min(1.0, score), detail


def _score_anomaly_detection(structure: dict, ocr_summary: dict) -> tuple[float, dict]:
    """
    评分维度5：异常检测（权重 0.10）
    检测空页、极端置信度、结构异常
    """
    score = 1.0
    anomalies = []

    # 检测空页
    pages = ocr_summary.get("pages", [])
    empty_pages = sum(
        1 for p in pages
        if p.get("result_count", 0) == 0
    )
    if empty_pages > 0:
        ratio = empty_pages / max(len(pages), 1)
        if ratio > 0.3:
            score -= 0.3
            anomalies.append(f"many_empty_pages:{empty_pages}")
        else:
            score -= 0.1 * empty_pages
            anomalies.append(f"empty_pages:{empty_pages}")

    # 检测置信度异常（极低或方差大）
    conf_values = [p.get("confidence_avg", 0) for p in pages if p.get("confidence_avg", 0) > 0]
    if conf_values:
        try:
            stdev = statistics.stdev(conf_values) if len(conf_values) >= 2 else 0
            if stdev > 0.2:
                score -= 0.1
                anomalies.append(f"high_confidence_variance:{stdev:.3f}")
        except Exception as e:
            logger.debug(f"Confidence stdev calculation skipped: {e}")

        # 极低置信度
        very_low = sum(1 for c in conf_values if c < 0.3)
        if very_low > 0:
            score -= 0.1
            anomalies.append(f"very_low_confidence_pages:{very_low}")

    # 全空结构
    if structure.get("total_sections", 0) == 0 and structure.get("total_paragraphs", 0) == 0:
        score -= 0.3
        anomalies.append("empty_structure")

    detail = {
        "anomalies": anomalies,
        "empty_pages": empty_pages,
    }

    return max(0.0, score), detail


def _max_heading_depth(sections: list[dict]) -> int:
    """计算最大标题层级深度"""
    if not sections:
        return 0
    max_d = 0
    for s in sections:
        depth = 1
        subs = s.get("subsections", [])
        if subs:
            depth += _max_heading_depth(subs)
        max_d = max(max_d, depth)
    return max_d


def score_structure(
    structured: dict,
    ocr_summary: dict | None = None,
    lists: list[dict] | None = None,
    tables: list[dict] | None = None,
) -> dict:
    """
    多维度结构化质量评分

    Args:
        structured: 结构化结果，包含 sections, orphan_paragraphs 等
        ocr_summary: OCR 汇总数据 {confidence_avg, pages: [...]}
        lists: 检测到的列表
        tables: 检测到的表格

    Returns:
        {
            "structure_score": float (0~1),
            "dimensions": {
                "ocr_confidence": {score, weight, detail},
                "structure_completeness": {score, weight, detail},
                "heading_quality": {score, weight, detail},
                "data_quality": {score, weight, detail},
                "anomaly_detection": {score, weight, detail},
            },
            "warnings": [...],
        }
    """
    ocr_summary = ocr_summary or {}
    lists = lists or []
    tables = tables or []

    # 权重配置
    weights = {
        "ocr_confidence": 0.35,
        "structure_completeness": 0.25,
        "heading_quality": 0.20,
        "data_quality": 0.10,
        "anomaly_detection": 0.10,
    }

    # 各维度评分
    ocr_score, ocr_detail = _score_ocr_confidence(ocr_summary)
    structure_score, structure_detail = _score_structure_completeness(structured)
    heading_score, heading_detail = _score_heading_quality(structured.get("sections", []))
    data_score, data_detail = _score_data_quality(structured, lists, tables)
    anomaly_score, anomaly_detail = _score_anomaly_detection(structured, ocr_summary)

    dimensions = {
        "ocr_confidence": {
            "score": round(ocr_score, 4),
            "weight": weights["ocr_confidence"],
            "detail": ocr_detail,
        },
        "structure_completeness": {
            "score": round(structure_score, 4),
            "weight": weights["structure_completeness"],
            "detail": structure_detail,
        },
        "heading_quality": {
            "score": round(heading_score, 4),
            "weight": weights["heading_quality"],
            "detail": heading_detail,
        },
        "data_quality": {
            "score": round(data_score, 4),
            "weight": weights["data_quality"],
            "detail": data_detail,
        },
        "anomaly_detection": {
            "score": round(anomaly_score, 4),
            "weight": weights["anomaly_detection"],
            "detail": anomaly_detail,
        },
    }

    # 加权总分
    total_score = sum(
        dim["score"] * dim["weight"]
        for dim in dimensions.values()
    )

    # 生成警告
    warnings = []
    if total_score < 0.5:
        warnings.append("low_overall_quality")
    if ocr_score < 0.5:
        warnings.append("poor_ocr_quality")
    if structure_score < 0.3:
        warnings.append("insufficient_structure")
    if anomaly_detail.get("anomalies"):
        for a in anomaly_detail["anomalies"]:
            warnings.append(f"anomaly:{a}")

    logger.info(
        f"Quality scoring: {total_score:.4f} "
        f"(OCR:{ocr_score:.3f} Struct:{structure_score:.3f} "
        f"Head:{heading_score:.3f} Data:{data_score:.3f})"
    )

    return {
        "structure_score": round(total_score, 4),
        "dimensions": dimensions,
        "warnings": warnings,
    }
