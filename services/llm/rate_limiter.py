"""
LLM 分布式限流器
================
基于 Redis 的分布式信号量，控制跨 Worker 的 LLM API 调用总数。

特性：
1. 全局并发控制：text(5) / ocr(10) / flash(15)
2. 超时等待：请求超出并发时排队等待，而非直接失败
3. 信号量 TTL 防泄漏：每个许可 60s 过期自动释放
4. 429 自适应降级：检测到频繁 429 时自动减少并发上限
5. 429 指数退避重试：自动重试最多 3 次

用法：
    limiter = LLMRateLimiter()

    # 获取许可
    if await limiter.acquire("text", timeout=30.0):
        try:
            result = await call_llm_api(...)
        finally:
            await limiter.release("text")

    # 或者使用上下文管理器
    async with limiter.semaphore("text"):
        result = await call_llm_api(...)
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional

from loguru import logger

from config.settings import settings


# 默认并发上限（保守值，适合4核8G服务器10人并发场景）
DEFAULT_LIMITS = {
    "text": 2,   # 文本深度分析（最耗API配额）
    "ocr": 5,    # OCR 识别
    "flash": 8,  # 快速模型（分类/提取）
}

# 信号量键前缀
SEMAPHORE_PREFIX = "llm_sem:"
# 每个许可的 TTL（秒），防止进程崩溃后信号量泄漏
PERMIT_TTL = 60
# 429 降级检查窗口（秒）
DEGRADATION_WINDOW = 60
# 429 降级阈值（窗口内 429 次数超过此值则降级）
DEGRADATION_THRESHOLD = 5


class LLMRateLimiter:
    """基于 Redis 的分布式 LLM 调用限流器"""

    def __init__(self):
        self._limits = {
            "text": settings.llm_rate_limiter_text,
            "ocr": settings.llm_rate_limiter_ocr,
            "flash": settings.llm_rate_limiter_flash,
        }
        self._redis = None

    @property
    def redis(self):
        """延迟初始化 Redis 连接（异步版，避免阻塞事件循环）"""
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
        return self._redis

    def _key(self, model_type: str) -> str:
        """获取信号量键"""
        return f"{SEMAPHORE_PREFIX}{model_type}"

    def _counter_key(self, model_type: str) -> str:
        """获取 429 计数器键"""
        return f"{SEMAPHORE_PREFIX}{model_type}:429"

    async def get_limit(self, model_type: str) -> int:
        """获取当前并发上限（可能被降级，异步）"""
        base = self._limits.get(model_type, DEFAULT_LIMITS.get(model_type, 5))
        # 检查是否需要降级
        try:
            count = await self.redis.get(self._counter_key(model_type))
            if count and int(count) >= DEGRADATION_THRESHOLD:
                # 降级到基础值的一半（最少 1）
                degraded = max(1, base // 2)
                logger.warning(
                    f"LLM rate limiter degradation: {model_type} "
                    f"{base} → {degraded} (429 count: {count})"
                )
                return degraded
        except Exception:
            pass
        return base

    async def acquire(self, model_type: str, timeout: float = 60.0) -> bool:
        """获取调用许可

        Args:
            model_type: 模型类型 (text/ocr/flash)
            timeout: 最大等待时间（秒），超时返回 False

        Returns:
            True 表示获取成功，False 表示超时
        """
        key = self._key(model_type)
        limit = await self.get_limit(model_type)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                # 原子操作：用 Lua 脚本实现 INCR + TTL 设置 + 上限检查（防止竞态）
                # Lua 脚本保证三步原子执行，避免 INCR 和 EXPIRE 分开导致计数器泄漏
                lua_script = """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local ttl = tonumber(ARGV[2])
                local current = redis.call('INCR', key)
                if current == 1 then
                    redis.call('EXPIRE', key, ttl)
                end
                if current <= limit then
                    return current
                else
                    redis.call('DECR', key)
                    return -1
                end
                """
                current = await self.redis.eval(lua_script, 1, key, limit, PERMIT_TTL)
                if isinstance(current, int) and current >= 1:
                    logger.debug(f"LLM semaphore acquired: {model_type} ({current}/{limit})")
                    return True
                else:
                    # 超出上限（Lua 返回 -1），等待重试
                    await asyncio.sleep(min(1.0, deadline - time.monotonic()))
            except Exception as e:
                logger.warning(f"LLM semaphore acquire error: {e}")
                # Redis 错误时放行（宁可多调也不要锁死）
                return True

        logger.warning(f"LLM semaphore acquire timeout: {model_type} (waited {timeout}s)")
        return False

    async def release(self, model_type: str) -> None:
        """释放调用许可（异步）"""
        key = self._key(model_type)
        try:
            current = await self.redis.decr(key)
            # 防止计数器变为负数
            if current < 0:
                await self.redis.set(key, 0)
                logger.warning(f"LLM semaphore underflow: {model_type}, reset to 0")
        except Exception as e:
            logger.warning(f"LLM semaphore release error: {e}")

    async def record_429(self, model_type: str) -> None:
        """记录一次 429 错误（用于自适应降级，异步）"""
        counter_key = self._counter_key(model_type)
        try:
            # 原子操作：INCR + EXPIRE（用 Lua 防竞态）
            lua_script = """
            local key = KEYS[1]
            local ttl = tonumber(ARGV[1])
            local count = redis.call('INCR', key)
            if count == 1 then
                redis.call('EXPIRE', key, ttl)
            end
            return count
            """
            count = await self.redis.eval(lua_script, 1, counter_key, DEGRADATION_WINDOW)
            logger.info(f"LLM 429 recorded: {model_type} (count: {count}/{DEGRADATION_THRESHOLD})")
        except Exception as e:
            logger.warning(f"LLM 429 record error: {e}")

    @asynccontextmanager
    async def semaphore(self, model_type: str, timeout: float = 60.0):
        """上下文管理器方式使用信号量

        Usage:
            async with limiter.semaphore("text"):
                result = await call_llm_api(...)
        """
        acquired = await self.acquire(model_type, timeout=timeout)
        if not acquired:
            raise RuntimeError(f"LLM rate limiter timeout: {model_type}")
        try:
            yield
        finally:
            await self.release(model_type)


# 全局单例
_rate_limiter: Optional[LLMRateLimiter] = None


def get_rate_limiter() -> LLMRateLimiter:
    """获取全局限流器单例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = LLMRateLimiter()
    return _rate_limiter


async def call_llm_with_retry(
    call_fn,
    model_type: str = "text",
    max_retries: int = 3,
    base_delay: float = 2.0,
):
    """带限流 + 429 重试的 LLM 调用封装

    Args:
        call_fn: 异步调用函数
        model_type: 模型类型 (text/ocr/flash)
        max_retries: 最大重试次数
        base_delay: 基础重试延迟（秒）

    Returns:
        调用函数的返回值
    """
    limiter = get_rate_limiter()

    async with limiter.semaphore(model_type):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return await call_fn() if asyncio.iscoroutinefunction(call_fn) else call_fn()
            except Exception as e:
                error_str = str(e)
                is_429 = "429" in error_str or "rate" in error_str.lower() or "throttl" in error_str.lower()

                if is_429 and attempt < max_retries:
                    await limiter.record_429(model_type)
                    delay = base_delay * (2 ** attempt)  # 指数退避: 2s → 4s → 8s
                    logger.warning(
                        f"LLM 429 error (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{model_type} | retry in {delay}s | {type(e).__name__}"
                    )
                    await asyncio.sleep(delay)
                else:
                    last_error = e
                    if is_429:
                        await limiter.record_429(model_type)
                    logger.error(
                        f"LLM call failed after {attempt + 1} attempts: "
                        f"{model_type} | {type(e).__name__}: {e}"
                    )
                    raise

        raise last_error  # type: ignore[misc]
