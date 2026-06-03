"""
Alembic 迁移环境（异步模式）
支持 offline（生成 SQL）和 online（直接执行）两种模式
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# 确保项目根目录在 sys.path 中（解决从子目录运行 alembic 时找不到模块的问题）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从配置文件加载数据库 URL
from config.settings import settings

# 覆盖 alembic.ini 中的 sqlalchemy.url
config.set_main_option("sqlalchemy.url", settings.database_url)

# 导入所有模型，确保 Base.metadata 包含所有表
from db.session import Base
from db.models import ScanTask, TaskStep, ScanFile, OutputTemplate  # noqa: F401
from db.models_evidence import EvidenceCase, EvidenceMaterial, EvidenceStep, EvidenceRequirement  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式：仅生成 SQL 不执行
    用法: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在线模式：在给定连接上执行迁移"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    在线模式：连接数据库并执行迁移
    """
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_async_engine(url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
