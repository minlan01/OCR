"""
MinIO Bucket 初始化脚本
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import setup_logging
from config.settings import settings
from services.storage.minio_client import minio_client
from loguru import logger


def main():
    setup_logging()
    logger.info("Initializing MinIO buckets...")

    try:
        # 检查连接
        if not minio_client.ping():
            logger.error("Cannot connect to MinIO at {settings.minio_endpoint}")
            logger.info("Make sure MinIO is running: docker-compose up -d minio")
            sys.exit(1)

        logger.info(f"Connected to MinIO at {settings.minio_endpoint}")

        # 创建所有 bucket
        minio_client.ensure_buckets()

        logger.info("All buckets created successfully!")
        for bucket in settings.all_minio_buckets:
            logger.info(f"  - {bucket}")

    except Exception as e:
        logger.error(f"Bucket initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
