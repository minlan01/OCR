"""
案件级并发控制器
================
基于 Redis 的分布式信号量，限制同时处理的案件数量。

防止多人同时使用时 CPU/内存过载导致服务器 OOM 宕机。
当超过并发上限时，新任务会排队等待（Celery retry），而不是硬失败。
"""
from __future__ import annotations

import redis
from loguru import logger
from config.settings import settings

# ─── 常量 ──────────────────────────────────────────────────────────────────

# 4核8G 服务器最多同时处理 3 个案件（可调）
_MAX_CONCURRENT_CASES: int = 3

# Redis key
_KEY = "scanstruct:concurrent_case_count"

# 兜底过期时间（秒）— 防止 worker 异常退出后计数器永远不归零
_KEY_TTL: int = 7200  # 2小时


# ─── Redis 连接（懒加载） ──────────────────────────────────────────────────

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    """获取 Redis 连接（懒加载单例）"""
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            settings.redis_url_with_auth,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _redis


# ─── 公开 API ──────────────────────────────────────────────────────────────

def try_acquire_case() -> bool:
    """尝试获取案件处理许可。

    Returns:
        True  — 获得许可，可以开始处理
        False — 系统繁忙，超过并发上限，应排队等待
    """
    try:
        r = _get_redis()
        current = r.incr(_KEY)
        if current == 1:
            # 第一个计数器，设置过期时间作为安全兜底
            r.expire(_KEY, _KEY_TTL)

        if current <= _MAX_CONCURRENT_CASES:
            logger.info(f"[并发控制] 获得处理许可 ({current}/{_MAX_CONCURRENT_CASES})")
            return True

        # 超过上限，回退计数
        r.decr(_KEY)
        logger.warning(
            f"[并发控制] 系统繁忙，当前 {current-1} 个案件在处理，"
            f"上限 {_MAX_CONCURRENT_CASES}，排队等待"
        )
        return False

    except redis.RedisError as e:
        # Redis 不可用时放行（降级策略：宁可多跑也不卡死）
        logger.warning(f"[并发控制] Redis 异常，降级放行: {e}")
        return True


def release_case() -> None:
    """释放案件处理许可。必须在 try/finally 中调用。"""
    try:
        r = _get_redis()
        current = r.decr(_KEY)
        if current < 0:
            # 计数器异常（可能因为 TTL 过期重置），修正为 0
            r.set(_KEY, 0)
            logger.warning("[并发控制] 计数器异常修正为 0")
        else:
            logger.info(f"[并发控制] 释放许可，当前 {current}/{_MAX_CONCURRENT_CASES}")
    except redis.RedisError as e:
        logger.warning(f"[并发控制] Redis 释放异常（忽略）: {e}")


def get_concurrent_count() -> int:
    """查询当前正在处理的案件数（调试用）"""
    try:
        r = _get_redis()
        val = r.get(_KEY)
        return int(val) if val else 0
    except redis.RedisError:
        return -1
