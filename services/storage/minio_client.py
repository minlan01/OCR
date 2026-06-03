"""
MinIO 存储客户端
管理文件上传、下载、删除、预签名 URL
"""
from __future__ import annotations

import io
from typing import Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from config.settings import settings


class MinioClient:
    """MinIO 客户端封装"""

    def __init__(self):
        self._client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            import urllib3
            # 设置 HTTP 超时防止挂起（连接 5s，读取 30s）
            http_client = urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=5.0, read=30.0),
                retries=urllib3.Retry(total=3, backoff_factor=0.5),
            )
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                http_client=http_client,
            )
        return self._client

    def ping(self) -> bool:
        """检查 MinIO 连接"""
        try:
            self.client.list_buckets()
            return True
        except Exception as e:
            logger.warning(f"MinIO ping failed: {e}")
            return False

    def ensure_buckets(self) -> None:
        """确保所有需要的 bucket 存在"""
        for bucket in settings.all_minio_buckets:
            self._ensure_bucket(bucket)

    def _ensure_bucket(self, bucket_name: str) -> None:
        """确保单个 bucket 存在"""
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info(f"Created MinIO bucket: {bucket_name}")
            else:
                logger.debug(f"MinIO bucket exists: {bucket_name}")
        except S3Error as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            raise

    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> int:
        """上传字节数据到 MinIO，返回文件大小"""
        try:
            result = self.client.put_object(
                bucket_name=bucket,
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            logger.debug(f"Uploaded {object_key} to {bucket} ({len(data)} bytes)")
            return len(data)
        except S3Error as e:
            logger.error(f"MinIO upload failed: {object_key} -> {bucket} | {e}")
            raise

    def upload_file(
        self,
        bucket: str,
        object_key: str,
        file_path: str,
        content_type: str = "application/octet-stream",
    ) -> int:
        """上传本地文件到 MinIO"""
        import os

        try:
            file_size = os.path.getsize(file_path)
            self.client.fput_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=file_path,
                content_type=content_type,
            )
            logger.debug(f"Uploaded file {file_path} -> {bucket}/{object_key} ({file_size} bytes)")
            return file_size
        except S3Error as e:
            logger.error(f"MinIO file upload failed: {file_path} -> {bucket} | {e}")
            raise

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        """从 MinIO 下载文件为字节"""
        try:
            response = self.client.get_object(bucket_name=bucket, object_name=object_key)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"MinIO download failed: {bucket}/{object_key} | {e}")
            raise

    def download_file(self, bucket: str, object_key: str, file_path: str) -> None:
        """从 MinIO 下载文件到本地"""
        try:
            self.client.fget_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=file_path,
            )
            logger.debug(f"Downloaded {bucket}/{object_key} -> {file_path}")
        except S3Error as e:
            logger.error(f"MinIO file download failed: {bucket}/{object_key} -> {file_path} | {e}")
            raise

    def delete_object(self, bucket: str, object_key: str) -> None:
        """删除 MinIO 对象"""
        try:
            self.client.remove_object(bucket_name=bucket, object_name=object_key)
            logger.debug(f"Deleted {bucket}/{object_key}")
        except S3Error as e:
            logger.warning(f"MinIO delete failed (non-critical): {bucket}/{object_key} | {e}")

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        """删除 MinIO 中指定前缀下的所有对象，返回删除数量"""
        deleted = 0
        try:
            objects = self.client.list_objects(bucket_name=bucket, prefix=prefix, recursive=True)
            for obj in objects:
                try:
                    self.client.remove_object(bucket_name=bucket, object_name=obj.object_name)
                    deleted += 1
                except S3Error as e:
                    logger.warning(f"MinIO delete failed: {bucket}/{obj.object_name} | {e}")
        except S3Error as e:
            logger.warning(f"MinIO list objects failed: {bucket}/{prefix} | {e}")
        if deleted > 0:
            logger.info(f"Deleted {deleted} objects under {bucket}/{prefix}")
        return deleted

    def object_exists(self, bucket: str, object_key: str) -> bool:
        """检查对象是否存在"""
        try:
            self.client.stat_object(bucket_name=bucket, object_name=object_key)
            return True
        except S3Error:
            return False

    def get_presigned_url(self, bucket: str, object_key: str, expires: int = 3600) -> str:
        """生成预签名下载 URL"""
        try:
            return self.client.presigned_get_object(
                bucket_name=bucket,
                object_name=object_key,
                expires=expires,
            )
        except S3Error as e:
            logger.error(f"MinIO presigned URL failed: {bucket}/{object_key} | {e}")
            raise

    def delete_task_objects(self, task_id: str) -> None:
        """删除某个任务的所有 MinIO 对象"""
        for bucket in settings.all_minio_buckets:
            prefix = f"{task_id}"
            try:
                objects = self.client.list_objects(bucket, prefix=prefix, recursive=True)
                for obj in objects:
                    self.delete_object(bucket, obj.object_name)
            except S3Error as e:
                logger.warning(f"Error listing objects for cleanup: {bucket}/{prefix} | {e}")


# 全局存储客户端单例
# 根据 storage_backend 自动选择 MinIO 或本地存储
if settings.storage_backend == "local":
    from services.storage.local_storage import local_storage as minio_client  # noqa: F811
    logger.info("Storage backend: local filesystem")
else:
    minio_client = MinioClient()
