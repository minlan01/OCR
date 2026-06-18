"""
百度智能云 OCR 引擎适配器

基于百度智能云文字识别 API，使用 baidu-aip Python SDK。
支持通用文字识别（高精度版）和医疗票据专项识别。

定位：主力 OCR 引擎（成本最低）。
成本：通用高精度版 0.006 元/次起，每月 1000 次免费额度。
局限：不支持表格结构解析（纯文字输出，无 bbox 坐标）。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

from config.settings import settings
from services.ocr.base import BaseOCREngine


class BaiduOCREngine(BaseOCREngine):
    """
    百度云 OCR 引擎

    使用 baidu-aip SDK 调用百度智能云文字识别服务。
    支持通用文字识别（高精度版）。

    特点:
      - 价格极低（0.006 元/次起，月免 1000 次）
      - 返回纯文字（不含 bbox 坐标和表格结构）
    """

    def __init__(
        self,
        app_id: str | None = None,
        api_key: str | None = None,
        secret_key: str | None = None,
        timeout: int | None = None,
    ):
        self._app_id = app_id if app_id is not None else settings.baidu_ocr_app_id
        self._api_key = api_key if api_key is not None else settings.baidu_ocr_api_key
        _sk = settings.baidu_ocr_secret_key
        if hasattr(_sk, 'get_secret_value'):
            _sk = _sk.get_secret_value()
        self._secret_key = secret_key if secret_key is not None else _sk
        self._timeout = timeout if timeout is not None else settings.baidu_ocr_timeout
        self._max_concurrent = settings.baidu_ocr_max_concurrent
        self._client = None
        self._model_loaded = False

    @property
    def is_ready(self) -> bool:
        return self._model_loaded and self._client is not None

    def load_model(self) -> None:
        if self._model_loaded:
            return
        if not self._app_id or not self._api_key or not self._secret_key:
            logger.warning(
                "百度云 OCR 凭证未完整配置 "
                f"(app_id={'yes' if self._app_id else 'no'}, "
                f"api_key={'yes' if self._api_key else 'no'}, "
                f"secret_key={'yes' if self._secret_key else 'no'})，引擎不可用"
            )
            return
        try:
            from aip import AipOcr
            self._client = AipOcr(self._app_id, self._api_key, self._secret_key)
            self._client.setConnectionTimeoutInMillis(self._timeout * 1000)
            self._client.setSocketTimeoutInMillis(self._timeout * 1000)
            self._model_loaded = True
            logger.info(
                f"Baidu OCR engine ready | type=basicAccurate | "
                f"timeout={self._timeout}s | max_concurrent={self._max_concurrent} | "
                f"cost=0.006¥/call (1000 free/month)"
            )
        except ImportError:
            logger.warning("baidu-aip 未安装，百度云 OCR 不可用。安装: pip install baidu-aip")
            self._model_loaded = False
        except Exception as e:
            logger.error(f"百度云 OCR 初始化失败: {e}")
            self._model_loaded = False

    def recognize(self, image_path: Path) -> list[dict]:
        if not self._model_loaded:
            self.load_model()
        if not self._model_loaded or self._client is None:
            logger.error("百度云 OCR 引擎未就绪")
            return []
        if not image_path.exists():
            logger.error(f"图片不存在: {image_path}")
            return []
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            result = self._client.basicAccurate(image_bytes)
            if "error_code" in result:
                error_code = result.get("error_code")
                error_msg = result.get("error_msg", "Unknown")
                logger.error(
                    f"百度云 OCR API 错误 [{image_path.name}]: "
                    f"code={error_code} msg={error_msg}"
                )
                if error_code == 17:
                    logger.warning("百度云 OCR 当日免费配额已用完")
                elif error_code == 18:
                    logger.warning("百度云 OCR QPS 超限")
                elif error_code in (100, 110, 111):
                    logger.warning("百度云 OCR 认证失败，请检查凭证")
                return []
            items = self._parse_result(result, image_path.name)
            logger.debug(
                f"Baidu OCR: {image_path.name} | words={len(items)} | "
                f"result_num={result.get('words_result_num', 0)}"
            )
            return items
        except Exception as e:
            logger.error(f"百度云 OCR 识别失败 [{image_path.name}]: {e}")
            return []

    def _parse_result(self, result: dict, filename: str) -> list[dict]:
        words_result = result.get("words_result", [])
        if not words_result:
            logger.warning(f"百度云 OCR 返回空结果 [{filename}]")
            return []
        items = []
        for item in words_result:
            text = (item.get("words") or "").strip()
            if not text:
                continue
            items.append({
                "text": text,
                "confidence": 0.95,
                "bbox": [[0, 0], [0, 0], [0, 0], [0, 0]],
            })
        return items

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        results: list[list[dict]] = [[] for _ in image_paths]
        with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
            future_to_idx = {
                pool.submit(self.recognize, path): idx
                for idx, path in enumerate(image_paths)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error(f"Baidu OCR batch item failed [{image_paths[idx].name}]: {e}")
                    results[idx] = []
        return results

    def save_result(self, results: list[dict], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.debug(f"Baidu OCR result saved: {output_path}")

    def __str__(self) -> str:
        return "BaiduOCR(basicAccurate)"
