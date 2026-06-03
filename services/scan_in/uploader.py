"""
文件上传服务
将校验通过的 PDF 上传到 MinIO 并创建数据库任务
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from loguru import logger
from sqlalchemy import select

from config.settings import settings
from db.models import ScanTask, ScanFile
from db.session import async_session_factory
from services.storage.minio_client import minio_client


def _compute_file_md5(file_path: Path) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def create_task_from_file(
    file_path: Path,
    scanner_id: str = "watch_folder",
    callback_url: Optional[str] = None,
    metadata: Optional[dict] = None,
    file_size: Optional[int] = None,
    file_md5: Optional[str] = None,
) -> ScanTask:
    """
    从本地文件创建扫描任务：
    1. 计算 MD5 并查重
    2. 上传原始 PDF 到 MinIO
    3. 创建数据库任务记录
    """
    filename = file_path.name
    file_size = file_size or file_path.stat().st_size
    file_md5 = file_md5 or _compute_file_md5(file_path)

    async with async_session_factory() as db:
        # 查重
        stmt = select(ScanTask).where(ScanTask.file_md5 == file_md5)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.info(f"Duplicate file: {filename} (MD5={file_md5}), reusing task {existing.id}")
            return existing

        # 创建任务
        task_id = uuid.uuid4()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        object_key = f"raw/{today}/{task_id}_{quote(filename)}"

        task = ScanTask(
            id=task_id,
            filename=filename,
            scanner_id=scanner_id,
            source_type="watch_folder",
            status="received",
            file_size=file_size,
            file_md5=file_md5,
            original_path=str(file_path),
            callback_url=callback_url,
            metadata_=metadata or {},
        )
        db.add(task)

        # 上传 MinIO
        try:
            minio_client.upload_file(
                bucket=settings.minio_bucket_raw,
                object_key=object_key,
                file_path=str(file_path),
                content_type="application/pdf",
            )
            task.original_path = object_key
        except Exception as e:
            task.status = "failed"
            task.error_message = f"MinIO upload failed: {e}"
            task.error_code = "MINIO_UPLOAD_ERROR"
            await db.commit()
            raise

        # 文件记录
        scan_file = ScanFile(
            task_id=task_id,
            file_type="raw_pdf",
            bucket=settings.minio_bucket_raw,
            object_key=object_key,
            size_bytes=file_size,
        )
        db.add(scan_file)

        await db.commit()
        logger.info(f"Task created: {task_id} <- {filename} ({file_size} bytes)")

        return task
