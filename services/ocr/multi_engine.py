"""
多引擎 OCR 包装器 — 优先级调度 + 自动降级

持有多个 OCR 引擎实例，按优先级依次尝试。
当主引擎失败时自动降级到备用引擎，全部失败时抛出异常。

典型配置:
  ocr_engine_type = "multi"
  ocr_multi_engines = ["baidu", "glm", "bailian"]
  → 百度云(主力,最省) → GLM(免费降级) → 百炼(最终兜底)

降级策略:
  - 引擎未就绪(is_ready=False) → 跳过
  - 引擎返回空结果 → 判定为失败，降级
  - 引擎抛异常 → 记录 warning，降级
  - 全部引擎失败 → 返回空列表（不抛异常，避免阻断 Pipeline）
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from config.settings import settings
from services.ocr.base import BaseOCREngine


class MultiOCREngine(BaseOCREngine):
    """
    多引擎组合 OCR

    按优先级依次尝试多个引擎，成功则返回，失败则降级。
    提供降级成本追踪（记录每次调用使用了哪个引擎）。

    Usage:
        engines = [BaiduOCREngine(), GlmOCREngine(), BailianOCREngine()]
        engine = MultiOCREngine(engines)
        engine.load_model()
        results = engine.recognize(image_path)
    """

    def __init__(self, engines: list[BaseOCREngine]):
        self._engines = engines
        self._model_loaded = False
        # 降级统计（用于成本分析）
        self._stats: dict[str, int] = {}  # 引擎名 → 成功次数

    @property
    def is_ready(self) -> bool:
        """至少一个引擎就绪即为可用"""
        return any(e.is_ready for e in self._engines)

    def load_model(self) -> None:
        """加载所有引擎"""
        loaded_count = 0
        for engine in self._engines:
            try:
                engine.load_model()
                if engine.is_ready:
                    loaded_count += 1
            except Exception as e:
                logger.warning(f"引擎 {engine} 加载失败: {e}")

        self._model_loaded = loaded_count > 0
        if self._model_loaded:
            logger.info(
                f"MultiOCR ready: {loaded_count}/{len(self._engines)} engines | "
                f"chain: {' → '.join(str(e) for e in self._engines)}"
            )
        else:
            logger.error(f"MultiOCR: 所有 {len(self._engines)} 个引擎均未就绪")

    def recognize(self, image_path: Path) -> list[dict]:
        """
        识别单张图片（带降级）

        依次尝试每个引擎:
        1. 跳过未就绪的引擎
        2. 尝试识别
        3. 成功(非空结果) → 返回
        4. 失败(/空/异常) → 记录降级，继续下一个
        5. 全部失败 → 返回空列表
        """
        if not self._model_loaded:
            self.load_model()

        errors = []
        for i, engine in enumerate(self._engines):
            if not engine.is_ready:
                logger.debug(
                    f"MultiOCR: 跳过未就绪引擎 {engine} "
                    f"({i+1}/{len(self._engines)})"
                )
                continue

            try:
                results = engine.recognize(image_path)
                if results:
                    # 成功！
                    engine_name = str(engine)
                    self._stats[engine_name] = self._stats.get(engine_name, 0) + 1
                    logger.debug(
                        f"MultiOCR: {image_path.name} → {engine_name} "
                        f"(attempt {i+1}/{len(self._engines)}, {len(results)} blocks)"
                    )
                    return results
                else:
                    # 空结果，视为失败
                    logger.warning(
                        f"MultiOCR: {engine} 返回空结果 [{image_path.name}]"
                        f"({i+1}/{len(self._engines)})，降级"
                    )
                    errors.append(f"{engine}: 空结果")
            except Exception as e:
                logger.warning(
                    f"MultiOCR: {engine} 异常 [{image_path.name}]: {e} "
                    f"({i+1}/{len(self._engines)})，降级"
                )
                errors.append(f"{engine}: {e}")

        # 全部失败
        logger.error(
            f"MultiOCR: 所有 {len(self._engines)} 个引擎均失败 "
            f"[{image_path.name}] | errors: {'; '.join(errors)}"
        )
        return []

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        """
        批量识别（带降级）

        策略：整批委托给第一个就绪引擎。
        如果某个引擎在 batch 中部分失败，不会降级到下一个引擎
        （因为下一个引擎也无法处理"同一批中的部分图片"）。
        如果整批返回全空结果，尝试降级到下一个引擎。
        """
        if not self._model_loaded:
            self.load_model()

        errors = []
        for i, engine in enumerate(self._engines):
            if not engine.is_ready:
                continue

            try:
                results = engine.recognize_batch(image_paths)
                # 检查是否有任何非空结果
                non_empty = [r for r in results if r]
                if non_empty:
                    engine_name = str(engine)
                    self._stats[engine_name] = (
                        self._stats.get(engine_name, 0) + len(non_empty)
                    )
                    logger.info(
                        f"MultiOCR batch: {len(non_empty)}/{len(image_paths)} "
                        f"成功 via {engine_name}"
                    )
                    return results
                else:
                    logger.warning(
                        f"MultiOCR batch: {engine} 全部返回空 "
                        f"({i+1}/{len(self._engines)})，降级"
                    )
                    errors.append(f"{engine}: 批量全空")
            except Exception as e:
                logger.warning(
                    f"MultiOCR batch: {engine} 异常: {e} "
                    f"({i+1}/{len(self._engines)})，降级"
                )
                errors.append(f"{engine}: {e}")

        # 全部失败 → 返回全空列表
        logger.error(
            f"MultiOCR batch: 所有 {len(self._engines)} 个引擎均失败 | "
            f"errors: {'; '.join(errors)}"
        )
        return [[] for _ in image_paths]

    def get_stats(self) -> dict:
        """获取降级统计（用于成本分析和监控）"""
        return dict(self._stats)

    def __str__(self) -> str:
        engine_names = ", ".join(str(e) for e in self._engines)
        return f"MultiOCR({engine_names})"
