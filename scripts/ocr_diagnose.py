#!/usr/bin/env python3
"""
OCR 质量诊断脚本

对指定案件的所有上传素材重新跑 RapidOCR，导出 CSV 报告：
- 每图的平均置信度 / 字符数 / 低质文本片段 Top5
- 关键字段（金额/报销/自费）命中情况
- 低质图清单 + 具体问题位置

用法:
    python scripts/ocr_diagnose.py <case_id>
    python scripts/ocr_diagnose.py 9950f946-1f90-4a65-a145-adf31948c44c

输出:
    .workbuddy/ocr_diagnosis_<case_id_short>.csv
    .workbuddy/ocr_diagnosis_<case_id_short>_low_quality.txt
"""
from __future__ import annotations

import sys
import io
import json
import csv
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from config.settings import settings


def fetch_case_catalog_data(case_id: str) -> dict:
    """从 Docker postgres 获取案件的 catalog_data"""
    result = subprocess.run(
        [
            "docker", "exec", "scanstruct-postgres",
            "psql", "-U", "scanstruct", "-d", "scanstruct",
            "-t", "-c",
            f"SELECT catalog_data FROM evidence_cases WHERE id = '{case_id}';",
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr}")
    raw = result.stdout.strip()
    if not raw:
        raise ValueError(f"case {case_id} not found or catalog_data empty")
    return json.loads(raw)


def fetch_material_files(case_id: str) -> list[dict]:
    """获取案件关联的素材文件列表（从 evidence_materials 表）"""
    result = subprocess.run(
        [
            "docker", "exec", "scanstruct-postgres",
            "psql", "-U", "scanstruct", "-d", "scanstruct",
            "-t", "-c",
            f"SELECT id, original_filename, storage_path, doc_type "
            f"FROM evidence_materials WHERE case_id = '{case_id}' "
            f"ORDER BY created_at;",
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        return []
    items = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            items.append({
                "id": parts[0].strip(),
                "filename": parts[1].strip(),
                "storage_path": parts[2].strip(),
                "doc_type": parts[3].strip(),
            })
    return items


def download_from_minio(storage_path: str, dest: Path) -> bool:
    """从 MinIO 下载文件到本地临时目录"""
    try:
        result = subprocess.run(
            [
                "docker", "exec", "scanstruct-minio", "mc", "cp",
                storage_path, f"/tmp/{dest.name}",
            ],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30,
        )
        if result.returncode != 0:
            return False
        # 从容器拷贝到宿主
        result = subprocess.run(
            [
                "docker", "cp",
                f"scanstruct-minio:/tmp/{dest.name}",
                str(dest),
            ],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def fetch_ocr_text_from_db(case_id: str) -> dict[str, str]:
    """直接从 catalog_data 提取已存的 ocr_text（避免重新跑OCR）"""
    catalog = fetch_case_catalog_data(case_id)
    ocr_map: dict[str, str] = {}
    for group in catalog.get("groups", []):
        for item in group.get("items", []):
            ev = item.get("evidence_name", {})
            fname = ev.get("original_filename", "") if isinstance(ev, dict) else ""
            ocr = item.get("ocr_text", "") or ""
            if fname:
                ocr_map[fname] = ocr
    return ocr_map


def run_rapidocr_on_image(image_path: Path) -> tuple[list[dict], float, int]:
    """
    对图片跑 RapidOCR，返回 (结果列表, 平均置信度, 总字符数)
    """
    try:
        from services.ocr.rapid_engine import RapidOCREngine
        engine = RapidOCREngine()
        if not engine.is_ready:
            engine.load_model()
        if not engine.is_ready:
            return [], 0.0, 0
        results = engine.recognize(image_path)
        if not results:
            return [], 0.0, 0
        total_conf = sum(r.get("confidence", 0.0) for r in results)
        avg_conf = total_conf / len(results) if results else 0.0
        total_chars = sum(len(r.get("text", "")) for r in results)
        return results, avg_conf, total_chars
    except Exception as e:
        logger.error(f"RapidOCR failed on {image_path}: {e}")
        return [], 0.0, 0


def check_field_hits(ocr_text: str) -> dict:
    """检查关键字段是否在 OCR 文本中命中"""
    import re
    fields = {
        "医疗费总额": bool(re.search(r"医疗费总额", ocr_text)),
        "基金支付总额": bool(re.search(r"基金支付总额", ocr_text)),
        "个人负担金额": bool(re.search(r"个人负担金额", ocr_text)),
        "统筹支付": bool(re.search(r"统筹支付", ocr_text)),
        "住院天数": bool(re.search(r"住院天数", ocr_text)),
        "合计金额": bool(re.search(r"合计(?:金额)?", ocr_text)),
        "金额数字": len(re.findall(r"[\d,]+\.?\d*", ocr_text)),
    }
    return fields


def find_low_confidence_segments(results: list[dict], threshold: float = 0.6) -> list[dict]:
    """提取低置信度文本片段 Top5"""
    low = [
        {"text": r.get("text", "")[:80], "confidence": r.get("confidence", 0.0)}
        for r in results
        if r.get("confidence", 0.0) < threshold
    ]
    low.sort(key=lambda x: x["confidence"])
    return low[:5]


def diagnose_case(case_id: str) -> None:
    """诊断指定案件"""
    print(f"\n{'='*60}")
    print(f"OCR 质量诊断 — 案件 {case_id}")
    print(f"{'='*60}\n")

    # 方法1: 从已有 catalog_data 提取已存 OCR（快速、不重跑）
    print("[1/3] 从数据库提取已存 OCR 文本...")
    try:
        ocr_map = fetch_ocr_text_from_db(case_id)
        print(f"    找到 {len(ocr_map)} 个素材的 OCR 文本")
    except Exception as e:
        print(f"    错误: {e}")
        ocr_map = {}

    # 方法2: 尝试重新跑 RapidOCR（如果素材可从 MinIO 下载）
    print("\n[2/3] 尝试从 MinIO 下载素材重新跑 RapidOCR...")
    materials = fetch_material_files(case_id)
    print(f"    找到 {len(materials)} 个素材记录")

    rapidocr_results: dict[str, dict] = {}
    if materials:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            for mat in materials[:20]:  # 限制20张避免太久
                fname = mat["filename"]
                storage = mat["storage_path"]
                if not storage:
                    continue
                dest = tmpdir / fname
                if download_from_minio(storage, dest):
                    results, avg_conf, chars = run_rapidocr_on_image(dest)
                    rapidocr_results[fname] = {
                        "results": results,
                        "avg_confidence": avg_conf,
                        "total_chars": chars,
                        "low_conf_segments": find_low_confidence_segments(results),
                    }
                    print(f"    {fname}: conf={avg_conf:.3f} chars={chars}")
                else:
                    print(f"    {fname}: 下载失败，跳过")

    # 方法3: 生成 CSV 报告
    print("\n[3/3] 生成诊断报告...")
    output_dir = PROJECT_ROOT / ".workbuddy"
    output_dir.mkdir(exist_ok=True)
    case_short = case_id[:8]

    csv_path = output_dir / f"ocr_diagnosis_{case_short}.csv"
    low_quality_path = output_dir / f"ocr_diagnosis_{case_short}_low_quality.txt"

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "文件名", "OCR来源", "平均置信度", "总字符数",
            "低质片段数", "低质片段Top5",
            "医疗费总额", "基金支付总额", "个人负担金额",
            "统筹支付", "住院天数", "合计金额", "金额数字数",
        ])

        all_rows = []

        # 写已存OCR结果（基于数据库）
        for fname, ocr_text in ocr_map.items():
            hits = check_field_hits(ocr_text)
            low_seg_str = "（从DB提取，无置信度数据）"
            row = [
                fname, "DB已存", "N/A", len(ocr_text),
                "N/A", low_seg_str,
                "Y" if hits["医疗费总额"] else "N",
                "Y" if hits["基金支付总额"] else "N",
                "Y" if hits["个人负担金额"] else "N",
                "Y" if hits["统筹支付"] else "N",
                "Y" if hits["住院天数"] else "N",
                "Y" if hits["合计金额"] else "N",
                hits["金额数字"],
            ]
            writer.writerow(row)
            all_rows.append((fname, "DB", ocr_text, hits))

        # 写 RapidOCR 重跑结果
        for fname, info in rapidocr_results.items():
            ocr_text = "\n".join(r.get("text", "") for r in info["results"])
            hits = check_field_hits(ocr_text)
            low_segs = info["low_conf_segments"]
            low_seg_str = " | ".join(
                f"[{s['confidence']:.2f}]{s['text']}" for s in low_segs
            )
            row = [
                fname, "RapidOCR重跑",
                f"{info['avg_confidence']:.3f}",
                info["total_chars"],
                len(low_segs),
                low_seg_str,
                "Y" if hits["医疗费总额"] else "N",
                "Y" if hits["基金支付总额"] else "N",
                "Y" if hits["个人负担金额"] else "N",
                "Y" if hits["统筹支付"] else "N",
                "Y" if hits["住院天数"] else "N",
                "Y" if hits["合计金额"] else "N",
                hits["金额数字"],
            ]
            writer.writerow(row)
            all_rows.append((fname, "RapidOCR", ocr_text, hits))

    # 生成低质图清单
    with open(low_quality_path, "w", encoding="utf-8") as f:
        f.write(f"OCR 低质图清单 — 案件 {case_id}\n")
        f.write(f"{'='*60}\n\n")

        # RapidOCR 重跑中置信度<0.6的图
        low_rapidocr = [
            (fname, info) for fname, info in rapidocr_results.items()
            if info["avg_confidence"] < 0.6
        ]
        if low_rapidocr:
            f.write(f"## RapidOCR 平均置信度 < 0.6 的图 ({len(low_rapidocr)} 张)\n\n")
            for fname, info in sorted(low_rapidocr, key=lambda x: x[1]["avg_confidence"]):
                f.write(f"### {fname}\n")
                f.write(f"  平均置信度: {info['avg_confidence']:.3f}\n")
                f.write(f"  总字符数: {info['total_chars']}\n")
                f.write(f"  低质片段:\n")
                for seg in info["low_conf_segments"]:
                    f.write(f"    [{seg['confidence']:.3f}] {seg['text']}\n")
                f.write("\n")

        # 字段未命中的图
        field_miss = []
        for fname, source, ocr_text, hits in all_rows:
            missing = []
            for field in ["医疗费总额", "基金支付总额", "个人负担金额", "住院天数"]:
                if not hits.get(field):
                    missing.append(field)
            if missing and ("结算" in fname or "医保" in fname):
                field_miss.append((fname, source, missing))

        if field_miss:
            f.write(f"## 结算单字段未命中 ({len(field_miss)} 张)\n\n")
            for fname, source, missing in field_miss:
                f.write(f"### {fname} ({source})\n")
                f.write(f"  缺失字段: {', '.join(missing)}\n\n")

        if not low_rapidocr and not field_miss:
            f.write("（无低质图，所有素材 OCR 质量正常）\n")

    print(f"\n✓ CSV 报告: {csv_path}")
    print(f"✓ 低质图清单: {low_quality_path}")
    print(f"\n建议:")
    print(f"  1. 打开 CSV 查看置信度分布和字段命中情况")
    print(f"  2. 打开低质图清单定位具体问题")
    print(f"  3. 如果字段未命中，检查 services/evidence/excel_generator.py 正则")


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/ocr_diagnose.py <case_id>")
        print("示例: python scripts/ocr_diagnose.py 9950f946-1f90-4a65-a145-adf31948c44c")
        sys.exit(1)

    case_id = sys.argv[1]
    diagnose_case(case_id)


if __name__ == "__main__":
    main()
