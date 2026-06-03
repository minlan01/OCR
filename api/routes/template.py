"""
输出模板 API 路由 — CRUD + 导出
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import quote

import os
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from loguru import logger
from api.rate_limit import limiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import OutputTemplate, ScanTask
from db.session import get_db
from api.schemas.template import (
    TemplateCreate,
    TemplateExportRequest,
    TemplateListItem,
    TemplateResponse,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["Templates"])

_TEMPLATE_OUTPUT_DIR = os.environ.get("TEMPLATE_OUTPUT_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "template_output"))


@router.get("/", response_model=list[TemplateListItem])
async def list_templates(db: AsyncSession = Depends(get_db)):
    stmt = select(OutputTemplate).order_by(OutputTemplate.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(OutputTemplate).where(OutputTemplate.id == template_id)
    result = await db.execute(stmt)
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


@router.post("/", response_model=TemplateResponse, status_code=201)
@limiter.limit("10/minute")
async def create_template(
    request: Request,
    name: str = Form(..., max_length=200),
    description: str = Form(default=""),
    schema_file: UploadFile | None = File(default=None),
    rules_file: UploadFile | None = File(default=None),
    generator_file: UploadFile | None = File(default=None),
    reference_file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    schema_json = {}
    if schema_file:
        raw = await schema_file.read()
        try:
            schema_json = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid schema JSON: {e}")

    rules_md = None
    if rules_file:
        raw = await rules_file.read()
        try:
            rules_md = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid rules file encoding: {e}")

    generator_code = None
    if generator_file:
        raw = await generator_file.read()
        try:
            generator_code = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid generator file encoding: {e}")

    reference_doc = None
    if reference_file:
        reference_doc = await reference_file.read()
        if len(reference_doc) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Reference document must be < 10MB")

    tmpl = OutputTemplate(
        name=name,
        description=description or None,
        schema_json=schema_json,
        rules_md=rules_md,
        generator_code=generator_code,
        reference_doc=reference_doc,
    )
    db.add(tmpl)
    await db.flush()
    await db.refresh(tmpl)
    logger.info(f"Template created: {tmpl.id} [{tmpl.name}]")
    return tmpl


@router.put("/{template_id}", response_model=TemplateResponse)
@limiter.limit("10/minute")
async def update_template(
    request: Request,
    template_id: uuid.UUID,
    name: str | None = Form(default=None, max_length=200),
    description: str | None = Form(default=None),
    schema_file: UploadFile | None = File(default=None),
    rules_file: UploadFile | None = File(default=None),
    generator_file: UploadFile | None = File(default=None),
    reference_file: UploadFile | None = File(default=None),
    clear_reference: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OutputTemplate).where(OutputTemplate.id == template_id)
    result = await db.execute(stmt)
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if name is not None:
        tmpl.name = name
    if description is not None:
        tmpl.description = description or None

    if schema_file:
        raw = await schema_file.read()
        try:
            tmpl.schema_json = json.loads(raw.decode("utf-8"))
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(tmpl, "schema_json")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid schema JSON: {e}")

    if rules_file:
        raw = await rules_file.read()
        try:
            tmpl.rules_md = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid rules file encoding: {e}")

    if generator_file:
        raw = await generator_file.read()
        try:
            tmpl.generator_code = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid generator file encoding: {e}")

    if reference_file:
        reference_doc = await reference_file.read()
        if len(reference_doc) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Reference document must be < 10MB")
        tmpl.reference_doc = reference_doc
    elif clear_reference == "1":
        tmpl.reference_doc = None

    await db.flush()
    await db.refresh(tmpl)
    logger.info(f"Template updated: {tmpl.id} [{tmpl.name}]")
    return tmpl


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(OutputTemplate).where(OutputTemplate.id == template_id)
    result = await db.execute(stmt)
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    await db.delete(tmpl)
    logger.info(f"Template deleted: {template_id}")


@router.post("/{task_id}/export")
@limiter.limit("10/minute")
async def export_with_template(
    request: Request,
    task_id: uuid.UUID,
    body: TemplateExportRequest,
    db: AsyncSession = Depends(get_db),
):
    """按模板导出 Word 文档

    流程: 加载任务结果 → 加载模板 → LLM 提取 → 生成器执行 → Word 下载
    """
    from api.routes.scan import _get_task_or_404, _fetch_result_json
    from services.template.llm_extractor import extract_with_schema
    from services.template.generator_runner import run_generator_to_docx

    task = await _get_task_or_404(task_id, db)
    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"Task status is '{task.status}', must be 'completed'")

    result_json = _fetch_result_json(task, task_id)

    stmt = select(OutputTemplate).where(OutputTemplate.id == body.template_id)
    result = await db.execute(stmt)
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if not tmpl.schema_json:
        raise HTTPException(status_code=400, detail="Template has no schema_json defined")

    try:
        extracted_data = await extract_with_schema(
            structured_result=result_json,
            schema_json=tmpl.schema_json,
            rules_md=tmpl.rules_md,
        )
    except Exception as e:
        logger.error(f"LLM extraction failed for task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LLM extraction failed: {e}")

    try:
        docx_bytes = run_generator_to_docx(
            extracted_data=extracted_data,
            generator_code=tmpl.generator_code,
            template_name=tmpl.name,
            reference_doc=tmpl.reference_doc,
        )
    except ValueError as e:
        logger.warning(f"Generator validation failed for task {task_id}: {e}")
        raise HTTPException(
            status_code=422,
            detail=f"提取的数据不满足模板要求: {e}。请确认该文件内容与模板匹配。",
        )
    except Exception as e:
        logger.error(f"Generator execution failed for task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generator execution failed: {e}")

    base_name = Path(task.filename).stem
    safe_filename = quote(f"{base_name}_{tmpl.name}.docx")

    # 同步保存到模板输出文件夹
    try:
        os.makedirs(_TEMPLATE_OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(_TEMPLATE_OUTPUT_DIR, f"{base_name}_{tmpl.name}.docx")
        with open(output_path, "wb") as f:
            f.write(docx_bytes)
        logger.info(f"Saved generated docx to: {output_path}")
    except Exception as e:
        logger.warning(f"Failed to save docx to template output folder: {e}")

    from fastapi.responses import Response
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        },
    )
