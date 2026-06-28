"""
FastAPI 应用主入口
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config.settings import settings
from config.logging import setup_logging
from api.routes import health, scan, admin, template, evidence, auth, step0
from api.middleware import AuthMiddleware, RequestSizeLimitMiddleware
from api.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    setup_logging()
    logger.info(f"🚀 {settings.app_name} v{settings.app_version} starting | env={settings.app_env}")

    # 安全提示
    if not settings.api_key_plain and not settings.jwt_secret_key:
        logger.warning(
            "⚠️  No API_KEY or JWT_SECRET configured — all API endpoints are unprotected! "
            "Set JWT_SECRET_KEY for SaaS auth mode."
        )

    # 尝试初始化 MinIO buckets（非阻塞）
    try:
        from services.storage.minio_client import minio_client
        minio_client.ensure_buckets()
        logger.info("MinIO buckets ensured")
    except Exception as e:
        logger.warning(f"MinIO init skipped: {e}")

    yield

    # 关闭
    logger.info(f"🛑 {settings.app_name} shutting down")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description="扫描件智能结构化处理系统",
        docs_url="/api/docs" if settings.is_development else None,
        redoc_url="/api/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    # CORS — 前后端同源部署（API serve 前端静态文件），生产环境不需要额外 origin
    cors_origins = (
        ["http://localhost:5173", "http://localhost:8900", "http://127.0.0.1:5173", "http://127.0.0.1:8900"]
        if settings.is_development
        else []
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求体大小限制（纵深防御，在认证之前拦截）
    app.add_middleware(RequestSizeLimitMiddleware)

    # 认证中间件 (JWT + API Key 双模式)
    app.add_middleware(AuthMiddleware)

    # 频率限制
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # 生产环境不记录完整 traceback，避免泄露文件路径/内部地址
        if settings.is_development:
            logger.error(f"Unhandled exception: {exc}", exc_info=True)
        else:
            logger.error(f"Unhandled exception at {request.method} {request.url.path}: {type(exc).__name__}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
        )

    # 注册路由
    app.include_router(health.router, prefix="/api/v1", tags=["Health"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
    app.include_router(scan.router, prefix="/api/v1", tags=["Scans"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
    app.include_router(template.router, prefix="/api/v1", tags=["Templates"])
    app.include_router(evidence.router, prefix="/api/v1", tags=["Evidence"])
    app.include_router(step0.router, prefix="/api/v1", tags=["Step0"])

    # 挂载 Admin SPA 静态文件（开发模式下可选）
    static_dir = Path(__file__).resolve().parent.parent / "static" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="admin_spa")

    @app.middleware("http")
    async def no_cache_html(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # SPA fallback: 非 API 路径的 404 返回 index.html（支持 Vue Router history 模式）
    @app.middleware("http")
    async def spa_fallback(request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404 and not request.url.path.startswith("/api"):
            from fastapi.responses import FileResponse
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(
                    index_path,
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
        return response

    return app


app = create_app()
