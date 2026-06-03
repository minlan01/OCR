"""
导入现有模板数据到数据库
用法: python scripts/import_templates.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import async_session_factory
from db.models import OutputTemplate


TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "template_output")))


async def main():
    schema_path = TEMPLATE_DIR / "complaint_schema.json"
    rules_path = TEMPLATE_DIR / "通用诉状模板_规则手册.md"
    generator_path = TEMPLATE_DIR / "generate_complaint.py"

    schema_json = json.loads(schema_path.read_text(encoding="utf-8"))
    rules_md = rules_path.read_text(encoding="utf-8")
    generator_code = generator_path.read_text(encoding="utf-8")

    async with async_session_factory() as db:
        from sqlalchemy import select
        stmt = select(OutputTemplate).where(OutputTemplate.name == "医疗损害诉状")
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.schema_json = schema_json
            existing.rules_md = rules_md
            existing.generator_code = generator_code
            existing.description = "医疗损害责任纠纷民事起诉状自动生成模板"
            print(f"Template updated: {existing.id}")
        else:
            tmpl = OutputTemplate(
                name="医疗损害诉状",
                description="医疗损害责任纠纷民事起诉状自动生成模板",
                schema_json=schema_json,
                rules_md=rules_md,
                generator_code=generator_code,
            )
            db.add(tmpl)
            print(f"Template created: {tmpl.id}")

        await db.flush()
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
