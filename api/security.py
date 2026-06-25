"""
JWT 安全工具 — token 生成/验证 + 密码哈希
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt as _bcrypt
from jose import JWTError, jwt
from loguru import logger
import redis as _redis

from config.settings import settings


def hash_password(password: str) -> str:
    """密码哈希 (bcrypt) — 直接使用 bcrypt 库避免 passlib 兼容问题"""
    pwd_bytes = password.encode("utf-8")
    # bcrypt 限制 72 字节，截断处理
    if len(pwd_bytes) > 72:
        pwd_bytes = pwd_bytes[:72]
    salt = _bcrypt.gensalt()
    return _bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    try:
        pwd_bytes = plain_password.encode("utf-8")
        if len(pwd_bytes) > 72:
            pwd_bytes = pwd_bytes[:72]
        return _bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict[str, Any]) -> str:
    """生成 access token (短期, 30分钟)"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    """生成 refresh token (长期, 7天) — 含 jti 用于轮转/撤销"""
    to_encode = data.copy()
    jti = str(uuid4())
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh", "jti": jti})
    # 将 jti 存入 Redis，TTL = refresh token 有效期
    try:
        r = _redis.from_url(settings.redis_url_with_auth, decode_responses=True, socket_timeout=3)
        r.setex(f"refresh_jti:{jti}", settings.jwt_refresh_token_expire_days * 86400, "valid")
    except Exception as e:
        logger.warning(f"Failed to store refresh jti in Redis: {e}")
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def is_refresh_token_valid(jti: str) -> bool:
    """检查 refresh token 的 jti 是否仍然有效（未被轮转/撤销）"""
    try:
        r = _redis.from_url(settings.redis_url_with_auth, decode_responses=True, socket_timeout=3)
        return bool(r.exists(f"refresh_jti:{jti}"))
    except Exception:
        return True  # Redis 不可用时降级放行


def revoke_refresh_token(jti: str) -> None:
    """撤销 refresh token（从 Redis 中删除 jti）"""
    try:
        r = _redis.from_url(settings.redis_url_with_auth, decode_responses=True, socket_timeout=3)
        r.delete(f"refresh_jti:{jti}")
    except Exception as e:
        logger.warning(f"Failed to revoke refresh jti: {e}")


def decode_token(token: str) -> dict[str, Any] | None:
    """解码 JWT token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode failed: {e}")
        return None
