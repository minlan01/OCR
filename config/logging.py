"""
ScanStruct 统一日志配置
使用 loguru，输出到控制台 + 文件

日志目录通过 settings.log_dir 配置:
- 本地开发: 默认 PROJECT_ROOT/logs
- Docker: 环境变量 LOG_DIR=/app/logs（挂载到宿主机）
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from config.settings import settings


def setup_logging() -> None:
    """配置 loguru 全局日志"""
    # 移除默认 handler
    logger.remove()

    # 日志目录（支持环境变量配置，Docker 用 /app/logs，本地开发用项目根目录/logs）
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # 控制台输出 - 开发环境彩色，生产环境简洁
    if settings.is_development:
        logger.add(
            sys.stderr,
            format=log_format,
            level="DEBUG",
            colorize=True,
            backtrace=True,
            diagnose=True,
        )
    else:
        logger.add(
            sys.stderr,
            format=log_format,
            level="INFO",
            colorize=False,
        )

    # 文件输出 - 所有级别
    logger.add(
        log_dir / "scanstruct_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="DEBUG",
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=settings.is_development,
    )

    # 错误文件单独记录
    logger.add(
        log_dir / "error_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="ERROR",
        rotation="00:00",
        retention="90 days",
        compression="gz",
        encoding="utf-8",
    )

    logger.info(f"Logging initialized | env={settings.app_env} | app={settings.app_name} | log_dir={log_dir}")
