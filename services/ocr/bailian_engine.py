"""
阿里云百炼 Qwen-OCR 引擎适配器
通过 OpenAI 兼容接口调用 Qwen-VL-OCR 模型，输出格式与 OCREngine 一致。

限流保护:
  - RPS 限速器: 控制每秒请求数，防止触发突发保护
  - 429 指数退避: 遇到限流自动等待重试
  - 备选模型回退: 限流时自动切换到备用模型
  - 分布式信号量: 通过 Redis 控制跨 Worker 全局并发
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from loguru import logger
from openai import OpenAI, APIStatusError

from config.settings import settings
from services.ocr.base import BaseOCREngine
from services.ocr.common import OCR_SYSTEM_PROMPT, _image_to_base64_url

BACKUP_MODELS = [
    "qwen-vl-ocr-latest",
    "qwen-vl-ocr-2025-11-20",
    "qwen-vl-ocr",
    "qwen-vl-plus-latest",
    "qwen-vl-max-latest",
]


class _RPSLimiter:
    """每秒请求数限速器（令牌桶）"""

    def __init__(self, max_rps: float):
        self._max_rps = max_rps
        self._min_interval = 1.0 / max_rps if max_rps > 0 else 0
        self._lock = threading.Lock()
        self._last_time = 0.0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_time = time.monotonic()


class BailianOCREngine(BaseOCREngine):
    """
    百炼 Qwen-OCR 引擎

    内置限流保护:
      - RPS 限速器: 控制每秒请求数不超过 bailian_ocr_max_rps
      - 429 指数退避: 最多重试 bailian_ocr_retry_max 次
      - 备选模型回退: 限流时自动切换到备用模型
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_concurrent: int | None = None,
    ):
        self._api_key = api_key if api_key is not None else settings.bailian_api_key_plain
        self._base_url = base_url if base_url is not None else settings.bailian_ocr_base_url
        self._model = model if model is not None else settings.bailian_ocr_model
        self._timeout = timeout if timeout is not None else settings.bailian_ocr_timeout
        self._max_concurrent = max_concurrent if max_concurrent is not None else settings.bailian_ocr_max_concurrent
        self._max_rps = settings.bailian_ocr_max_rps
        self._retry_max = settings.bailian_ocr_retry_max
        self._client: Optional[OpenAI] = None
        self._model_loaded = False
        self._min_pixels = settings.bailian_ocr_min_pixels
        self._max_pixels = settings.bailian_ocr_max_pixels
        self._limiter = _RPSLimiter(self._max_rps)

    @property
    def is_ready(self) -> bool:
        return self._model_loaded

    def load_model(self) -> None:
        if self._model_loaded:
            return

        if not self._api_key:
            logger.warning("bailian_api_key 未配置，百炼 OCR 不可用")
            return

        try:
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
            models = self._client.models.list()
            ocr_models = [m.id for m in models if "ocr" in m.id.lower()]
            self._model_loaded = True
            logger.info(
                f"Bailian OCR engine ready | model={self._model} | "
                f"max_rps={self._max_rps} | max_concurrent={self._max_concurrent} | "
                f"retry_max={self._retry_max} | "
                f"available_ocr_models={ocr_models}"
            )
        except Exception as e:
            logger.error(f"Bailian OCR 初始化失败: {e}")
            self._model_loaded = False

    def recognize(self, image_path: Path) -> list[dict]:
        if not self._model_loaded:
            self.load_model()

        if not self._model_loaded or self._client is None:
            logger.error("Bailian OCR 引擎未就绪")
            return []

        if not image_path.exists():
            logger.error(f"图片不存在: {image_path}")
            return []

        data_url = _image_to_base64_url(image_path)
        return self._call_with_retry(data_url, image_path.name)

    def _call_with_retry(
        self,
        data_url: str,
        filename: str,
        max_retries: int | None = None,
    ) -> list[dict]:
        retry_max = max_retries if max_retries is not None else self._retry_max

        models_to_try = [self._model]
        for m in BACKUP_MODELS:
            if m != self._model:
                models_to_try.append(m)

        for model in models_to_try:
            for attempt in range(retry_max + 1):
                self._limiter.acquire()

                try:
                    completion = self._client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": data_url},
                                        "min_pixels": self._min_pixels,
                                        "max_pixels": self._max_pixels,
                                    },
                                    {"type": "text", "text": OCR_SYSTEM_PROMPT},
                                ],
                            }
                        ],
                    )

                    raw_text = completion.choices[0].message.content or ""
                    usage = completion.usage
                    logger.debug(
                        f"Bailian OCR: {filename} | model={model} | "
                        f"tokens={usage.total_tokens if usage else '?'} | "
                        f"raw_len={len(raw_text)}"
                    )

                    return self._parse_response(raw_text)

                except APIStatusError as e:
                    if e.status_code == 429:
                        wait = min(2 ** attempt * 2, 60)
                        logger.warning(
                            f"Bailian OCR 429 限流 [{filename}] | model={model} | "
                            f"attempt={attempt+1}/{retry_max+1} | wait={wait}s"
                        )
                        # 记录 429 到分布式限流器（用于自适应降级）
                        try:
                            from services.llm.rate_limiter import get_rate_limiter
                            import asyncio as _aio
                            _limiter = get_rate_limiter()
                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_running():
                                    asyncio.ensure_future(_limiter.record_429("ocr"))
                                else:
                                    loop.run_until_complete(_limiter.record_429("ocr"))
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                loop.run_until_complete(_limiter.record_429("ocr"))
                                loop.close()
                        except Exception:
                            pass
                        if attempt < retry_max:
                            time.sleep(wait)
                            continue
                        else:
                            logger.warning(
                                f"Bailian OCR 主模型限流耗尽重试 [{filename}]，尝试备选模型"
                            )
                            break
                    else:
                        logger.error(f"Bailian OCR API 错误 [{filename}] | model={model} | {e}")
                        break
                except Exception as e:
                    # 超时等异常时尝试 fallback 到备选模型，而不是直接返回空
                    logger.error(f"Bailian OCR 识别失败 [{filename}] | model={model} | {e}")
                    break

        # 百炼所有模型均失败，尝试硅基流动回退
        sf_result = self._call_siliconflow_fallback(data_url, filename)
        if sf_result is not None:
            return sf_result

        logger.error(f"Bailian OCR 所有模型（含硅基流动回退）均失败 [{filename}]")
        return []

    def _call_siliconflow_fallback(self, data_url: str, filename: str) -> list[dict] | None:
        """当百炼所有模型失败后，回退到硅基流动 deepseek-ocr"""
        sf_api_key = settings.siliconflow_api_key_plain
        if not sf_api_key:
            logger.debug("硅基流动 API Key 未配置，跳过回退")
            return None

        sf_model = settings.siliconflow_ocr_model
        sf_base_url = settings.siliconflow_ocr_base_url

        try:
            sf_client = OpenAI(
                api_key=sf_api_key,
                base_url=sf_base_url,
                timeout=self._timeout,
            )

            logger.info(f"尝试硅基流动回退 [{filename}] | model={sf_model}")

            # 硅基流动的 messages 格式与 OpenAI 兼容，但不需要 min_pixels/max_pixels
            completion = sf_client.chat.completions.create(
                model=sf_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {"type": "text", "text": OCR_SYSTEM_PROMPT},
                        ],
                    }
                ],
            )

            raw_text = completion.choices[0].message.content or ""
            usage = completion.usage
            logger.info(
                f"硅基流动 OCR 成功 [{filename}] | model={sf_model} | "
                f"tokens={usage.total_tokens if usage else '?'} | "
                f"raw_len={len(raw_text)}"
            )

            return self._parse_response(raw_text)

        except APIStatusError as e:
            logger.error(f"硅基流动 OCR API 错误 [{filename}] | model={sf_model} | {e}")
            return None
        except Exception as e:
            logger.error(f"硅基流动 OCR 回退失败 [{filename}] | model={sf_model} | {e}")
            return None

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        # 使用分布式限流器的并发上限（而非本地 max_concurrent）
        try:
            from services.llm.rate_limiter import get_rate_limiter
            limiter = get_rate_limiter()
            effective_concurrent = limiter.get_limit("ocr")
        except Exception:
            effective_concurrent = self._max_concurrent

        results: list[list[dict]] = [[] for _ in image_paths]

        with ThreadPoolExecutor(max_workers=effective_concurrent) as pool:
            future_to_idx = {
                pool.submit(self.recognize, path): idx
                for idx, path in enumerate(image_paths)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error(f"Bailian OCR batch item failed [{image_paths[idx].name}]: {e}")
                    results[idx] = []

        return results

    def save_result(self, results: list[dict], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.debug(f"Bailian OCR result saved: {output_path}")

    def _parse_response(self, raw_text: str) -> list[dict]:
        text = raw_text.strip()

        try:
            items = json.loads(text)
            if isinstance(items, list):
                return self._normalize_items(items)
        except json.JSONDecodeError:
            pass

        code_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if code_match:
            try:
                items = json.loads(code_match.group(1).strip())
                if isinstance(items, list):
                    return self._normalize_items(items)
            except json.JSONDecodeError:
                pass

        array_match = re.search(r"\[.*\]", text, re.DOTALL)
        if array_match:
            try:
                items = json.loads(array_match.group(0))
                if isinstance(items, list):
                    return self._normalize_items(items)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Bailian OCR 返回非 JSON 格式，使用纯文本回退解析 | preview: {text[:200]}")
        return self._fallback_parse(text)

    def _normalize_items(self, items: list[dict]) -> list[dict]:
        results = []
        for item in items:
            text = (item.get("text") or "").strip()
            if not text:
                continue

            bbox = item.get("bbox")
            if bbox and isinstance(bbox, list) and len(bbox) == 4:
                normalized_bbox = []
                for pt in bbox:
                    if isinstance(pt, (list, tuple)) and len(pt) == 2:
                        normalized_bbox.append([int(pt[0]), int(pt[1])])
                    else:
                        normalized_bbox = [[0, 0], [0, 0], [0, 0], [0, 0]]
                        break
            else:
                normalized_bbox = [[0, 0], [0, 0], [0, 0], [0, 0]]

            confidence = item.get("confidence", 0.95)
            if not isinstance(confidence, (int, float)):
                confidence = 0.95

            results.append({
                "text": text,
                "confidence": round(float(confidence), 4),
                "bbox": normalized_bbox,
            })

        return results

    def _fallback_parse(self, raw_text: str) -> list[dict]:
        results = []
        for line in raw_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            coord_match = re.match(r"^[\d,\s]+[,\s](.+)$", line)
            if coord_match:
                line = coord_match.group(1).strip()
            if line:
                results.append({
                    "text": line,
                    "confidence": 0.90,
                    "bbox": [[0, 0], [0, 0], [0, 0], [0, 0]],
                })
        return results
