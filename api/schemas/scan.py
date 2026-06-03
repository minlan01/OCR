"""
扫描任务 API Schema
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScanUploadResponse(BaseModel):
    task_id: UUID
    status: str
    filename: str
    message: str = "accepted"


class BatchProcessRequest(BaseModel):
    task_ids: list[UUID] = Field(..., min_length=1, max_length=50, description="待识别任务 ID 列表（1-50 个）")


class BatchProcessResult(BaseModel):
    dispatched: list[UUID] = Field(default_factory=list, description="成功派发的任务 ID")
    skipped: list[dict] = Field(default_factory=list, description="跳过的任务（含原因）")
    failed: list[dict] = Field(default_factory=list, description="派发失败的任务（含原因）")


class BatchUploadResult(BaseModel):
    uploaded: list[ScanUploadResponse] = Field(default_factory=list, description="成功上传的文件")
    skipped: list[dict] = Field(default_factory=list, description="跳过的文件（含原因）")
    failed: list[dict] = Field(default_factory=list, description="上传失败的文件（含原因）")


class ScanTaskSummary(BaseModel):
    """任务列表摘要"""
    task_id: UUID
    filename: str
    status: str
    page_count: int | None = None
    confidence_avg: float | None = None
    created_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskStepOut(BaseModel):
    """步骤信息"""
    id: int
    step_name: str
    status: str
    duration_ms: int | None = None
    retry_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ScanFileOut(BaseModel):
    """文件产物"""
    id: int
    file_type: str
    page_no: int | None = None
    bucket: str
    object_key: str
    size_bytes: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ScanTaskDetail(BaseModel):
    """任务详情"""
    task_id: UUID
    filename: str
    scanner_id: str | None = None
    source_type: str
    status: str
    priority: int = 0
    file_size: int | None = None
    file_md5: str | None = None
    page_count: int | None = None
    confidence_avg: float | None = None
    structure_score: float | None = None
    table_count: int = 0
    heading_count: int = 0
    paragraph_count: int = 0
    callback_url: str | None = None
    callback_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[TaskStepOut] = Field(default_factory=list)
    files: list[ScanFileOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


