"""
管理后台 API 路由
GET  /api/v1/admin/stats      - 统计概览
GET  /api/v1/admin/queue      - 队列状态
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.rate_limit import limiter
from api.schemas.common import AdminQueueResponse, AdminStatsResponse
from db.models import ScanTask
from db.session import get_db

router = APIRouter()


@router.get("/stats", response_model=AdminStatsResponse)
@limiter.limit("20/minute")
async def admin_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """系统统计概览"""
    # 任务总数
    total_stmt = select(func.count(ScanTask.id))
    total = (await db.execute(total_stmt)).scalar()

    # 按状态统计
    status_stmt = (
        select(ScanTask.status, func.count(ScanTask.id))
        .group_by(ScanTask.status)
    )
    status_result = await db.execute(status_stmt)
    by_status = {row[0]: row[1] for row in status_result.fetchall()}

    # 今天任务数
    today_stmt = select(func.count(ScanTask.id)).where(
        func.date(ScanTask.created_at) == func.current_date()
    )
    today_count = (await db.execute(today_stmt)).scalar()

    # 失败任务数
    failed = by_status.get("failed", 0)

    # 平均处理置信度
    avg_stmt = select(func.avg(ScanTask.confidence_avg)).where(
        ScanTask.confidence_avg.isnot(None)
    )
    avg_confidence = (await db.execute(avg_stmt)).scalar()

    return {
        "total_tasks": total,
        "today_tasks": today_count,
        "failed_tasks": failed,
        "avg_confidence": float(avg_confidence) if avg_confidence else None,
        "by_status": by_status,
    }


@router.get("/queue", response_model=AdminQueueResponse)
@limiter.limit("20/minute")
async def admin_queue(request: Request, db: AsyncSession = Depends(get_db)):
    """查看当前待处理队列"""
    pending_stmt = (
        select(ScanTask)
        .where(ScanTask.status.in_(["pending", "received", "retrying"]))
        .order_by(ScanTask.priority.desc(), ScanTask.created_at.asc())
        .limit(50)
    )
    result = await db.execute(pending_stmt)
    tasks = result.scalars().all()

    return {
        "queue_length": len(tasks),
        "items": [
            {
                "task_id": str(t.id),
                "filename": t.filename,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    }
