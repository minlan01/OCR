"""
认证路由 — 注册/登录/刷新/用户信息
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from uuid import UUID

from config.settings import settings
from db.session import get_db
from db.models_auth import Tenant, User
from api.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    is_refresh_token_valid,
    revoke_refresh_token,
)
from api.dependencies import get_current_user

router = APIRouter()
_limiter = Limiter(key_func=get_remote_address)


# ─── Schemas ───

class RegisterRequest(BaseModel):
    tenant_name: str | None = None
    tenant_id: UUID | None = None
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str


class TenantNameItem(BaseModel):
    id: str
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    tenant_id: str
    tenant_name: str
    plan: str
    features: dict | None = None


# 前向引用解决
TokenResponse.model_rebuild()


# ─── 路由 ───

@router.get("/auth/tenants", response_model=list[TenantNameItem])
async def list_tenant_names(db: AsyncSession = Depends(get_db)):
    """获取租户名称列表（公开接口，注册时选择用）"""
    result = await db.execute(
        select(Tenant.id, Tenant.name)
        .where(Tenant.status == "active")
        .order_by(Tenant.name)
    )
    return [
        TenantNameItem(id=str(row[0]), name=row[1])
        for row in result.all()
    ]


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
@_limiter.limit("3/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册：可选择已有租户（member）或创建新租户（tenant_admin）"""
    # 检查邮箱是否已注册
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # 选择已有租户 or 创建新租户
    if req.tenant_id:
        # 加入已有租户 → member
        tenant_row = await db.execute(select(Tenant).where(Tenant.id == req.tenant_id))
        tenant = tenant_row.scalar_one_or_none()
        if not tenant or tenant.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected tenant not found or inactive",
            )
        user_role = "member"
    else:
        # 创建新租户 → tenant_admin
        if not req.tenant_name or not req.tenant_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization name is required when not joining an existing one",
            )
        tenant = Tenant(
            name=req.tenant_name.strip(),
            plan="free",
            max_cases=settings.default_tenant_max_cases,
            max_concurrent=settings.default_tenant_max_concurrent,
            storage_quota_mb=settings.default_tenant_storage_quota_mb,
            status="active",
        )
        db.add(tenant)
        await db.flush()
        user_role = "tenant_admin"

    # 创建用户
    user = User(
        tenant_id=tenant.id,
        email=req.email,
        hashed_password=hash_password(req.password),
        display_name=req.display_name,
        role=user_role,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # 生成 token
    token_data = {"sub": str(user.id), "tenant_id": str(tenant.id), "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info(f"New registration: {req.email} -> tenant {tenant.name}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            tenant_id=str(tenant.id),
            tenant_name=tenant.name,
            plan=tenant.plan,
            features=tenant.features,
        ),
    )


@router.post("/auth/login", response_model=TokenResponse)
@_limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录获取 JWT token"""
    result = await db.execute(
        select(User).where(User.email == req.email)
    )
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    # 更新最后登录时间
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # 获取租户信息（super_admin 无租户，跳过租户检查）
    tenant = None
    if user.tenant_id:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

        if not tenant or tenant.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant suspended",
            )

    # super_admin 的 tenant_id 可能为 None，token 中用空字符串代替
    token_tid = str(tenant.id) if tenant else ""
    token_data = {"sub": str(user.id), "tenant_id": token_tid, "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info(f"User logged in: {req.email}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            tenant_id=str(tenant.id) if tenant else "",
            tenant_name=tenant.name if tenant else "System",
            plan=tenant.plan if tenant else "enterprise",
            features=tenant.features if tenant else None,
        ),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
@_limiter.limit("10/minute")
async def refresh_token(request: Request, req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """用 refresh token 换取新的 access token"""
    payload = decode_token(req.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # 检查 jti 是否有效（轮转/撤销检查）
    jti = payload.get("jti")
    if jti and not is_refresh_token_valid(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # 获取租户（super_admin 无租户）
    tenant = None
    if user.tenant_id:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant or tenant.status != "active":
            raise HTTPException(status_code=403, detail="Tenant suspended")

    # 撤销旧 refresh token（轮转）
    if jti:
        revoke_refresh_token(jti)

    token_tid = str(tenant.id) if tenant else ""
    token_data = {"sub": str(user.id), "tenant_id": token_tid, "role": user.role}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user=UserInfo(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            tenant_id=str(tenant.id) if tenant else "",
            tenant_name=tenant.name if tenant else "System",
            plan=tenant.plan if tenant else "enterprise",
            features=tenant.features if tenant else None,
        ),
    )


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.put("/auth/change-password")
@_limiter.limit("5/minute")
async def change_password(
    request: Request,
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改当前用户密码"""
    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters",
        )

    if not current_user.hashed_password or not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(req.new_password)
    await db.commit()

    logger.info(f"Password changed for user: {current_user.email}")
    return {"message": "Password changed successfully"}


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None


@router.put("/auth/profile", response_model=UserInfo)
async def update_profile(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户个人信息"""
    if req.display_name is not None:
        current_user.display_name = req.display_name.strip()

    await db.commit()

    # 获取租户信息（super_admin 无租户）
    tenant = None
    if current_user.tenant_id is not None:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

    return UserInfo(
        id=str(current_user.id),
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        tenant_id=str(tenant.id) if tenant else "",
        tenant_name=tenant.name if tenant else "System",
        plan=tenant.plan if tenant else "enterprise",
        features=tenant.features if tenant else None,
    )


@router.get("/auth/me", response_model=UserInfo)
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """获取当前登录用户信息"""
    # super_admin 的 tenant_id 可能为 None，需兼容
    tenant = None
    if current_user.tenant_id is not None:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

    return UserInfo(
        id=str(current_user.id),
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        tenant_id=str(tenant.id) if tenant else "",
        tenant_name=tenant.name if tenant else "System",
        plan=tenant.plan if tenant else "enterprise",
        features=tenant.features if tenant else None,
    )
