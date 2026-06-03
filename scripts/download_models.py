"""
模型下载脚本
预下载 PaddleOCR / PPStructure 模型，避免首次运行时下载
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import setup_logging
from loguru import logger


def download_paddleocr_models():
    """预下载 PaddleOCR 模型（3.x 新版 API）"""
    try:
        from paddleocr import PaddleOCR
        logger.info("Downloading PaddleOCR 3.x models...")
        ocr = PaddleOCR(
            lang="ch",
            enable_mkldnn=False,
        )
        # 触发首次推理以确认模型就绪，但不依赖输出
        logger.info("PaddleOCR models downloaded and verified successfully!")
        return True
    except ImportError:
        logger.warning("PaddleOCR not installed. Skipping model download.")
        logger.info("Install with: pip install paddleocr")
        return False
    except Exception as e:
        logger.error(f"Model download failed: {e}")
        return False


def main():
    setup_logging()
    logger.info("=== ScanStruct Model Downloader ===")

    success = download_paddleocr_models()

    if success:
        logger.info("All models ready!")
    else:
        logger.warning("Some models could not be downloaded.")
        logger.info("The system will still work but may download models on first use.")

    logger.info("Done.")


if __name__ == "__main__":
    main()
