"""callback 单元测试 — 业务回调 HTTP 通知"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.exporter.callback import send_callback


@pytest.mark.asyncio
async def test_send_callback_success():
    """成功回调应返回 True"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok = await send_callback("https://example.com/webhook", {"task_id": "1"})

    assert ok is True


@pytest.mark.asyncio
async def test_send_callback_network_error():
    """网络错误应返回 False 而非抛异常"""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.side_effect = ConnectionError("refused")

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok = await send_callback("https://example.com/webhook", {"task_id": "1"})

    assert ok is False


@pytest.mark.asyncio
async def test_send_callback_http_error():
    """HTTP 非 2xx 响应应返回 False"""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("500 Server Error")

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok = await send_callback("https://example.com/webhook", {"task_id": "1"})

    assert ok is False


@pytest.mark.asyncio
async def test_send_callback_timeout():
    """超时应返回 False"""
    from config.settings import settings

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.side_effect = TimeoutError("timeout")

    with patch("httpx.AsyncClient", return_value=mock_client):
        ok = await send_callback("https://example.com/webhook", {"task_id": "1"})

    assert ok is False


@pytest.mark.asyncio
async def test_send_callback_posts_correct_url():
    """应 POST 到正确的 URL"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        await send_callback("https://api.example.com/v1/scan-callback", {"task_id": "abc"})

    call_args = mock_client.__aenter__.return_value.post.call_args
    assert call_args[0][0] == "https://api.example.com/v1/scan-callback"


@pytest.mark.asyncio
async def test_send_callback_posts_json_data():
    """应 POST JSON 任务数据"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post.return_value = mock_response

    task_data = {
        "task_id": "uuid-001",
        "status": "completed",
        "filename": "report.pdf",
        "page_count": 10,
        "confidence_avg": 0.92,
        "structure_score": 0.88,
        "heading_count": 5,
        "paragraph_count": 42,
        "table_count": 3,
        "completed_at": "2026-01-01T00:00:00",
    }

    with patch("httpx.AsyncClient", return_value=mock_client):
        await send_callback("https://example.com/webhook", task_data)

    call_kwargs = mock_client.__aenter__.return_value.post.call_args
    assert call_kwargs[1]["json"] == task_data
