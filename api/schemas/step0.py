"""
步骤0 · API Schema 定义
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Step0MaterialOut(BaseModel):
    """步骤0 素材响应"""
    id: str
    original_filename: str | None = None
    file_type: str = "image"
    file_size: int | None = None
    ocr_status: str = "pending"
    ocr_text: str | None = None
    auto_category: str | None = None
    manual_category: str | None = None
    effective_category: str | None = None
    category_confidence: float | None = None
    # step0 metadata 字段
    step0_fee_category: str | None = None
    step0_fee_category_cn: str | None = None
    step0_page_number: int | None = None
    step0_parent_material_id: str | None = None
    step0_corrected: bool = False
    step0_needs_review: bool = False
    step0_archived_key: str | None = None
    created_at: datetime
    updated_at: datetime


class Step0UploadResponse(BaseModel):
    """步骤0 上传响应"""
    case_id: str
    uploaded_count: int
    materials: list[Step0MaterialOut]


class Step0PreprocessRequest(BaseModel):
    """步骤0 预处理请求"""
    pass


class Step0PreprocessResponse(BaseModel):
    """步骤0 预处理响应"""
    case_id: str
    message: str
    task_id: str | None = None


class Step0CorrectRequest(BaseModel):
    """步骤0 手动纠正分类请求"""
    new_category: str = Field(..., description="新的费用类别 key，如 fee_medical")


class Step0ProgressResponse(BaseModel):
    """步骤0 进度响应"""
    case_id: str
    total: int = 0
    processed: int = 0
    failed: int = 0
    pending: int = 0
    progress_percent: float = 0.0
    step0_status: str = "not_started"
    category_summary: dict[str, int] = Field(default_factory=dict)


class Step0SummaryResponse(BaseModel):
    """步骤0 分类汇总响应"""
    case_id: str
    category_summary: dict[str, int] = Field(default_factory=dict)
    category_detail: list[dict[str, Any]] = Field(default_factory=list)


class Step0SkipResponse(BaseModel):
    """步骤0 跳过响应"""
    case_id: str
    message: str
