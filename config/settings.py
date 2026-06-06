"""
ScanStruct 全局配置
基于 pydantic-settings，从 .env 和环境变量加载

安全性:
- 所有凭据字段无硬编码默认值，生产环境必须显式配置
- api_key / bailian_api_key 使用 SecretStr 防止日志泄露
- 枚举字段使用 Literal 约束，数值字段使用范围校验

可移植性:
- 所有路径、连接串通过环境变量配置，不依赖特定机器路径
- 开发环境提供合理默认值，生产环境强制校验
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录（自动推断，不依赖硬编码路径）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置，所有字段可从 .env / 环境变量覆盖"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ==================== 基础 ====================
    app_name: str = "ScanStruct"
    app_env: Literal["development", "production"] = "development"
    app_version: str = "0.1.0"

    # ==================== API ====================
    api_host: str = "0.0.0.0"
    api_port: int = 8900
    api_workers: int = 1
    api_key: SecretStr = SecretStr("")  # 生产环境必须设置，开发环境可空
    max_upload_size: int = 500 * 1024 * 1024  # 单文件上传最大 500 MB
    max_batch_upload_size: int = 5 * 1024 * 1024 * 1024  # 批量上传最大 5 GB（多文件合计）
    allowed_extensions: list[str] = [".pdf", ".mp3", ".wav", ".m4a", ".amr", ".aac"]  # 允许上传的文件扩展名

    # ==================== 数据库 ====================
    # 无硬编码默认值 — 必须通过 .env 或环境变量提供
    database_url: str = ""
    database_url_sync: str = ""
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20

    # ==================== Redis ====================
    redis_url: str = "redis://localhost:6379/0"
    redis_broker_url: str = "redis://localhost:6379/1"
    redis_result_backend: str = "redis://localhost:6379/2"
    redis_password: str = ""  # Redis 密码（生产环境建议设置）

    # ==================== MinIO ====================
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""  # 必须通过 .env 或环境变量提供
    minio_secret_key: str = ""  # 必须通过 .env 或环境变量提供
    minio_secure: bool = False
    minio_bucket_raw: str = "scan-raw"
    # TODO: 待后续阶段使用（当前仅 minio_bucket_raw 和 minio_bucket_result 被生产代码引用）
    minio_bucket_processed: str = "scan-processed"
    minio_bucket_ocr: str = "scan-ocr"
    minio_bucket_layout: str = "scan-layout"
    minio_bucket_result: str = "scan-result"

    # ==================== 存储后端 ====================
    storage_backend: Literal["minio", "local"] = "minio"
    local_storage_dir: str = str(PROJECT_ROOT / "local_storage")

    # ==================== 文件监听 ====================
    # 使用相对于 PROJECT_ROOT 的默认路径，而非硬编码 E: 盘路径
    watch_dir: str = str(PROJECT_ROOT / "scan_input")
    error_dir: str = str(PROJECT_ROOT / "scan_error")
    archive_dir: str = str(PROJECT_ROOT / "scan_archive")

    # ==================== OCR ====================
    ocr_engine_type: Literal["paddle", "bailian"] = "paddle"
    ocr_use_gpu: bool = False
    ocr_lang: str = "ch"
    ocr_gpu_mem: int = 8000
    ocr_max_pages: int = 200
    ocr_max_file_size: int = 52_428_800  # 50 MB
    ocr_batch_size: int = 100
    ocr_confidence_threshold: float = 0.70

    # ==================== 百炼 OCR (阿里云 DashScope) ====================
    bailian_api_key: SecretStr = SecretStr("")
    bailian_ocr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_ocr_model: str = "qwen-vl-ocr-latest"
    bailian_ocr_max_pixels: int = 8_388_608
    bailian_ocr_min_pixels: int = 3_072
    bailian_ocr_timeout: int = 120
    bailian_ocr_max_concurrent: int = 25
    bailian_ocr_max_rps: float = 25.0
    bailian_ocr_retry_max: int = 3

    # ==================== 百炼文本模型 (深度分析) ====================
    bailian_text_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_text_model: str = "qwen3.5-plus"
    bailian_text_timeout: int = 60
    bailian_text_max_concurrent: int = 5

    # ==================== 百炼快速模型 (分类/提取/起诉状) ====================
    bailian_flash_model: str = "deepseek-v4-flash"

    # ==================== 硅基流动 OCR 回退 (SiliconFlow) ====================
    siliconflow_api_key: SecretStr = SecretStr("")
    siliconflow_ocr_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_ocr_model: str = "deepseek-ai/DeepSeek-OCR"

    # ==================== Celery ====================
    celery_queue_name: str = "scanstruct"
    celery_task_timeout_seconds: int = 7200  # 单个任务最大执行时间（2小时）

    # ==================== LLM 限流 ====================
    llm_rate_limiter_text: int = 5   # 文本分析全局最大并发
    llm_rate_limiter_ocr: int = 10   # OCR 全局最大并发
    llm_rate_limiter_flash: int = 15  # 快速模型（分类）全局最大并发
    llm_retry_max: int = 3            # 429 重试最大次数
    llm_retry_base_delay: float = 2.0  # 429 重试基础延迟（秒）

    # ==================== LLM 上下文截断 ====================
    llm_context_material_detail_limit: int = 12000  # 关键类别材料OCR原文最大字数（鉴定/病历/死亡证明）
    llm_context_material_normal_limit: int = 5000   # 普通类别材料OCR原文最大字数
    llm_context_merged_limit: int = 60000           # 合并上下文最大字数（Slot提取）
    llm_context_slot_limit: int = 15000             # 单槽位提取上下文最大字数

    # ==================== 预处理 ====================
    preprocess_dpi: int = 300
    preprocess_deskew: bool = True
    preprocess_denoise: bool = True
    preprocess_binary: bool = False
    preprocess_crop_border: bool = True
    skip_classify: bool = False

    # ==================== 日志 ====================
    log_dir: str = str(PROJECT_ROOT / "logs")  # 日志目录（Docker 环境设为 /app/logs）

    # ==================== Callback ====================
    callback_timeout_seconds: int = 10
    callback_retry_delays: str | list[int] = [10, 30, 60]
    alert_webhook_url: str = ""

    # ==================== 业务 ====================
    max_retry_count: int = 3
    retention_days: int = 30

    # ================================================================
    # 验证器
    # ================================================================

    @field_validator("callback_retry_delays", mode="before")
    @classmethod
    def parse_retry_delays(cls, v) -> list[int]:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return v

    # ---- 生产环境必填校验 ----

    @field_validator("database_url", "database_url_sync")
    @classmethod
    def require_db_url_in_production(cls, v, info):
        """生产环境必须配置数据库 URL"""
        if info.data.get("app_env") == "production" and not v:
            raise ValueError(
                f"{info.field_name} is required when APP_ENV=production. "
                "Set it in .env or environment variable."
            )
        return v

    @field_validator("minio_access_key", "minio_secret_key")
    @classmethod
    def require_minio_creds_in_production(cls, v, info):
        """生产环境必须配置 MinIO 凭据"""
        if info.data.get("app_env") == "production" and not v:
            raise ValueError(
                f"{info.field_name} is required when APP_ENV=production. "
                "Set it in .env or environment variable."
            )
        return v

    @field_validator("api_key")
    @classmethod
    def require_api_key_in_production(cls, v, info):
        """生产环境必须配置 API Key 且长度 >= 16"""
        if info.data.get("app_env") == "production":
            key = v.get_secret_value() if isinstance(v, SecretStr) else v
            if len(key) < 16:
                raise ValueError(
                    "api_key must be at least 16 characters when APP_ENV=production."
                )
        return v

    @field_validator("bailian_api_key")
    @classmethod
    def require_bailian_key_if_selected(cls, v, info):
        """选择百炼引擎时必须配置 API Key"""
        engine_type = info.data.get("ocr_engine_type", "")
        if engine_type == "bailian":
            key = v.get_secret_value() if isinstance(v, SecretStr) else v
            if not key:
                raise ValueError(
                    "bailian_api_key is required when OCR_ENGINE_TYPE=bailian. "
                    "Set BAILIAN_API_KEY in your .env file."
                )
        return v

    # ---- 范围校验 ----

    @field_validator("api_port")
    @classmethod
    def validate_api_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"api_port must be between 1 and 65535, got {v}")
        return v

    @field_validator("api_workers")
    @classmethod
    def validate_api_workers(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"api_workers must be >= 1, got {v}")
        return v

    @field_validator("ocr_confidence_threshold")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"ocr_confidence_threshold must be 0.0-1.0, got {v}")
        return v

    @field_validator("preprocess_dpi")
    @classmethod
    def validate_dpi(cls, v: int) -> int:
        if not (72 <= v <= 1200):
            raise ValueError(f"preprocess_dpi must be 72-1200, got {v}")
        return v

    @field_validator("db_pool_size")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"db_pool_size must be >= 1, got {v}")
        return v

    @field_validator("db_pool_max_overflow")
    @classmethod
    def validate_max_overflow(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"db_pool_max_overflow must be >= 0, got {v}")
        return v

    @field_validator("retention_days")
    @classmethod
    def validate_retention(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"retention_days must be >= 0, got {v}")
        return v

    @field_validator("callback_timeout_seconds")
    @classmethod
    def validate_callback_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"callback_timeout_seconds must be > 0, got {v}")
        return v

    @field_validator("ocr_max_file_size")
    @classmethod
    def validate_max_file_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"ocr_max_file_size must be > 0, got {v}")
        return v

    # ---- URL 格式校验 ----

    @field_validator("database_url", "database_url_sync", "redis_url",
                      "redis_broker_url", "redis_result_backend")
    @classmethod
    def validate_url_format(cls, v: str, info) -> str:
        if not v:
            return v  # 空值由 require_in_production 验证器处理
        try:
            urlparse(
                v.replace("postgresql+asyncpg", "postgresql")
                 .replace("postgresql+psycopg2", "postgresql")
                 .replace("redis://:", "redis://")  # 处理密码前缀
            )
        except Exception:
            raise ValueError(f"{info.field_name} is not a valid URL: {v}")
        return v

    # ================================================================
    # 辅助属性
    # ================================================================

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def api_key_plain(self) -> str:
        """获取 API Key 明文（安全访问 SecretStr）"""
        return self.api_key.get_secret_value()

    @property
    def bailian_api_key_plain(self) -> str:
        """获取百炼 API Key 明文（安全访问 SecretStr）"""
        return self.bailian_api_key.get_secret_value()

    @property
    def siliconflow_api_key_plain(self) -> str:
        """获取硅基流动 API Key 明文（安全访问 SecretStr）"""
        return self.siliconflow_api_key.get_secret_value()

    @property
    def all_minio_buckets(self) -> list[str]:
        return [
            self.minio_bucket_raw, self.minio_bucket_processed,
            self.minio_bucket_ocr, self.minio_bucket_layout,
            self.minio_bucket_result,
        ]

    def _inject_redis_password(self, url: str) -> str:
        """为 Redis URL 注入密码（如果已配置且 URL 中尚未包含密码）"""
        if not self.redis_password:
            return url
        if "@" in url.split("://", 1)[-1]:
            return url
        return url.replace("redis://", f"redis://:{self.redis_password}@")

    @property
    def redis_url_with_auth(self) -> str:
        """构造含认证的 Redis URL（开发环境可无密码，生产环境必须）"""
        return self._inject_redis_password(self.redis_url)

    @property
    def redis_broker_url_with_auth(self) -> str:
        """Celery broker 用 Redis URL（含密码）"""
        return self._inject_redis_password(self.redis_broker_url)

    @property
    def redis_result_backend_with_auth(self) -> str:
        """Celery result backend 用 Redis URL（含密码）"""
        return self._inject_redis_password(self.redis_result_backend)


# 全局单例
settings = Settings()
