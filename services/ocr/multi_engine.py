"""
多引擎 OCR 包装器 -- 优先级调度 + 自动降级 + 置信度分档 + 二次识别

持有多个 OCR 引擎实例，按优先级依次尝试。
当主引擎失败时自动降级到备用引擎，全部失败时抛出异常。

功能:
  - 置信度分档: 金额/数字字段阈值 0.85, 普通文本 0.70
  - 低置信度二次识别: 中置信度行用备用引擎重识
  - 本地筛+云端精: 本地引擎结果中质量页(avg<0.85)自动用云端引擎精识
  - 区域裁剪重识: 低置信度行裁剪放大2x后单独重识
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

    def __init__(self, engines: list[BaseOCREngine]) -> None:
        self._engines = engines
        self._model_loaded = False
        # 降级统计（用于成本分析）
        self._stats: dict[str, int] = {}  # 引擎名 -> 成功次数

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
                f"chain: {' -> '.join(str(e) for e in self._engines)}"
            )
        else:
            logger.error(f"MultiOCR: 所有 {len(self._engines)} 个引擎均未就绪")

    def recognize(self, image_path: Path) -> list[dict]:
        """
        识别单张图片（带降级 + 置信度分档 + 本地筛云端精 + 区域裁剪重识）

        流程:
        1. 按优先级尝试引擎，跳过未就绪的
        2. 主引擎成功后，检查页面平均置信度
        3. 如果主引擎是本地引擎且avg<0.85(中质量)，用云端引擎精识整页
        4. 对低置信度行做区域裁剪重识(放大2x)
        5. 置信度分档过滤 + 中置信度行备用引擎重试
        """
        if not self._model_loaded:
            self.load_model()

        errors = []
        primary_result = None
        primary_engine_name = None

        for i, engine in enumerate(self._engines):
            if not engine.is_ready:
                logger.debug(
                    f"MultiOCR: skip unready {engine} "
                    f"({i+1}/{len(self._engines)})"
                )
                continue

            try:
                results = engine.recognize(image_path)
                if results:
                    engine_name = str(engine)
                    self._stats[engine_name] = self._stats.get(engine_name, 0) + 1
                    logger.debug(
                        f"MultiOCR: {image_path.name} -> {engine_name} "
                        f"(attempt {i+1}/{len(self._engines)}, {len(results)} blocks)"
                    )
                    primary_result = results
                    primary_engine_name = engine_name
                    break
                else:
                    logger.warning(
                        f"MultiOCR: {engine} empty result [{image_path.name}]"
                        f"({i+1}/{len(self._engines)}), degrade"
                    )
                    errors.append(f"{engine}: empty")
            except Exception as e:
                logger.warning(
                    f"MultiOCR: {engine} error [{image_path.name}]: {e} "
                    f"({i+1}/{len(self._engines)}), degrade"
                )
                errors.append(f"{engine}: {e}")

        if primary_result is None:
            logger.error(
                f"MultiOCR: all {len(self._engines)} engines failed "
                f"[{image_path.name}] | errors: {'; '.join(errors)}"
            )
            return []

        # -- Step 2: local-screen + cloud-refine --
        primary_result = self._cloud_refine_if_needed(
            primary_result, image_path, primary_engine_name
        )

        # -- Step 3: region crop retry for low-confidence blocks --
        primary_result = self._retry_low_confidence_regions(
            primary_result, image_path
        )

        # -- Step 4: confidence tier filtering + fallback retry --
        return self._refine_with_retry(primary_result, image_path, primary_engine_name)

    def _refine_with_retry(
        self,
        primary_result: list[dict],
        image_path: Path,
        primary_engine_name: str,
    ) -> list[dict]:
        """置信度分档过滤 + 低置信度行二次识别"""
        from config.settings import settings

        text_threshold = settings.ocr_confidence_threshold
        numeric_threshold = settings.ocr_confidence_threshold_numeric
        retry_threshold = settings.ocr_confidence_retry_threshold

        # 分类行
        high_conf = []      # 高置信度，直接保留
        retry_needed = []    # 中置信度，需二次识别
        low_conf = []       # 低置信度，直接丢弃

        import re
        numeric_pattern = re.compile(r'^[\d,.\-+/￥¥$%元角万]+$')

        for item in primary_result:
            text = item.get("text", "")
            confidence = item.get("confidence", 0.0)

            # 判断是否为金额/数字行
            is_numeric = bool(numeric_pattern.match(text.strip())) or any(
                kw in text for kw in ["元", "万", "￥", "¥", "$", "合计", "总计", "金额"]
            )
            threshold = numeric_threshold if is_numeric else text_threshold

            if confidence >= threshold:
                high_conf.append(item)
            elif confidence >= retry_threshold:
                retry_needed.append(item)
            else:
                low_conf.append(item)

        if low_conf:
            logger.debug(
                f"MultiOCR: {image_path.name} dropped {len(low_conf)} low-confidence blocks "
                f"(<{retry_threshold})"
            )

        if not retry_needed:
            return high_conf

        # ── 对中置信度行用备用引擎二次识别 ──
        retry_engine = self._get_fallback_engine(primary_engine_name)
        if retry_engine is None:
            # 没有备用引擎，保留中置信度行（降级到 text_threshold）
            for item in retry_needed:
                high_conf.append(item)
            logger.debug(
                f"MultiOCR: {image_path.name} no fallback for retry, "
                f"kept {len(retry_needed)} medium-confidence blocks"
            )
            return high_conf

        try:
            retry_result = retry_engine.recognize(image_path)
            if not retry_result:
                # 备用引擎也失败，保留中置信度行
                for item in retry_needed:
                    high_conf.append(item)
                return high_conf

            # 构建 retry_result 的文本->置信度映射
            retry_map = {}
            for item in retry_result:
                key = item.get("text", "").strip()
                if key:
                    retry_map[key] = item

            improved = 0
            for item in retry_needed:
                text = item.get("text", "").strip()
                retry_item = retry_map.get(text)
                if retry_item and retry_item.get("confidence", 0) > item.get("confidence", 0):
                    # 备用引擎结果更优
                    high_conf.append(retry_item)
                    improved += 1
                else:
                    high_conf.append(item)  # 保留原始

            if improved > 0:
                logger.info(
                    f"MultiOCR: {image_path.name} retry improved {improved}/{len(retry_needed)} "
                    f"blocks via {retry_engine}"
                )
        except Exception as e:
            logger.warning(f"MultiOCR retry failed: {e}")
            for item in retry_needed:
                high_conf.append(item)

        return high_conf

    def _cloud_refine_if_needed(
        self,
        primary_result: list[dict],
        image_path: Path,
        primary_engine_name: str,
    ) -> list[dict]:
        """local-screen + cloud-refine: 如果本地引擎结果质量不高，用云端引擎精识

        策略:
        - 主引擎是本地引擎(RapidOCR/local) 且
        - 页面平均置信度 < 0.85(中质量)
        - 则用云端引擎(baidu/bailian/glm)重新识别整页，取更好的结果
        """
        # 判断主引擎是否是本地引擎
        is_local = any(kw in primary_engine_name.lower() for kw in ["rapid", "local", "paddle"])
        if not is_local:
            return primary_result

        # 计算平均置信度
        if not primary_result:
            return primary_result
        avg_conf = sum(r.get("confidence", 0) for r in primary_result) / len(primary_result)

        # 只对中质量页面触发云端精识 (0.50 <= avg < 0.85)
        if avg_conf >= 0.85 or avg_conf < 0.50:
            return primary_result

        # 找云端引擎
        cloud_engine = None
        for engine in self._engines:
            name = str(engine).lower()
            if any(kw in name for kw in ["baidu", "bailian", "glm", "qwen"]):
                if engine.is_ready:
                    cloud_engine = engine
                    break

        if cloud_engine is None:
            logger.debug(
                f"MultiOCR: {image_path.name} avg_conf={avg_conf:.3f} needs cloud refine "
                f"but no cloud engine available"
            )
            return primary_result

        try:
            cloud_result = cloud_engine.recognize(image_path)
            if not cloud_result:
                return primary_result

            cloud_avg = sum(r.get("confidence", 0) for r in cloud_result) / len(cloud_result)
            if cloud_avg > avg_conf:
                self._stats[str(cloud_engine)] = self._stats.get(str(cloud_engine), 0) + 1
                logger.info(
                    f"MultiOCR cloud-refine: {image_path.name} "
                    f"local avg={avg_conf:.3f} -> cloud avg={cloud_avg:.3f} via {cloud_engine}"
                )
                return cloud_result
            else:
                logger.debug(
                    f"MultiOCR cloud-refine: {image_path.name} cloud result not better "
                    f"({cloud_avg:.3f} vs local {avg_conf:.3f})"
                )
        except Exception as e:
            logger.debug(f"MultiOCR cloud-refine failed: {e}")

        return primary_result

    def _retry_low_confidence_regions(
        self,
        primary_result: list[dict],
        image_path: Path,
    ) -> list[dict]:
        """区域裁剪重识: 对低置信度区域放大2x后单独重识

        对置信度在 [region_retry_min_conf, confidence_threshold) 的行:
        1. 根据 bbox 从原图裁剪该区域(加20%边距)
        2. 放大2x
        3. 用本地引擎(RapidOCR)重识
        4. 如果重识结果置信度更高，替换原始结果
        """
        min_conf = settings.ocr_region_retry_min_conf  # 0.40
        max_conf = settings.ocr_confidence_threshold     # 0.70
        text_threshold = settings.ocr_confidence_threshold

        # 收集需要重识的行
        retry_items = []
        for i, item in enumerate(primary_result):
            conf = item.get("confidence", 0)
            if min_conf <= conf < max_conf:
                bbox = item.get("bbox")
                if bbox and bbox != [[0, 0], [0, 0], [0, 0], [0, 0]]:
                    retry_items.append((i, item))

        if not retry_items:
            return primary_result

        # 找本地引擎用于重识
        local_engine = None
        for engine in self._engines:
            name = str(engine).lower()
            if any(kw in name for kw in ["rapid", "local"]):
                if engine.is_ready:
                    local_engine = engine
                    break
        if local_engine is None:
            return primary_result

        try:
            import cv2
            import tempfile
        except ImportError:
            return primary_result

        img = cv2.imread(str(image_path))
        if img is None:
            return primary_result

        h, w = img.shape[:2]
        improved = 0
        tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_region_"))

        for idx, item in retry_items:
            bbox = item["bbox"]
            # bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)

            # 加20%边距
            margin_x = int((x_max - x_min) * 0.2)
            margin_y = int((y_max - y_min) * 0.2)
            x_min = max(0, x_min - margin_x)
            y_min = max(0, y_min - margin_y)
            x_max = min(w, x_max + margin_x)
            y_max = min(h, y_max + margin_y)

            # 裁剪
            region = img[y_min:y_max, x_min:x_max]
            if region.size == 0:
                continue

            # 放大2x
            region_h, region_w = region.shape[:2]
            region = cv2.resize(
                region,
                (region_w * 2, region_h * 2),
                interpolation=cv2.INTER_CUBIC,
            )

            # 保存到临时文件
            tmp_path = tmp_dir / f"region_{idx}.png"
            cv2.imwrite(str(tmp_path), region)

            try:
                region_result = local_engine.recognize(tmp_path)
                if region_result:
                    # 找最匹配的行（文本最相似的）
                    original_text = item.get("text", "").strip()
                    best_match = None
                    for rr in region_result:
                        if rr.get("confidence", 0) > item.get("confidence", 0):
                            # 文本有重叠即可（裁剪区域可能识别出多行）
                            rr_text = rr.get("text", "").strip()
                            if (original_text in rr_text or rr_text in original_text
                                    or len(set(original_text) & set(rr_text)) > len(original_text) * 0.5):
                                best_match = rr
                                break

                    if best_match and best_match.get("confidence", 0) > item.get("confidence", 0):
                        # 保留原始 bbox，更新 text 和 confidence
                        primary_result[idx] = {
                            **item,
                            "text": best_match["text"],
                            "confidence": best_match["confidence"],
                        }
                        improved += 1
            except Exception:
                pass

        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

        if improved > 0:
            logger.info(
                f"MultiOCR region-retry: {image_path.name} improved {improved}/{len(retry_items)} "
                f"blocks via crop+2x+reOCR"
            )

        return primary_result

    def _get_fallback_engine(self, primary_name: str) -> BaseOCREngine | None:
        """获取主引擎的备用引擎（优先级次高的就绪引擎）"""
        found_primary = False
        for engine in self._engines:
            if str(engine) == primary_name:
                found_primary = True
                continue
            if found_primary and engine.is_ready:
                return engine
        # 如果没有找到主引擎之后的就绪引擎，返回第一个非主引擎的就绪引擎
        for engine in self._engines:
            if str(engine) != primary_name and engine.is_ready:
                return engine
        return None

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

        # 全部失败 -> 返回全空列表
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
