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


# Lua 脚本：原子化 acquire（incr → 检查 → 超限则 decr 回滚）
# 保证 incr+decr 不会被打断，消除竞态：
#   返回 1 = 成功获取，返回 0 = 已满
_LUA_ACQUIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
if current <= tonumber(ARGV[1]) then
    return current
else
    redis.call('DECR', KEYS[1])
    return 0
end
"""


# ─── Redis 连接（懒加载） ──────────────────────────────────────────────────

_redis: redis.Redis | None = None
_lua_acquire_sha: str | None = None


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
    """尝试获取案件处理许可（原子操作）。

    Returns:
        True  — 获得许可，可以开始处理
        False — 系统繁忙，超过并发上限，应排队等待
    """
    try:
        r = _get_redis()
        # 用 Lua 脚本一次性完成 incr + 检查 + 超限回滚（消除竞态）
        result = r.eval(_LUA_ACQUIRE, 1, _KEY, _MAX_CONCURRENT_CASES, _KEY_TTL)
        current = int(result)
        if current > 0:
            logger.info(f"[并发控制] 获得处理许可 ({current}/{_MAX_CONCURRENT_CASES})")
            return True
        logger.warning(
            f"[并发控制] 系统繁忙，已达上限 {_MAX_CONCURRENT_CASES}，排队等待"
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
