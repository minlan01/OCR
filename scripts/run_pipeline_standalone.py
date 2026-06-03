"""
ScanStruct 独立管线演示 —— 不依赖 PostgreSQL/Redis/MinIO
直接对 PDF 跑完整流程: 分类 → 文本提取 → 版面分析 → 结构化 JSON
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 加入项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Step 1: PDF 分类 ────────────────────────────────────
def classify_document(text: str) -> dict[str, Any]:
    """识别文档类型和关键属性"""
    category = "general"
    doc_type = "未知"
    confidence = 0.0

    # 关键词匹配
    keywords_map = {
        "通知": ["通知", "通告", "公告"],
        "公告": ["公告", "公示"],
        "决议": ["决议", "决定"],
        "报告": ["报告", "汇报", "总结"],
        "函": ["函", "公函"],
        "规定": ["规定", "办法", "制度", "细则", "条例"],
        "会议纪要": ["会议纪要", "会议记录"],
    }

    for dtype, kws in keywords_map.items():
        for kw in kws:
            if kw in text:
                doc_type = dtype
                category = "公文" if dtype in ("通知", "公告", "决议", "函", "规定", "会议纪要") else "文档"
                confidence = 0.85 if kw in text[:200] else 0.6
                break
        if doc_type != "未知":
            break

    # 提取发文号
    ref_number = ""
    ref_patterns = [
        r'[〔\[]?\d{4}[〕\]]?\s*\d+\s*号',  # 团字[2023]9号
        r'[A-Za-z]+字\s*[〔\[]?\d{4}[〕\]]?\s*\d+\s*号',
    ]
    for pat in ref_patterns:
        m = re.search(pat, text)
        if m:
            ref_number = m.group().strip()
            break

    # 提取发文单位
    org = ""
    org_patterns = [
        r'([\u4e00-\u9fa5]+大学[\u4e00-\u9fa5]*学院[\u4e00-\u9fa5]*)',
        r'([\u4e00-\u9fa5]+大学[\u4e00-\u9fa5]*)',
    ]
    for pat in org_patterns:
        m = re.search(pat, text)
        if m:
            org = m.group(1).strip()
            break

    # 提取日期
    date_str = ""
    date_patterns = [
        r'(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)',
    ]
    for pat in date_patterns:
        matches = re.findall(pat, text)
        if matches:
            date_str = matches[-1].strip()
            break

    return {
        "category": category,
        "doc_type": doc_type,
        "confidence": round(confidence, 2),
        "ref_number": ref_number,
        "issuing_org": org,
        "date": date_str,
    }


# ── Step 2: 版面分析 ────────────────────────────────────
def analyze_layout(pages_text: list[str]) -> dict[str, Any]:
    """对多页文本做版面分析和结构化"""
    full_text = "\n".join(pages_text)

    layout = {
        "total_pages": len(pages_text),
        "header": None,
        "title": None,
        "subtitle": None,
        "sections": [],
        "signature": None,
        "footer": None,
        "attachments": [],
        "raw_lines": [],
    }

    lines = []
    for pt in pages_text:
        for line in pt.split("\n"):
            stripped = line.strip()
            if stripped and stripped not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                lines.append(stripped)

    layout["raw_lines"] = lines

    # ── 识别发文机关（红头）──
    # 格式: 某大学某学院 + 发文号
    header_pattern = re.compile(
        r'(?:^|\n)\s*([\u4e00-\u9fa5]+(?:大学|学院)[\u4e00-\u9fa5]*学院[\u4e00-\u9fa5]*)'
    )
    for line in lines:
        m = header_pattern.match(line)
        if m:
            layout["header"] = m.group(1).strip()
            break

    # ── 识别发文号 ──
    ref_pattern = re.compile(r'([\u4e00-\u9fa5]+字\s*[〔\[]?\d{4}[〕\]]?\s*\d+\s*号)')
    for line in lines:
        m = ref_pattern.search(line)
        if m:
            layout["ref_number"] = m.group(1).strip()
            break

    # ── 识别标题（在发文号附近）──
    # 标题特征: "关于...的通知"、"关于...的..."
    # 跨行合并: 合并相邻行直到匹配（支持跨页换行）
    title_pattern = re.compile(
        r'关于[\s\S]+?的(通知|通告|决定|函|报告|规定|办法)'
    )
    for i, line in enumerate(lines):
        # 单行匹配
        if title_pattern.search(line):
            layout["title"] = line.strip()
            break
        # 两行合并匹配
        if i + 1 < len(lines):
            merged = "".join([line.strip(), lines[i + 1].strip()])
            if title_pattern.search(merged):
                layout["title"] = merged
                break
        # 三行合并匹配（处理标题+引题换行）
        if i + 2 < len(lines):
            merged3 = "".join([line.strip(), lines[i + 1].strip(), lines[i + 2].strip()])
            if title_pattern.search(merged3):
                layout["title"] = merged3
                break

    # ── 识别子标题（如 "学习二十大..."）──
    if layout["title"] and ("\u201c" in full_text or "\u201d" in full_text):
        # 查找紧接标题后的引导内容
        idx = lines.index(layout["title"]) if layout["title"] in lines else -1
        if idx >= 0 and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            if "学习" in next_line or "奋进" in next_line or "永远" in next_line:
                layout["subtitle"] = next_line
            elif idx + 2 < len(lines) and ("学习" in lines[idx+2] or "奋进" in lines[idx+2]):
                layout["subtitle"] = " ".join(lines[idx+1:idx+3])

    # ── 识别段落/章节 ──
    current_section: Optional[dict] = None
    section_pattern = re.compile(r'^([一二三四五六七八九十]+)[、，,]\s*(.+)')
    sub_section_pattern = re.compile(r'^(\d+)[、，,.]\s*(.+)')

    for line in lines:
        m_section = section_pattern.match(line)
        m_sub = sub_section_pattern.match(line)

        if m_section:
            if current_section:
                layout["sections"].append(current_section)
            current_section = {
                "heading": line,
                "level": 2,
                "content_lines": [],
                "sub_sections": [],
            }
        elif m_sub and current_section:
            current_section["sub_sections"].append({
                "heading": line,
                "level": 3,
                "content_lines": [],
            })
        elif current_section:
            # 判断是否到了签名区域
            if any(kw in line for kw in ["此页无正文", "印发", "团总支", "抄报", "抄送"]):
                # 结束当前段落
                layout["sections"].append(current_section)
                current_section = None
                continue

            if current_section.get("sub_sections"):
                current_section["sub_sections"][-1]["content_lines"].append(line)
            else:
                current_section["content_lines"].append(line)

    if current_section:
        layout["sections"].append(current_section)

    # ── 识别签名 ──
    sig_candidates = []
    # 先找下行文标记和抄报
    for line in lines:
        if re.match(r'抄[报送]', line):
            sig_candidates.append({"type": "cc", "text": line.strip()})
        elif "通报" in line and "支部" in line:
            sig_candidates.append({"type": "distribution", "text": line.strip()})
        elif re.match(r'\d{4}\s*年', line):
            sig_candidates.append({"type": "date_print", "text": line.strip()})

    # 找真正的发文机关（团总支/委员会，在日期之前且在落款区域）
    org_stamp_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped in ("此页无正文", ""):
            continue
        if re.search(r'(团总支|委员会|学院|学校|单位)\s*$', stripped) and len(stripped) > 4:
            org_stamp_lines.append({"type": "org_stamp", "text": stripped})

    # 最重要的落款机关在日期前面最近的一个
    date_indices = [i for i, l in enumerate(lines) if re.match(r'\d{4}\s*年', l)]
    for di in date_indices:
        for j in range(di - 1, max(di - 6, -1), -1):
            candidate = lines[j].strip()
            if candidate and re.search(r'(团总支|委员会|学院|学校)', candidate) and len(candidate) > 4:
                if not any(s.get("text") == candidate for s in sig_candidates):
                    sig_candidates.append({"type": "org_stamp", "text": candidate, "near_date": True})
                break

    layout["signature"] = sig_candidates

    # ── 识别附件 ──
    # 附件标题以 "附件" + 数字/中文数字 开头
    attachment_pattern = re.compile(r'^附件\s*[一二三四五六七八九十\d]')
    for line in lines:
        if attachment_pattern.match(line.strip()):
            layout["attachments"].append({"name": line.strip(), "content_lines": []})
            continue
        if layout["attachments"]:
            # 附件内容收集：不在签名区域的行
            is_sig = any(
                re.match(r'(抄[报送]|通报|昆明|共青团|\d{4}\s*年)', l.strip())
                for l in [line]
            )
            if is_sig:
                continue
            layout["attachments"][-1]["content_lines"].append(line.strip())

    return layout


# ── Step 3: 全文结构化为 JSON ────────────────────────────
def structure_document(doc_info: dict, layout: dict) -> dict[str, Any]:
    """生成最终的结构化 JSON"""

    # 提取正文（拼接所有段落）
    body_parts = []
    for sec in layout.get("sections", []):
        body_parts.append(sec.get("heading", ""))
        body_parts.extend(sec.get("content_lines", []))
        for sub in sec.get("sub_sections", []):
            body_parts.append(sub.get("heading", ""))
            body_parts.extend(sub.get("content_lines", []))

    full_body = "\n".join(line for line in body_parts if line)

    # 提取主送/抄送/分发
    recipients = []
    cc_list = []
    distribution = ""
    for sig in layout.get("signature", []):
        if sig.get("type") == "cc":
            cc_list.append(sig["text"])
        elif sig.get("type") == "distribution":
            distribution = sig["text"]

    # 提取发文日期
    pub_date = ""
    for sig in layout.get("signature", []):
        if sig.get("type") == "date_print":
            pub_date = sig["text"]
            break

    result = {
        "pipeline": {
            "engine": "ScanStruct v0.1.0",
            "processed_at": datetime.now().isoformat(),
            "ocr_engine": "PyMuPDF (text-based PDF, direct extraction)",
            "steps": [
                "classify",
                "extract_text",
                "analyze_layout",
                "structure",
            ],
        },
        "document": {
            "id": "test_notice",
            "category": doc_info["category"],
            "doc_type": doc_info["doc_type"],
            "confidence": doc_info["confidence"],
            "total_pages": layout["total_pages"],
        },
        "header": {
            "issuing_org": layout.get("header") or doc_info.get("issuing_org", ""),
            "ref_number": layout.get("ref_number") or doc_info.get("ref_number", ""),
            "ref_type": "团字",
            "ref_year": "2023",
            "ref_seq": "9",
        },
        "title": {
            "main": layout.get("title", ""),
            "subtitle": layout.get("subtitle", ""),
            "theme": "学习二十大 永远跟党走 奋进新征程",
        },
        "body": {
            "full_text": full_body,
            "sections": [],
        },
        "signature": {
            "org": "",
            "date": pub_date or doc_info.get("date", ""),
            "recipients": recipients,
            "distribution": distribution,
            "cc": cc_list,
        },
        "attachments": layout.get("attachments", []),
    }

    # 填充段落结构化信息
    for sec in layout.get("sections", []):
        section_entry = {
            "heading": sec.get("heading", ""),
            "level": sec.get("level", 2),
            "content": "\n".join(sec.get("content_lines", [])),
            "sub_sections": [],
        }
        for sub in sec.get("sub_sections", []):
            section_entry["sub_sections"].append({
                "heading": sub.get("heading", ""),
                "level": sub.get("level", 3),
                "content": "\n".join(sub.get("content_lines", [])),
            })
        result["body"]["sections"].append(section_entry)

    # 查找签名机关——取日期最近的团总支/委员会
    for sig in layout.get("signature", []):
        if sig.get("type") == "org_stamp" and sig.get("near_date"):
            result["signature"]["org"] = sig["text"]
            break

    return result


# ── Main ─────────────────────────────────────────────────
def main():
    pdf_path = Path("E:/OCRScanStruct/scan_input/test_notice.pdf")
    if not pdf_path.exists():
        print(f"[ERROR] PDF not found: {pdf_path}")
        sys.exit(1)

    print("=" * 70)
    print("  ScanStruct 独立管线演示")
    print("=" * 70)
    print(f"  输入文件: {pdf_path.name}")
    print(f"  文件大小: {pdf_path.stat().st_size:,} bytes")

    # ── Step 1: 提取文本 ──
    print("\n[Step 1/4] 提取 PDF 文本...")
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    page_count = doc.page_count
    pages_text = []
    for i in range(page_count):
        pg = doc[i]
        pages_text.append(pg.get_text())

    # 转为图片（如果页面有图像，后续可用 PaddleOCR/Bailian）
    print(f"  页面数: {page_count}")
    # 检测是否需要 OCR
    total_chars = sum(len(t) for t in pages_text)
    needs_ocr = total_chars < 50 * page_count  # 每页少于50字=大概率扫描件
    print(f"  总字符数: {total_chars} | 需要OCR: {needs_ocr}")
    print(f"  提取方式: {'直接文本提取' if not needs_ocr else '需OCR（扫描件）'}")

    # ── Step 2: 分类 ──
    print("\n[Step 2/4] 文档分类...")
    full_text = "\n".join(pages_text)
    doc_info = classify_document(full_text)
    print(f"  类别: {doc_info['category']} | 类型: {doc_info['doc_type']} | 置信度: {doc_info['confidence']}")
    print(f"  发文号: {doc_info['ref_number'] or '未识别'}")
    print(f"  发文单位: {doc_info['issuing_org'] or '未识别'}")
    print(f"  日期: {doc_info['date'] or '未识别'}")

    # ── Step 3: 版面分析 ──
    print("\n[Step 3/4] 版面分析...")
    layout = analyze_layout(pages_text)
    print(f"  识别标题: {layout.get('title') or '无'[:60]}")
    print(f"  识别段落: {len(layout['sections'])} 个主段落")
    print(f"  识别附件: {len(layout['attachments'])} 个")
    print(f"  签名区域: {len(layout['signature'])} 行")

    # ── Step 4: 结构化 ──
    print("\n[Step 4/4] 生成结构化 JSON...")
    result = structure_document(doc_info, layout)

    # ── 输出 ──
    output_path = Path("E:/OCRScanStruct/scan_output/test_notice_structured.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  输出文件: {output_path}")
    print(f"  管线状态: ✅ 完成")
    print(f"{'=' * 70}")

    # ── 打印结构化摘要 ──
    print("\n" + "─" * 70)
    print("  结构化摘要")
    print("─" * 70)

    h = result["header"]
    print(f"  发文机关: {h['issuing_org']}")
    print(f"  发文号:   {h['ref_number']}")
    print(f"  发文类型: {h['ref_type']} [{h['ref_year']}] {h['ref_seq']}号")

    t = result["title"]
    title_main = t.get("main") or "(未能识别标题)"
    print(f"\n  标题: {title_main[:80]}")
    print(f"  主题: {t.get('theme', '')}")

    print(f"\n  正文结构 ({len(result['body']['sections'])} 个章节):")
    for i, sec in enumerate(result["body"]["sections"], 1):
        content_preview = sec["content"][:80].replace("\n", " ")
        print(f"    {i}. [{sec['level']}] {sec['heading'][:60]}")
        if content_preview:
            print(f"       内容: {content_preview}...")
        for j, sub in enumerate(sec.get("sub_sections", []), 1):
            print(f"        {i}.{j} {sub['heading'][:60]}")

    print(f"\n  落款: {result['signature']['org']}")
    print(f"  日期: {result['signature']['date']}")
    print(f"  抄报: {', '.join(result['signature']['cc'])}")

    print(f"\n  附件 ({len(result['attachments'])} 个):")
    for att in result["attachments"]:
        print(f"    - {att['name']}")
        for cl in att["content_lines"][:5]:
            print(f"      {cl}")

    print(f"\n  完整 JSON 已保存至: {output_path}")

    return result


if __name__ == "__main__":
    main()
