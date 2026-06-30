"""
证据材料 OCR 结果存储

大文档（多页 PDF 等）逐页写入 MinIO，PostgreSQL 只保留摘要/metadata，
避免 3000 页 OCR 把 ocr_result JSONB / ocr_text 撑爆数据库。

MinIO 布局（bucket 默认 scan-result）:
  evidence/{case_id}/ocr/{material_id}/
    manifest.json       # 摘要（与 DB ocr_result 一致）
    full_text.txt       # 全文（分类/导出时按需加载）
    pages/page_0001.json
    pages/page_0002.json
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

from loguru import logger

from config.settings import settings

OCR_STORAGE_MINIO = "minio"
OCR_STORAGE_INLINE = "inline"


def make_ocr_prefix(case_id: str, material_id: str) -> str:
    return f"evidence/{case_id}/ocr/{material_id}"


def is_ocr_offloaded(material) -> bool:
    return (getattr(material, "ocr_result", None) or {}).get("storage") == OCR_STORAGE_MINIO


def get_material_ocr_text(material) -> str:
    """加载完整 OCR 文本：MinIO  offload 时从 full_text.txt 读取，否则用 DB 列。"""
    ocr_result = getattr(material, "ocr_result", None) or {}
    if ocr_result.get("storage") == OCR_STORAGE_MINIO:
        from services.storage.minio_client import minio_client

        bucket = ocr_result.get("minio_bucket") or settings.minio_bucket_result
        key = ocr_result.get("full_text_key")
        if not key:
            prefix = ocr_result.get("minio_prefix")
            if prefix:
                key = f"{prefix}/full_text.txt"
        if key:
            try:
                return minio_client.download_bytes(bucket, key).decode("utf-8")
            except Exception as e:
                logger.warning(
                    f"Failed to load OCR full_text from MinIO {bucket}/{key}: {e}"
                )
    return getattr(material, "ocr_text", None) or ""


def delete_material_ocr(material) -> int:
    """删除材料在 MinIO 上的 OCR 产物（重试/删除材料时调用）。"""
    from services.storage.minio_client import minio_client

    ocr_result = getattr(material, "ocr_result", None) or {}
    bucket = ocr_result.get("minio_bucket") or settings.minio_bucket_result
    prefix = ocr_result.get("minio_prefix")
    if not prefix:
        case_id = getattr(material, "evidence_case_id", None)
        mat_id = getattr(material, "id", None)
        if case_id and mat_id:
            prefix = make_ocr_prefix(str(case_id), str(mat_id))
    if not prefix:
        return 0
    if hasattr(minio_client, "delete_prefix"):
        return minio_client.delete_prefix(bucket, prefix)
    return 0


class EvidenceOCRStore:
    """增量 OCR 写入器：逐页上传 MinIO，全文流式写入临时文件后上传。"""

    def __init__(
        self,
        case_id: str,
        material_id: str,
        bucket: str | None = None,
    ):
        from services.storage.minio_client import minio_client

        self._minio = minio_client
        self.case_id = str(case_id)
        self.material_id = str(material_id)
        self.bucket = bucket or settings.minio_bucket_result
        self.prefix = make_ocr_prefix(self.case_id, self.material_id)
        self._block_count = 0
        self._pages_written = 0
        self._preview_parts: list[str] = []
        self._preview_len = 0
        self._preview_limit = settings.ocr_text_db_preview_chars
        self._source_type = "pdf_ocr"
        self._extra: dict[str, Any] = {}
        self._closed = False

        work_base = os.getenv("OCR_WORK_DIR") or None
        if work_base:
            os.makedirs(work_base, exist_ok=True)
        fd, self._text_path = tempfile.mkstemp(dir=work_base, suffix=".ocr.txt")
        os.close(fd)
        self._text_file = open(self._text_path, "w", encoding="utf-8")

    def set_meta(self, source_type: str, **extra: Any) -> None:
        self._source_type = source_type
        self._extra.update(extra)

    def write_page(self, page_num: int, results: list[dict]) -> None:
        lines = [r.get("text", "") for r in results if r.get("text")]
        page_text = "\n".join(lines)
        blocks = [
            {
                "text": r.get("text", ""),
                "confidence": r.get("confidence", 0),
                "page": page_num,
            }
            for r in results
        ]

        payload = json.dumps(
            {"page": page_num, "text": page_text, "blocks": blocks},
            ensure_ascii=False,
        ).encode("utf-8")
        page_key = f"{self.prefix}/pages/page_{page_num:04d}.json"
        self._minio.upload_bytes(
            self.bucket,
            page_key,
            payload,
            content_type="application/json; charset=utf-8",
        )

        if page_text:
            self._text_file.write(page_text)
            self._text_file.write("\n")

        self._block_count += len(blocks)
        self._pages_written += 1

        if self._preview_len < self._preview_limit and page_text:
            remaining = self._preview_limit - self._preview_len
            chunk = page_text[:remaining]
            if chunk:
                self._preview_parts.append(chunk)
                self._preview_len += len(chunk)

    def finalize(self) -> tuple[str, dict]:
        if self._closed:
            raise RuntimeError("EvidenceOCRStore already finalized")

        self._text_file.close()
        self._closed = True
        full_text_len = os.path.getsize(self._text_path)

        preview = "".join(self._preview_parts)
        if full_text_len > self._preview_limit:
            preview += f"\n…（共 {full_text_len:,} 字符，完整文本已存 MinIO）"

        summary: dict[str, Any] = {
            "storage": OCR_STORAGE_MINIO,
            "minio_bucket": self.bucket,
            "minio_prefix": self.prefix,
            "full_text_key": f"{self.prefix}/full_text.txt",
            "source_type": self._source_type,
            "page_count": self._pages_written,
            "block_count": self._block_count,
            "full_text_length": full_text_len,
            "text_preview": preview[: self._preview_limit],
        }
        summary.update(self._extra)

        # 复用静态方法上传 full_text + manifest（收口器也调它，行为一致）
        full_text_key = f"{self.prefix}/full_text.txt"
        self._write_full_text_and_manifest(
            bucket=self.bucket,
            prefix=self.prefix,
            full_text_path=self._text_path,
            full_text_len=full_text_len,
            preview=preview,
            summary=summary,
            full_text_key=full_text_key,
        )

        self._cleanup_text_file()
        logger.info(
            f"OCR offloaded to MinIO: {self.bucket}/{self.prefix} "
            f"({self._pages_written} pages, {full_text_len:,} chars)"
        )
        return preview, summary

    def abort(self) -> None:
        if not self._closed:
            try:
                self._text_file.close()
            except Exception:
                pass
            self._closed = True
        self._cleanup_text_file()
        try:
            if hasattr(self._minio, "delete_prefix"):
                self._minio.delete_prefix(self.bucket, self.prefix)
        except Exception as e:
            logger.warning(f"Failed to cleanup partial OCR prefix {self.prefix}: {e}")

    def abort_text_only(self) -> None:
        """仅关闭并清理本地 text 临时文件，保留 MinIO pages（分片批次 task 用）。

        与 abort 的区别：不删 MinIO prefix，因为批次 task 写的 pages 需要保留
        供收口器拼接 full_text。
        """
        if not self._closed:
            try:
                self._text_file.close()
            except Exception:
                pass
            self._closed = True
        self._cleanup_text_file()

    def _cleanup_text_file(self) -> None:
        try:
            os.unlink(self._text_path)
        except OSError:
            pass

    @staticmethod
    def _write_full_text_and_manifest(
        bucket: str,
        prefix: str,
        full_text_path: str,
        full_text_len: int,
        preview: str,
        summary: dict[str, Any],
        full_text_key: str | None = None,
    ) -> None:
        """上传 full_text.txt + manifest.json 到指定 MinIO 路径。

        EvidenceOCRStore.finalize 与分片收口器 _assemble_full_text 共用此方法，
        保证两条路径写出的 manifest 结构一致。
        """
        from services.storage.minio_client import minio_client

        key = full_text_key or f"{prefix}/full_text.txt"
        minio_client.upload_file(
            bucket,
            key,
            full_text_path,
            content_type="text/plain; charset=utf-8",
        )

        manifest_key = f"{prefix}/manifest.json"
        minio_client.upload_bytes(
            bucket,
            manifest_key,
            json.dumps(summary, ensure_ascii=False).encode("utf-8"),
            content_type="application/json; charset=utf-8",
        )

    @classmethod
    def load_page_text(cls, case_id: str, material_id: str, page_num: int) -> str:
        """从 MinIO 读 pages/page_NNNN.json，提取 text 字段。

        供分片收口器按页号顺序拼接 full_text 用。读失败返回空串。
        """
        from services.storage.minio_client import minio_client

        bucket = settings.minio_bucket_result
        prefix = make_ocr_prefix(str(case_id), str(material_id))
        key = f"{prefix}/pages/page_{page_num:04d}.json"
        try:
            raw = minio_client.download_bytes(bucket, key)
            data = json.loads(raw.decode("utf-8"))
            return data.get("text", "") or ""
        except Exception as e:
            logger.warning(
                f"load_page_text failed: {bucket}/{key}: {e}"
            )
            return ""

    @property
    def page_count(self) -> int:
        return self._pages_written

    @property
    def block_count(self) -> int:
        return self._block_count


def persist_inline_ocr(ocr_result: dict) -> tuple[str, dict]:
    """小文档（docx/xlsx/短文本）：DB 存全文 + 无 blocks 的摘要。"""
    full_text = ocr_result.get("full_text", "") or ocr_result.get("text", "") or ""
    blocks = ocr_result.get("blocks") or []
    limit = settings.ocr_text_db_preview_chars

    summary = {
        k: v
        for k, v in ocr_result.items()
        if k not in ("blocks", "full_text", "text")
    }
    summary["storage"] = OCR_STORAGE_INLINE
    summary["block_count"] = (
        len(blocks) if blocks else int(ocr_result.get("block_count") or 0)
    )
    summary["full_text_length"] = len(full_text)
    summary.setdefault("source_type", ocr_result.get("source_type", "unknown"))
    summary.setdefault("page_count", ocr_result.get("page_count"))

    if len(full_text) <= limit:
        db_text = full_text
    else:
        db_text = full_text[:limit] + f"\n…（共 {len(full_text):,} 字符，仅存预览）"
        summary["text_preview"] = db_text[:limit]

    return db_text, summary


def should_offload_ocr(ocr_result: dict, file_type: str | None = None) -> bool:
    """判断是否应逐页 offload 到 MinIO。"""
    if not settings.ocr_offload_enabled:
        return False
    source = ocr_result.get("source_type", "")
    if source in ("docx", "xlsx", "pptx", "audio"):
        return False
    if source in ("pdf_ocr", "pdf_ocr_selected", "image_ocr"):
        return True
    if file_type == "pdf":
        return True
    page_count = int(ocr_result.get("page_count") or 0)
    full_text = ocr_result.get("full_text", "") or ocr_result.get("text", "") or ""
    blocks = ocr_result.get("blocks") or []
    return (
        page_count >= settings.ocr_offload_min_pages
        or len(full_text) >= settings.ocr_offload_min_chars
        or len(blocks) >= settings.ocr_offload_min_blocks
    )


def persist_ocr_from_result(
    case_id: str,
    material_id: str,
    ocr_result: dict,
    bucket: str | None = None,
    file_type: str | None = None,
) -> tuple[str, dict]:
    """将内存中的 OCR 结果持久化（大文档写 MinIO，小文档 inline）。"""
    if not should_offload_ocr(ocr_result, file_type):
        return persist_inline_ocr(ocr_result)

    store = EvidenceOCRStore(case_id, material_id, bucket)
    store.set_meta(
        ocr_result.get("source_type", "unknown"),
        **{
            k: v
            for k, v in ocr_result.items()
            if k not in ("blocks", "full_text", "text", "source_type")
        },
    )
    blocks = ocr_result.get("blocks") or []
    if blocks:
        pages: dict[int, list[dict]] = {}
        for b in blocks:
            p = int(b.get("page") or 1)
            pages.setdefault(p, []).append(b)
        for p in sorted(pages):
            store.write_page(p, pages[p])
    else:
        full_text = ocr_result.get("full_text", "") or ocr_result.get("text", "") or ""
        if full_text.strip():
            pseudo = [{"text": line, "confidence": 0} for line in full_text.split("\n") if line]
            store.write_page(1, pseudo)
    return store.finalize()
