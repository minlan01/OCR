"""
管理后台 Schema — 用户/租户/使用量
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ─── 用户管理 ───

class UserListItem(BaseModel):
    """用户列表项"""
    id: UUID
    email: EmailStr
    display_name: str
    role: str
    is_active: bool
    last_login: datetime | None = None
    created_at: datetime
    tenant_id: UUID | None = None
    tenant_name: str | None = None

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    """创建/邀请用户"""
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=6, max_length=128)
    role: Literal["member", "tenant_admin"] = "member"
    tenant_id: UUID | None = Field(
        default=None,
        description="仅 super_admin 可指定；其他角色创建到自身租户",
    )


class UserUpdateRequest(BaseModel):
    """更新用户"""
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["member", "tenant_admin"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserResponse(BaseModel):
    """用户操作后返回"""
    id: UUID
    email: EmailStr
    display_name: str
    role: str
    is_active: bool
    tenant_id: UUID

    model_config = {"from_attributes": True}


# ─── 租户管理 ───

class TenantListItem(BaseModel):
    """租户列表项"""
    id: UUID
    name: str
    plan: str
    max_cases: int
    max_concurrent: int
    storage_quota_mb: int
    storage_used_mb: int
    status: str
    user_count: int = 0
    case_count: int = 0
    created_at: datetime
    features: dict | None = None

    model_config = {"from_attributes": True}


class TenantDetail(BaseModel):
    """租户详情（含统计）"""
    id: UUID
    name: str
    plan: str
    max_cases: int
    max_concurrent: int
    storage_quota_mb: int
    storage_used_mb: int
    status: str
    created_at: datetime
    updated_at: datetime | None = None
    user_count: int = 0
    case_count: int = 0
    last_active: datetime | None = None
    features: dict | None = None

    model_config = {"from_attributes": True}


class TenantCreateRequest(BaseModel):
    """创建租户"""
    name: str = Field(..., min_length=1, max_length=200)
    plan: Literal["free", "pro", "enterprise"] = "free"
    max_cases: int = Field(default=20, ge=0)
    max_concurrent: int = Field(default=2, ge=1)
    storage_quota_mb: int = Field(default=2048, ge=0)
    status: Literal["active", "suspended"] = "active"
    features: dict | None = Field(default=None, description="功能开关")


class TenantUpdateRequest(BaseModel):
    """更新租户配置"""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    plan: Literal["free", "pro", "enterprise"] | None = None
    max_cases: int | None = Field(default=None, ge=0)
    max_concurrent: int | None = Field(default=None, ge=1)
    storage_quota_mb: int | None = Field(default=None, ge=0)
    status: Literal["active", "suspended"] | None = None
    features: dict | None = None


# ─── 使用量 ───

class UsageTenant(BaseModel):
    name: str
    plan: str
    max_cases: int


class UsageData(BaseModel):
    evidence_cases: int
    scan_tasks: int
    storage_used_mb: int
    storage_quota_mb: int
    active_users: int
    concurrent_used: int
    concurrent_max: int


class UsageResponse(BaseModel):
    """使用量响应"""
    tenant: UsageTenant
    usage: UsageData
