"""
GLM-4V-Flash OCR 引擎适配器

基于 BailianOCREngine 架构，适配智谱 GLM-4V-Flash 多模态模型。
通过 OpenAI 兼容接口调用，支持 Base64 data URL 和公网 URL 两种图像传入方式。

定位：免费降级引擎，当百度云 OCR 不可用时自动切换。
成本：GLM-4V-Flash 完全免费（智谱开放平台）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from loguru import logger
from openai import OpenAI, APIStatusError

from config.settings import settings
from services.ocr.base import BaseOCREngine
from services.ocr.common import OCR_SYSTEM_PROMPT, _image_to_base64_url


class GlmOCREngine(BaseOCREngine):
    """
    GLM-4V-Flash OCR 引擎

    通过 OpenAI 兼容接口调用智谱 GLM-4V-Flash 多模态模型。
    免费使用，适合作为百度云 OCR 的降级备份。

    特点:
      - 完全免费（智谱开放平台）
      - 中文识别能力良好
      - 单张图片顺序处理（免费模型 QPS 限制）
      - 支持 Base64 data URL
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self._api_key = api_key if api_key is not None else settings.glm_api_key_plain
        self._base_url = base_url if base_url is not None else settings.glm_base_url
        self._model = model if model is not None else settings.glm_model
        self._timeout = timeout if timeout is not None else settings.glm_timeout
        self._client: Optional[OpenAI] = None
        self._model_loaded = False

    @property
    def is_ready(self) -> bool:
        return self._model_loaded

    def load_model(self) -> None:
        if self._model_loaded:
            return
        if not self._api_key:
            logger.warning("glm_api_key 未配置，GLM-4V-Flash OCR 不可用")
            return
        try:
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
            )
            self._model_loaded = True
            logger.info(
                f"GLM-4V-Flash OCR engine ready | model={self._model} | "
                f"base_url={self._base_url} | timeout={self._timeout}s | cost=FREE"
            )
        except Exception as e:
            logger.error(f"GLM-4V-Flash OCR 初始化失败: {e}")
            self._model_loaded = False

    def recognize(self, image_path: Path) -> list[dict]:
        if not self._model_loaded:
            self.load_model()
        if not self._model_loaded or self._client is None:
            logger.error("GLM-4V-Flash OCR 引擎未就绪")
            return []
        if not image_path.exists():
            logger.error(f"图片不存在: {image_path}")
            return []
        data_url = _image_to_base64_url(image_path)
        return self._call_api(data_url, image_path.name)

    def _call_api(self, data_url: str, filename: str) -> list[dict]:
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": OCR_SYSTEM_PROMPT},
                        ],
                    }],
                    max_tokens=4096,
                    temperature=0.1,
                )
                raw_text = completion.choices[0].message.content or ""
                usage = completion.usage
                logger.info(
                    f"GLM-4V-Flash OCR: {filename} | model={self._model} | "
                    f"tokens={usage.total_tokens if usage else '?'} | "
                    f"raw_len={len(raw_text)} | attempt={attempt+1}"
                )
                return self._parse_response(raw_text)
            except APIStatusError as e:
                if e.status_code == 429:
                    wait = min(2 ** attempt * 3, 30)
                    logger.warning(
                        f"GLM-4V-Flash 429 [{filename}] | "
                        f"attempt={attempt+1}/{max_retries+1} | wait={wait}s"
                    )
                    if attempt < max_retries:
                        time.sleep(wait)
                        continue
                else:
                    logger.error(f"GLM-4V-Flash API error [{filename}] | {e.status_code}: {e}")
                    break
            except Exception as e:
                logger.error(f"GLM-4V-Flash 识别失败 [{filename}]: {e}")
                break
        logger.error(f"GLM-4V-Flash 所有重试均失败 [{filename}]")
        return []

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        results = []
        for path in image_paths:
            try:
                results.append(self.recognize(path))
            except Exception as e:
                logger.error(f"GLM-4V-Flash batch item failed [{path.name}]: {e}")
                results.append([])
        return results

    def save_result(self, results: list[dict], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.debug(f"GLM-4V-Flash OCR result saved: {output_path}")

    def __str__(self) -> str:
        return f"GlmOCR({self._model})"

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
        logger.warning(f"GLM-4V-Flash 返回非 JSON 格式，使用纯文本回退 | preview: {text[:200]}")
        return self._fallback_parse(text)

    def _normalize_items(self, items: list[dict]) -> list[dict]:
        results = []
        for item in items:
            text_val = (item.get("text") or "").strip()
            if not text_val:
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
            confidence = item.get("confidence", 0.90)
            if not isinstance(confidence, (int, float)):
                confidence = 0.90
            results.append({
                "text": text_val,
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
                    "confidence": 0.85,
                    "bbox": [[0, 0], [0, 0], [0, 0], [0, 0]],
                })
        return results
