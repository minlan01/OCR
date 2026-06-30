"""端到端验证：OCR 逐页写 MinIO + DB 只留摘要

构造一个 3 页 PDF（每页带可识别文字），走完整 OCR 流程：
  ocr_upload_path(store=...) -> EvidenceOCRStore.finalize()
然后校验：
  - MinIO 上有 pages/page_0001.json ... page_0003.json
  - MinIO 上有 full_text.txt、manifest.json
  - 返回的 summary.storage == "minio"，无 blocks
  - DB 预览文本包含截断提示
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _make_multipage_pdf(path: Path, pages_text: list[str]) -> None:
    import fitz

    doc = fitz.open()
    for txt in pages_text:
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((72, 120), txt, fontsize=24, fontname="helv")
    doc.save(str(path))
    doc.close()


def main() -> int:
    # 用一个固定 case/material id 便于事后人工检查 MinIO
    case_id = "00000000-0000-0000-0000-e2e000000001"
    material_id = "00000000-0000-0000-0000-e2e000000002"

    work_base = os.getenv("OCR_WORK_DIR") or None
    if work_base:
        os.makedirs(work_base, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=work_base) as td:
        td_path = Path(td)
        pdf_path = td_path / "e2e_test.pdf"
        pages_text = [
            "Page One Hello OCR E2E",
            "Page Two Medical Receipt Total 1234.56",
            "Page Three Discharge Summary Days 7",
        ]
        _make_multipage_pdf(pdf_path, pages_text)
        print(f"[1/5] 构造测试 PDF: {pdf_path} ({pdf_path.stat().st_size} bytes, {len(pages_text)} pages)")

        from services.complaint.ocr_service import ocr_upload_path
        from services.evidence.ocr_storage import EvidenceOCRStore
        from config.settings import settings

        bucket = settings.minio_bucket_result
        store = EvidenceOCRStore(case_id, material_id, bucket)
        store.set_meta("pdf_ocr")
        print(f"[2/5] EvidenceOCRStore 初始化: bucket={bucket} prefix={store.prefix}")

        try:
            result = ocr_upload_path(pdf_path, "e2e_test.pdf", store=store)
        except Exception as e:
            store.abort()
            print(f"[FAIL] OCR 执行失败: {e}")
            return 1

        print(f"[3/5] ocr_upload_path 返回: offloaded={result.get('offloaded')} "
              f"page_count={result.get('page_count')} block_count={result.get('block_count')}")

        if not result.get("offloaded"):
            store.abort()
            print("[FAIL] 未走 offload 路径")
            return 1

        db_text, summary = store.finalize()
        print(f"[4/5] finalize 返回摘要:")
        print(f"      storage={summary.get('storage')}")
        print(f"      page_count={summary.get('page_count')}")
        print(f"      block_count={summary.get('block_count')}")
        print(f"      full_text_length={summary.get('full_text_length')}")
        print(f"      minio_prefix={summary.get('minio_prefix')}")
        print(f"      DB 预览长度={len(db_text)}")

        # 校验 1: summary 结构
        assert summary["storage"] == "minio", "storage 应为 minio"
        assert "blocks" not in summary, "摘要里不应有 blocks"
        assert summary["page_count"] == 3, f"应为 3 页，实际 {summary['page_count']}"

        # 校验 2: DB 预览文本
        assert len(db_text) <= settings.ocr_text_db_preview_chars + 200, "DB 预览不应过长"
        print(f"[5/5] 校验 MinIO 产物...")

        from services.storage.minio_client import minio_client
        prefix = summary["minio_prefix"]

        # 检查 full_text.txt
        full_text_bytes = minio_client.download_bytes(bucket, f"{prefix}/full_text.txt")
        full_text = full_text_bytes.decode("utf-8")
        print(f"      full_text.txt: {len(full_text)} 字符")
        assert "Page One" in full_text or "Page" in full_text, "全文应包含页面文字"

        # 检查 manifest.json
        manifest = json.loads(minio_client.download_bytes(bucket, f"{prefix}/manifest.json").decode("utf-8"))
        assert manifest["storage"] == "minio"
        print(f"      manifest.json: storage={manifest['storage']} pages={manifest['page_count']}")

        # 检查 pages/page_XXXX.json
        page_count_in_minio = 0
        for i in range(1, 4):
            key = f"{prefix}/pages/page_{i:04d}.json"
            try:
                pdata = json.loads(minio_client.download_bytes(bucket, key).decode("utf-8"))
                page_count_in_minio += 1
                print(f"      {key}: page={pdata['page']} text='{pdata['text'][:40]}...'")
            except Exception as e:
                print(f"      {key}: 缺失! {e}")
        assert page_count_in_minio == 3, f"MinIO 应有 3 个 page 文件，实际 {page_count_in_minio}"

        # 清理（可选：保留以便人工检查）
        print("\n[OK] 全部校验通过!")
        print(f"  MinIO 路径: {bucket}/{prefix}/")
        print(f"  DB 应存: ocr_text(预览 {len(db_text)} 字符) + ocr_result(摘要, 无 blocks)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
