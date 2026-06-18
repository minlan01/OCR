"""
MinIO 存储客户端
管理文件上传、下载、删除、预签名 URL
支持大文件流式分片上传 + 重试
"""
from __future__ import annotations

import io
import os
import time
from typing import Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from config.settings import settings


class MinioClient:
    """MinIO 客户端封装"""

    # 大文件分片阈值和分片大小
    MULTIPART_THRESHOLD = 100 * 1024 * 1024   # 100MB 以上走分片
    PART_SIZE = 50 * 1024 * 1024              # 每片 50MB
    MAX_RETRIES = 3                            # 上传最大重试次数
    RETRY_DELAYS = [1.0, 2.0, 4.0]            # 重试间隔（秒）

    def __init__(self):
        self._client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            import urllib3
            # 设置 HTTP 超时防止挂起（连接 5s，读取 30s）
            # maxsize=10: 连接池大小调大，避免并发下载时 "Connection pool is full" 丢弃连接
            http_client = urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=5.0, read=30.0),
                retries=urllib3.Retry(total=3, backoff_factor=0.5),
                maxsize=10,
            )
            _minio_secret = settings.minio_secret_key
            if hasattr(_minio_secret, 'get_secret_value'):
                _minio_secret = _minio_secret.get_secret_value()
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=_minio_secret,
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

    # ────────────────────────────────────────────
    # 上传方法
    # ────────────────────────────────────────────

    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> int:
        """上传字节数据到 MinIO，返回文件大小（带重试）"""
        return self._upload_with_retry(
            lambda: self.client.put_object(
                bucket_name=bucket,
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            ),
            bucket=bucket,
            object_key=object_key,
            size=len(data),
        )

    def upload_file(
        self,
        bucket: str,
        object_key: str,
        file_path: str,
        content_type: str = "application/octet-stream",
    ) -> int:
        """上传本地文件到 MinIO（适合大文件，使用 fput_object 分片上传）"""
        file_size = os.path.getsize(file_path)
        return self._upload_with_retry(
            lambda: self.client.fput_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=file_path,
                content_type=content_type,
                part_size=self.PART_SIZE,  # 大文件自动分片
            ),
            bucket=bucket,
            object_key=object_key,
            size=file_size,
        )

    def upload_streaming(
        self,
        bucket: str,
        object_key: str,
        data_stream: io.IOBase,
        content_type: str = "application/octet-stream",
        known_size: Optional[int] = None,
    ) -> int:
        """流式上传到 MinIO，适合大文件（内存恒定）

        Args:
            data_stream: 可读的文件流对象
            known_size: 已知的文件大小（如果不确定传 None，MinIO 会使用分片上传）
        """
        size = known_size
        if size is None:
            # 尝试获取流大小
            try:
                pos = data_stream.tell()
                data_stream.seek(0, 2)  # seek to end
                size = data_stream.tell()
                data_stream.seek(pos)  # seek back
            except (OSError, AttributeError):
                size = -1  # 未知大小，MinIO 会走分片上传

        def _do_upload():
            self.client.put_object(
                bucket_name=bucket,
                object_name=object_key,
                data=data_stream,
                length=size if size > 0 else -1,  # -1 触发分片上传
                content_type=content_type,
                part_size=self.PART_SIZE if (size is None or size < 0 or size >= self.MULTIPART_THRESHOLD) else 0,
            )

        return self._upload_with_retry(
            _do_upload,
            bucket=bucket,
            object_key=object_key,
            size=size if size and size > 0 else 0,
        )

    def _upload_with_retry(
        self,
        upload_fn,
        bucket: str,
        object_key: str,
        size: int = 0,
    ) -> int:
        """带指数退避重试的上传封装

        Args:
            upload_fn: 执行上传的回调函数
            bucket: 桶名
            object_key: 对象键
            size: 文件大小（用于日志）
        Returns:
            文件大小
        """
        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                import time as _time
                start = _time.monotonic()
                upload_fn()
                elapsed = _time.monotonic() - start
                logger.info(
                    f"MinIO upload OK: {bucket}/{object_key} "
                    f"({size:,} bytes, {elapsed:.1f}s, attempt {attempt + 1})"
                )
                return size
            except (S3Error, Exception) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAYS[attempt] if attempt < len(self.RETRY_DELAYS) else 4.0
                    logger.warning(
                        f"MinIO upload failed (attempt {attempt + 1}/{self.MAX_RETRIES + 1}): "
                        f"{bucket}/{object_key} | {type(e).__name__}: {e} | retry in {delay}s"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"MinIO upload FAILED after {self.MAX_RETRIES + 1} attempts: "
                        f"{bucket}/{object_key} | {type(e).__name__}: {e}"
                    )
        raise last_error  # type: ignore[misc]

    # ────────────────────────────────────────────
    # 下载方法
    # ────────────────────────────────────────────

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        """从 MinIO 下载文件为字节"""
        response = None
        try:
            response = self.client.get_object(bucket_name=bucket, object_name=object_key)
            data = response.read()
            return data
        except S3Error as e:
            logger.error(f"MinIO download failed: {bucket}/{object_key} | {e}")
            raise
        finally:
            # 无论成功还是异常都确保释放连接
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

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

    # ────────────────────────────────────────────
    # 删除方法
    # ────────────────────────────────────────────

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

    # ────────────────────────────────────────────
    # 其他方法
    # ────────────────────────────────────────────

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
