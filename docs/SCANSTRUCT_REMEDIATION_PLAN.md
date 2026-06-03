# ScanStruct 系统修复方案

> **版本**: v1.0  
> **日期**: 2026-05-14  
> **基于**: 4 维度审计报告（Config / API / Services / Worker），共计 ~82 项发现  
> **修复周期**: 4 轮迭代，总计 8-14 人天

---

## 目录

1. [总体策略](#1-总体策略)
2. [Round 1: 安全加固（2-3天）](#2-round-1-安全加固)
3. [Round 2: 管线可靠性（3-4天）](#3-round-2-管线可靠性)
4. [Round 3: API 加固（1-2天）](#4-round-3-api-加固)
5. [Round 4: 代码质量（3-5天）](#5-round-4-代码质量)
6. [变更影响矩阵](#6-变更影响矩阵)
7. [验收清单](#7-验收清单)

---

## 1. 总体策略

### 1.1 修复原则

| 原则 | 说明 |
|---|---|
| **安全优先** | 凭据泄露、明文密码等 CRITICAL 项必须先修 |
| **向后兼容** | 环境变量驱动变更，已部署实例仅需更新 .env |
| **渐进交付** | 每轮产出可独立部署、可独立验证的增量 |
| **测试先行** | 修复类变更尽量附带对应测试用例 |

### 1.2 分支策略

```
main ← release/0.2.0 ← fix/round-1-security
                     ← fix/round-2-pipeline
                     ← fix/round-3-api-hardening
                     ← fix/round-4-code-quality
```

### 1.3 关键文件清单

| 文件 | 角色 | 变更风险 |
|---|---|---|
| `config/settings.py` | 全局配置中心 | **高** — 所有服务依赖 |
| `docker-compose.yml` | 容器编排 | **高** — 环境变量引用调整 |
| `Dockerfile` / `Dockerfile.worker` | 镜像构建 | **高** — 需重建镜像 |
| `.env.example` | 新开发者模板 | **低** — 仅文档性质 |
| `.env` | 运行时敏感配置 | **中** — 需本地同步更新 |
| `api/middleware.py` | 认证中间件 | **中** — 涉及安全策略 |
| `api/routes/scan.py` | 核心 API | **中** — 错误消息格式变更 |
| `db/models.py` | 数据库模型 | **中** — 需生成 Alembic 迁移 |
| `services/pipeline.py` | 管线编排器 | **低** — 仅增强错误处理 |
| `services/structurer/heading_parser.py` | 标题解析 | **中** — 算法行为变更 |

---

## 2. Round 1: 安全加固

> **优先级**: CRITICAL + HIGH  
> **估算**: 2-3 人天  
> **目标**: 消除凭据泄露、Docker 安全漏洞、配置缺失

---

### FIX-1.1: 旋转百炼 API Key 并清理 .env

| 属性 | 值 |
|---|---|
| **审计编号** | Config 1.4 |
| **严重级别** | **CRITICAL** |
| **影响文件** | `.env:48`, `.env.example`, 阿里云控制台 |

**操作步骤**:

```bash
# 步骤 1 — 登录阿里云 DashScope 控制台，创建新 Key（或使用现有其他 Key）
# https://dashscope.console.aliyun.com/apiKey

# 步骤 2 — 在阿里云控制台删除旧 Key (sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)

# 步骤 3 — 更新 .env（使用新 Key）
# 编辑 .env 第 48 行，替换旧的 API Key

# 步骤 4 — 验证旧 Key 是否已失效
curl -X POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Authorization: Bearer sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -d '{"model":"qwen-vl-ocr-latest","messages":[{"role":"user","content":"test"}]}'
# 预期返回: 401 Unauthorized
```

**验证**: 启动应用后执行一次 OCR 识别任务，确认百炼引擎正常工作。

---

### FIX-1.2: 从 settings.py 移除硬编码密码默认值

| 属性 | 值 |
|---|---|
| **审计编号** | Config 1.1, 1.2 |
| **严重级别** | **CRITICAL** |
| **影响文件** | `config/settings.py:41-42, 51-52` |

**修改内容 — `config/settings.py`**:

```python
# === 修改前 (lines 41-42) ===
database_url: str = "postgresql+asyncpg://scanstruct:scanstruct123@localhost:5432/scanstruct"
database_url_sync: str = "postgresql+psycopg2://scanstruct:scanstruct123@localhost:5432/scanstruct"

# === 修改后 ===
database_url: str = ""  # 必须通过 .env 或环境变量提供
database_url_sync: str = ""  # 必须通过 .env 或环境变量提供


# === 修改前 (lines 51-52) ===
minio_access_key: str = "minioadmin"
minio_secret_key: str = "minioadmin123"

# === 修改后 ===
minio_access_key: str = ""  # 必须通过 .env 或环境变量提供
minio_secret_key: str = ""  # 必须通过 .env 或环境变量提供
```

**追加验证器** (在 `settings.py` 的 `Settings` 类中追加):

```python
from pydantic import SecretStr

# 将敏感字段改为 SecretStr
api_key: SecretStr = SecretStr("")
database_url: str = ""
database_url_sync: str = ""
minio_access_key: str = ""
minio_secret_key: str = ""
bailian_api_key: SecretStr = SecretStr("")

@field_validator("database_url", "database_url_sync")
@classmethod
def require_db_url_in_production(cls, v, info):
    """生产环境必须配置数据库 URL"""
    if info.data.get("app_env") == "production" and not v:
        raise ValueError(
            "database_url is required when APP_ENV=production. "
            "Set it in .env or environment variable."
        )
    return v

@field_validator("minio_access_key", "minio_secret_key")
@classmethod
def require_minio_creds_in_production(cls, v, info):
    """生产环境必须配置 MinIO 凭据"""
    field_name = info.field_name
    if info.data.get("app_env") == "production" and not v:
        raise ValueError(
            f"{field_name} is required when APP_ENV=production. "
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
```

**注意**: 引入 `SecretStr` 后，所有访问 `settings.api_key` 的代码需调用 `.get_secret_value()`。受影响的文件：

- `api/middleware.py:37,61` — 需改为 `settings.api_key.get_secret_value()`
- `services/ocr/bailian_engine.py` — 需改为 `settings.bailian_api_key.get_secret_value()`

**验证**: 启动应用时不提供 .env，应报错 `database_url is required`。

---

### FIX-1.3: Docker 镜像多阶段构建 + 非 root 用户

| 属性 | 值 |
|---|---|
| **审计编号** | Config 3.1, 3.2 |
| **严重级别** | **CRITICAL** |
| **影响文件** | `Dockerfile`, `Dockerfile.worker` |

**新 `Dockerfile`**:

```dockerfile
# =====================================================
# Stage 1: Builder — 安装系统依赖 + Python 包
# =====================================================
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# 系统构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（安装到 /install 目录）
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# =====================================================
# Stage 2: Runtime — 最小运行时镜像
# =====================================================
FROM python:3.12-slim

LABEL app="ScanStruct API"
LABEL version="0.1.0"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APP_ENV=production

# 运行时系统依赖（无开发头文件）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r scanstruct -g 10000 \
    && useradd -r -u 10000 -g scanstruct -d /app -s /sbin/nologin scanstruct

WORKDIR /app

# 从 builder 复制 Python 包
COPY --from=builder /install /usr/local/lib/python3.12/site-packages

# 复制应用代码
COPY --chown=scanstruct:scanstruct . .

# 创建数据目录并设置权限
RUN mkdir -p /app/scan_input /app/scan_error /app/scan_archive \
    && chown -R scanstruct:scanstruct /app

# 追加 HEALTHCHECK
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8900/api/v1/health')" || exit 1

USER scanstruct

EXPOSE 8900

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8900"]
```

**新 `Dockerfile.worker`**:

```dockerfile
# =====================================================
# Stage 1: Builder
# =====================================================
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# =====================================================
# Stage 2: Runtime
# =====================================================
FROM python:3.12-slim

LABEL app="ScanStruct Worker"
LABEL version="0.1.0"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r scanstruct -g 10000 \
    && useradd -r -u 10000 -g scanstruct -d /app -s /sbin/nologin scanstruct

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.12/site-packages

COPY --chown=scanstruct:scanstruct . .

RUN mkdir -p /app/scan_input /app/scan_error /app/scan_archive \
    && chown -R scanstruct:scanstruct /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD celery -A worker.celery_app inspect ping -d celery@$(hostname) || exit 1

USER scanstruct

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
```

**验证**:
```bash
# 构建并检查
docker build -t scanstruct-api .
docker run --rm scanstruct-api id
# 预期输出: uid=10000(scanstruct) gid=10000(scanstruct)
```

---

### FIX-1.4: docker-compose.yml 凭据外部化 ✅ 已完成

| 属性 | 值 |
|---|---|
| **状态** | ✅ **已完成** (2026-05-19) |
| **审计编号** | Config 5.3 |
| **严重级别** | **HIGH** |
| **影响文件** | `docker-compose.yml`, `.env.docker` (新建), `.env.example`, `.gitignore` |

**新建 `.env.docker` 文件** (Docker Compose 环境变量):

```bash
# ============================================
# Docker Compose 变量 — 不包含在此文件中的凭据
# 必须通过环境变量覆盖
# ============================================

# PostgreSQL
POSTGRES_USER=scanstruct
POSTGRES_PASSWORD=change_me_in_production_use_32char_random
POSTGRES_DB=scanstruct

# Redis
REDIS_PASSWORD=change_me_in_production_use_32char_random

# MinIO
MINIO_ROOT_USER=minio_admin
MINIO_ROOT_PASSWORD=change_me_in_production_use_32char_random

# API
API_KEY=change_me_in_production_at_least_32char

# OCR Engine
OCR_ENGINE_TYPE=paddle
BAILIAN_API_KEY=
```

**修改 `docker-compose.yml`** (以 PostgreSQL + Redis + MinIO 为例):

```yaml
  postgres:
    image: postgres:16-alpine
    container_name: scanstruct-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-scanstruct}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?err}
      POSTGRES_DB: ${POSTGRES_DB:-scanstruct}
    # ... rest unchanged

  redis:
    image: redis:7-alpine
    container_name: scanstruct-redis
    command: redis-server --requirepass ${REDIS_PASSWORD:?err}
    # ... rest unchanged

  minio:
    image: minio/minio:RELEASE.2024-08-17T01-24-54Z  # 固定版本
    container_name: scanstruct-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minio_admin}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?err}
    # ... rest unchanged

  api:
    environment:
      APP_ENV: production
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-scanstruct}:${POSTGRES_PASSWORD:?err}@postgres:5432/${POSTGRES_DB:-scanstruct}
      DATABASE_URL_SYNC: postgresql+psycopg2://${POSTGRES_USER:-scanstruct}:${POSTGRES_PASSWORD:?err}@postgres:5432/${POSTGRES_DB:-scanstruct}
      REDIS_URL: redis://:${REDIS_PASSWORD:?err}@redis:6379/0
      REDIS_BROKER_URL: redis://:${REDIS_PASSWORD:?err}@redis:6379/1
      REDIS_RESULT_BACKEND: redis://:${REDIS_PASSWORD:?err}@redis:6379/2
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_ROOT_USER:-minio_admin}
      MINIO_SECRET_KEY: ${MINIO_ROOT_PASSWORD:?err}
      API_KEY: ${API_KEY:?err}
      # ... rest unchanged
```

**Redis URL 格式变更** (含密码): 确认 `config/settings.py` 的默认值同步更新:

```python
# Redis URL 模板（开发环境默认无密码）
redis_url: str = "redis://localhost:6379/0"
# 生产环境示例: redis://:your_password@redis-host:6379/0
```

**验证**: `docker compose --env-file .env.docker config` 不输出明文密码（docker compose 默认遮蔽敏感值）。

---

### FIX-1.5: Redis 密码支持

| 属性 | 值 |
|---|---|
| **审计编号** | Config 1.3 |
| **严重级别** | **MEDIUM** |
| **影响文件** | `config/settings.py:45-47`, `docker-compose.yml:27-41` |

**修改 `config/settings.py`**:

```python
# 在 Settings 类中追加属性
redis_password: str = ""  # Redis 密码（生产环境必须设置）

@property
def redis_url_with_auth(self) -> str:
    """构造含认证的 Redis URL"""
    if not self.redis_password:
        return self.redis_url
    # 在 redis:// 后插入密码
    return self.redis_url.replace("redis://", f"redis://:{self.redis_password}@")

@property
def redis_broker_url_with_auth(self) -> str:
    if not self.redis_password:
        return self.redis_broker_url
    return self.redis_broker_url.replace("redis://", f"redis://:{self.redis_password}@")
```

**验证**: 启动 Redis 容器时设置 `--requirepass`，确认应用连接到带密码的 Redis。

---

### FIX-1.6: .env.example 补全 + 分类注释

| 属性 | 值 |
|---|---|
| **审计编号** | Config 5.2 |
| **严重级别** | **HIGH** |
| **影响文件** | `.env.example` |

**重写 `.env.example`**:

```bash
# ============================================================
# ScanStruct 环境配置模板
# ============================================================
# 使用说明:
#   1. 复制此文件为 .env:  cp .env.example .env
#   2. 修改标注 [REQUIRED] 的字段
#   3. 生产环境: 使用 openssl rand -hex 32 生成随机密码
#
# 标记说明: [REQUIRED]=生产必填 [OPTIONAL]=可选 [DEV]=仅开发
# ============================================================

# ---------- 基础 ----------
APP_NAME=ScanStruct
APP_ENV=development            # [REQUIRED] development | production
APP_VERSION=0.1.0

# ---------- API 服务 ----------
API_HOST=0.0.0.0
API_PORT=8900
API_WORKERS=1
API_KEY=                       # [REQUIRED/production] 至少 32 字符的 API Key

# ---------- PostgreSQL ----------
DATABASE_URL=postgresql+asyncpg://scanstruct:change_me@localhost:5432/scanstruct    # [REQUIRED]
DATABASE_URL_SYNC=postgresql+psycopg2://scanstruct:change_me@localhost:5432/scanstruct  # [REQUIRED]

# ---------- Redis ----------
REDIS_URL=redis://localhost:6379/0                     # [REQUIRED]
REDIS_BROKER_URL=redis://localhost:6379/1              # [REQUIRED] Celery broker
REDIS_RESULT_BACKEND=redis://localhost:6379/2          # [REQUIRED] Celery result backend
REDIS_PASSWORD=                                        # [OPTIONAL] 生产环境建议设置

# ---------- MinIO ----------
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=change_me                              # [REQUIRED]
MINIO_SECRET_KEY=change_me                              # [REQUIRED]
MINIO_SECURE=false
MINIO_BUCKET_RAW=scan-raw
MINIO_BUCKET_PROCESSED=scan-processed
MINIO_BUCKET_OCR=scan-ocr
MINIO_BUCKET_LAYOUT=scan-layout
MINIO_BUCKET_RESULT=scan-result

# ---------- 文件监听 ----------
WATCH_DIR=E:/OCRScanStruct/scan_input
ERROR_DIR=E:/OCRScanStruct/scan_error
ARCHIVE_DIR=E:/OCRScanStruct/scan_archive

# ---------- OCR 引擎 ----------
OCR_ENGINE_TYPE=paddle         # [REQUIRED] paddle | bailian
OCR_USE_GPU=false
OCR_LANG=ch
OCR_GPU_MEM=8000
OCR_MAX_PAGES=200
OCR_MAX_FILE_SIZE=52428800
OCR_BATCH_SIZE=4
OCR_CONFIDENCE_THRESHOLD=0.70  # 0.0 ~ 1.0

# ---------- 百炼 OCR (仅 OCR_ENGINE_TYPE=bailian 时需要) ----------
BAILIAN_API_KEY=               # [REQUIRED if bailian] 阿里云 DashScope API Key
BAILIAN_OCR_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_OCR_MODEL=qwen-vl-ocr-latest
BAILIAN_OCR_MAX_PIXELS=8388608
BAILIAN_OCR_MIN_PIXELS=3072
BAILIAN_OCR_TIMEOUT=60         # API 超时秒数

# ---------- 预处理 ----------
PREPROCESS_DPI=300             # 72 ~ 1200
PREPROCESS_DESKEW=true
PREPROCESS_DENOISE=true
PREPROCESS_BINARY=false
PREPROCESS_CROP_BORDER=true

# ---------- 回调 ----------
CALLBACK_TIMEOUT_SECONDS=10
CALLBACK_RETRY_DELAYS=10,30,60
ALERT_WEBHOOK_URL=

# ---------- 业务 ----------
MAX_RETRY_COUNT=3
RETENTION_DAYS=30
```

**验证**: `diff <(grep -oP '^\w+' .env | sort) <(grep -oP '^\w+' .env.example | sort)` 应完全一致。

---

### FIX-1.7: 百炼 API Key 跨字段验证

| 属性 | 值 |
|---|---|
| **审计编号** | Config 2.1 |
| **严重级别** | **HIGH** |
| **影响文件** | `config/settings.py` |

**追加验证器**:

```python
@field_validator("bailian_api_key")
@classmethod
def require_bailian_key_if_selected(cls, v, info):
    engine_type = info.data.get("ocr_engine_type", "")
    if engine_type == "bailian":
        key = v.get_secret_value() if isinstance(v, SecretStr) else v
        if not key:
            raise ValueError(
                "bailian_api_key is required when OCR_ENGINE_TYPE=bailian. "
                "Set BAILIAN_API_KEY in your .env file."
            )
    return v
```

**验证**: 设置 `OCR_ENGINE_TYPE=bailian` 但 `BAILIAN_API_KEY=` 空，启动应失败。

---

### FIX-1.8: 配置枚举约束 + 范围验证

| 属性 | 值 |
|---|---|
| **审计编号** | Config 2.2, 2.3, 2.5 |
| **严重级别** | **MEDIUM** |
| **影响文件** | `config/settings.py` |

**追加到 Settings 类**:

```python
from typing import Literal
from pydantic import AnyUrl, field_validator

# 替换原有字段类型
app_env: Literal["development", "production"] = "development"
ocr_engine_type: Literal["paddle", "bailian"] = "paddle"

# 追加范围验证器
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

# URL 格式验证
@field_validator("database_url", "database_url_sync", "redis_url",
                  "redis_broker_url", "redis_result_backend")
@classmethod
def validate_url_format(cls, v: str, info) -> str:
    if not v:
        return v  # 空值由 require_in_production 验证器处理
    try:
        # 将 postgresql+asyncpg 转为标准 URL 解析
        from urllib.parse import urlparse
        urlparse(v.replace("postgresql+asyncpg", "postgresql")
                  .replace("postgresql+psycopg2", "postgresql"))
    except Exception:
        raise ValueError(f"{info.field_name} is not a valid URL: {v}")
    return v
```

---

## 3. Round 2: 管线可靠性

> **优先级**: HIGH (Services audit)  
> **估算**: 3-4 人天  
> **目标**: 补齐核心模块错误处理、测试覆盖、性能修复

---

### FIX-2.1: pipeline.py 增加错误处理

| 属性 | 值 |
|---|---|
| **审计编号** | Services 2.2 |
| **严重级别** | **HIGH** |
| **影响文件** | `services/pipeline.py:18-39` |

**修改后代码**:

```python
"""
处理管线编排器
同步模式（MVP 阶段）/ 异步模式（Celery 阶段）
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from loguru import logger

from config.settings import settings


class PipelineOrchestrator:
    """处理管线编排器

    提供两个调度入口：
    - run_sync: 同步派发（Celery delay，任意 worker 消费）
    - run_async: 指定队列派发（Celery apply_async，scanstruct 队列）
    """

    async def run_sync(self, task_id: UUID) -> str | None:
        """
        同步派发完整管线到 Celery（任意 worker 消费）

        Args:
            task_id: 扫描任务 UUID

        Returns:
            Celery 任务 ID，派发失败返回 None

        Raises:
            RuntimeError: Celery 不可用时
        """
        logger.info(f"Pipeline sync dispatch: task_id={task_id}")

        try:
            from worker.tasks import process_scan
        except ImportError as e:
            logger.error(f"Cannot import Celery tasks: {e}")
            raise RuntimeError(
                "Celery worker.tasks module not importable. "
                "Ensure the worker package is in PYTHONPATH."
            ) from e

        try:
            result = process_scan.delay(str(task_id))
            logger.info(
                f"Pipeline queued: task_id={task_id}, celery_id={result.id}"
            )
            return result.id
        except Exception as e:
            logger.error(
                f"Failed to dispatch task {task_id} to Celery: {e}",
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to queue task {task_id}: {e}"
            ) from e

    async def run_async(self, task_id: UUID) -> str | None:
        """
        异步派发到指定队列 scanstruct

        Args:
            task_id: 扫描任务 UUID

        Returns:
            Celery 任务 ID，派发失败返回 None
        """
        logger.info(f"Pipeline async dispatch: task_id={task_id}")

        try:
            from worker.tasks import process_scan
        except ImportError as e:
            logger.error(f"Cannot import Celery tasks: {e}")
            raise RuntimeError("Celery worker.tasks module not importable.") from e

        try:
            result = process_scan.apply_async(
                args=[str(task_id)],
                queue=settings.celery_queue_name
                if hasattr(settings, "celery_queue_name")
                else "scanstruct",
            )
            logger.info(
                f"Pipeline dispatched: task_id={task_id}, celery_id={result.id}"
            )
            return result.id
        except Exception as e:
            logger.error(
                f"Failed to dispatch async task {task_id} to Celery: {e}",
                exc_info=True,
            )
            raise RuntimeError(
                f"Failed to queue async task {task_id}: {e}"
            ) from e
```

同时需要在 `config/settings.py` 追加:

```python
# Celery 配置
celery_queue_name: str = "scanstruct"
celery_task_timeout_seconds: int = 3600  # 单个任务最大执行时间（1小时）
```

**验证**: Mock Celery 不可用场景，确认 pipeline.py 抛出 `RuntimeError` 而非原始 `ImportError`/`ConnectionError`。

---

### FIX-2.2: watcher.py 异步 sleep 修复

| 属性 | 值 |
|---|---|
| **审计编号** | Services 3.6-3 |
| **严重级别** | **HIGH** |
| **影响文件** | `services/scan_in/watcher.py:43` |

**修改内容**:

```python
# === 修改前 (line 43) ===
        time.sleep(STABLE_CHECK_INTERVAL)

# === 修改后 ===
        await asyncio.sleep(STABLE_CHECK_INTERVAL)

# === 同时将 _is_file_stable 改为 async ===
# 函数签名改为:
async def _is_file_stable(file_path: Path) -> bool:
    """检查文件是否写入完成（连续 N 次大小不变）"""
    last_size = -1
    stable_count = 0
    for _ in range(STABLE_CHECK_COUNT + 1):
        try:
            current_size = file_path.stat().st_size
        except OSError:
            return False
        if current_size == last_size:
            stable_count += 1
        else:
            stable_count = 0
        last_size = current_size
        if stable_count >= STABLE_CHECK_COUNT:
            return True
        await asyncio.sleep(STABLE_CHECK_INTERVAL)  # 改为异步 sleep
    return False

# === handle_new_file 中的调用也改为 await ===
# Line 94:
if not await _is_file_stable(file_path):
```

**验证**: 检查日志 `asyncio` 没有 "Executing took X seconds" 的阻塞警告。

---

### FIX-2.3: heading_parser.py 完整实现

| 属性 | 值 |
|---|---|
| **审计编号** | Services 3.7-1 |
| **严重级别** | **HIGH** |
| **影响文件** | `services/structurer/heading_parser.py` (27行 → ~150行) |

**策略**: 在原有正则匹配基础上，增加字体大小推断、加粗居中启发式、页面顶部位置推断。

**关键变更点**:
1. 在 `detect_heading_level()` 增加参数 `font_size`, `is_bold`, `is_centered`, `bbox`
2. 字体策略: 收集所有文本块字体大小，找中位数；标题字体 > 1.3x 中位数 → 提升级别
3. 中文居中标题（x 坐标在页面中央 10% 范围内）→ 标记为 H2 候选
4. 页面顶部位置（bbox[1] < 页面高度 5%）→ H1 候选
5. 支持 Western 模式: `Chapter X`, `Section X.Y`, `X. Title`, `(a)` 等

完整实现代码见本方案附录或直接从 git 分支获取。

**验证**: 用包含混合中西文标题的测试 PDF 验证解析准确率 > 85%。

---

### FIX-2.4: 补齐缺失的测试覆盖 (8个模块)

| 审计编号 | Services 3.1 |
|---|---|
| **严重级别** | **HIGH** |
| **影响文件** | `tests/` 目录，新建 8 个测试文件 |

**新增测试文件清单**:

| # | 新建文件 | 被测模块 | 最小测试用例数 |
|---|---|---|---|
| 1 | `tests/test_ocr_engine.py` | `services/ocr/engine.py` | 5 (加载、识别、置信度过滤、空输入、GPU/CPU切换) |
| 2 | `tests/test_minio_client.py` | `services/storage/minio_client.py` | 6 (连接、上传、下载、删除、预签名URL、桶管理) |
| 3 | `tests/test_image_enhancer.py` | `services/preprocessor/image_enhancer.py` | 4 (降噪、二值化、黑边裁切、纠偏) |
| 4 | `tests/test_pdf_classifier.py` | `services/preprocessor/pdf_classifier.py` | 4 (扫描件检测、文本PDF检测、混合类型、损坏文件) |
| 5 | `tests/test_text_pdf_extractor.py` | `services/preprocessor/text_pdf_extractor.py` | 4 (纯文本提取、结构化提取、空文档、大字体检测) |
| 6 | `tests/test_validator.py` | `services/scan_in/validator.py` | 6 (扩展名、文件大小、页数、加密检测、损坏检测、跳过原因) |
| 7 | `tests/test_watcher.py` | `services/scan_in/watcher.py` | 3 (文件创建、稳定性检测、错误处理) |
| 8 | `tests/test_deskew.py` | `services/preprocessor/deskew.py` | 1 (基础功能，该模块仅重导出) |

**验证**: `pytest --cov=services --cov-report=term-missing` 覆盖率从 65% → 90%+。

---

### FIX-2.5: Redis 连接池 (stream_publisher.py)

| 审计编号 | Services 3.6-2 |
|---|---|
| **严重级别** | **MEDIUM** |
| **影响文件** | `services/exporter/stream_publisher.py` |

**修改**: `_get_redis()` 每次调用创建新连接 → 使用模块级连接池

```python
# 在模块顶部替换 _get_redis():
import redis.asyncio as aioredis

_pool: aioredis.ConnectionPool | None = None

def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url_with_auth if hasattr(settings, 'redis_url_with_auth') else settings.redis_url,
            max_connections=10,
            socket_connect_timeout=2,
        )
    return _pool

def _get_redis():
    """获取 Redis 连接（从连接池）"""
    return aioredis.Redis(connection_pool=_get_pool())
```

**验证**: 连续发布 100 条消息，确认仅创建 1 个 TCP 连接（netstat 验证）。

---

### FIX-2.6: Celery 任务超时 + async 修复

| 审计编号 | Config/Worker |
|---|---|
| **严重级别** | **CRITICAL** |
| **影响文件** | `worker/celery_app.py`, `worker/tasks.py` |

**修改 1 — Celery 配置增加任务超时**:

```python
# worker/celery_app.py 追加配置
app.conf.update(
    task_soft_time_limit=3300,   # 55分钟软超时 (抛出 SoftTimeLimitExceeded)
    task_time_limit=3600,        # 60分钟硬超时 (SIGKILL)
    task_acks_late=True,         # 任务完成后才 ACK (防止超时后重投)
    task_reject_on_worker_lost=True,
)
```

**修改 2 — 检查 worker/tasks.py 中 `asyncio.run()` 使用**:

```python
# === 问题模式 ===
# asyncio.run(some_async_function())  # 阻塞 Celery solo pool

# === 修复 ===
# 如果 --pool=solo，直接 await：
# async def process_scan(self, task_id_str: str):
#     ...
# 如果必须同步调用异步代码，使用 nest_asyncio 或重构
```

**验证**: 提交一个超大 PDF（>200 页），确认任务在 55 分钟时收到 `SoftTimeLimitExceeded`，60 分钟时被强制终止。

---

## 4. Round 3: API 加固

> **优先级**: MEDIUM (API audit)  
> **估算**: 1-2 人天  
> **目标**: 消除信息泄露、加固认证、规范化响应

---

### FIX-3.1: 异常消息泄露修复 (5处)

| 审计编号 | API M4, M5 |
|---|---|
| **严重级别** | **MEDIUM** |
| **影响文件** | `api/routes/scan.py:160,405,415,515`, `api/routes/health.py:38,49,62` |

**修复规则**: 面向用户的消息不包含 `{e}` 详情；完整错误仅写入日志。

| 文件:行号 | 修改前 | 修改后 |
|---|---|---|
| `scan.py:160` | `f"Failed to read file: {e}"` | `"Failed to read uploaded file"` |
| `scan.py:405` | `f"Failed to retrieve result from storage: {e}"` | `"Failed to retrieve processing result"` |
| `scan.py:415` | `f"Result file is corrupted: {e}"` | `"Result data is corrupted, please retry"` |
| `scan.py:515` | `f"Failed to dispatch retry task: {e}"` | `"Failed to dispatch retry task"` |
| `health.py:38` | `f"error: {e}"` | `"unhealthy"` |
| `health.py:49` | `f"error: {e}"` | `"unhealthy"` |
| `health.py:62` | `f"error: {e}"` | `"unhealthy"` |

**验证**: 模拟 MinIO 不可用场景，确认 HTTP 响应中不含 `AccessDenied`、`Connection refused` 等内部详情。

---

### FIX-3.2: 常量时间 API Key 对比

| 审计编号 | API M1 |
|---|---|
| **严重级别** | **MEDIUM** |
| **影响文件** | `api/middleware.py:61` |

**修改**:

```python
# === 修改前 ===
import secrets  # 追加到文件顶部导入

# Line 61: 修改前
if api_key != settings.api_key:

# Line 61: 修改后
if not secrets.compare_digest(api_key, settings.api_key.get_secret_value()):
```

**验证**: 单元测试验证不同长度 key 的比较不泄露时间信息。

---

### FIX-3.3: 请求频率限制 (Rate Limiting)

| 审计编号 | API M2 |
|---|---|
| **严重级别** | **MEDIUM** |
| **影响文件** | `api/main.py`, 新建 `api/rate_limit.py` |

**方案**: 使用 `slowapi` (FastAPI 兼容)

```python
# api/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# api/main.py
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 对认证端点收紧限制
@router.post("/scans/upload")
@limiter.limit("10/minute")  # 上传接口: 10次/分钟
async def upload_scan(...):
    ...
```

**验证**: 快速连续发送 11 个 POST 请求到 `/scans/upload`，第 11 个返回 429。

---

### FIX-3.4: Content-Type 校验

| 审计编号 | API M3 |
|---|---|
| **严重级别** | **MEDIUM** |
| **影响文件** | `api/routes/scan.py:140-160` |

**修改**: 在扩展名校验之后立即追加 Content-Type 校验

```python
# 在 scan.py 的 upload_scan 函数中，line 154 之后追加:
    # 1.5. 校验 Content-Type
    ALLOWED_CONTENT_TYPES = {"application/pdf"}
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type. Expected: application/pdf",
        )
```

**验证**: 上传一个 `Content-Type: image/png` 但文件名为 `.pdf` 的请求，返回 400。

---

### FIX-3.5: 全局异常处理器

| 审计编号 | API I5 |
|---|---|
| **严重级别** | **INFO** |
| **影响文件** | `api/main.py` |

```python
# api/main.py 追加
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器：防止 traceback 泄露"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
    )
```

---

### FIX-3.6: 缺失的响应模型

| 审计编号 | API L1-L3 |
|---|---|
| **严重级别** | **LOW** |
| **影响文件** | `api/schemas/common.py`, `api/routes/health.py`, `api/routes/scan.py`, `api/routes/admin.py` |

**新增 Schema**:

```python
# api/schemas/common.py 追加

class PingResponse(BaseModel):
    ping: str = "pong"
    time: float
    host: str

class AdminStatsResponse(BaseModel):
    total_tasks: int
    today_tasks: int
    failed_tasks: int
    avg_confidence: float | None
    by_status: dict[str, int]

class AdminQueueResponse(BaseModel):
    total_pending: int
    items: list[ScanTaskSummary]

class ScanResultResponse(BaseModel):
    """内联返回的扫描结果"""
    task_id: str
    status: str
    result: dict

# 分别应用到对应的路由 endpoint 的 response_model 参数
```

**验证**: `/api/docs` 中 Swagger 展示完整的响应 Schema。

---

## 5. Round 4: 代码质量

> **优先级**: MEDIUM/LOW (Services audit cross-cutting)  
> **估算**: 3-5 人天  
> **目标**: 消除重复代码、提取共享模块、完善文档

---

### FIX-4.1: 提取共享工具模块 `services/utils/`

| 审计编号 | Services 3.5-2, 3.8 |
|---|---|
| **影响文件** | 新建 3 个文件 |

**新建文件清单**:

| 文件 | 内容 | 替代的分散代码位置 |
|---|---|---|
| `services/utils/__init__.py` | 包标记 | — |
| `services/utils/bbox.py` | `normalize_bbox()`, `bbox_to_rect()`, `rect_to_bbox()`, `bbox_overlap()` | `detector.py`, `reading_order.py`, `table_recognizer.py`, `header_footer_cleaner.py`, `list_detector.py`, `paragraph_grouper.py` (6 处) |
| `services/utils/text_patterns.py` | `PAGE_NUMBER_PATTERN`, `TERMINAL_PUNCTUATION`, `is_page_number()`, `ends_with_terminal()` | `cross_page_merger.py`, `header_footer_cleaner.py`, `paragraph_grouper.py`, `list_detector.py` (4 处) |
| `services/constants.py` | `DEFAULT_PAGE_WIDTH=2480`, `DEFAULT_PAGE_HEIGHT=3508`, `BASE_DPI=72`, `DEFAULT_DPI=300`, 所有魔法数字 | `detector.py`, `reading_order.py`, `header_footer_cleaner.py`, `pdf_splitter.py`, `quality_scorer.py` (5+ 处) |

**重构后**: 从各模块删除重复代码，改为 `from services.utils.bbox import normalize_bbox` 等。

**验证**: `grep -r "isinstance(bbox\[0\], list)" services/` 仅在 `services/utils/bbox.py` 中出现。

---

### FIX-4.2: 清理未使用的代码

| 审计编号 | API L4-L5 |
|---|---|
| **影响文件** | `api/schemas/scan.py`, `services/preprocessor/deskew.py` |

| 删除项 | 文件 | 原因 |
|---|---|---|
| `ScanUploadRequest` | `api/schemas/scan.py` | 从未被导入或使用 |
| `ScanListQuery` | `api/schemas/scan.py` | 从未被导入或使用 |
| `deskew.py` 整个文件 | `services/preprocessor/deskew.py` | 仅重导出 `Deskewer`；调用方改为直接 `from services.preprocessor.image_enhancer import Deskewer` |

**验证**: `rg "ScanUploadRequest\|ScanListQuery" api/ services/` 仅出现在 `schemas/scan.py` 中，无外部引用。

---

### FIX-4.3: 模块级 `import re` / `import statistics` 提升

| 审计编号 | Services 3.9-3 |
|---|---|
| **影响文件** | `layout/detector.py:302`, `quality_scorer.py:236` |

**修改**: 将函数内的 `import re` / `import statistics` 移至模块顶部。

```python
# layout/detector.py 顶部追加
import re

# quality_scorer.py 顶部追加
import statistics
```

---

### FIX-4.4: 数据库模型增强

| 审计编号 | Config 4.2.1-4.2.6 |
|---|---|
| **影响文件** | `db/models.py`, Alembic 迁移脚本 |

| # | 变更 | 文件:行号 | SQL |
|---|---|---|---|
| 1 | `confidence_avg` 改为 `Numeric(4,3)` + CHECK `BETWEEN 0 AND 1` | `models.py:47` | `ALTER TABLE scan_tasks ADD CONSTRAINT ck_confidence_range CHECK (confidence_avg BETWEEN 0 AND 1)` |
| 2 | `structure_score` 改为 `Numeric(4,3)` + CHECK | `models.py:48` | 同上模式 |
| 3 | `task_steps` 增加 `UNIQUE(task_id, step_name)` | `models.py:111` | 添加 `UniqueConstraint` |
| 4 | `scan_files` 增加 `updated_at` 列 | `models.py:135` | `ALTER TABLE scan_files ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW()` |
| 5 | `scan_files` 增加复合索引 `(task_id, file_type)` | `models.py:142` | `CREATE INDEX idx_scan_files_task_type ON scan_files(task_id, file_type)` |
| 6 | `status` 列增加 CHECK 约束 | `models.py:37,98` | `CHECK (status IN ('pending','received','processing','completed','failed','cancelled','retrying'))` |

**验证**: 执行 `alembic upgrade head` 无错误，确认约束生效。

---

### FIX-4.5: docstring 补全

| 审计编号 | Services 3.3 |
|---|---|
| **影响文件** | 15 个 "Minimal" 评级模块 |

**补全优先级**:

| 优先级 | 文件 | 最小要求 |
|---|---|---|
| P0 | `services/pipeline.py` | 方法级 Args/Returns/Raises |
| P0 | `services/exporter/callback.py` | 函数级 docstring |
| P0 | `services/exporter/json_exporter.py` | 函数级 docstring |
| P0 | `services/preprocessor/image_enhancer.py` | 每个方法一行描述 |
| P1 | `services/preprocessor/pdf_classifier.py` | `classify()` 的 Returns 描述 |
| P1 | `services/preprocessor/pdf_splitter.py` | `split_to_bytes()` docstring |
| P1 | `services/preprocessor/text_pdf_extractor.py` | `extract_structured()` Returns |
| P2 | 其余 Minimal 模块 | 至少模块级 docstring |

---

### FIX-4.6: table_recognizer.py HTML 增强

| 审计编号 | Services 3.7-3 |
|---|---|
| **影响文件** | `services/layout/table_recognizer.py` |

**变更**:
1. 实现 `merge_info` 参数 → 支持 `colspan`/`rowspan`
2. HTML 增加 `<thead>`/`<tbody>` 语义标签
3. 输出 `class="scanstruct-table"` → 改为参数化
4. 去掉 `border="1" cellpadding="4" cellspacing="0"` → CSS 类控制

---

## 6. 变更影响矩阵

| Fix # | 影响文件数 | DB 迁移 | 需要重启 | 需要重建镜像 | 回滚复杂度 |
|---|---|---|---|---|---|
| FIX-1.1 | 1 (.env) | N | N | N | **低** |
| FIX-1.2 | 3 (settings, middleware, bailian) | N | Y | N | **中** (SecretStr API 变更) |
| FIX-1.3 | 2 (Dockerfile x2) | N | Y | Y | **低** |
| FIX-1.4 | 2 (compose, .env.docker) | N | Y | Y | **中** |
| FIX-1.5 | 2 (settings, compose) | N | Y | N | **低** |
| FIX-1.6 | 1 (.env.example) | N | N | N | **无** |
| FIX-1.7 | 1 (settings) | N | Y | N | **低** |
| FIX-1.8 | 1 (settings) | N | Y | N | **低** |
| FIX-2.1 | 2 (pipeline, settings) | N | Y | N | **低** |
| FIX-2.2 | 1 (watcher) | N | Y | N | **低** |
| FIX-2.3 | 1 (heading_parser) | N | Y | N | **中** (行为变更) |
| FIX-2.4 | 8 (tests) | N | N | N | **无** |
| FIX-2.5 | 1 (stream_publisher) | N | Y | N | **低** |
| FIX-2.6 | 2 (celery_app, tasks) | N | Y | N | **低** |
| FIX-3.1 | 2 (scan, health) | N | Y | N | **无** (消息格式变更) |
| FIX-3.2 | 1 (middleware) | N | Y | N | **低** |
| FIX-3.3 | 2 (main, rate_limit) | N | Y | N | **低** |
| FIX-3.4 | 1 (scan) | N | Y | N | **无** |
| FIX-3.5 | 1 (main) | N | Y | N | **无** |
| FIX-3.6 | 4 (schemas, health, scan, admin) | N | Y | N | **低** |
| FIX-4.1 | 10+ (新建3 + 修改7+) | N | Y | N | **中** (重构影响面大) |
| FIX-4.2 | 3 | N | Y | N | **低** |
| FIX-4.3 | 2 | N | Y | N | **无** |
| FIX-4.4 | 2 (models + migration) | **Y** | Y | N | **高** (涉及生产数据) |
| FIX-4.5 | 15 | N | N | N | **无** |
| FIX-4.6 | 1 | N | Y | N | **低** |

---

## 7. 验收清单

### Round 1 验收 (安全加固)

- [x] `.env` 中的旧百炼 API Key 已在阿里云控制台删除，应用使用新 Key
- [x] `settings.py` 中所有凭据字段无硬编码默认值，生产环境需显式配置
- [x] `docker run --rm scanstruct-api id` 输出 `uid=10000(scanstruct)`
- [x] `docker compose config` 不输出明文密码
- [x] 启动 Redis（含 `requirepass`）后应用正常连接
- [x] `.env.example` 包含所有配置字段，标注 [REQUIRED] / [OPTIONAL]
- [x] 设置 `OCR_ENGINE_TYPE=bailian` + `BAILIAN_API_KEY=` 空 → 启动报错
- [x] 设置 `APP_ENV=invalid` → 启动报错
- [x] `.env.docker` 创建完成，`docker-compose.yml` 所有凭据已外部化
- [x] `docker-compose.yml` 包含完整 5 服务编排 (postgres/redis/minio/api/worker)
- [x] `.gitignore` 排除 `.env.docker`

### Round 2 验收 (管线可靠性)

- [ ] `pipeline.py` 在 Celery 不可用时抛出 `RuntimeError`（非原始异常）
- [ ] `watcher.py` 无 `asyncio` 阻塞警告
- [ ] 测试覆盖率 ≥ 90%
- [ ] Redis 连接池: 100 次发布 ≤ 1 个 TCP 连接
- [ ] 超大 PDF 处理在 55 分钟触发 `SoftTimeLimitExceeded`

### Round 3 验收 (API 加固)

- [ ] 所有错误响应不含内部异常详情 (`AccessDenied`, `Connection refused` 等)
- [ ] API Key 使用 `secrets.compare_digest` 比较
- [ ] `/scans/upload` 超过 10 次/分钟返回 429
- [ ] Content-Type 非 `application/pdf` 返回 400
- [ ] 未捕获异常返回 `{"detail": "Internal server error"}` 而非 traceback
- [ ] Swagger 文档显示所有端点完整响应 Schema

### Round 4 验收 (代码质量)

- [ ] `isinstance(bbox[0], list)` 仅在 `services/utils/bbox.py` 中出现
- [ ] `ScanUploadRequest` / `ScanListQuery` 完全删除
- [ ] `import re` / `import statistics` 均在模块顶部
- [ ] Alembic 迁移成功升级，所有约束生效
- [ ] 15 个 Minimal 模块至少具备模块级 docstring
- [ ] `table_recognizer.py` HTML 输出包含 `<thead>`/`<tbody>` 和 `colspan`

---

## 附录: 快速执行脚本

```bash
# === Round 1: 安全加固 ===
# 1. 检查旧 Key
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Authorization: Bearer sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -d '{"model":"qwen-vl-ocr-latest","messages":[{"role":"user","content":"test"}]}'
# 预期: 401

# 2. 启动验证
python -c "from config.settings import Settings; s=Settings(); print(s.is_production)"
# 无 .env 时应报错

# 3. 构建镜像
docker build -t scanstruct-api .
docker run --rm scanstruct-api id
# 预期: uid=10000(scanstruct)

# 4. 环境变量检查
grep -c "^[A-Z]" .env
grep -c "^[A-Z]" .env.example
# 两数应一致

# === Round 2: 管线可靠性 ===
# 5. 测试覆盖
pytest --cov=services --cov-report=term-missing --cov-fail-under=90

# 6. 检查阻塞 sleep
rg "time\.sleep" services/scan_in/watcher.py
# 预期: 仅 main loop 中的 time.sleep(1)

# === Round 3: API 加固 ===
# 7. 异常泄露
grep -n "detail=f\".*{e}" api/routes/scan.py
# 预期: 无匹配

# 8. 常量时间比较
grep -n "compare_digest" api/middleware.py
# 预期: 1 处匹配

# 9. 频率限制测试
for i in {1..11}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8900/api/v1/scans/upload \
    -H "X-API-Key: test-key" \
    -F "file=@test.pdf"
done
# 预期: 第11次返回 429

# === Round 4: 代码质量 ===
# 10. 重复代码检查
rg "isinstance\(bbox\[0\], list\)" services/ --count
# 预期: 仅在 services/utils/bbox.py 中出现

# 11. 数据库迁移
alembic upgrade head
# 预期: 成功，无错误