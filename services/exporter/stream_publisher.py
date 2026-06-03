"""
Redis Stream 实时推送
将处理完成的结构化结果通过 Redis Pub/Sub 推送给订阅方

使用模块级连接池避免每次创建新连接，提升性能并减少资源消耗。
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger
import redis.asyncio as aioredis

from config.settings import settings


# 模块级连接池（懒加载）
_pool: aioredis.ConnectionPool | None = None


def _get_pool() -> aioredis.ConnectionPool:
    """获取 Redis 连接池（全局单例）

    Returns:
        aioredis.ConnectionPool: 已初始化的连接池
    """
    global _pool
    if _pool is None:
        redis_url = settings.redis_url_with_auth
        _pool = aioredis.ConnectionPool.from_url(
            redis_url,
            max_connections=10,
            socket_connect_timeout=2,
        )
        logger.debug(f"Redis connection pool created | max_connections=10")
    return _pool


def _get_redis() -> aioredis.Redis:
    """获取 Redis 连接（从连接池）

    Returns:
        aioredis.Redis: 连接到 Redis 的客户端实例
    """
    return aioredis.Redis(connection_pool=_get_pool())


def publish_result(
    task_id: str,
    result: dict[str, Any],
    channel_prefix: str = "scanstruct:result",
) -> bool:
    """
    将结构化处理结果发布到 Redis Pub/Sub 频道

    Args:
        task_id: 任务 UUID
        result: 结构化处理结果字典
        channel_prefix: 频道前缀，默认 scanstruct:result

    Returns:
        True 发布成功，False 发布失败
    """
    channel = f"{channel_prefix}:{task_id}"
    payload = json.dumps(result, ensure_ascii=False, default=str)

    try:
        r = _get_redis()
        r.publish(channel, payload)
        logger.debug(f"Published result to channel '{channel}' ({len(payload)} bytes)")
        return True
    except Exception as e:
        logger.error(f"Failed to publish result to channel '{channel}': {e}")
        return False


def publish_progress(
    task_id: str,
    step_name: str,
    status: str,
    progress: float,
    channel_prefix: str = "scanstruct:progress",
) -> bool:
    """
    发布任务进度更新到 Redis Pub/Sub

    Args:
        task_id: 任务 UUID
        step_name: 当前步骤名称
        status: 步骤状态
        progress: 进度百分比 (0-100)
        channel_prefix: 频道前缀

    Returns:
        True 发布成功
    """
    channel = f"{channel_prefix}:{task_id}"
    payload = json.dumps({
        "task_id": task_id,
        "step": step_name,
        "status": status,
        "progress": min(max(progress, 0.0), 100.0),
    }, ensure_ascii=False)

    try:
        r = _get_redis()
        r.publish(channel, payload)
        return True
    except Exception as e:
        logger.warning(f"Failed to publish progress: {e}")
        return False
