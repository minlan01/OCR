"""
认证中间件 — JWT Bearer + API Key 双模式

优先级: JWT Bearer token > X-API-Key > 无认证(开发模式)

公开路径（注册/登录/刷新/健康检查）直接放行。
认证成功后将 user_id/tenant_id 注入 request.state。
"""
from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from config.settings import settings
from api.security import decode_token


# 始终豁免认证的路径（健康检查 + 文档 + 认证端点）
PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/ping",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    # 认证端点 — 公开
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/tenants",
}

# 静态资源扩展名
STATIC_EXTENSIONS = {
    ".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map", ".json",
    ".xml", ".txt", ".webmanifest",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    统一认证中间件

    1. 非 API 路径 → 放行
    2. 公开路径 → 放行
    3. JWT Bearer token → 解析并注入 user_id/tenant_id 到 request.state
    4. X-API-Key → 兼容旧模式（不注入 user_id，纯 API 访问）
    5. 开发模式（无 JWT secret 且无 API_KEY）→ 放行
    6. 否则 → 401
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # ── 非 API 路径直接放行 ──
        if not path.startswith("/api"):
            return await call_next(request)

        # ── 公开路径直接放行 ──
        if path in PUBLIC_PATHS or path.startswith("/api/docs") or path.startswith("/api/redoc"):
            return await call_next(request)

        # ── 静态资源文件 ──
        _, _, ext = path.rpartition(".") if "." in path else ("", "", "")
        if ext and f".{ext}" in STATIC_EXTENSIONS:
            return await call_next(request)

        # ── 尝试 JWT 认证 ──
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_token(token)

            if payload and payload.get("type") == "access":
                user_id = payload.get("sub")
                tenant_id = payload.get("tenant_id")
                # super_admin 的 tenant_id 为空字符串，允许通过
                if user_id and (tenant_id is not None) and (tenant_id != "" or payload.get("role") == "super_admin"):
                    request.state.user_id = user_id
                    request.state.tenant_id = tenant_id if tenant_id else None
                    request.state.role = payload.get("role", "member")
                    return await call_next(request)
            # JWT 提供了但无效 → 401
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token", "error_code": "INVALID_TOKEN"},
            )

        # ── 尝试 API Key 认证（兼容旧模式）──
        # API Key 是系统级密钥，不关联特定用户/租户。
        # 注入 api_key_mode=True + role=super_admin，后续依赖项可据此判断。
        # 优先从查询参数 tenant_id / X-Tenant-Id 读取目标租户（供外部集成用）。
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        if api_key and settings.api_key_plain:
            if secrets.compare_digest(api_key, settings.api_key_plain):
                request.state.api_key_mode = True
                request.state.role = "super_admin"
                # 尝试从请求头或查询参数获取 tenant_id
                tid = (
                    request.headers.get("X-Tenant-Id")
                    or request.query_params.get("tenant_id")
                )
                request.state.tenant_id = tid if tid else None
                request.state.user_id = None  # API Key 不关联特定用户
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key", "error_code": "FORBIDDEN"},
            )

        # ── 开发模式：未配置 JWT secret 且未配置 API_KEY → 放行 ──
        if not settings.jwt_secret_key and not settings.api_key_plain:
            return await call_next(request)

        # ── 生产模式：需要认证 ──
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required", "error_code": "UNAUTHORIZED"},
        )


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
