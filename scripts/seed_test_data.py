"""
测试数据填充脚本
创建模拟测试任务
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import setup_logging
from loguru import logger
from db.models import ScanTask, TaskStep
from db.session import async_session_factory


async def seed():
    setup_logging()
    logger.info("Seeding test data...")

    # 创建测试任务
    test_tasks = [
        {
            "filename": "test_contract_10pages.pdf",
            "status": "completed",
            "page_count": 10,
            "confidence_avg": 0.952,
            "structure_score": 0.91,
            "table_count": 3,
            "heading_count": 8,
            "paragraph_count": 45,
            "source_type": "api_upload",
        },
        {
            "filename": "test_report_5pages.pdf",
            "status": "completed",
            "page_count": 5,
            "confidence_avg": 0.897,
            "structure_score": 0.88,
            "table_count": 1,
            "heading_count": 4,
            "paragraph_count": 20,
            "source_type": "watch_folder",
        },
        {
            "filename": "test_corrupted.pdf",
            "status": "failed",
            "error_code": "PDF_CORRUPTED",
            "error_message": "PDF appears to be corrupted: invalid page structure",
            "source_type": "api_upload",
        },
        {
            "filename": "test_processing.pdf",
            "status": "preprocessing",
            "source_type": "watch_folder",
        },
    ]

    async with async_session_factory() as db:
        for td in test_tasks:
            task_id = uuid.uuid4()
            task = ScanTask(
                id=task_id,
                filename=td["filename"],
                status=td["status"],
                page_count=td.get("page_count"),
                confidence_avg=td.get("confidence_avg"),
                structure_score=td.get("structure_score"),
                table_count=td.get("table_count", 0),
                heading_count=td.get("heading_count", 0),
                paragraph_count=td.get("paragraph_count", 0),
                error_code=td.get("error_code"),
                error_message=td.get("error_message"),
                source_type=td.get("source_type", "api_upload"),
                scanner_id="test_scanner",
                file_size=1024000,
                file_md5=uuid.uuid4().hex[:32],
                started_at=datetime.now(timezone.utc) if td["status"] != "pending" else None,
                completed_at=datetime.now(timezone.utc) if td["status"] == "completed" else None,
            )
            db.add(task)

            # 为已完成的任务创建步骤记录
            if td["status"] == "completed":
                steps = ["preprocessing", "ocr", "layout", "structuring", "exporting"]
                for i, step_name in enumerate(steps):
                    step = TaskStep(
                        task_id=task_id,
                        step_name=step_name,
                        status="completed",
                        duration_ms=1000 + i * 500,
                        started_at=datetime.now(timezone.utc),
                        completed_at=datetime.now(timezone.utc),
                    )
                    db.add(step)

        await db.commit()
        logger.info(f"Seeded {len(test_tasks)} test tasks")

    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(seed())
