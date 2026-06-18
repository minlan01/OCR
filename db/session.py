"""
数据库会话管理 — SQLAlchemy 2.0 async
"""
from __future__ import annotations

from contextvars import ContextVar
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config.settings import settings


# 异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# 会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Worker 专用 session factory（通过 ContextVar 传递，避免 event loop 绑定冲突）
_worker_session_factory: ContextVar[async_sessionmaker | None] = ContextVar(
    "_worker_session_factory", default=None
)


def get_session_factory() -> async_sessionmaker:
    """获取当前上下文的 session factory

    Worker 上下文中返回 worker 专属 factory（绑定到正确的 event loop），
    FastAPI 上下文中返回全局 factory。
    """
    worker_factory = _worker_session_factory.get()
    if worker_factory is not None:
        return worker_factory
    return async_session_factory


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖：获取数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
            # 仅在 session 有 pending changes 时才 commit（避免纯 GET 请求产生 WAL）
            if session.in_transaction() and session.is_active:
                # 检查是否有 dirty/new/deleted 对象
                if session.dirty or session.new or session.deleted:
                    await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """创建所有表（开发环境用，生产用 Alembic 迁移）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """删除所有表（仅开发环境）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def run_in_worker(coro):
    """在独立 event loop 中运行 async 协程（Celery Worker 安全）

    核心问题：全局 async_session_factory 底层的 asyncpg 连接池
    绑定到创建时的 event loop。在 Worker 的 asyncio.new_event_loop()
    中使用会导致 "Future attached to a different loop" 错误。

    解决方案：
    1. 在新 loop 中创建独立的 async engine + session factory
    2. 通过 ContextVar 注入，协程内部用 get_session_factory() 获取
    3. 执行完毕后关闭 engine 释放资源

    用法:
        # 各模块中用 get_session_factory() 替代 async_session_factory:
        from db.session import get_session_factory
        async with get_session_factory()() as db:
            ...

        # Worker 调用入口:
        from db.session import run_in_worker
        run_in_worker(_do_work())
    """
    import asyncio as _asyncio

    async def _wrapper():
        from sqlalchemy.ext.asyncio import (
            AsyncSession as _AS,
            async_sessionmaker as _asm,
            create_async_engine as _cae,
        )

        _worker_engine = _cae(
            settings.database_url,
            echo=settings.is_development,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        _worker_factory = _asm(
            _worker_engine,
            class_=_AS,
            expire_on_commit=False,
        )
        # 通过 ContextVar 注入 worker session factory
        token = _worker_session_factory.set(_worker_factory)
        try:
            return await coro
        finally:
            _worker_session_factory.reset(token)
            await _worker_engine.dispose()

    loop = _asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_wrapper())
    finally:
        loop.close()
