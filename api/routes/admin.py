"""
管理后台 API 路由
GET  /api/v1/admin/stats         - 统计概览
GET  /api/v1/admin/queue         - 队列状态
GET  /api/v1/admin/users         - 用户列表（租户内）
POST /api/v1/admin/users         - 创建/邀请用户
PUT  /api/v1/admin/users/{id}    - 修改用户
DELETE /api/v1/admin/users/{id}  - 禁用用户
GET  /api/v1/admin/tenants       - 租户列表（super_admin）
GET  /api/v1/admin/tenants/{id}  - 租户详情
PUT  /api/v1/admin/tenants/{id}  - 修改租户配置
GET  /api/v1/admin/usage         - 当前租户使用量
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from api.rate_limit import limiter
from api.schemas.common import AdminQueueResponse, AdminStatsResponse, PaginatedResponse
from api.schemas.admin import (
    TenantCreateRequest,
    TenantDetail,
    TenantListItem,
    TenantUpdateRequest,
    UsageData,
    UsageResponse,
    UsageTenant,
    UserCreateRequest,
    UserListItem,
    UserResponse,
    UserUpdateRequest,
)
from api.security import hash_password
from api.dependencies import get_current_user, get_tenant_filter
from db.models import ScanTask
from db.models_auth import User, Tenant
from db.models_evidence import EvidenceCase
from db.session import get_db

router = APIRouter()


# ─── 角色层级常量（数值越大权限越高） ───
_ROLE_LEVEL: dict[str, int] = {
    "member": 1,
    "tenant_admin": 2,
    "super_admin": 3,
}


async def _resolve_admin_scope(
    current_user: User,
) -> uuid.UUID | None:
    """根据用户角色返回查询范围。

    - super_admin → None（全局可见）
    - tenant_admin → 返回该用户的 tenant_id（仅本租户）
    - 其他角色 → 抛出 403
    """
    if current_user.role == "super_admin":
        return None
    if current_user.role == "tenant_admin":
        return current_user.tenant_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required (super_admin or tenant_admin)",
    )


@router.get("/stats", response_model=AdminStatsResponse)
@limiter.limit("20/minute")
async def admin_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """系统统计概览（super_admin 看全局，tenant_admin 看本租户）"""
    scope_tenant_id = await _resolve_admin_scope(current_user)

    # ─── ScanTask 统计 ───
    total_stmt = select(func.count(ScanTask.id))
    status_stmt = (
        select(ScanTask.status, func.count(ScanTask.id))
        .group_by(ScanTask.status)
    )
    today_stmt = select(func.count(ScanTask.id)).where(
        func.date(ScanTask.created_at) == func.current_date()
    )
    avg_stmt = select(func.avg(ScanTask.confidence_avg)).where(
        ScanTask.confidence_avg.isnot(None)
    )

    if scope_tenant_id is not None:
        total_stmt = total_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        status_stmt = status_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        today_stmt = today_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        avg_stmt = avg_stmt.where(ScanTask.tenant_id == scope_tenant_id)

    total = (await db.execute(total_stmt)).scalar()
    status_result = await db.execute(status_stmt)
    by_status = {row[0]: row[1] for row in status_result.fetchall()}
    today_count = (await db.execute(today_stmt)).scalar()
    failed = by_status.get("failed", 0)
    avg_confidence = (await db.execute(avg_stmt)).scalar()

    # ─── EvidenceCase 统计 ───
    evidence_total_stmt = select(func.count(EvidenceCase.id))
    if scope_tenant_id is not None:
        evidence_total_stmt = evidence_total_stmt.where(
            EvidenceCase.tenant_id == scope_tenant_id
        )
    evidence_total = (await db.execute(evidence_total_stmt)).scalar() or 0

    return {
        "total_tasks": total,
        "today_tasks": today_count,
        "failed_tasks": failed,
        "avg_confidence": float(avg_confidence) if avg_confidence else None,
        "by_status": by_status,
        "evidence_total": evidence_total,
        "scope": "global" if scope_tenant_id is None else str(scope_tenant_id),
    }


@router.get("/queue", response_model=AdminQueueResponse)
@limiter.limit("20/minute")
async def admin_queue(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看当前待处理队列（super_admin 看全局，tenant_admin 看本租户）"""
    scope_tenant_id = await _resolve_admin_scope(current_user)

    pending_stmt = (
        select(ScanTask)
        .where(ScanTask.status.in_(["pending", "received", "retrying"]))
        .order_by(ScanTask.priority.desc(), ScanTask.created_at.asc())
        .limit(50)
    )
    if scope_tenant_id is not None:
        pending_stmt = pending_stmt.where(ScanTask.tenant_id == scope_tenant_id)

    result = await db.execute(pending_stmt)
    tasks = result.scalars().all()

    return {
        "queue_length": len(tasks),
        "scope": "global" if scope_tenant_id is None else str(scope_tenant_id),
        "items": [
            {
                "task_id": str(t.id),
                "filename": t.filename,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    }


# ══════════════════════════════════════════════════════════════
#  用户管理（租户内）
# ══════════════════════════════════════════════════════════════

def _require_super_admin(user: User) -> bool:
    return user.role == "super_admin"


def _require_tenant_admin_or_higher(user: User) -> None:
    """tenant_admin 或 super_admin，否则 403"""
    if _ROLE_LEVEL.get(user.role, 0) < _ROLE_LEVEL["tenant_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required (super_admin or tenant_admin)",
        )


@router.get("/users", response_model=PaginatedResponse[UserListItem])
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表（super_admin 看全部，tenant_admin 看本租户）"""
    _require_tenant_admin_or_higher(current_user)

    base = select(User)
    count_base = select(func.count(User.id))
    if not _require_super_admin(current_user):
        base = base.where(User.tenant_id == current_user.tenant_id)
        count_base = count_base.where(User.tenant_id == current_user.tenant_id)

    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * size
    rows = (
        await db.execute(
            base.order_by(User.created_at.desc()).offset(offset).limit(size)
        )
    ).scalars().all()

    items = [UserListItem.model_validate(u) for u in rows]
    return PaginatedResponse[UserListItem](
        items=items, page=page, size=size, total=total
    )


@router.post("/users", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
async def create_user(
    request: Request,
    payload: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建/邀请用户到租户"""
    _require_tenant_admin_or_higher(current_user)

    # 确定目标租户
    target_tenant_id: uuid.UUID
    if _require_super_admin(current_user) and payload.tenant_id is not None:
        target_tenant_id = payload.tenant_id
    else:
        target_tenant_id = current_user.tenant_id

    # role 不可高于创建者
    if _ROLE_LEVEL[payload.role] > _ROLE_LEVEL[current_user.role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create a user with a higher role than your own",
        )

    # 邮箱唯一性
    exists = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        tenant_id=target_tenant_id,
        email=payload.email,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(
        f"User created by {current_user.email}: {user.email} "
        f"role={user.role} tenant={target_tenant_id}"
    )
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
@limiter.limit("20/minute")
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改用户信息（display_name/role/is_active）"""
    _require_tenant_admin_or_higher(current_user)

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 租户隔离：非 super_admin 只能改本租户用户
    if not _require_super_admin(current_user) and user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify users outside your tenant",
        )

    # 不能把自己的 is_active 改为 False（防自锁）
    if (
        payload.is_active is False
        and user.id == current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account",
        )

    # role 校验：不能修改 super_admin 的角色；不能将他人提升至与自己同级或更高
    if payload.role is not None and payload.role != user.role:
        if user.role == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change role of a super_admin",
            )
        if _ROLE_LEVEL[payload.role] > _ROLE_LEVEL[current_user.role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign a role higher than your own",
            )
        user.role = payload.role

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=200)
@limiter.limit("10/minute")
async def disable_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """禁用用户（软删除 is_active=False）"""
    _require_tenant_admin_or_higher(current_user)

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 租户隔离
    if not _require_super_admin(current_user) and user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot disable users outside your tenant",
        )

    # 不能禁用自己
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable your own account",
        )

    # 不能禁用 super_admin
    if user.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot disable a super_admin",
        )

    user.is_active = False
    await db.commit()
    logger.info(f"User disabled by {current_user.email}: {user.email}")
    return {"message": "User disabled", "success": True}


# ══════════════════════════════════════════════════════════════
#  租户管理（super_admin 专属）
# ══════════════════════════════════════════════════════════════

@router.post("/tenants", response_model=TenantDetail, status_code=201)
@limiter.limit("10/minute")
async def create_tenant(
    request: Request,
    payload: TenantCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建租户（仅 super_admin）"""
    if not _require_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    tenant = Tenant(
        name=payload.name,
        plan=payload.plan,
        max_cases=payload.max_cases,
        max_concurrent=payload.max_concurrent,
        storage_quota_mb=payload.storage_quota_mb,
        status=payload.status,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    logger.info(f"Tenant created by {current_user.email}: {tenant.name}")
    return TenantDetail(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
        max_cases=tenant.max_cases,
        max_concurrent=tenant.max_concurrent,
        storage_quota_mb=tenant.storage_quota_mb,
        storage_used_mb=tenant.storage_used_mb,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        user_count=0,
        case_count=0,
        last_active=None,
    )


@router.get("/tenants", response_model=PaginatedResponse[TenantListItem])
@limiter.limit("20/minute")
async def list_tenants(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """租户列表（仅 super_admin）"""
    if not _require_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    total = (await db.execute(select(func.count(Tenant.id)))).scalar() or 0
    offset = (page - 1) * size
    tenants = (
        await db.execute(
            select(Tenant).order_by(Tenant.created_at.desc()).offset(offset).limit(size)
        )
    ).scalars().all()

    # 聚合用户数与案件数
    items: list[TenantListItem] = []
    for t in tenants:
        user_count = (
            await db.execute(
                select(func.count(User.id)).where(User.tenant_id == t.id)
            )
        ).scalar() or 0
        case_count = (
            await db.execute(
                select(func.count(EvidenceCase.id)).where(
                    EvidenceCase.tenant_id == t.id
                )
            )
        ).scalar() or 0
        items.append(
            TenantListItem(
                id=t.id,
                name=t.name,
                plan=t.plan,
                max_cases=t.max_cases,
                max_concurrent=t.max_concurrent,
                storage_quota_mb=t.storage_quota_mb,
                storage_used_mb=t.storage_used_mb,
                status=t.status,
                user_count=user_count,
                case_count=case_count,
                created_at=t.created_at,
            )
        )

    return PaginatedResponse[TenantListItem](
        items=items, page=page, size=size, total=total
    )


@router.get("/tenants/{tenant_id}", response_model=TenantDetail)
@limiter.limit("30/minute")
async def get_tenant(
    request: Request,
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """租户详情（super_admin 或本租户 tenant_admin）"""
    # 权限：super_admin 任意；tenant_admin 只能看自己租户；member 禁止
    if not _require_super_admin(current_user):
        _require_tenant_admin_or_higher(current_user)
        if tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot view other tenants",
            )

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user_count = (
        await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id)
        )
    ).scalar() or 0
    case_count = (
        await db.execute(
            select(func.count(EvidenceCase.id)).where(
                EvidenceCase.tenant_id == tenant_id
            )
        )
    ).scalar() or 0
    last_active_row = (
        await db.execute(
            select(func.max(User.last_login)).where(User.tenant_id == tenant_id)
        )
    ).scalar()

    return TenantDetail(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
        max_cases=tenant.max_cases,
        max_concurrent=tenant.max_concurrent,
        storage_quota_mb=tenant.storage_quota_mb,
        storage_used_mb=tenant.storage_used_mb,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        user_count=user_count,
        case_count=case_count,
        last_active=last_active_row,
    )


@router.put("/tenants/{tenant_id}", response_model=TenantDetail)
@limiter.limit("10/minute")
async def update_tenant(
    request: Request,
    tenant_id: uuid.UUID,
    payload: TenantUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改租户配置（仅 super_admin）"""
    if not _require_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if payload.name is not None:
        tenant.name = payload.name
    if payload.plan is not None:
        tenant.plan = payload.plan
    if payload.max_cases is not None:
        tenant.max_cases = payload.max_cases
    if payload.max_concurrent is not None:
        tenant.max_concurrent = payload.max_concurrent
    if payload.storage_quota_mb is not None:
        tenant.storage_quota_mb = payload.storage_quota_mb
    if payload.status is not None:
        tenant.status = payload.status

    await db.commit()
    await db.refresh(tenant)

    user_count = (
        await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id)
        )
    ).scalar() or 0
    case_count = (
        await db.execute(
            select(func.count(EvidenceCase.id)).where(
                EvidenceCase.tenant_id == tenant_id
            )
        )
    ).scalar() or 0
    last_active_row = (
        await db.execute(
            select(func.max(User.last_login)).where(User.tenant_id == tenant_id)
        )
    ).scalar()

    logger.info(f"Tenant updated by {current_user.email}: {tenant.name}")
    return TenantDetail(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
        max_cases=tenant.max_cases,
        max_concurrent=tenant.max_concurrent,
        storage_quota_mb=tenant.storage_quota_mb,
        storage_used_mb=tenant.storage_used_mb,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        user_count=user_count,
        case_count=case_count,
        last_active=last_active_row,
    )


# ══════════════════════════════════════════════════════════════
#  使用量统计
# ══════════════════════════════════════════════════════════════

@router.get("/usage", response_model=UsageResponse)
@limiter.limit("30/minute")
async def get_usage(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前租户使用量（所有登录用户均可查看自己的租户）"""
    tenant_id = current_user.tenant_id

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    evidence_cases = (
        await db.execute(
            select(func.count(EvidenceCase.id)).where(
                EvidenceCase.tenant_id == tenant_id
            )
        )
    ).scalar() or 0

    scan_tasks = (
        await db.execute(
            select(func.count(ScanTask.id)).where(ScanTask.tenant_id == tenant_id)
        )
    ).scalar() or 0

    active_users = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id, User.is_active.is_(True)
            )
        )
    ).scalar() or 0

    concurrent_used = (
        await db.execute(
            select(func.count(ScanTask.id)).where(
                ScanTask.tenant_id == tenant_id,
                ScanTask.status.in_(["processing", "pending", "received", "retrying"]),
            )
        )
    ).scalar() or 0

    return UsageResponse(
        tenant=UsageTenant(
            name=tenant.name,
            plan=tenant.plan,
            max_cases=tenant.max_cases,
        ),
        usage=UsageData(
            evidence_cases=evidence_cases,
            scan_tasks=scan_tasks,
            storage_used_mb=tenant.storage_used_mb,
            storage_quota_mb=tenant.storage_quota_mb,
            active_users=active_users,
            concurrent_used=concurrent_used,
            concurrent_max=tenant.max_concurrent,
        ),
    )
