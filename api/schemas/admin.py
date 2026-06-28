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
    tenant_id: UUID | None = Field(
        default=None,
        description="仅 super_admin 可修改用户所属租户",
    )


class UserResponse(BaseModel):
    """用户操作后返回"""
    id: UUID
    email: EmailStr
    display_name: str
    role: str
    is_active: bool
    tenant_id: UUID | None = None

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


# ─── OCR 监控 ───

class OcrMaterialStat(BaseModel):
    """单个材料的 OCR 统计"""
    material_id: str
    filename: str | None = None
    file_type: str
    effective_category: str | None = None
    ocr_status: str
    source_type: str | None = None
    block_count: int = 0
    avg_confidence: float | None = None
    min_confidence: float | None = None
    low_conf_count: int = 0  # confidence < 0.6 的 block 数
    char_count: int = 0
    has_blocks: bool = False


class OcrCaseStat(BaseModel):
    """单个案件的 OCR 统计"""
    case_id: str
    case_name: str
    case_type: str
    is_minor: bool
    tenant_id: str | None = None
    tenant_name: str | None = None
    material_count: int = 0
    ocr_completed: int = 0
    ocr_failed: int = 0
    avg_confidence: float | None = None
    low_quality_count: int = 0  # avg_confidence < 0.6 的材料数
    materials: list[OcrMaterialStat] = []


class OcrMonitorResponse(BaseModel):
    """OCR 监控总览响应"""
    scope: str  # "global" | tenant uuid
    total_cases: int
    total_materials: int
    materials_with_ocr: int
    ocr_completed: int
    ocr_failed: int
    ocr_pending: int
    avg_confidence: float | None = None
    low_quality_count: int = 0  # avg_confidence < 0.6
    high_quality_count: int = 0  # avg_confidence >= 0.9
    quality_distribution: dict[str, int] = {
        "high": 0,    # >= 0.9
        "medium": 0,  # 0.6 ~ 0.9
        "low": 0,     # < 0.6
        "no_data": 0, # 无 blocks
    }
    source_type_stats: dict[str, int] = {}  # image_ocr/pdf_ocr/docx → count
    field_hit_rates: dict[str, float] = {}  # 医疗费总额等关键字段命中率
    cases: list[OcrCaseStat] = []
    generated_at: datetime
