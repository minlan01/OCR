"""
API 频率限制配置
================
SaaS 优化版：基于 slowapi，支持按 IP / 按用户 限流

限流策略:
- 默认全局限流: 100次/分钟（兜底）
- OCR 触发端点: 5次/分钟/用户
- 普通读写端点: 60次/分钟/用户
- 超级管理员豁免
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


def _key_func(request) -> str:
    """限流 key 函数：优先按用户ID，兜底按 IP

    当 JWT 认证生效后，request.state.user_id 存在则按用户限流；
    否则降级为按 IP 限流（兼容当前无认证模式）。
    """
    # 优先使用用户ID（SaaS 模式）
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    # 兜底使用 IP
    return get_remote_address(request)


# 全局限流器：默认 100 次/分钟
limiter = Limiter(key_func=_key_func, default_limits=["100/minute"])
