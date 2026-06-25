"""
Redis Stream 实时推送
将处理完成的结构化结果通过 Redis Pub/Sub 推送给订阅方

使用模块级连接池避免每次创建新连接，提升性能并减少资源消耗。
publish 函数自动检测事件循环上下文，在异步管线中用 async publish，
在同步 Celery 代码中用同步 publish。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
import redis.asyncio as aioredis

from config.settings import settings


# 模块级连接池（懒加载）
_pool: aioredis.ConnectionPool | None = None
_sync_redis: redis.Redis | None = None  # 同步 Redis 用于 Celery worker


def _get_pool() -> aioredis.ConnectionPool:
    """获取异步 Redis 连接池（全局单例）"""
    global _pool
    if _pool is None:
        redis_url = settings.redis_url_with_auth
        _pool = aioredis.ConnectionPool.from_url(
            redis_url,
            max_connections=10,
            socket_connect_timeout=2,
        )
        logger.debug("Redis connection pool created | max_connections=10")
    return _pool


def _get_redis() -> aioredis.Redis:
    """获取异步 Redis 连接（从连接池）"""
    return aioredis.Redis(connection_pool=_get_pool())


def _get_sync_redis() -> "redis.Redis":
    """获取同步 Redis 连接（Celery worker 线程中使用）"""
    global _sync_redis
    if _sync_redis is None:
        import redis as sync_redis
        _sync_redis = sync_redis.from_url(
            settings.redis_url_with_auth,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )
    return _sync_redis


def _is_in_event_loop() -> bool:
    """检测当前是否在运行的事件循环中"""
    try:
        asyncio.get_running_event_loop()
        return True
    except RuntimeError:
        return False


def publish_result(
    task_id: str,
    result: dict[str, Any],
    channel_prefix: str = "scanstruct:result",
) -> bool:
    """发布结果到 Redis Pub/Sub（自动选择同步/异步）"""
    channel = f"{channel_prefix}:{task_id}"
    payload = json.dumps(result, ensure_ascii=False, default=str)

    try:
        if _is_in_event_loop():
            # 在异步上下文中：用同步 Redis 避免阻塞事件循环
            _get_sync_redis().publish(channel, payload)
        else:
            # 在 Celery worker 同步线程中：用同步 Redis
            _get_sync_redis().publish(channel, payload)
        logger.debug(f"Published result to '{channel}' ({len(payload)} bytes)")
        return True
    except Exception as e:
        logger.error(f"Failed to publish result to '{channel}': {e}")
        return False


def publish_progress(
    task_id: str,
    step_name: str,
    status: str,
    progress: float,
    channel_prefix: str = "scanstruct:progress",
) -> bool:
    """发布进度到 Redis Pub/Sub（自动选择同步/异步）"""
    channel = f"{channel_prefix}:{task_id}"
    payload = json.dumps({
        "task_id": task_id,
        "step": step_name,
        "status": status,
        "progress": min(max(progress, 0.0), 100.0),
    }, ensure_ascii=False)

    try:
        _get_sync_redis().publish(channel, payload)
        return True
    except Exception as e:
        logger.warning(f"Failed to publish progress: {e}")
        return False
