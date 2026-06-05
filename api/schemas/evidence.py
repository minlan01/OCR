"""
证据模块 API Schema
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─── 创建案件 ────────────────────────────────────────────────────────────────

class CreateEvidenceCaseRequest(BaseModel):
    case_name: str = Field(..., min_length=1, max_length=500, description="案件名称")
    case_type: Literal["injury", "death", "neonatal"] = Field(..., description="案件类型: injury=医疗损害（伤残）, death=医疗损害（死亡）, neonatal=医疗损害（新生儿）")
    is_minor: bool = Field(default=False, description="是否未成年人")
    # 原被告信息从素材中自动提取，创建时无需手动填写
    plaintiff_info: dict[str, Any] = Field(default_factory=dict, description="原告信息（自动提取）")
    defendant_info: dict[str, Any] = Field(default_factory=dict, description="被告信息（自动提取）")


# ─── 案件响应 ────────────────────────────────────────────────────────────────

class MaterialResponse(BaseModel):
    id: str
    original_filename: str | None = None
    file_type: str = "other"
    minio_bucket: str | None = None
    minio_key: str | None = None
    file_size: int | None = None
    auto_category: str | None = None
    manual_category: str | None = None
    effective_category: str | None = None
    category_confidence: float | None = None
    ocr_status: str = "pending"
    ocr_text: str | None = None
    ocr_result: dict[str, Any] = Field(default_factory=dict)
    page_count: int | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    manual_edit: dict[str, Any] = Field(default_factory=dict)
    catalog_index: int | None = None
    catalog_title: str | None = None
    catalog_description: str | None = None
    proof_purpose: str | None = None
    fee_detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class StepResponse(BaseModel):
    id: int
    step_name: str
    status: str = "pending"
    progress: int = 0
    duration_ms: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvidenceCaseResponse(BaseModel):
    id: str
    case_name: str
    case_type: str
    is_minor: bool
    status: str
    plaintiff_info: dict[str, Any] = Field(default_factory=dict)
    defendant_info: dict[str, Any] = Field(default_factory=dict)
    catalog_data: dict[str, Any] = Field(default_factory=dict)
    catalog_pdf_path: str | None = None
    analysis_result: dict[str, Any] = Field(default_factory=dict)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    missing_items: dict[str, Any] = Field(default_factory=dict)
    export_bundle_path: str | None = None
    export_files: dict[str, Any] = Field(default_factory=dict)
    lawyer_info: list[dict[str, str]] = Field(default_factory=list, description="律师信息 [{name, phone}]")
    metadata: dict[str, Any] = Field(default_factory=dict)
    materials: list[MaterialResponse] = Field(default_factory=list)
    steps: list[StepResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvidenceCaseListResponse(BaseModel):
    items: list[EvidenceCaseResponse]
    total: int


# ─── 材料编辑 ────────────────────────────────────────────────────────────────

class UpdateMaterialRequest(BaseModel):
    manual_category: str | None = Field(default=None, max_length=50)
    catalog_title: str | None = Field(default=None, max_length=200)
    catalog_description: str | None = Field(default=None, max_length=1000)
    proof_purpose: str | None = Field(default=None, max_length=500)
    manual_edit: dict[str, Any] | None = None


class UpdateCaseRequest(BaseModel):
    case_name: str | None = Field(default=None, min_length=1, max_length=500, description="案件名称")
    case_type: Literal["injury", "death", "neonatal"] | None = Field(default=None, description="案件类型")
    is_minor: bool | None = Field(default=None, description="是否未成年人")
    lawyer_info: list[dict[str, str]] | None = Field(default=None, max_length=2, description="律师信息，格式: [{name, phone}, ...]，最多2个")
    defendant_phone: str | None = Field(default=None, max_length=20, description="被告联系电话（手动输入）")

    @field_validator("lawyer_info")
    @classmethod
    def validate_lawyer_info(cls, v: list[dict[str, str]] | None) -> list[dict[str, str]] | None:
        if v is None:
            return v
        for i, lawyer in enumerate(v):
            if "name" not in lawyer or not lawyer["name"].strip():
                raise ValueError(f"律师{i+1}必须包含姓名(name)")
            if "phone" not in lawyer or not lawyer["phone"].strip():
                raise ValueError(f"律师{i+1}必须包含电话(phone)")
            # 验证姓名长度
            if len(lawyer["name"]) > 20:
                raise ValueError(f"律师{i+1}姓名不能超过20个字符")
            # 验证电话格式（中国大陆手机号或座机）
            phone = lawyer["phone"].strip()
            if not re.match(r"^1[3-9]\d{9}$|^0\d{2,3}-?\d{6,8}$", phone):
                raise ValueError(f"律师{i+1}电话格式不正确（应为手机号或座机号）")
        return v

    @field_validator("defendant_phone")
    @classmethod
    def validate_defendant_phone(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return v
        phone = v.strip()
        # 允许手机号、座机号、或"未知"
        if phone == "未知":
            return phone
        if not re.match(r"^1[3-9]\d{9}$|^0\d{2,3}-?\d{6,8}$", phone):
            raise ValueError("电话格式不正确（应为手机号或座机号，如13800138000或010-12345678）")
        return phone


# ─── 清单编辑 ────────────────────────────────────────────────────────────────

class CatalogItemUpdate(BaseModel):
    material_id: str
    manual_category: str | None = Field(default=None, max_length=50)
    catalog_title: str | None = Field(default=None, max_length=200)
    catalog_description: str | None = Field(default=None, max_length=1000)
    proof_purpose: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None


class UpdateCatalogRequest(BaseModel):
    items: list[CatalogItemUpdate] = Field(default_factory=list)


# ─── 进度响应 ────────────────────────────────────────────────────────────────

class ProgressResponse(BaseModel):
    case_id: str
    status: str
    current_step: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    progress_percent: float = 0.0
    steps: list[StepResponse] = Field(default_factory=list)


# ─── 清单响应 ────────────────────────────────────────────────────────────────

class CatalogGroupResponse(BaseModel):
    category: str
    category_name: str
    items: list[MaterialResponse]


class CatalogResponse(BaseModel):
    case_id: str
    case_name: str
    case_type: str
    groups: list[CatalogGroupResponse]
    fee_summary: dict[str, Any] = Field(default_factory=dict)
    total_amount: float = 0.0


# ─── 分析响应 ────────────────────────────────────────────────────────────────

class AnalysisResponse(BaseModel):
    case_id: str
    status: str
    analysis_result: dict[str, Any] = Field(default_factory=dict)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    missing_items: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, description="分析失败时的错误信息")


# ─── 导出响应 ────────────────────────────────────────────────────────────────

class ExportBundleResponse(BaseModel):
    case_id: str
    message: str
    bundle_path: str | None = None


class ProcessResponse(BaseModel):
    case_id: str
    message: str
    task_id: str | None = None


# ─── 案件列表项（精简） ──────────────────────────────────────────────────────

class EvidenceCaseListItem(BaseModel):
    id: str
    case_name: str
    case_type: str
    is_minor: bool
    status: str
    created_at: datetime
    updated_at: datetime


class EvidenceCaseListSlimResponse(BaseModel):
    items: list[EvidenceCaseListItem]
    total: int
