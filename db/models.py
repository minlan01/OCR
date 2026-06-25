"""
数据库模型 — scan_tasks / task_steps / scan_files / output_templates
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base

# 任务/步骤共享的状态枚举常量（用于 CHECK 约束）
VALID_TASK_STATUSES = "'pending','received','processing','completed','failed','cancelled','retrying'"


class ScanTask(Base):
    """扫描任务主表"""
    __tablename__ = "scan_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        default=None,
        nullable=True,
        comment="租户ID（SaaS隔离用，开发模式可为null）",
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    scanner_id: Mapped[str | None] = mapped_column(String(100), default=None)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="watch_folder")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    original_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    result_path: Mapped[str | None] = mapped_column(String(1000), default=None)

    file_size: Mapped[int | None] = mapped_column(BigInteger, default=None)
    file_md5: Mapped[str | None] = mapped_column(String(32), default=None)

    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    confidence_avg: Mapped[float | None] = mapped_column(Numeric(5, 4), default=None)
    structure_score: Mapped[float | None] = mapped_column(Numeric(5, 4), default=None)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    heading_count: Mapped[int] = mapped_column(Integer, default=0)
    paragraph_count: Mapped[int] = mapped_column(Integer, default=0)

    callback_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    callback_status: Mapped[str | None] = mapped_column(String(30), default=None)

    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    metadata_: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, name="metadata")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # 关联
    steps: Mapped[list["TaskStep"]] = relationship(
        "TaskStep", back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )
    files: Mapped[list["ScanFile"]] = relationship(
        "ScanFile", back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_scan_tasks_md5", "file_md5", unique=True, postgresql_where=file_md5.isnot(None)),
        Index("idx_scan_tasks_status", "status"),
        Index("idx_scan_tasks_created_at", created_at.desc()),
        Index("idx_scan_tasks_scanner_id", "scanner_id"),
        Index("idx_scan_tasks_priority", "priority"),
        Index("idx_scan_tasks_tenant_id", "tenant_id"),
        CheckConstraint(
            f"status IN ({VALID_TASK_STATUSES})",
            name="ck_scan_tasks_status",
        ),
        CheckConstraint(
            "confidence_avg IS NULL OR (confidence_avg >= 0 AND confidence_avg <= 1)",
            name="ck_confidence_avg_range",
        ),
        CheckConstraint(
            "structure_score IS NULL OR (structure_score >= 0 AND structure_score <= 1)",
            name="ck_structure_score_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<ScanTask {self.id} [{self.status}] {self.filename}>"


class TaskStep(Base):
    """处理步骤记录表"""
    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # 预留字段：步骤产物路径（当前未读写，预留给未来阶段使用）
    output_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    step_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # 关联
    task: Mapped["ScanTask"] = relationship("ScanTask", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("task_id", "step_name", name="uq_task_steps_task_step"),
        Index("idx_task_steps_task_id", "task_id"),
        Index("idx_task_steps_step_name", "step_name"),
        CheckConstraint(
            f"status IN ({VALID_TASK_STATUSES})",
            name="ck_task_steps_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<TaskStep {self.step_name} [{self.status}] task={self.task_id}>"


class ScanFile(Base):
    """文件产物表"""
    __tablename__ = "scan_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer, default=None)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    file_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, name="metadata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    # 关联
    task: Mapped["ScanTask"] = relationship("ScanTask", back_populates="files")

    __table_args__ = (
        Index("idx_scan_files_task_id", "task_id"),
        Index("idx_scan_files_type", "file_type"),
        Index("idx_scan_files_task_type", "task_id", "file_type"),
    )

    def __repr__(self) -> str:
        return f"<ScanFile {self.file_type} bucket={self.bucket} task={self.task_id}>"


class OutputTemplate(Base):
    """输出模板表 — 存储 Schema + 规则手册 + 生成器代码"""
    __tablename__ = "output_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        default=None,
        nullable=True,
        comment="租户ID（SaaS隔离用，null表示全局模板）",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rules_md: Mapped[str | None] = mapped_column(Text, default=None)
    generator_code: Mapped[str | None] = mapped_column(Text, default=None)
    sample_output: Mapped[str | None] = mapped_column(Text, default=None)
    reference_doc: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    __table_args__ = (
        Index("idx_output_templates_name", "name"),
        Index("idx_output_templates_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<OutputTemplate {self.id} [{self.name}]>"


# ComplaintCase / ComplaintUpload / ComplaintStep 已废弃并移除
# 民事起诉状功能已合并到证据整理模块中
