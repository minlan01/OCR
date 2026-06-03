"""
证据模块数据模型 — evidence_cases / evidence_materials / evidence_requirements
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base

VALID_EVIDENCE_CASE_TYPES = "'injury','death','neonatal'"
VALID_EVIDENCE_STATUSES = (
    "'draft','uploading','processing','catalog_ready',"
    "'analyzing','analysis_done','exporting','completed','failed'"
)
VALID_FILE_TYPES = "'pdf','image','docx','xlsx','other'"
VALID_OCR_STATUSES = "'pending','processing','completed','failed','skipped'"


class EvidenceCase(Base):
    """证据案件主表"""
    __tablename__ = "evidence_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_name: Mapped[str] = mapped_column(String(500), nullable=False)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    complaint_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        default=None,
        comment="已废弃：原关联民事起诉状案件ID，保留兼容",
    )
    plaintiff_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    defendant_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    catalog_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    catalog_pdf_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    analysis_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_items: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    export_bundle_path: Mapped[str | None] = mapped_column(String(1000), default=None)
    export_files: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    lawyer_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list, comment="律师信息，格式: [{name, phone}, ...]")
    metadata_: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, name="metadata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    # 关联
    materials: Mapped[list["EvidenceMaterial"]] = relationship(
        "EvidenceMaterial", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    steps: Mapped[list["EvidenceStep"]] = relationship(
        "EvidenceStep", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_evidence_cases_status", "status"),
        Index("idx_evidence_cases_created_at", created_at.desc()),
        Index("idx_evidence_cases_case_type", "case_type"),
        CheckConstraint(
            f"case_type IN ({VALID_EVIDENCE_CASE_TYPES})",
            name="ck_evidence_cases_case_type",
        ),
        CheckConstraint(
            f"status IN ({VALID_EVIDENCE_STATUSES})",
            name="ck_evidence_cases_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<EvidenceCase {self.id} [{self.case_type}] {self.status}>"


class EvidenceMaterial(Base):
    """证据材料表"""
    __tablename__ = "evidence_materials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    evidence_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str | None] = mapped_column(String(500), default=None)
    file_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    minio_bucket: Mapped[str | None] = mapped_column(String(100), default=None)
    minio_key: Mapped[str | None] = mapped_column(String(1000), default=None)
    file_size: Mapped[int | None] = mapped_column(BigInteger, default=None)
    auto_category: Mapped[str | None] = mapped_column(String(50), default=None)
    manual_category: Mapped[str | None] = mapped_column(String(50), default=None)
    effective_category: Mapped[str | None] = mapped_column(String(50), default=None)
    category_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    ocr_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    ocr_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    extracted_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    manual_edit: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    catalog_index: Mapped[int | None] = mapped_column(Integer, default=None)
    catalog_title: Mapped[str | None] = mapped_column(String(500), default=None)
    catalog_description: Mapped[str | None] = mapped_column(Text, default=None)
    proof_purpose: Mapped[str | None] = mapped_column(String(500), default=None)
    fee_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected_pages: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="用户选择的待处理页码列表（1-based），空列表=处理全部页面"
    )
    metadata_: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, name="metadata")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    # 关联
    case: Mapped["EvidenceCase"] = relationship("EvidenceCase", back_populates="materials")

    __table_args__ = (
        Index("idx_evidence_materials_case_id", "evidence_case_id"),
        Index("idx_evidence_materials_category", "effective_category"),
        Index("idx_evidence_materials_ocr_status", "ocr_status"),
        CheckConstraint(
            f"file_type IN ({VALID_FILE_TYPES})",
            name="ck_evidence_materials_file_type",
        ),
        CheckConstraint(
            f"ocr_status IN ({VALID_OCR_STATUSES})",
            name="ck_evidence_materials_ocr_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<EvidenceMaterial {self.id} [{self.effective_category}] case={self.evidence_case_id}>"


class EvidenceStep(Base):
    """证据案件处理步骤记录表"""
    __tablename__ = "evidence_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    step_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    case: Mapped["EvidenceCase"] = relationship("EvidenceCase", back_populates="steps")

    __table_args__ = (
        Index("idx_evidence_steps_case_id", "case_id"),
    )

    def __repr__(self) -> str:
        return f"<EvidenceStep {self.step_name} [{self.status}] case={self.case_id}>"


class EvidenceRequirement(Base):
    """证据要件配置表"""
    __tablename__ = "evidence_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    category_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    check_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_evidence_requirements_case_type", "case_type", "is_minor"),
        Index("idx_evidence_requirements_category", "category"),
    )

    def __repr__(self) -> str:
        return f"<EvidenceRequirement [{self.case_type}] {self.category}>"


# ─── 默认要件配置种子数据 ──────────────────────────────────────────────────

DEFAULT_REQUIREMENTS: list[dict] = [
    # identity_id_card — 原告身份证信息
    {"case_type": "injury", "is_minor": False, "category": "identity_id_card", "category_name": "原告身份证信息",
     "description": "原告身份证正反面", "is_required": True, "sort_order": 1,
     "check_rules": {"min_count": 1}},
    {"case_type": "death", "is_minor": False, "category": "identity_id_card", "category_name": "原告身份证信息",
     "description": "原告身份证正反面", "is_required": True, "sort_order": 1,
     "check_rules": {"min_count": 1}},
    {"case_type": "neonatal", "is_minor": True, "category": "identity_id_card", "category_name": "原告（法定代理人）身份证信息",
     "description": "法定代理人身份证正反面", "is_required": True, "sort_order": 1,
     "check_rules": {"min_count": 1}},
    # identity_hukou — 户口本信息
    {"case_type": "injury", "is_minor": False, "category": "identity_hukou", "category_name": "户口本信息",
     "description": "户口本主页及本人页", "is_required": False, "sort_order": 2,
     "check_rules": {}},
    {"case_type": "death", "is_minor": False, "category": "identity_hukou", "category_name": "户口本信息",
     "description": "户口本主页及本人页", "is_required": False, "sort_order": 2,
     "check_rules": {}},
    {"case_type": "neonatal", "is_minor": True, "category": "identity_hukou", "category_name": "户口本信息",
     "description": "户口本主页及本人页（含新生儿页）", "is_required": False, "sort_order": 2,
     "check_rules": {}},
    # identity_other — 其他身份信息
    {"case_type": "injury", "is_minor": False, "category": "identity_other", "category_name": "其他身份信息",
     "description": "出生医学证明、监护证明等", "is_required": False, "sort_order": 3,
     "check_rules": {}},
    {"case_type": "death", "is_minor": False, "category": "identity_other", "category_name": "其他身份信息",
     "description": "出生医学证明、监护证明等", "is_required": False, "sort_order": 3,
     "check_rules": {}},
    {"case_type": "neonatal", "is_minor": True, "category": "identity_other", "category_name": "其他身份信息",
     "description": "出生医学证明、监护证明等", "is_required": True, "sort_order": 3,
     "check_rules": {"min_count": 1}},
    # identity_defendant — 被告身份信息
    {"case_type": "injury", "is_minor": False, "category": "identity_defendant", "category_name": "被告身份信息",
     "description": "医疗机构营业执照/执业许可证、统一社会信用代码等", "is_required": True, "sort_order": 4,
     "check_rules": {"min_count": 1}},
    {"case_type": "death", "is_minor": False, "category": "identity_defendant", "category_name": "被告身份信息",
     "description": "医疗机构营业执照/执业许可证、统一社会信用代码等", "is_required": True, "sort_order": 4,
     "check_rules": {"min_count": 1}},
    {"case_type": "neonatal", "is_minor": True, "category": "identity_defendant", "category_name": "被告身份信息",
     "description": "医疗机构营业执照/执业许可证、统一社会信用代码等", "is_required": True, "sort_order": 4,
     "check_rules": {"min_count": 1}},
    # death_certificate — 死亡证明（仅死亡案件）
    {"case_type": "death", "is_minor": False, "category": "death_certificate", "category_name": "死亡医学证明书",
     "description": "死亡医学证明书、尸检报告、死亡诊断书等", "is_required": True, "sort_order": 5,
     "check_rules": {"min_count": 1}},
    # medical_record — 病历资料
    {"case_type": "injury", "is_minor": False, "category": "medical_record", "category_name": "病历资料",
     "description": "门诊病历、住院病历、手术记录、检查报告等", "is_required": True, "sort_order": 6,
     "check_rules": {"min_count": 1}},
    {"case_type": "death", "is_minor": False, "category": "medical_record", "category_name": "病历资料",
     "description": "门诊病历、住院病历、手术记录、检查报告等", "is_required": True, "sort_order": 6,
     "check_rules": {"min_count": 1}},
    {"case_type": "neonatal", "is_minor": True, "category": "medical_record", "category_name": "病历资料",
     "description": "门诊病历、住院病历、分娩记录、新生儿病历、检查报告等", "is_required": True, "sort_order": 6,
     "check_rules": {"min_count": 1}},
    # appraisal — 司法鉴定意见书
    {"case_type": "injury", "is_minor": False, "category": "appraisal", "category_name": "司法鉴定意见书",
     "description": "伤残等级鉴定、因果关系鉴定、参与度鉴定等", "is_required": False, "sort_order": 7,
     "check_rules": {}},
    {"case_type": "death", "is_minor": False, "category": "appraisal", "category_name": "司法鉴定意见书",
     "description": "死因鉴定、因果关系鉴定、参与度鉴定等", "is_required": False, "sort_order": 7,
     "check_rules": {}},
    {"case_type": "neonatal", "is_minor": True, "category": "appraisal", "category_name": "司法鉴定意见书",
     "description": "伤残等级鉴定、因果关系鉴定、参与度鉴定等", "is_required": False, "sort_order": 7,
     "check_rules": {}},
    # fee_receipt — 医疗费用及相关票据
    {"case_type": "injury", "is_minor": False, "category": "fee_receipt", "category_name": "医疗费用及相关票据",
     "description": "医疗费发票、收费收据、费用结算单等", "is_required": True, "sort_order": 8,
     "check_rules": {"min_count": 1}},
    {"case_type": "death", "is_minor": False, "category": "fee_receipt", "category_name": "医疗费用及相关票据",
     "description": "医疗费发票、收费收据、费用结算单等", "is_required": True, "sort_order": 8,
     "check_rules": {"min_count": 1}},
    {"case_type": "neonatal", "is_minor": True, "category": "fee_receipt", "category_name": "医疗费用及相关票据",
     "description": "医疗费发票、收费收据、费用结算单等", "is_required": True, "sort_order": 8,
     "check_rules": {"min_count": 1}},
    # other_evidence — 其他证据
    {"case_type": "injury", "is_minor": False, "category": "other_evidence", "category_name": "其他证据",
     "description": "其他与案件有关的证据材料", "is_required": False, "sort_order": 9,
     "check_rules": {}},
    {"case_type": "death", "is_minor": False, "category": "other_evidence", "category_name": "其他证据",
     "description": "其他与案件有关的证据材料", "is_required": False, "sort_order": 9,
     "check_rules": {}},
    {"case_type": "neonatal", "is_minor": True, "category": "other_evidence", "category_name": "其他证据",
     "description": "其他与案件有关的证据材料", "is_required": False, "sort_order": 9,
     "check_rules": {}},
]
