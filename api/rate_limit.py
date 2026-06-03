"""
API 频率限制配置
基于 slowapi，支持按 IP 限流
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局限流器：默认 100 次/分钟
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
