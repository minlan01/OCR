"""
健康检查路由
GET /api/v1/health
"""
from __future__ import annotations

import platform
import time

from fastapi import APIRouter
from loguru import logger
from redis import Redis
from redis.exceptions import RedisError

from api.schemas.common import HealthResponse, PingResponse
from config.settings import settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """系统健康检查"""
    result = HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )

    # 检查数据库
    try:
        from sqlalchemy import text
        from db.session import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result.db = "ok"
    except Exception as e:
        result.db = "unhealthy"
        result.status = "degraded"
        logger.warning(f"DB health check failed: {e}")

    # 检查 Redis
    try:
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        r.close()
        result.redis = "ok"
    except RedisError as e:
        result.redis = "unhealthy"
        result.status = "degraded"
        logger.warning(f"Redis health check failed: {e}")

    # 检查 MinIO
    try:
        from services.storage.minio_client import minio_client
        if minio_client.ping():
            result.minio = "ok"
        else:
            result.minio = "unreachable"
            result.status = "degraded"
    except Exception as e:
        result.minio = "unhealthy"
        result.status = "degraded"

    return result


@router.get("/ping", response_model=PingResponse)
async def ping():
    """轻量 ping"""
    return PingResponse(ping="pong", time=time.time(), host=platform.node())
