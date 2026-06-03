"""
本地文件系统存储 — MinIO 的开发替代方案
接口与 MinioClient 完全一致，可直接替换
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings


class LocalStorageClient:
    """本地文件系统存储客户端，接口兼容 MinioClient"""

    def __init__(self):
        self._base: Optional[Path] = None

    @property
    def base_dir(self) -> Path:
        if self._base is None:
            self._base = Path(settings.local_storage_dir)
            self._base.mkdir(parents=True, exist_ok=True)
        return self._base

    def _bucket_dir(self, bucket: str) -> Path:
        d = self.base_dir / bucket
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ping(self) -> bool:
        return self.base_dir.is_dir()

    def ensure_buckets(self) -> None:
        for bucket in settings.all_minio_buckets:
            self._bucket_dir(bucket)
        logger.info(f"Local storage buckets ensured: {settings.all_minio_buckets}")

    def upload_bytes(
        self, bucket: str, object_key: str, data: bytes,
        content_type: str = "application/octet-stream",
    ) -> int:
        fp = self._bucket_dir(bucket) / object_key
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)
        logger.debug(f"Local upload: {bucket}/{object_key} ({len(data)} bytes)")
        return len(data)

    def upload_file(
        self, bucket: str, object_key: str, file_path: str,
        content_type: str = "application/octet-stream",
    ) -> int:
        src = Path(file_path)
        dst = self._bucket_dir(bucket) / object_key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        size = src.stat().st_size
        logger.debug(f"Local file upload: {file_path} -> {bucket}/{object_key} ({size} bytes)")
        return size

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        fp = self._bucket_dir(bucket) / object_key
        if not fp.exists():
            raise FileNotFoundError(f"Local object not found: {bucket}/{object_key}")
        return fp.read_bytes()

    def download_file(self, bucket: str, object_key: str, file_path: str) -> None:
        src = self._bucket_dir(bucket) / object_key
        if not src.exists():
            raise FileNotFoundError(f"Local object not found: {bucket}/{object_key}")
        dst = Path(file_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        logger.debug(f"Local download: {bucket}/{object_key} -> {file_path}")

    def delete_object(self, bucket: str, object_key: str) -> None:
        fp = self._bucket_dir(bucket) / object_key
        try:
            if fp.is_file():
                fp.unlink()
            elif fp.is_dir():
                shutil.rmtree(str(fp))
            logger.debug(f"Local delete: {bucket}/{object_key}")
        except OSError as e:
            logger.warning(f"Local delete failed (non-critical): {bucket}/{object_key} | {e}")

    def object_exists(self, bucket: str, object_key: str) -> bool:
        return (self._bucket_dir(bucket) / object_key).exists()

    def get_presigned_url(self, bucket: str, object_key: str, expires: int = 3600) -> str:
        fp = self._bucket_dir(bucket) / object_key
        return f"file:///{fp.as_posix()}"

    def delete_task_objects(self, task_id: str) -> None:
        for bucket in settings.all_minio_buckets:
            d = self._bucket_dir(bucket)
            prefix = str(task_id)
            for item in list(d.glob(f"{prefix}*")):
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(str(item))
                except OSError as e:
                    logger.warning(f"Local cleanup failed: {item} | {e}")


# 全局单例
local_storage = LocalStorageClient()
