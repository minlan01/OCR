"""
通用 API Schema — 分页、错误响应、健康检查、统计等
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: list[T]
    page: int
    size: int
    total: int


class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str
    error_code: str | None = None


class MessageResponse(BaseModel):
    """简单消息响应"""
    message: str
    success: bool = True


class PingResponse(BaseModel):
    """Ping 响应"""
    ping: str = "pong"
    time: float
    host: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str
    version: str
    db: str = "unknown"
    redis: str = "unknown"
    minio: str = "unknown"


class AdminStatsResponse(BaseModel):
    """管理后台统计概览"""
    total_tasks: int
    today_tasks: int
    failed_tasks: int
    avg_confidence: float | None
    by_status: dict[str, int]


class QueueItem(BaseModel):
    """队列中的任务项"""
    task_id: str
    filename: str
    status: str
    priority: int
    created_at: str | None = None


class AdminQueueResponse(BaseModel):
    """管理后台队列状态"""
    queue_length: int
    items: list[QueueItem]


class ScanResultResponse(BaseModel):
    """内联返回的扫描结果"""
    task_id: str
    status: str
    result: dict
