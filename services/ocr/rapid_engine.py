"""
RapidOCR 引擎 — 基于 ONNX Runtime 的轻量本地 OCR

优势:
  - 不依赖 PaddlePaddle（避免 oneDNN/CPU 兼容性问题）
  - 模型仅约 15MB，首次运行自动下载
  - 支持 GPU (CUDA) 和 CPU 推理
  - 基于 PaddleOCR 同源 PP-OCRv4 模型，中文识别效果一致
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loguru import logger

from config.settings import settings
from services.ocr.base import BaseOCREngine


class RapidOCREngine(BaseOCREngine):
    """
    RapidOCR 本地引擎

    使用 rapidocr 库 + ONNX Runtime 推理。
    模型常驻内存，不重复初始化。
    """

    # 批量处理线程数（ONNX Runtime CPU 模式下多线程并行推理）
    _max_concurrent = int(os.environ.get("RAPIDOCR_MAX_WORKERS", "4"))

    def __init__(self):
        self._engine = None
        self._model_loaded = False

    @property
    def is_ready(self) -> bool:
        return self._model_loaded

    def load_model(self) -> None:
        """加载 RapidOCR 模型（常驻内存）

        Docker 容器中以非 root 用户运行时，默认模型下载路径
        (site-packages/rapidocr/models) 可能不可写。
        使用 /tmp/rapidocr_models 作为可写的模型缓存目录。
        """
        if self._model_loaded:
            return

        try:
            from rapidocr import RapidOCR
            import tempfile

            # 模型目录优先级：
            # 1. /app/rapidocr_models（Docker 内预下载）
            # 2. $TEMP/rapidocr_models（本地开发）
            docker_model_dir = Path("/app/rapidocr_models")
            if docker_model_dir.exists() and any(docker_model_dir.glob("*.onnx")):
                model_dir = docker_model_dir
            else:
                model_dir = Path(tempfile.gettempdir()) / "rapidocr_models"
                model_dir.mkdir(parents=True, exist_ok=True)

            self._engine = RapidOCR(
                params={"Global.model_root_dir": str(model_dir)}
            )
            self._model_loaded = True
            logger.info(
                f"RapidOCR loaded | GPU=auto-detect | lang=ch (PP-OCRv4) "
                f"| model_dir={model_dir} | workers={self._max_concurrent}"
            )
        except ImportError:
            logger.error(
                "rapidocr not installed. Run: pip install rapidocr onnxruntime"
            )
            self._model_loaded = False
        except Exception as e:
            logger.error(f"Failed to load RapidOCR: {e}")
            self._model_loaded = False

    def recognize(self, image_path: Path) -> list[dict]:
        """
        识别单张图片

        返回:
            [{"text": str, "confidence": float, "bbox": [[x1,y1],...,[x4,y4]]}, ...]
        """
        if not self._model_loaded:
            self.load_model()

        if not self._model_loaded:
            logger.error("RapidOCR not loaded, cannot recognize")
            return []

        try:
            result = self._engine(str(image_path))

            if result is None or result.txts is None:
                return []

            ocr_results = []
            confidence_threshold = getattr(settings, "ocr_confidence_threshold", 0.5)

            for i, (text, score, box) in enumerate(
                zip(result.txts, result.scores, result.boxes)
            ):
                if not text or not text.strip():
                    continue
                confidence = float(score)
                if confidence < confidence_threshold:
                    continue

                # box shape: (4, 2) — [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                bbox = None
                if box is not None:
                    try:
                        import numpy as np
                        if isinstance(box, np.ndarray):
                            bbox = [[int(p[0]), int(p[1])] for p in box.tolist()]
                        elif isinstance(box, (list, tuple)):
                            bbox = [[int(p[0]), int(p[1])] for p in box]
                    except Exception:
                        pass

                ocr_results.append({
                    "text": text.strip(),
                    "confidence": round(confidence, 4),
                    "bbox": bbox or [[0, 0], [0, 0], [0, 0], [0, 0]],
                })

            return ocr_results

        except Exception as e:
            logger.error(f"RapidOCR failed for {image_path}: {e}")
            return []

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        """批量识别（多线程并行）

        使用 ThreadPoolExecutor 并行处理多张图片。
        ONNX Runtime 在 CPU 模式下是线程安全的，可以并行推理。
        线程数由 RAPIDOCR_MAX_WORKERS 环境变量控制（默认 4）。
        """
        if not self._model_loaded:
            self.load_model()

        total = len(image_paths)
        results: list[list[dict]] = [None] * total  # type: ignore

        def _recognize_one(idx_and_path):
            idx, path = idx_and_path
            return idx, self.recognize(path)

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
            futures = []
            for i, path in enumerate(image_paths):
                futures.append(pool.submit(_recognize_one, (i, path)))

            completed = 0
            for future in futures:
                idx, result = future.result()
                results[idx] = result
                completed += 1
                if completed % 10 == 0 or completed == total:
                    logger.debug(f"RapidOCR batch {completed}/{total}: {image_paths[idx].name}")

        return results

    def __str__(self) -> str:
        return "RapidOCR(local)"
