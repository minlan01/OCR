"""
OCR 引擎抽象基类

定义所有 OCR 引擎的统一接口，包括本地 PaddleOCR 和云端 API 引擎。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger


class BaseOCREngine(ABC):
    """
    OCR 引擎统一接口

    所有引擎必须实现:
      - is_ready      → 模型是否就绪
      - load_model()  → 加载/初始化模型
      - recognize()   → 单图识别
      - recognize_batch() → 批量识别
      - save_result() → 保存结果为 JSON
    """

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """模型是否已加载且就绪"""
        ...

    @abstractmethod
    def load_model(self) -> None:
        """加载 OCR 模型（幂等，常驻内存）"""
        ...

    @abstractmethod
    def recognize(self, image_path: Path) -> list[dict]:
        """
        识别单张图片

        返回:
            [{"text": str, "confidence": float, "bbox": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}, ...]
        """
        ...

    @abstractmethod
    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        """批量识别多张图片"""
        ...

    def save_result(self, results: list[dict], output_path: Path) -> None:
        """保存 OCR 结果为 JSON（默认实现，子类可覆盖）"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.debug(f"OCR result saved: {output_path}")
