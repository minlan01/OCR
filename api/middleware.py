"""
API Key 认证中间件
对 /api/v1/admin/* 路径强制要求 X-API-Key 头
如果配置了 API_KEY，则对所有 /api/v1/*（除 health/ping）强制执行
非 API 路径（静态文件、SPA 页面）直接放行，避免与 StaticFiles mount 冲突
"""
from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from config.settings import settings


# 始终豁免认证的路径（健康检查 + 文档）
PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/ping",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
}

# 静态资源扩展名 — 这些请求不触发 API 认证（Swagger UI / ReDoc 等加载的静态文件）
STATIC_EXTENSIONS = {
    ".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".json",
    ".xml", ".txt", ".webmanifest",
}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # ── 非 API 路径直接放行（静态文件、SPA 页面等）──
        # 放在最前面，避免 StaticFiles mount 的请求被拦截
        if not path.startswith("/api"):
            return await call_next(request)

        # ── 公开路径直接放行 ──
        if path in PUBLIC_PATHS or path.startswith("/api/docs") or path.startswith("/api/redoc"):
            return await call_next(request)

        # ── 静态资源文件（API docs 页面加载的 JS/CSS 等）──
        # rpartition 返回 (head, sep, tail) 三元组
        _, _, ext = path.rpartition(".") if "." in path else ("", "", "")
        if ext and f".{ext}" in STATIC_EXTENSIONS:
            return await call_next(request)

        # ── 如果未配置 API_KEY，跳过认证（开发模式）──
        if not settings.api_key_plain:
            return await call_next(request)

        # ── API 路径：配置了 key 时强制认证 ──
        return await self._authenticate(request, call_next)

    async def _authenticate(self, request: Request, call_next):
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")

        if not api_key:
            logger.warning(f"Missing API key for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key", "error_code": "UNAUTHORIZED"},
            )

        if not secrets.compare_digest(api_key, settings.api_key_plain):
            logger.warning(f"Invalid API key for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key", "error_code": "FORBIDDEN"},
            )

        return await call_next(request)


# ═══════════════════════════════════════════════════════════
# 请求体大小限制中间件（纵深防御：在应用层校验之前拦截超大请求）
# ═══════════════════════════════════════════════════════════
DEFAULT_BODY_SIZE = 10 * 1024 * 1024   # 10 MB 默认上限（其他端点）
UPLOAD_PATHS = {"/api/v1/scans/upload", "/api/v1/scans/batch-upload"}
BATCH_UPLOAD_PATHS = {"/api/v1/scans/batch-upload"}
EVIDENCE_UPLOAD_PREFIX = "/api/v1/evidence/cases/"  # 动态路径前缀匹配


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """限制请求体大小，防止超大 payload 耗尽资源"""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length is None:
            return await call_next(request)

        try:
            body_size = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Content-Length header", "error_code": "BAD_REQUEST"},
            )

        if request.url.path in BATCH_UPLOAD_PATHS:
            max_size = settings.max_batch_upload_size
        elif request.url.path in UPLOAD_PATHS:
            max_size = settings.max_upload_size
        elif request.url.path.startswith(EVIDENCE_UPLOAD_PREFIX) and request.url.path.endswith("/upload"):
            max_size = settings.max_upload_size
        else:
            max_size = DEFAULT_BODY_SIZE

        if body_size > max_size:
            logger.warning(
                f"Request body too large: {body_size} bytes "
                f"for {request.method} {request.url.path} (limit: {max_size})"
            )
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body too large. Maximum: {max_size // (1024*1024)} MB",
                    "error_code": "PAYLOAD_TOO_LARGE",
                },
            )

        return await call_next(request)
