"""
管理后台 API 路由
GET  /api/v1/admin/stats      - 统计概览
GET  /api/v1/admin/queue      - 队列状态
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.rate_limit import limiter
from api.schemas.common import AdminQueueResponse, AdminStatsResponse
from api.dependencies import get_current_user, get_tenant_filter
from db.models import ScanTask
from db.models_auth import User, Tenant
from db.models_evidence import EvidenceCase
from db.session import get_db

router = APIRouter()


async def _resolve_admin_scope(
    current_user: User,
) -> uuid.UUID | None:
    """根据用户角色返回查询范围。

    - super_admin → None（全局可见）
    - tenant_admin → 返回该用户的 tenant_id（仅本租户）
    - 其他角色 → 抛出 403
    """
    if current_user.role == "super_admin":
        return None
    if current_user.role == "tenant_admin":
        return current_user.tenant_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required (super_admin or tenant_admin)",
    )


@router.get("/stats", response_model=AdminStatsResponse)
@limiter.limit("20/minute")
async def admin_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """系统统计概览（super_admin 看全局，tenant_admin 看本租户）"""
    scope_tenant_id = await _resolve_admin_scope(current_user)

    # ─── ScanTask 统计 ───
    total_stmt = select(func.count(ScanTask.id))
    status_stmt = (
        select(ScanTask.status, func.count(ScanTask.id))
        .group_by(ScanTask.status)
    )
    today_stmt = select(func.count(ScanTask.id)).where(
        func.date(ScanTask.created_at) == func.current_date()
    )
    avg_stmt = select(func.avg(ScanTask.confidence_avg)).where(
        ScanTask.confidence_avg.isnot(None)
    )

    if scope_tenant_id is not None:
        total_stmt = total_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        status_stmt = status_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        today_stmt = today_stmt.where(ScanTask.tenant_id == scope_tenant_id)
        avg_stmt = avg_stmt.where(ScanTask.tenant_id == scope_tenant_id)

    total = (await db.execute(total_stmt)).scalar()
    status_result = await db.execute(status_stmt)
    by_status = {row[0]: row[1] for row in status_result.fetchall()}
    today_count = (await db.execute(today_stmt)).scalar()
    failed = by_status.get("failed", 0)
    avg_confidence = (await db.execute(avg_stmt)).scalar()

    # ─── EvidenceCase 统计 ───
    evidence_total_stmt = select(func.count(EvidenceCase.id))
    if scope_tenant_id is not None:
        evidence_total_stmt = evidence_total_stmt.where(
            EvidenceCase.tenant_id == scope_tenant_id
        )
    evidence_total = (await db.execute(evidence_total_stmt)).scalar() or 0

    return {
        "total_tasks": total,
        "today_tasks": today_count,
        "failed_tasks": failed,
        "avg_confidence": float(avg_confidence) if avg_confidence else None,
        "by_status": by_status,
        "evidence_total": evidence_total,
        "scope": "global" if scope_tenant_id is None else str(scope_tenant_id),
    }


@router.get("/queue", response_model=AdminQueueResponse)
@limiter.limit("20/minute")
async def admin_queue(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看当前待处理队列（super_admin 看全局，tenant_admin 看本租户）"""
    scope_tenant_id = await _resolve_admin_scope(current_user)

    pending_stmt = (
        select(ScanTask)
        .where(ScanTask.status.in_(["pending", "received", "retrying"]))
        .order_by(ScanTask.priority.desc(), ScanTask.created_at.asc())
        .limit(50)
    )
    if scope_tenant_id is not None:
        pending_stmt = pending_stmt.where(ScanTask.tenant_id == scope_tenant_id)

    result = await db.execute(pending_stmt)
    tasks = result.scalars().all()

    return {
        "queue_length": len(tasks),
        "scope": "global" if scope_tenant_id is None else str(scope_tenant_id),
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
