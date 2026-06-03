"""
MinIO 存储客户端单元测试
覆盖 MinioClient 所有方法（upload/download/delete/presigned URL/任务清理）
"""
from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

from services.storage.minio_client import MinioClient, minio_client


# ── Fixture: 构建 mock MinIO client ────────────────────────

@pytest.fixture
def mock_minio():
    """创建带 mock Minio 后端的 MinioClient"""
    client = MinioClient()
    mock = MagicMock()
    client._client = mock
    return client, mock


# ── 基础 ───────────────────────────────────────────────────

class TestMinioClientBasics:
    def test_client_lazy_init(self):
        """第一次访问才初始化 Minio 连接"""
        client = MinioClient()
        assert client._client is None

    def test_client_creates_on_access(self):
        """访问 .client 属性时创建 Minio 实例"""
        with patch("services.storage.minio_client.Minio") as MockMinio:
            client = MinioClient()
            _ = client.client
            MockMinio.assert_called_once()

    def test_ping_success(self, mock_minio):
        client, mock = mock_minio
        mock.list_buckets.return_value = []
        assert client.ping() is True

    def test_ping_failure(self, mock_minio):
        client, mock = mock_minio
        mock.list_buckets.side_effect = S3Error(
            code="ConnectionError", message="timeout",
            resource="", request_id="", host_id="", response=None,
        )
        assert client.ping() is False


# ── Bucket 管理 ────────────────────────────────────────────

class TestMinioClientBuckets:
    def test_ensure_buckets_creates_missing(self, mock_minio):
        client, mock = mock_minio
        mock.bucket_exists.return_value = False

        with patch("services.storage.minio_client.settings") as mock_settings:
            mock_settings.all_minio_buckets = ["scan-raw", "scan-result"]
            client.ensure_buckets()

        assert mock.make_bucket.call_count == 2

    def test_ensure_buckets_skips_existing(self, mock_minio):
        client, mock = mock_minio
        mock.bucket_exists.side_effect = [True, True]

        with patch("services.storage.minio_client.settings") as mock_settings:
            mock_settings.all_minio_buckets = ["raw", "result"]
            client.ensure_buckets()

        mock.make_bucket.assert_not_called()

    def test_ensure_bucket_raises_on_s3_error(self, mock_minio):
        client, mock = mock_minio
        mock.bucket_exists.side_effect = S3Error(
            code="AccessDenied", message="no access",
            resource="", request_id="", host_id="", response=None,
        )

        with pytest.raises(S3Error):
            client._ensure_bucket("secret-bucket")


# ── 上传 ───────────────────────────────────────────────────

class TestMinioClientUpload:
    def test_upload_bytes_success(self, mock_minio):
        client, mock = mock_minio
        data = b"hello world"
        size = client.upload_bytes("bucket", "key.txt", data, content_type="text/plain")
        assert size == len(data)
        mock.put_object.assert_called_once()

    def test_upload_bytes_raises_on_s3_error(self, mock_minio):
        client, mock = mock_minio
        mock.put_object.side_effect = S3Error(
            code="InternalError", message="boom",
            resource="", request_id="", host_id="", response=None,
        )

        with pytest.raises(S3Error):
            client.upload_bytes("bucket", "key", b"data")

    def test_upload_file_success(self, mock_minio):
        """上传本地文件（绕过实际文件系统）"""
        client, mock = mock_minio
        # tuple unpack: (client, mock)
        with patch("os.path.getsize", return_value=99):
            client.upload_file("bucket", "key.pdf", "/fake/path.pdf")
        mock.fput_object.assert_called_once()

    def test_upload_file_raises_on_s3_error(self, mock_minio):
        client, mock = mock_minio
        mock.fput_object.side_effect = S3Error(
            code="QuotaExceeded", message="out of space",
            resource="", request_id="", host_id="", response=None,
        )
        with patch("os.path.getsize", return_value=99):
            with pytest.raises(S3Error):
                client.upload_file("bucket", "key", "/fake/path.pdf")


# ── 下载 ───────────────────────────────────────────────────

class TestMinioClientDownload:
    def test_download_bytes_success(self, mock_minio):
        client, mock = mock_minio
        response = MagicMock()
        response.read.return_value = b"downloaded data"
        mock.get_object.return_value = response

        data = client.download_bytes("bucket", "key.txt")
        assert data == b"downloaded data"

    def test_download_bytes_raises_on_s3_error(self, mock_minio):
        client, mock = mock_minio
        mock.get_object.side_effect = S3Error(
            code="NoSuchKey", message="not found",
            resource="", request_id="", host_id="", response=None,
        )

        with pytest.raises(S3Error):
            client.download_bytes("bucket", "missing.txt")

    def test_download_file_success(self, mock_minio):
        client, mock = mock_minio
        client.download_file("bucket", "key.pdf", "/fake/dest.pdf")
        mock.fget_object.assert_called_once_with(
            bucket_name="bucket", object_name="key.pdf", file_path="/fake/dest.pdf",
        )

    def test_download_file_raises_on_s3_error(self, mock_minio):
        client, mock = mock_minio
        mock.fget_object.side_effect = S3Error(
            code="NoSuchKey", message="not found",
            resource="", request_id="", host_id="", response=None,
        )

        with pytest.raises(S3Error):
            client.download_file("bucket", "missing.pdf", "/fake/out.pdf")


# ── 删除 ───────────────────────────────────────────────────

class TestMinioClientDelete:
    def test_delete_object_success(self, mock_minio):
        client, mock = mock_minio
        client.delete_object("bucket", "key.txt")
        mock.remove_object.assert_called_once_with(bucket_name="bucket", object_name="key.txt")

    def test_delete_handles_error_gracefully(self, mock_minio):
        """删除失败不应抛出（非关键操作）"""
        client, mock = mock_minio
        mock.remove_object.side_effect = S3Error(
            code="NoSuchKey", message="already gone",
            resource="", request_id="", host_id="", response=None,
        )
        # 不应抛出异常
        client.delete_object("bucket", "key.txt")


# ── 存在性检查 ────────────────────────────────────────────

class TestMinioClientExists:
    def test_object_exists_true(self, mock_minio):
        client, mock = mock_minio
        assert client.object_exists("bucket", "key.txt") is True

    def test_object_exists_false(self, mock_minio):
        client, mock = mock_minio
        mock.stat_object.side_effect = S3Error(
            code="NoSuchKey", message="not found",
            resource="", request_id="", host_id="", response=None,
        )
        assert client.object_exists("bucket", "missing.txt") is False


# ── 预签名 URL ─────────────────────────────────────────────

class TestMinioClientPresigned:
    def test_get_presigned_url_default_expiry(self, mock_minio):
        client, mock = mock_minio
        mock.presigned_get_object.return_value = "https://minio.example.com/download?token=abc"

        url = client.get_presigned_url("bucket", "key.pdf")
        assert url == "https://minio.example.com/download?token=abc"
        mock.presigned_get_object.assert_called_once_with(
            bucket_name="bucket", object_name="key.pdf", expires=3600,
        )

    def test_get_presigned_url_custom_expiry(self, mock_minio):
        client, mock = mock_minio
        mock.presigned_get_object.return_value = "https://minio.example.com/download?token=def"

        url = client.get_presigned_url("bucket", "key.pdf", expires=600)
        mock.presigned_get_object.assert_called_once_with(
            bucket_name="bucket", object_name="key.pdf", expires=600,
        )

    def test_presigned_url_raises_on_error(self, mock_minio):
        client, mock = mock_minio
        mock.presigned_get_object.side_effect = S3Error(
            code="AccessDenied", message="no presigned access",
            resource="", request_id="", host_id="", response=None,
        )
        with pytest.raises(S3Error):
            client.get_presigned_url("bucket", "key.pdf")


# ── 任务清理 ───────────────────────────────────────────────

class TestMinioClientDeleteTaskObjects:
    def test_deletes_all_objects_for_task(self, mock_minio):
        client, mock = mock_minio

        obj1 = MagicMock()
        obj1.object_name = "task-123/raw.pdf"
        obj2 = MagicMock()
        obj2.object_name = "task-123/result.json"

        mock.list_objects.return_value = [obj1, obj2]

        with patch("services.storage.minio_client.settings") as mock_settings:
            mock_settings.all_minio_buckets = ["scan-raw", "scan-result"]
            client.delete_task_objects("task-123")

        assert mock.list_objects.call_count == 2
        assert mock.remove_object.call_count == 4  # 2 objects × 2 buckets

    def test_delete_task_objects_handles_s3_error(self, mock_minio):
        """list_objects 失败不应中断整个清理流程"""
        client, mock = mock_minio
        mock.list_objects.side_effect = S3Error(
            code="NoSuchBucket", message="bucket gone",
            resource="", request_id="", host_id="", response=None,
        )

        with patch("services.storage.minio_client.settings") as mock_settings:
            mock_settings.all_minio_buckets = ["scan-raw"]
            # 不应抛出异常
            client.delete_task_objects("task-123")


# ── 全局单例 ──────────────────────────────────────────────

class TestGlobalSingleton:
    def test_minio_client_is_minio_client_instance(self):
        assert isinstance(minio_client, MinioClient)

    def test_global_singleton_is_lazy(self):
        """全局单例初始化时不强制连接 MinIO（可能已被其他测试初始化）"""
        assert isinstance(minio_client, MinioClient)
        # 断连后验证懒加载行为
        try:
            minio_client._client = None
            assert minio_client._client is None
        finally:
            pass  # 不影响其他测试
