"""
案件级并发控制器
================
基于 Redis 的分布式信号量，限制同时处理的案件数量。

防止多人同时使用时 CPU/内存过载导致服务器 OOM 宕机。
当超过并发上限时，新任务会排队等待（Celery retry），而不是硬失败。

支持租户级配额：每个租户有独立的并发上限，防止单租户挤占全局资源。
全局配额通过 try_acquire_case() 控制；
租户配额通过 try_acquire_tenant(tenant_id) / release_tenant(tenant_id) 控制。
"""
from __future__ import annotations

import redis
from loguru import logger
from config.settings import settings

# ─── 常量 ──────────────────────────────────────────────────────────────────

# 全局最大并发数，可通过 settings 配置覆盖
_MAX_CONCURRENT_CASES: int = getattr(settings, 'max_concurrent_cases', 3)

# 每个租户的最大并发数（防止单租户挤占全局资源）
_MAX_CONCURRENT_PER_TENANT: int = getattr(settings, 'max_concurrent_per_tenant', 2)

# Redis keys
_KEY = "scanstruct:concurrent_case_count"
_TENANT_KEY_PREFIX = "scanstruct:concurrent_tenant:"  # + tenant_id

# 兜底过期时间（秒）— 防止 worker 异常退出后计数器永远不归零
_KEY_TTL: int = 7200  # 2小时


# Lua 脚本：原子化 acquire（incr → 检查 → 超限则 decr 回滚）
# 保证 incr+decr 不会被打断，消除竞态：
#   返回 >0 = 成功获取（返回当前值），返回 0 = 已满
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


# ─── 全局并发控制 ──────────────────────────────────────────────────────────

def try_acquire_case() -> bool:
    """尝试获取案件处理许可（原子操作）。

    Returns:
        True  — 获得许可，可以开始处理
        False — 系统繁忙，超过并发上限，应排队等待
    """
    try:
        r = _get_redis()
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
        logger.warning(f"[并发控制] Redis 异常，降级放行: {e}")
        return True


def release_case() -> None:
    """释放案件处理许可。必须在 try/finally 中调用。"""
    try:
        r = _get_redis()
        current = r.decr(_KEY)
        if current < 0:
            r.set(_KEY, 0)
            logger.warning("[并发控制] 计数器异常修正为 0")
        else:
            logger.info(f"[并发控制] 释放许可，当前 {current}/{_MAX_CONCURRENT_CASES}")
    except redis.RedisError as e:
        logger.warning(f"[并发控制] Redis 释放异常（忽略）: {e}")


# ─── 租户级并发控制 ────────────────────────────────────────────────────────

def try_acquire_tenant(tenant_id: str) -> bool:
    """尝试获取租户级并发许可（原子操作）。

    每个租户最多同时处理 _MAX_CONCURRENT_PER_TENANT 个案件，
    防止单租户挤占全局资源。

    Args:
        tenant_id: 租户 UUID 字符串

    Returns:
        True  — 获得许可
        False — 该租户已达并发上限
    """
    if not tenant_id:
        return True  # 无租户（开发模式/API Key 全局模式）不限制

    try:
        r = _get_redis()
        key = f"{_TENANT_KEY_PREFIX}{tenant_id}"
        result = r.eval(_LUA_ACQUIRE, 1, key, _MAX_CONCURRENT_PER_TENANT, _KEY_TTL)
        current = int(result)
        if current > 0:
            logger.info(f"[租户并发] {tenant_id[:8]}.. 获得许可 ({current}/{_MAX_CONCURRENT_PER_TENANT})")
            return True
        logger.warning(
            f"[租户并发] {tenant_id[:8]}.. 已达上限 {_MAX_CONCURRENT_PER_TENANT}，排队等待"
        )
        return False

    except redis.RedisError as e:
        logger.warning(f"[租户并发] Redis 异常，降级放行: {e}")
        return True


def release_tenant(tenant_id: str) -> None:
    """释放租户级并发许可。"""
    if not tenant_id:
        return
    try:
        r = _get_redis()
        key = f"{_TENANT_KEY_PREFIX}{tenant_id}"
        current = r.decr(key)
        if current < 0:
            r.set(key, 0)
    except redis.RedisError as e:
        logger.warning(f"[租户并发] Redis 释放异常（忽略）: {e}")


# ─── 查询工具 ──────────────────────────────────────────────────────────────

def get_concurrent_count() -> int:
    """查询当前全局正在处理的案件数（调试用）"""
    try:
        r = _get_redis()
        val = r.get(_KEY)
        return int(val) if val else 0
    except redis.RedisError:
        return -1


def get_tenant_concurrent_count(tenant_id: str) -> int:
    """查询某租户当前正在处理的案件数"""
    if not tenant_id:
        return 0
    try:
        r = _get_redis()
        val = r.get(f"{_TENANT_KEY_PREFIX}{tenant_id}")
        return int(val) if val else 0
    except redis.RedisError:
        return -1
