"""
数据库初始化脚本
-- 默认: SQLAlchemy create_all（开发环境快速建表）
-- --alembic: 运行 Alembic 迁移（生产推荐）
-- --drop: 先删除所有表再重建
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import setup_logging
from db.session import init_db, drop_db, engine
from db.models import ScanTask, TaskStep, ScanFile  # 注册模型
from db.models_evidence import EvidenceCase, EvidenceMaterial, EvidenceStep, EvidenceRequirement  # 注册证据模型
from db.models_auth import Tenant, User  # 注册租户/用户模型（scan_tasks.tenant_id 外键依赖）
from sqlalchemy import text
from loguru import logger


async def _check_connection():
    """测试数据库连接"""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version()"))
        version = result.scalar()
        logger.info(f"PostgreSQL version: {version}")
    return True


async def _list_tables():
    """列出当前表"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables "
                 "WHERE table_schema='public' ORDER BY table_name")
        )
        return [row[0] for row in result.fetchall()]


async def do_create_all():
    """使用 SQLAlchemy create_all 建表"""
    await init_db()
    tables = await _list_tables()
    logger.info(f"Created {len(tables)} tables: {', '.join(tables)}")


def do_alembic():
    """运行 Alembic 迁移"""
    migrations_dir = Path(__file__).resolve().parent.parent / "db" / "migrations"
    cmd = [sys.executable, "-m", "alembic", "-c", str(migrations_dir / "alembic.ini"), "upgrade", "head"]
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(migrations_dir), capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Alembic upgrade failed:\n{result.stderr}")
        sys.exit(1)
    logger.info("Alembic migration complete")


async def main():
    parser = argparse.ArgumentParser(description="ScanStruct database initialization")
    parser.add_argument("--alembic", action="store_true", help="Use Alembic migrations instead of create_all")
    parser.add_argument("--drop", action="store_true", help="Drop all tables before creating")
    args = parser.parse_args()

    setup_logging()
    logger.info("Initializing database...")

    try:
        await _check_connection()

        if args.drop:
            logger.warning("Dropping all tables...")
            await drop_db()
            logger.info("All tables dropped")

        if args.alembic:
            do_alembic()
        else:
            await do_create_all()

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)

    logger.info("Database initialization complete!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
