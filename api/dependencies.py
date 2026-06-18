"""
FastAPI 依赖项 — 认证/授权/租户上下文
"""
from __future__ import annotations

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models_auth import User, Tenant


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    从 request.state 获取当前登录用户（由 AuthMiddleware 注入）
    如果未登录则抛出 401
    """
    user_id = getattr(request.state, "user_id", None)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """获取当前用户的租户"""
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant suspended or not found",
        )

    return tenant


def require_role(*allowed_roles: str) -> Callable:
    """
    角色检查依赖工厂
    用法: @router.get("/admin-only", dependencies=[Depends(require_role("super_admin", "tenant_admin"))])
    """
    async def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' not permitted. Required: {', '.join(allowed_roles)}",
            )
        return current_user

    return _check_role


async def get_tenant_filter(request: Request) -> uuid.UUID | None:
    """
    获取当前租户ID用于查询过滤
    如果未认证返回 None（兼容旧 API Key 模式）
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return uuid.UUID(tenant_id)
    return None
