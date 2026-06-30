"""
OCR 流式处理器 — 含 Redis 缓存 + 低置信度区域重识

功能:
  - 所有页面一次性提交到线程池，消除批次边界等待
  - Redis 缓存 OCR 结果: 相同文件内容 hash 直接返回，避免重复识别
  - 低置信度区域裁剪重识: 对模糊区域放大2x后单独重识
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings
from services.ocr.engine import ocr_engine


def _file_hash(path: Path) -> str:
    """计算文件 SHA256 哈希（分块读取，避免大文件 OOM）"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _get_redis():
    """获取 Redis 连接（懒加载，连接失败返回 None）"""
    try:
        from config.settings import settings as s
        import redis as rlib
        cli = rlib.Redis.from_url(s.redis_url, decode_responses=True, socket_timeout=3)
        cli.ping()
        return cli
    except Exception as e:
        logger.debug(f"OCR cache: Redis unavailable: {e}")
        return None


def _cache_key(file_hash: str) -> str:
    """生成 Redis 缓存 key"""
    engine_type = settings.ocr_engine_type
    return f"ocr:result:{engine_type}:{file_hash}"


class OCRBatchProcessor:
    """OCR 流式处理器（含缓存）"""

    def __init__(self, batch_size: int | None = None):
        self.batch_size = batch_size if batch_size is not None else settings.ocr_batch_size

    def process_pages(
        self,
        page_images: list[Path],
        output_dir: Path,
        page_offset: int = 0,
    ) -> dict:
        """
        流式处理所有页面图片（含 Redis 缓存）

        对每页图片:
        1. 计算文件内容 SHA256 哈希
        2. 查 Redis 缓存，命中则直接返回
        3. 未命中则执行 OCR，结果写入缓存 (OCR_CACHE_TTL)
        4. 保存结果 JSON 文件

        返回: {
            "total_pages": int,
            "pages": [{"page": N, "results": [...], "confidence_avg": float}, ...],
            "confidence_avg": float,
        }
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        all_pages = []
        total_confidence = 0.0
        total_results = 0

        cache_enabled = settings.ocr_cache_enabled
        redis_cli = _get_redis() if cache_enabled else None
        cache_hits = 0
        cache_misses = 0

        # 预计算哈希 + 查缓存
        hashes = []
        cached_results: list[Optional[list[dict]]] = []
        uncached_indices: list[int] = []

        for i, img_path in enumerate(page_images):
            fhash = _file_hash(img_path)
            hashes.append(fhash)

            if redis_cli is not None:
                try:
                    cached = redis_cli.get(_cache_key(fhash))
                    if cached is not None:
                        cached_results.append(json.loads(cached))
                        cache_hits += 1
                        continue
                except Exception:
                    pass

            cached_results.append(None)
            uncached_indices.append(i)

        # 对未缓存的页面执行 OCR
        logger.info(
            f"OCR streaming: {len(page_images)} pages | "
            f"cache: {cache_hits} hits / {len(uncached_indices)} misses | "
            f"workers={getattr(ocr_engine, '_max_concurrent', 6)}"
        )

        uncached_images = [page_images[i] for i in uncached_indices]
        if uncached_images:
            ocr_raw = ocr_engine.recognize_batch(uncached_images)
        else:
            ocr_raw = []

        # 将 OCR 原始结果填回 cached_results
        for idx, ocr_idx in enumerate(uncached_indices):
            cached_results[ocr_idx] = ocr_raw[idx]
            cache_misses += 1

            # 写入缓存
            if redis_cli is not None:
                try:
                    redis_cli.setex(
                        _cache_key(hashes[ocr_idx]),
                        settings.ocr_cache_ttl,
                        json.dumps(ocr_raw[idx], ensure_ascii=False, default=str),
                    )
                except Exception as e:
                    logger.debug(f"OCR cache write failed: {e}")

        # 组装结果
        for j, results in enumerate(cached_results):
            page_num = page_offset + j + 1
            confidence_avg = 0.0
            if results:
                confidence_avg = sum(r.get("confidence", 0) for r in results) / len(results)
                total_confidence += sum(r.get("confidence", 0) for r in results)
                total_results += len(results)

            page_data = {
                "page": page_num,
                "image": page_images[j].name,
                "results": results or [],
                "result_count": len(results) if results else 0,
                "confidence_avg": round(confidence_avg, 4),
            }
            all_pages.append(page_data)

            ocr_engine.save_result(
                results or [],
                output_dir / f"page_{page_num:04d}.json",
            )

        overall_confidence = total_confidence / total_results if total_results > 0 else 0.0

        summary = {
            "total_pages": len(page_images),
            "pages": all_pages,
            "confidence_avg": round(overall_confidence, 4),
            "total_text_items": total_results,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
        }

        logger.info(
            f"OCR complete: {len(page_images)} pages | "
            f"avg confidence: {overall_confidence:.4f} | "
            f"total items: {total_results} | "
            f"cache: {cache_hits}H/{cache_misses}M"
        )

        return summary
