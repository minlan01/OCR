"""
认证模块数据模型 — tenants / users
SaaS 多租户用户体系
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base

VALID_TENANT_PLANS = "'free','pro','enterprise'"
VALID_TENANT_STATUSES = "'active','suspended'"
VALID_USER_ROLES = "'super_admin','tenant_admin','member'"
VALID_AUTH_TYPES = "'password','oauth'"


class Tenant(Base):
    """租户表 — 每个租户代表一个组织/律所"""
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="租户名称/公司名")
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="free", comment="套餐: free/pro/enterprise")
    max_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=20, comment="最大案件数")
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False, default=2, comment="最大并发处理数")
    storage_quota_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=2048, comment="存储配额(MB)")
    storage_used_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已用存储(MB)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", comment="状态: active/suspended")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )
    features: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None,
        comment="功能开关 JSON: {evidence: bool, timeline: bool, ocr: bool}"
    )

    # 关联
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_tenants_status", "status"),
        Index("idx_tenants_plan", "plan"),
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.id} [{self.plan}] {self.name}>"


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), default=None, comment="bcrypt哈希密码，oauth用户可为null")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member", comment="角色: super_admin/tenant_admin/member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    # 关联
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")

    __table_args__ = (
        Index("idx_users_tenant_id", "tenant_id"),
        Index("idx_users_role", "role"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.role}] tenant={self.tenant_id}>"
