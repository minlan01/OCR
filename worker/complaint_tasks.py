"""
民事起诉状模块 Celery 异步任务
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from loguru import logger

from worker.celery_app import celery_app
from config.settings import settings


@celery_app.task(bind=True, name="process_complaint_ocr", max_retries=2)
def process_complaint_ocr(self, case_id: str):
    logger.info(f"Complaint OCR processing started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        result = _run_ocr_pipeline(case_id)
        return {"case_id": case_id, "status": result.get("status", "completed"), "summary": result}
    except Exception as e:
        logger.error(f"Complaint OCR fatal error: case_id={case_id} | {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, name="generate_complaint_doc", max_retries=2)
def generate_complaint_doc(self, case_id: str):
    logger.info(f"Complaint doc generation started: case_id={case_id}")

    try:
        uuid.UUID(case_id)
    except ValueError:
        return {"case_id": case_id, "status": "failed", "error": "Invalid case_id format"}

    try:
        result = _run_generate_pipeline(case_id)
        return {"case_id": case_id, "status": result.get("status", "completed"), "summary": result}
    except Exception as e:
        logger.error(f"Complaint generate fatal error: case_id={case_id} | {e}")
        raise self.retry(exc=e)


def _run_ocr_pipeline(case_id: str) -> dict:
    from db.models import ComplaintCase, ComplaintStep, ComplaintUpload
    from db.session import async_session_factory
    from services.complaint.ocr_service import ocr_upload
    from services.complaint.llm_extractor import extract_slot_info, extract_medical_large

    summary = {"case_id": case_id, "status": "completed", "processed_slots": [], "errors": []}

    async def _pipeline():
        case_uuid = uuid.UUID(case_id)
        async with async_session_factory() as db:
            from sqlalchemy import select

            stmt = select(ComplaintCase).where(ComplaintCase.id == case_uuid)
            r = await db.execute(stmt)
            case = r.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")

            step = ComplaintStep(
                case_id=case_uuid,
                step_name="ocr_extract",
                status="processing",
                started_at=datetime.now(timezone.utc),
            )
            db.add(step)
            await db.flush()

            stmt2 = select(ComplaintUpload).where(
                ComplaintUpload.case_id == case_uuid,
                ComplaintUpload.ocr_status == "pending",
            )
            r2 = await db.execute(stmt2)
            uploads = r2.scalars().all()

            if not uploads:
                step.status = "completed"
                step.completed_at = datetime.now(timezone.utc)
                step.duration_ms = 0
                await db.commit()
                return summary

            from concurrent.futures import ThreadPoolExecutor

            def _process_one(upload_id_str: str):
                import asyncio as _aio
                _loop = _aio.new_event_loop()
                try:
                    return _loop.run_until_complete(_process_single_upload(upload_id_str))
                finally:
                    _loop.close()

            upload_ids = [str(u.id) for u in uploads]
            with ThreadPoolExecutor(max_workers=settings.bailian_text_max_concurrent) as pool:
                futures = {pool.submit(_process_one, uid): uid for uid in upload_ids}
                for future in futures:
                    try:
                        result = future.result()
                        if result.get("success"):
                            summary["processed_slots"].append(result.get("slot"))
                        else:
                            summary["errors"].append(f"{result.get('slot')}: {result.get('error')}")
                    except Exception as e:
                        summary["errors"].append(str(e))

            step.status = "completed"
            step.completed_at = datetime.now(timezone.utc)
            if step.started_at:
                step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
            await db.commit()

            return summary

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        from db.session import engine as _db_engine
        try:
            loop.run_until_complete(_db_engine.dispose())
        except Exception:
            pass
        loop.close()


async def _process_single_upload(upload_id: str) -> dict:
    from db.models import ComplaintUpload
    from db.session import async_session_factory
    from services.complaint.ocr_service import ocr_upload
    from services.complaint.llm_extractor import extract_slot_info, extract_medical_large
    from services.storage.minio_client import minio_client

    upload_uuid = uuid.UUID(upload_id)
    async with async_session_factory() as db:
        from sqlalchemy import select

        stmt = select(ComplaintUpload).where(ComplaintUpload.id == upload_uuid)
        r = await db.execute(stmt)
        upload = r.scalar_one_or_none()
        if not upload:
            return {"success": False, "slot": "unknown", "error": "Upload not found"}

        slot = upload.slot
        try:
            upload.ocr_status = "processing"
            await db.flush()

            if upload.file_type == "manual_input" and upload.manual_input:
                ocr_text = upload.manual_input
                ocr_result = {"full_text": ocr_text, "source": "manual_input"}
            elif upload.minio_bucket and upload.minio_key:
                file_bytes = minio_client.download_bytes(
                    bucket=upload.minio_bucket,
                    object_key=upload.minio_key,
                )
                filename = upload.original_filename or "upload"
                ocr_result = ocr_upload(file_bytes, filename)
                ocr_text = ocr_result.get("full_text", "")
            else:
                upload.ocr_status = "skipped"
                await db.commit()
                return {"success": True, "slot": slot, "note": "no content to process"}

            upload.ocr_result = ocr_result

            if slot == "medical" and len(ocr_text) > 6000:
                extracted = extract_medical_large(ocr_text)
            else:
                extracted = extract_slot_info(slot, ocr_text)

            upload.extracted_data = extracted
            upload.ocr_status = "completed"
            await db.commit()

            logger.info(f"Complaint OCR+extract done: slot={slot} case={upload.case_id}")
            return {"success": True, "slot": slot}

        except Exception as e:
            logger.error(f"Complaint OCR failed: slot={slot} upload={upload_id} | {e}")
            upload.ocr_status = "failed"
            upload.ocr_result = {"error": str(e)}
            await db.commit()
            return {"success": False, "slot": slot, "error": str(e)}


def _run_generate_pipeline(case_id: str) -> dict:
    from db.models import ComplaintCase, ComplaintStep, ComplaintUpload
    from db.session import async_session_factory
    from services.complaint.doc_generator import generate_complaint
    from services.storage.minio_client import minio_client

    summary = {"case_id": case_id, "status": "completed", "errors": []}

    async def _pipeline():
        case_uuid = uuid.UUID(case_id)
        async with async_session_factory() as db:
            from sqlalchemy import select

            stmt = select(ComplaintCase).where(ComplaintCase.id == case_uuid)
            r = await db.execute(stmt)
            case = r.scalar_one_or_none()
            if not case:
                raise ValueError(f"Case not found: {case_id}")

            step = ComplaintStep(
                case_id=case_uuid,
                step_name="generate_doc",
                status="processing",
                started_at=datetime.now(timezone.utc),
            )
            db.add(step)
            await db.flush()

            stmt2 = select(ComplaintUpload).where(ComplaintUpload.case_id == case_uuid)
            r2 = await db.execute(stmt2)
            uploads = r2.scalars().all()

            slot_data = {}
            for u in uploads:
                data = u.manual_edit if u.manual_edit else u.extracted_data
                if data:
                    slot_data[u.slot] = data

            try:
                doc_bytes = generate_complaint(
                    case_type=case.case_type,
                    is_minor=case.is_minor,
                    slot_data=slot_data,
                )

                doc_key = f"complaint/{case_id}/民事起诉状_{case.case_type}.docx"
                minio_client.upload_bytes(
                    bucket="scan-result",
                    object_key=doc_key,
                    data=doc_bytes,
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

                case.generated_doc_path = doc_key
                case.status = "completed"
                step.status = "completed"
                step.completed_at = datetime.now(timezone.utc)
                if step.started_at:
                    step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)
                await db.commit()

                logger.info(f"Complaint doc generated: case={case_id} key={doc_key}")
            except Exception as e:
                step.status = "failed"
                step.error_message = str(e)
                step.completed_at = datetime.now(timezone.utc)
                case.status = "failed"
                await db.commit()
                summary["status"] = "failed"
                summary["errors"].append(f"generate: {e}")
                logger.error(f"Complaint doc generation failed: case={case_id} | {e}")

            return summary

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_pipeline())
    finally:
        from db.session import engine as _db_engine
        try:
            loop.run_until_complete(_db_engine.dispose())
        except Exception:
            pass
        loop.close()
