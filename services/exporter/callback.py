"""业务回调通知 — HTTP POST 结果到业务方

安全措施:
- 校验回调 URL 协议（仅 http/https）
- 阻止内网/私有 IP 地址，防止 SSRF
- 使用 httpx 超时控制
"""
from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx
from loguru import logger
from config.settings import settings

# 内网/私有/保留 IP 地址段 — 禁止作为回调目标
_PRIVATE_NETWORKS = [
    ipaddress.IPv4Network("127.0.0.0/8"),       # Loopback
    ipaddress.IPv4Network("10.0.0.0/8"),        # Class A private
    ipaddress.IPv4Network("172.16.0.0/12"),     # Class B private
    ipaddress.IPv4Network("192.168.0.0/16"),    # Class C private
    ipaddress.IPv4Network("169.254.0.0/16"),    # Link-local
    ipaddress.IPv4Network("0.0.0.0/8"),         # Current network
    ipaddress.IPv4Network("100.64.0.0/10"),     # CGNAT (RFC 6598)
    ipaddress.IPv4Network("198.18.0.0/15"),     # Benchmarking (RFC 2544)
    ipaddress.IPv6Network("::1/128"),           # IPv6 loopback
    ipaddress.IPv6Network("fc00::/7"),          # IPv6 unique local
    ipaddress.IPv6Network("fe80::/10"),         # IPv6 link-local
]


def validate_callback_url(url: str) -> str:
    """校验回调 URL 安全性，防止 SSRF 攻击

    检查规则:
    1. 协议必须为 http 或 https
    2. 必须有 hostname
    3. hostname 不能解析到内网/私有 IP

    Args:
        url: 待校验的回调 URL

    Returns:
        校验通过的 URL（原样返回）

    Raises:
        ValueError: URL 不安全
    """
    if not url:
        raise ValueError("Callback URL must not be empty")

    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError(f"Invalid callback URL format: {url!r}")

    # 规则 1: 仅允许 http/https
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Callback URL scheme must be http or https, got: {parsed.scheme!r}"
        )

    # 规则 2: 必须有 hostname
    if not parsed.hostname:
        raise ValueError("Callback URL must include a hostname")

    # 规则 3: 阻止内网/私有 IP
    # 注意: 域名形式的 URL 不在此处解析，存在 DNS rebinding 风险
    # 生产环境应配合网络层防火墙（如 iptables/安全组）做出站白名单
    try:
        addr = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        # hostname 是域名而非 IP 地址，允许通过
        # 注意: DNS rebinding 风险应由网络层防火墙覆盖
        pass
    else:
        # hostname 是 IP 地址，检查是否为私有/保留地址
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                raise ValueError(
                    f"Callback URL targets private/reserved IP address: {parsed.hostname!r}"
                )

    return url


async def send_callback(callback_url: str, task_data: dict) -> bool:
    """向业务方发送 HTTP POST 回调通知

    Args:
        callback_url: 业务方回调地址（已通过 validate_callback_url 校验）
        task_data: 处理结果数据，包含 task_id、status、structured 等字段

    Returns:
        True 表示回调成功，False 表示失败（网络错误、非 2xx 响应等）
    """
    # 安全校验（纵深防御：即使上层已校验，此处再次检查）
    try:
        validate_callback_url(callback_url)
    except ValueError as e:
        logger.error(f"Callback URL rejected: {e}")
        return False

    retry_delays = settings.callback_retry_delays or []
    max_attempts = 1 + len(retry_delays)

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=settings.callback_timeout_seconds) as client:
                resp = await client.post(callback_url, json=task_data)
                resp.raise_for_status()
                logger.info(f"Callback sent successfully (attempt {attempt + 1}/{max_attempts})")
                return True
        except Exception:
            if attempt < max_attempts - 1:
                delay = retry_delays[attempt]
                logger.warning(f"Callback attempt {attempt + 1} failed, retrying in {delay}s")
                await asyncio.sleep(delay)
            else:
                logger.warning(f"Callback failed after {max_attempts} attempts")
                return False
    return False
