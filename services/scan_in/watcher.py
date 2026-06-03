"""
Watch Folder 监听器
监听扫描仪共享目录，自动接收新 PDF 文件
使用异步 sleep 避免阻塞事件循环
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config.settings import settings
from services.scan_in.validator import pdf_validator, ValidationResult
from services.scan_in.uploader import create_task_from_file


# 文件大小稳定检测：连续 2 次检查间隔和次数
STABLE_CHECK_INTERVAL = 2.0  # 秒
STABLE_CHECK_COUNT = 2


async def _is_file_stable(file_path: Path) -> bool:
    """检查文件是否写入完成（连续 N 次大小不变）

    使用 asyncio.sleep 替代 time.sleep，避免阻塞事件循环。

    Args:
        file_path: 待检查的文件路径

    Returns:
        True 如果文件已稳定（不再变化），False 如果文件无法访问或仍在写入
    """
    last_size = -1
    stable_count = 0
    for _ in range(STABLE_CHECK_COUNT + 1):
        try:
            current_size = file_path.stat().st_size
        except OSError:
            return False
        if current_size == last_size:
            stable_count += 1
        else:
            stable_count = 0
        last_size = current_size
        if stable_count >= STABLE_CHECK_COUNT:
            return True
        await asyncio.sleep(STABLE_CHECK_INTERVAL)
    return False


def _ensure_dir(path_str: str) -> Path:
    """确保目录存在

    Args:
        path_str: 目录路径字符串

    Returns:
        Path 对象
    """
    p = Path(path_str)
    p.mkdir(parents=True, exist_ok=True)
    return p


class ScanWatcherHandler(FileSystemEventHandler):
    """扫描目录事件处理器

    监听文件系统事件，当新 PDF 文件出现时自动排队处理。
    使用异步方式避免阻塞事件循环。
    """

    def __init__(self):
        self._processing: set[str] = set()
        _ensure_dir(settings.error_dir)
        _ensure_dir(settings.archive_dir)

    def on_created(self, event):
        """文件创建事件

        Args:
            event: watchdog 文件系统事件
        """
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        suffix = file_path.suffix.lower()

        # 忽略非 PDF 文件
        if suffix != ".pdf":
            logger.debug(f"Ignored non-PDF file: {file_path.name}")
            return

        # 忽略临时文件
        if file_path.name.startswith("~") or file_path.name.startswith("."):
            return

        # 防重复处理
        abs_path = str(file_path.absolute())
        if abs_path in self._processing:
            return

        self._processing.add(abs_path)
        asyncio.create_task(self._handle_new_file(file_path))

    async def _handle_new_file(self, file_path: Path):
        """处理新文件（异步）

        完整流程: 稳定检测 → 校验 → 创建任务 → 归档

        Args:
            file_path: 新文件的绝对路径
        """
        abs_path = str(file_path.absolute())
        try:
            logger.info(f"New PDF detected: {file_path.name}")

            # 1. 等待文件写入完成（异步检查）
            if not await _is_file_stable(file_path):
                logger.warning(f"File not stable: {file_path.name}, skipping")
                self._move_to_error(file_path, "FILE_UNSTABLE")
                return

            # 2. 校验
            validation = pdf_validator.validate(file_path)
            if not validation.is_valid:
                logger.error(
                    f"Validation failed: {file_path.name} | "
                    f"{validation.error_code}: {validation.error_message}"
                )
                self._move_to_error(file_path, validation.error_code or "VALIDATION_FAILED")
                return

            # 3. 创建任务并上传
            task = await create_task_from_file(
                file_path=file_path,
                scanner_id=settings.watch_dir.replace("\\", "/").split("/")[-1] or "watch_folder",
                file_size=validation.file_size,
            )

            logger.info(
                f"Task created: {task.id} | pages={validation.page_count} | "
                f"text_pdf={validation.is_text_pdf} | size={validation.file_size}"
            )

            # 4. 归档成功文件
            self._move_to_archive(file_path)

        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}", exc_info=True)
            self._move_to_error(file_path, "PROCESSING_ERROR")
        finally:
            self._processing.discard(abs_path)

    def _move_to_error(self, file_path: Path, error_code: str):
        """移动失败文件到错误目录

        Args:
            file_path: 源文件路径
            error_code: 错误代码，用于文件名前缀
        """
        try:
            dest = Path(settings.error_dir) / f"{error_code}_{file_path.name}"
            shutil.move(str(file_path), str(dest))
            logger.info(f"Moved to error: {file_path.name} -> {dest.name}")
        except Exception as e:
            logger.error(f"Failed to move error file: {e}")

    def _move_to_archive(self, file_path: Path):
        """归档成功处理文件

        Args:
            file_path: 源文件路径
        """
        try:
            dest = Path(settings.archive_dir) / file_path.name
            # 处理重名
            if dest.exists():
                dest = Path(settings.archive_dir) / f"{int(time.time())}_{file_path.name}"
            shutil.move(str(file_path), str(dest))
            logger.info(f"Archived: {file_path.name} -> {dest.name}")
        except Exception as e:
            logger.error(f"Failed to archive file: {e}")


def start_watcher():
    """启动目录监听（阻塞）

    持续监听 watch_dir，新文件到达时自动排队处理。
    使用 Ctrl+C 停止。
    """
    watch_dir = _ensure_dir(settings.watch_dir)
    _ensure_dir(settings.error_dir)
    _ensure_dir(settings.archive_dir)

    logger.info(f"ScanStruct Watcher started | watching: {watch_dir}")

    handler = ScanWatcherHandler()
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Watcher stopped by user")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    from config.logging import setup_logging
    setup_logging()
    start_watcher()
