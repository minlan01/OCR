"""
民事起诉状模块 API Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    case_type: Literal["injury", "death", "neonatal"]
    is_minor: bool = False


class CaseResponse(BaseModel):
    case_id: str
    case_type: str
    is_minor: bool
    status: str
    generated_doc_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    uploads: list["UploadResponse"] = Field(default_factory=list)
    steps: list["StepResponse"] = Field(default_factory=list)


class UploadResponse(BaseModel):
    id: str
    slot: str
    file_type: str
    original_filename: str | None = None
    ocr_status: str
    ocr_result: dict[str, Any] = Field(default_factory=dict)
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    manual_edit: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class StepResponse(BaseModel):
    id: int
    step_name: str
    status: str
    duration_ms: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class UploadFileRequest(BaseModel):
    slot: Literal["plaintiff", "guardian", "defendant", "fee", "medical", "appraisal", "staff_error", "evidence"]
    manual_input: str | None = None


class StartOcrResponse(BaseModel):
    case_id: str
    message: str
    processing_slots: list[str]


class SlotResultItem(BaseModel):
    slot: str
    ocr_status: str
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    manual_edit: dict[str, Any] = Field(default_factory=dict)
    effective_data: dict[str, Any] = Field(default_factory=dict)


class ResultsResponse(BaseModel):
    case_id: str
    case_type: str
    is_minor: bool
    slots: list[SlotResultItem]


class UpdateResultsRequest(BaseModel):
    slots: list[SlotResultUpdate]


class SlotResultUpdate(BaseModel):
    slot: str
    manual_edit: dict[str, Any] = Field(default_factory=dict)


class GenerateResponse(BaseModel):
    case_id: str
    message: str
    status: str


class CaseListResponse(BaseModel):
    items: list[CaseResponse]
    total: int


UploadResponse.model_rebuild()
CaseResponse.model_rebuild()
