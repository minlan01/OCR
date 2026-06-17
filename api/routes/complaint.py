"""
DEPRECATED: 此模块已被 evidence 模块替代，保留仅为兼容性。
ComplaintCase / ComplaintUpload / ComplaintStep 模型已从 db/models.py 中移除。
本路由文件在运行时不会被正常加载（所有模型导入将失败）。
如需民事起诉状功能，请使用 /api/v1/evidence 模块。

原：民事起诉状 API 路由（已废弃）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.complaint import (
    CaseListResponse,
    CaseResponse,
    CreateCaseRequest,
    GenerateRequest,
    GenerateResponse,
    ResultsResponse,
    SlotResultItem,
    StartOcrResponse,
    StepResponse,
    UpdateResultsRequest,
    UploadResponse,
)
from api.schemas.common import MessageResponse
from api.rate_limit import limiter
from config.settings import settings
from db.models import ComplaintCase, ComplaintStep, ComplaintUpload
from db.session import get_db
from services.storage.minio_client import minio_client

try:
    from worker.complaint_tasks import process_complaint_ocr, generate_complaint_doc
except ImportError:
    process_complaint_ocr = None
    generate_complaint_doc = None

router = APIRouter(prefix="/complaint")

COMPLAINT_MINIO_BUCKET = "scan-result"

REQUIRED_SLOTS = {"plaintiff", "defendant", "medical"}
CONDITIONAL_SLOTS = {"guardian"}
OPTIONAL_SLOTS = {"fee", "appraisal", "staff_error", "evidence"}
ALL_SLOTS = REQUIRED_SLOTS | CONDITIONAL_SLOTS | OPTIONAL_SLOTS


def _build_upload_out(u: ComplaintUpload) -> UploadResponse:
    return UploadResponse(
        id=str(u.id),
        slot=u.slot,
        file_type=u.file_type,
        original_filename=u.original_filename,
        ocr_status=u.ocr_status,
        ocr_result=u.ocr_result,
        extracted_data=u.extracted_data,
        manual_edit=u.manual_edit,
        created_at=u.created_at,
    )


def _build_step_out(s: ComplaintStep) -> StepResponse:
    return StepResponse(
        id=s.id,
        step_name=s.step_name,
        status=s.status,
        duration_ms=s.duration_ms,
        error_message=s.error_message,
        started_at=s.started_at,
        completed_at=s.completed_at,
    )


def _build_case_out(case: ComplaintCase) -> CaseResponse:
    return CaseResponse(
        case_id=str(case.id),
        case_type=case.case_type,
        is_minor=case.is_minor,
        status=case.status,
        generated_doc_path=case.generated_doc_path,
        metadata=case.metadata_,
        created_at=case.created_at,
        updated_at=case.updated_at,
        uploads=[_build_upload_out(u) for u in (case.uploads or [])],
        steps=[_build_step_out(s) for s in (case.steps or [])],
    )


async def _get_case_or_404(case_id: uuid.UUID, db: AsyncSession) -> ComplaintCase:
    stmt = select(ComplaintCase).where(ComplaintCase.id == case_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
    return case


@router.post("/cases", response_model=CaseResponse, status_code=201)
@limiter.limit("10/minute")
async def create_case(
    request: Request,
    body: CreateCaseRequest,
    db: AsyncSession = Depends(get_db),
):
    case = ComplaintCase(
        case_type=body.case_type,
        is_minor=body.is_minor,
        status="draft",
    )
    db.add(case)
    await db.flush()
    await db.refresh(case)
    logger.info(f"Complaint case created: {case.id} type={body.case_type} minor={body.is_minor}")
    return _build_case_out(case)


@router.get("/cases", response_model=CaseListResponse)
@limiter.limit("30/minute")
async def list_cases(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func, desc
    count_stmt = select(func.count(ComplaintCase.id))
    total = (await db.execute(count_stmt)).scalar()

    stmt = (
        select(ComplaintCase)
        .order_by(desc(ComplaintCase.created_at))
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    cases = result.scalars().all()

    return CaseListResponse(
        items=[_build_case_out(c) for c in cases],
        total=total,
    )


@router.get("/cases/{case_id}", response_model=CaseResponse)
@limiter.limit("60/minute")
async def get_case(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    case = await _get_case_or_404(case_id, db)
    return _build_case_out(case)


@router.post("/cases/{case_id}/upload", response_model=UploadResponse, status_code=201)
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    case_id: uuid.UUID,
    slot: str = Form(...),
    file: UploadFile | None = File(default=None),
    manual_input: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    if slot not in ALL_SLOTS:
        raise HTTPException(status_code=400, detail=f"Invalid slot: {slot}. Allowed: {', '.join(sorted(ALL_SLOTS))}")

    case = await _get_case_or_404(case_id, db)

    if not file and not manual_input:
        raise HTTPException(status_code=400, detail="Must provide either a file or manual_input")

    file_type = "manual_input"
    original_filename = None
    minio_bucket = None
    minio_key = None

    if file:
        content = await file.read()
        if len(content) > settings.max_upload_size:
            raise HTTPException(status_code=400, detail="File too large")

        file_type = "image" if file.content_type and file.content_type.startswith("image/") else "pdf"
        if file.filename:
            fn = file.filename.lower()
            if fn.endswith((".docx", ".doc")):
                file_type = "docx"
            elif fn.endswith((".xlsx", ".xls")):
                file_type = "xlsx"
            elif fn.endswith((".pptx", ".ppt")):
                file_type = "pptx"
        original_filename = file.filename or "upload"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        minio_key = f"complaint/{case_id}/{slot}/{uuid.uuid4()}_{quote(original_filename)}"
        minio_bucket = COMPLAINT_MINIO_BUCKET

        try:
            minio_client.upload_bytes(
                bucket=minio_bucket,
                object_key=minio_key,
                data=content,
                content_type=file.content_type or "application/octet-stream",
            )
        except Exception as e:
            logger.error(f"MinIO upload failed for complaint case {case_id}: {e}")
            raise HTTPException(status_code=500, detail="File storage failed")

    upload = ComplaintUpload(
        case_id=case_id,
        slot=slot,
        file_type=file_type,
        original_filename=original_filename,
        minio_bucket=minio_bucket,
        minio_key=minio_key,
        manual_input=manual_input,
        ocr_status="skipped" if (file_type == "manual_input" and not file) else "pending",
    )
    db.add(upload)
    await db.flush()
    await db.refresh(upload)

    logger.info(f"Upload added to case {case_id}: slot={slot} type={file_type}")
    return _build_upload_out(upload)


@router.post("/cases/{case_id}/start-ocr", response_model=StartOcrResponse)
@limiter.limit("5/minute")
async def start_ocr(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    if process_complaint_ocr is None:
        raise HTTPException(status_code=500, detail="Celery task dispatcher not available")

    case = await _get_case_or_404(case_id, db)

    if case.status not in ("draft", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot start OCR for case with status: {case.status}")

    stmt = select(ComplaintUpload).where(
        ComplaintUpload.case_id == case_id,
        ComplaintUpload.ocr_status == "pending",
    )
    result = await db.execute(stmt)
    pending_uploads = result.scalars().all()

    if not pending_uploads:
        raise HTTPException(status_code=400, detail="No pending uploads to process")

    processing_slots = [u.slot for u in pending_uploads]

    case.status = "processing"
    await db.flush()

    try:
        process_complaint_ocr.delay(str(case_id))
    except Exception as e:
        logger.error(f"Failed to dispatch OCR task for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch OCR task")

    return StartOcrResponse(
        case_id=str(case_id),
        message="OCR processing started",
        processing_slots=processing_slots,
    )


@router.get("/cases/{case_id}/results", response_model=ResultsResponse)
@limiter.limit("60/minute")
async def get_results(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    case = await _get_case_or_404(case_id, db)

    stmt = select(ComplaintUpload).where(ComplaintUpload.case_id == case_id)
    result = await db.execute(stmt)
    uploads = result.scalars().all()

    slot_items = []
    for u in uploads:
        effective = u.manual_edit if u.manual_edit else u.extracted_data
        slot_items.append(SlotResultItem(
            slot=u.slot,
            ocr_status=u.ocr_status,
            extracted_data=u.extracted_data,
            manual_edit=u.manual_edit,
            effective_data=effective,
        ))

    return ResultsResponse(
        case_id=str(case_id),
        case_type=case.case_type,
        is_minor=case.is_minor,
        slots=slot_items,
    )


@router.put("/cases/{case_id}/results", response_model=MessageResponse)
@limiter.limit("10/minute")
async def update_results(
    request: Request,
    case_id: uuid.UUID,
    body: UpdateResultsRequest,
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(case_id, db)

    for slot_update in body.slots:
        stmt = select(ComplaintUpload).where(
            ComplaintUpload.case_id == case_id,
            ComplaintUpload.slot == slot_update.slot,
        )
        result = await db.execute(stmt)
        upload = result.scalar_one_or_none()
        if upload:
            upload.manual_edit = slot_update.manual_edit

    await db.flush()
    return MessageResponse(message="Results updated")


@router.post("/cases/{case_id}/generate", response_model=GenerateResponse)
@limiter.limit("3/minute")
async def generate_complaint(
    request: Request,
    case_id: uuid.UUID,
    body: GenerateRequest = Body(default=GenerateRequest()),
    db: AsyncSession = Depends(get_db),
):
    if generate_complaint_doc is None:
        raise HTTPException(status_code=500, detail="Celery task dispatcher not available")

    case = await _get_case_or_404(case_id, db)

    if case.status not in ("processing", "draft"):
        if case.status == "completed" and case.generated_doc_path:
            return GenerateResponse(
                case_id=str(case_id),
                message="Complaint already generated",
                status="completed",
            )
        raise HTTPException(status_code=400, detail=f"Cannot generate for case with status: {case.status}")

    try:
        task_kwargs: dict[str, Any] = {"case_id": str(case_id)}
        if body.manual_total_fee is not None:
            task_kwargs["manual_total_fee"] = body.manual_total_fee
        generate_complaint_doc.delay(**task_kwargs)
    except Exception as e:
        logger.error(f"Failed to dispatch generate task for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to dispatch generate task")

    return GenerateResponse(
        case_id=str(case_id),
        message="Complaint generation started",
        status="processing",
    )


@router.get("/cases/{case_id}/download")
@limiter.limit("30/minute")
async def download_complaint(
    request: Request,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    case = await _get_case_or_404(case_id, db)

    if case.status != "completed" or not case.generated_doc_path:
        raise HTTPException(status_code=400, detail="Complaint document not ready")

    try:
        data = minio_client.download_bytes(
            bucket=COMPLAINT_MINIO_BUCKET,
            object_key=case.generated_doc_path,
        )
    except Exception as e:
        logger.error(f"Failed to download complaint doc for case {case_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document")

    safe_filename = quote(f"民事起诉状_{case.case_type}.docx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )
