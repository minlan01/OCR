"""stream_publisher 单元测试 — Redis Pub/Sub 进度 & 结果推送"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from services.exporter.stream_publisher import publish_progress, publish_result


class TestPublishProgress:
    """进度推送"""

    def test_publishes_valid_payload(self):
        """进度推送应发布合法的 JSON 载荷到正确频道"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            ok = publish_progress("task-001", "ocr", "running", 45.0)

        assert ok is True
        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "scanstruct:progress:task-001"
        data = json.loads(payload)
        assert data["task_id"] == "task-001"
        assert data["step"] == "ocr"
        assert data["status"] == "running"
        assert data["progress"] == 45.0

    def test_progress_clamped_negative(self):
        """负数进度应被 clamp 到 0"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_progress("t1", "step", "ok", -10.0)

        _, payload = mock_redis.publish.call_args[0]
        data = json.loads(payload)
        assert data["progress"] == 0.0

    def test_progress_clamped_above_100(self):
        """超过 100 的进度应被 clamp 到 100"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_progress("t1", "step", "ok", 150.0)

        _, payload = mock_redis.publish.call_args[0]
        data = json.loads(payload)
        assert data["progress"] == 100.0

    def test_returns_false_on_redis_failure(self):
        """Redis 失败时应返回 False 而非抛异常"""
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = ConnectionError("down")
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            ok = publish_progress("t1", "step", "ok", 50.0)

        assert ok is False

    def test_fractional_progress(self):
        """浮点进度值应被保留"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_progress("t1", "step", "ok", 33.333)

        _, payload = mock_redis.publish.call_args[0]
        data = json.loads(payload)
        assert abs(data["progress"] - 33.333) < 0.001

    def test_custom_channel_prefix(self):
        """自定义频道前缀应生效"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_progress("t1", "s1", "ok", 10, channel_prefix="custom:progress")

        channel, _ = mock_redis.publish.call_args[0]
        assert channel == "custom:progress:t1"


class TestPublishResult:
    """结果推送"""

    def test_publishes_result_json(self):
        """结果推送应发布 JSON 序列化的结构化结果"""
        mock_redis = MagicMock()
        result_data = {
            "sections": [{"title": "第一章", "paragraphs": []}],
            "total_sections": 1,
            "source_type": "scan_pdf",
        }

        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            ok = publish_result("task-002", result_data)

        assert ok is True
        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "scanstruct:result:task-002"
        data = json.loads(payload)
        assert data["total_sections"] == 1
        assert data["source_type"] == "scan_pdf"

    def test_non_serializable_values_use_str(self):
        """不可序列化的值应 fallback 到 str()"""
        mock_redis = MagicMock()
        result_data = {"timestamp": MagicMock(__str__=lambda s: "2026-01-01")}

        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            ok = publish_result("t3", result_data)

        assert ok is True
        _, payload = mock_redis.publish.call_args[0]
        assert "2026-01-01" in payload

    def test_returns_false_on_redis_failure(self):
        """Redis 失败时应返回 False"""
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = OSError("no connection")

        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            ok = publish_result("t4", {"key": "value"})

        assert ok is False

    def test_custom_channel_prefix(self):
        """自定义频道前缀应生效"""
        mock_redis = MagicMock()
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_result("t5", {}, channel_prefix="custom:result")

        channel, _ = mock_redis.publish.call_args[0]
        assert channel == "custom:result:t5"

    def test_unicode_content_serialized(self):
        """中文内容应正确序列化"""
        mock_redis = MagicMock()
        result_data = {"title": "第一章 概述", "content": "这是测试内容"}
        with patch("services.exporter.stream_publisher._get_redis", return_value=mock_redis):
            publish_result("t6", result_data)

        _, payload = mock_redis.publish.call_args[0]
        data = json.loads(payload)
        assert data["title"] == "第一章 概述"
