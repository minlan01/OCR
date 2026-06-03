# ScanStruct 冗余代码修复执行计划

**版本**: v1.0  
**日期**: 2026-05-19  
**状态**: 待审批  
**预计总工时**: Phase 1 ~6h / Phase 2 ~8h / Phase 3 ~3h

---

## 执行总览

```
Phase 1 ── Critical + High (9项) ──── 数据安全 / 逻辑正确性
Phase 2 ── Medium (10项) ──────────── 代码质量 / 重复消除
Phase 3 ── Low (14项) ────────────── 代码整洁 / 风格统一
```

**执行原则**:
- 每个 Phase 独立可交付，Phase 间可暂停
- 每项修复完成后立即运行 `pytest tests/` 验证
- 数据库迁移变更需先备份再执行
- 文件路径均为相对于 `E:\OCRScanStruct` 的路径

---

## Phase 1 — Critical + High (必须立即修复)

### 1.1 [C1] 统一 Numeric 精度

**文件**: `db/models.py`  
**行号**: 48-49  
**当前**:
```python
confidence_avg: Mapped[float | None] = mapped_column(Numeric(4, 3), default=None)
structure_score: Mapped[float | None] = mapped_column(Numeric(4, 3), default=None)
```
**修改为**:
```python
confidence_avg: Mapped[float | None] = mapped_column(Numeric(5, 4), default=None)
structure_score: Mapped[float | None] = mapped_column(Numeric(5, 4), default=None)
```
**验证**: `pytest tests/ -q` 确认通过  
**风险**: 低 — 迁移已是 `Numeric(5,4)`，这是对齐到实际 DB schema

---

### 1.2 [C2] 创建迁移补齐缺失约束/索引/列

**新建文件**: `db/migrations/versions/0002_add_constraints_indexes.py`

迁移内容：
1. `task_steps` 表添加 `UniqueConstraint("task_id", "step_name", name="uq_task_steps_task_step")`
2. `scan_files` 表添加 `Index("idx_scan_files_task_type", "task_id", "file_type")`
3. `scan_files` 表添加 `updated_at` 列 `DateTime(timezone=True), server_default=text("NOW()")`
4. `scan_tasks` 表添加 CHECK 约束（如迁移中缺失）

```python
"""add missing constraints, indexes and columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. task_steps: 添加唯一约束 (task_id, step_name)
    op.create_unique_constraint("uq_task_steps_task_step", "task_steps", ["task_id", "step_name"])

    # 2. task_steps: 添加 CHECK 约束
    op.execute(
        "ALTER TABLE task_steps ADD CONSTRAINT ck_task_steps_status "
        "CHECK (status IN ('pending','received','processing','completed','failed','cancelled','retrying'))"
    )

    # 3. scan_files: 添加复合索引
    op.create_index("idx_scan_files_task_type", "scan_files", ["task_id", "file_type"])

    # 4. scan_files: 添加 updated_at 列
    op.add_column(
        "scan_files",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # 5. scan_tasks: 添加 CHECK 约束（如缺失）
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_scan_tasks_status "
        "CHECK (status IN ('pending','received','processing','completed','failed','cancelled','retrying'))"
    )

    # 6. scan_tasks: 添加 confidence_avg / structure_score 范围约束
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_confidence_avg_range "
        "CHECK (confidence_avg IS NULL OR (confidence_avg >= 0 AND confidence_avg <= 1))"
    )
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_structure_score_range "
        "CHECK (structure_score IS NULL OR (structure_score >= 0 AND structure_score <= 1))"
    )


def downgrade() -> None:
    op.drop_constraint("ck_structure_score_range", "scan_tasks")
    op.drop_constraint("ck_confidence_avg_range", "scan_tasks")
    op.drop_constraint("ck_scan_tasks_status", "scan_tasks")
    op.drop_column("scan_files", "updated_at")
    op.drop_index("idx_scan_files_task_type", "scan_files")
    op.drop_constraint("ck_task_steps_status", "task_steps")
    op.drop_constraint("uq_task_steps_task_step", "task_steps")
```

**验证**: 手动检查迁移语法 `python -m py_compile db/migrations/versions/0002_add_constraints_indexes.py`

---

### 1.3 [H1] 简化 middleware 死分支

**文件**: `api/middleware.py`  
**行号**: 61-69  

**当前**:
```python
# ── Admin 路径强制要求认证 ──
is_admin = path.startswith("/api/v1/admin/")
is_callback = "/callback" in path  # 未来的回调路径

if is_admin or is_callback:
    return await self._authenticate(request, call_next)

# ── 普通 API 路径：配置了 key 时强制认证 ──
return await self._authenticate(request, call_next)
```

**修改为**:
```python
# ── API 路径：配置了 key 时强制认证 ──
return await self._authenticate(request, call_next)
```

**验证**: `pytest tests/test_api.py tests/test_scan_api.py -q`

---

### 1.4 [H2] 删除 scan.py 遮蔽变量

**文件**: `api/routes/scan.py`  
**行号**: 165  

**当前**:
```python
    # 1.5. 校验 Content-Type
    ALLOWED_CONTENT_TYPES = {"application/pdf"}
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
```

**修改为**:
```python
    # 1.5. 校验 Content-Type
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
```

删除行165的局部变量定义，使用行58的模块级常量。

**验证**: `pytest tests/test_scan_api.py -q`

---

### 1.5 [H3] 删除不可达的 watch_folder 分支

**文件**: `api/routes/scan.py`  
**行号**: 262-279  

**删除整个 if 块**:
```python
    if task.source_type == "watch_folder" and process_scan is not None:
        try:
            celery_result = process_scan.delay(str(task_id))
            logger.info(...)
        except Exception as e:
            ...
            return ScanUploadResponse(...)
```

**同时简化返回值**（行285）：

**当前**:
```python
    message="uploaded_pending_process" if task.source_type == "api_upload" else "accepted",
```

**修改为**:
```python
    message="uploaded_pending_process",
```

因为 `source_type` 在此函数中始终为 `"api_upload"`。

**验证**: `pytest tests/test_scan_api.py tests/test_e2e_workflows.py -q`

---

### 1.6 [H4] 删除 PipelineOrchestrator 死代码

**文件**: `services/pipeline.py`  

**方案 A (推荐): 删除整个文件**
- 删除 `services/pipeline.py`
- 更新 `services/__init__.py`（如有重导出）
- 删除 `tests/test_pipeline.py`（测试的是死代码）

**方案 B: 保留为轻量模块**
- 将 `PipelineOrchestrator` 替换为简单函数：
```python
"""Celery 任务派发辅助"""
from __future__ import annotations

from loguru import logger

from config.settings import settings


def dispatch_scan_task(task_id: str) -> str | None:
    """派发扫描任务到 Celery 队列
    
    Args:
        task_id: 任务 UUID 字符串
    Returns:
        Celery 任务 ID，派发失败返回 None
    """
    try:
        from worker.tasks import process_scan
        result = process_scan.delay(task_id)
        logger.info(f"Task {task_id} dispatched: celery_id={result.id}")
        return result.id
    except Exception as e:
        logger.error(f"Failed to dispatch task {task_id}: {e}")
        return None
```

**选择**: 采用方案 A，删除文件和测试。当前 `process_scan.delay()` 在 `scan.py` 中直接调用足够简单，无需额外包装。

**验证**: 删除后运行 `pytest tests/ -q --ignore=tests/test_pipeline.py`，确认无导入错误

---

### 1.7 [H5] 删除 reading_order.py 及其测试

**删除文件**:
- `services/layout/reading_order.py`
- `tests/test_reading_order.py`

**检查**: 确认无其他文件 `from services.layout.reading_order import ...`（已确认：零引用）

**验证**: `pytest tests/ -q --ignore=tests/test_reading_order.py`

---

### 1.8 [H6] 统一文本PDF检测阈值

**文件 1**: `services/preprocessor/pdf_classifier.py`  
**行号**: 19  
**保持不变**: `MIN_CHARS_PER_TEXT_PAGE = 300`（这是正确的阈值）

**文件 2**: `services/scan_in/validator.py`  
**行号**: ~155  

**当前**: 硬编码 `50` 字符阈值
```python
def _check_text_pdf(self, file_path: Path) -> bool:
    ...
    if len(text.strip()) < 50:
```

**修改**: 引用共享常量

```python
from services.constants import MIN_CHARS_PER_TEXT_PAGE

class PDFValidator:
    ...
    def _check_text_pdf(self, file_path: Path) -> bool:
        ...
        if len(text.strip()) < MIN_CHARS_PER_TEXT_PAGE:
```

**文件 3**: `services/constants.py`  
**添加**:
```python
# 文本 PDF 检测阈值：每页最少字符数
MIN_CHARS_PER_TEXT_PAGE: int = 300
```

**文件 4**: `services/preprocessor/pdf_classifier.py`  
**修改**: 删除本地 `MIN_CHARS_PER_TEXT_PAGE = 300`，改为导入
```python
from services.constants import MIN_CHARS_PER_TEXT_PAGE
```

**验证**: `pytest tests/test_pdf_classifier.py tests/test_validator.py -q`

---

### 1.9 [H7] 集中上传大小限制到 settings

**文件 1**: `config/settings.py`  
**添加字段**（在 `api_workers` 之后）:
```python
    max_upload_size: int = 100 * 1024 * 1024  # 上传文件最大 100 MB
```

**文件 2**: `api/routes/scan.py`  
**行号**: 60  
**删除**: `MAX_UPLOAD_SIZE = 100 * 1024 * 1024`  
**行号**: 182  
**修改**: `if len(content) > MAX_UPLOAD_SIZE:` → `if len(content) > settings.max_upload_size:`  
**行号**: 185  
**修改**: `detail=f"File too large. Max size: {MAX_UPLOAD_SIZE // (1024*1024)} MB"` → `detail=f"File too large. Max size: {settings.max_upload_size // (1024*1024)} MB"`

**文件 3**: `api/middleware.py`  
**行号**: 94  
**删除**: `MAX_BODY_SIZE = 150 * 1024 * 1024`  
**行号**: 118  
**修改**: `max_size = MAX_BODY_SIZE if request.url.path in UPLOAD_PATHS else DEFAULT_BODY_SIZE` → `max_size = settings.max_upload_size if request.url.path in UPLOAD_PATHS else DEFAULT_BODY_SIZE`

**文件 4**: `services/scan_in/validator.py`  
**行号**: 32  
**删除**: `MAX_FILE_SIZE = 100 * 1024 * 1024`  
**修改引用处**: `self.max_file_size = max_file_size or MAX_FILE_SIZE` → `self.max_file_size = max_file_size or settings.max_upload_size`

**验证**: `pytest tests/test_scan_api.py tests/test_validator.py -q`

---

## Phase 2 — Medium (计划修复)

### 2.1 [M1] Schema 类接入或清理

**文件**: `api/schemas/common.py`

**决策矩阵**:

| Schema | 策略 | 理由 |
|--------|------|------|
| `ErrorResponse` | 接入 | 提升所有错误响应格式一致性 |
| `AdminStatsResponse` | 接入 | admin 路由应使用 response_model |
| `QueueItem` + `AdminQueueResponse` | 接入 | admin 路由应使用 response_model |
| `ScanResultResponse` | 删除 | 结果端点直接返回 dict/Response 更灵活 |
| `PaginatedResponse.pages` | 删除 | 从未被消费 |

**执行**:
1. `api/routes/admin.py` 添加 `response_model=AdminStatsResponse` / `AdminQueueResponse`
2. `api/routes/scan.py` 的 HTTPException 使用 `JSONResponse` + `ErrorResponse` 模式
3. 删除 `ScanResultResponse` 和 `PaginatedResponse.pages` 属性

---

### 2.2 [M2] 提取"标记任务失败"辅助函数

**文件**: `api/routes/scan.py`  
**位置**: 在 `_compute_md5()` 之后添加模块级辅助函数

```python
async def _mark_task_failed(
    task: ScanTask,
    db: AsyncSession,
    error_code: str,
    error_message: str,
) -> None:
    """标记任务为失败状态"""
    task.status = "failed"
    task.error_code = error_code
    task.error_message = error_message
    await db.flush()
```

**替换 5 处内联代码**:
- 行 243-246: → `await _mark_task_failed(task, db, "MINIO_UPLOAD_ERROR", f"MinIO upload failed: {e}")`
- 行 270-273: → `await _mark_task_failed(task, db, "DISPATCH_ERROR", f"Failed to dispatch: {e}")`
- 行 342-345: → `await _mark_task_failed(task, db, "DISPATCH_ERROR", f"Failed to dispatch: {e}")`
- 行 725-728: → `await _mark_task_failed(task, db, "RETRY_DISPATCH_ERROR", "Celery dispatcher unavailable during retry")`
- 行 742-745: → `await _mark_task_failed(task, db, "RETRY_DISPATCH_ERROR", f"Failed to dispatch retry: {e}")`

---

### 2.3 [M3] 提取 Celery 派发辅助函数

**文件**: `api/routes/scan.py`

```python
def _dispatch_celery(task_id: uuid.UUID) -> str:
    """派发 Celery 任务，返回 celery_task_id
    
    Raises:
        RuntimeError: Celery 不可用或派发失败
    """
    if process_scan is None:
        raise RuntimeError("Celery task dispatcher not available")
    try:
        result = process_scan.delay(str(task_id))
        logger.info(f"Task {task_id} dispatched to Celery: celery_task_id={result.id}")
        return result.id
    except Exception as e:
        logger.error(f"Failed to dispatch Celery task for {task_id}: {e}")
        raise RuntimeError(f"Failed to dispatch: {e}") from e
```

**替换 3 处**: `upload_scan` / `batch_process` / `retry_scan` 中的 try/except dispatch 块

---

### 2.4 [M4] 提取结果获取辅助函数

**文件**: `api/routes/scan.py`

```python
def _fetch_result_json(task: ScanTask, task_id: uuid.UUID) -> dict:
    """获取已完成任务的结构化结果 JSON
    
    Args:
        task: 扫描任务对象
        task_id: 任务 UUID（用于日志）
    
    Returns:
        解析后的 JSON dict
        
    Raises:
        HTTPException: 任务未完成 / 结果不存在 / 下载失败 / 数据损坏
    """
    if task.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task.status}",
        )
    if not task.result_path:
        raise HTTPException(status_code=404, detail="Result file not found for this task")
    try:
        data = minio_client.download_bytes(
            bucket=settings.minio_bucket_result,
            object_key=task.result_path,
        )
    except Exception as e:
        logger.error(f"Failed to fetch result for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve processing result")
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Result data corrupted for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Result data is corrupted, please retry")
```

**替换**: `get_scan_result` (495-526) 和 `download_scan_docx` (570-601) 中的重复代码块

---

### 2.5 [M5] celery_app 接入 settings

**文件**: `worker/celery_app.py`

**当前** (行 38-39):
```python
task_soft_time_limit=3300,
task_time_limit=3600,
```
**修改为**:
```python
task_soft_time_limit=settings.celery_task_timeout_seconds - 300,
task_time_limit=settings.celery_task_timeout_seconds,
```

**当前** (行 43-47):
```python
celery_app.conf.task_routes = {
    "worker.tasks.process_scan": {"queue": "scanstruct"},
    "worker.tasks.preprocess_task": {"queue": "scanstruct"},
    "worker.tasks.ocr_task": {"queue": "scanstruct"},
}
```
**修改为**:
```python
celery_app.conf.task_routes = {
    "worker.tasks.process_scan": {"queue": settings.celery_queue_name},
}
```
（同时删除 `preprocess_task` 和 `ocr_task` 的路由，对应 M8）

---

### 2.6 [M6] MinIO bucket 设置标注 TODO

**文件**: `config/settings.py`  
**行号**: 67-69

```python
    # TODO: 待后续阶段使用（当前仅 minio_bucket_raw 和 minio_bucket_result 被生产代码引用）
    minio_bucket_processed: str = "scan-processed"
    minio_bucket_ocr: str = "scan-ocr"
    minio_bucket_layout: str = "scan-layout"
```

---

### 2.7 [M7] 清理未用设置项

**文件**: `config/settings.py`

| 项目 | 操作 |
|------|------|
| `database_url_sync` | 保留（Alembic 迁移需要），添加注释 |
| `celery_task_timeout_seconds` | 保留（M5 接入后即有引用） |
| `is_production` 属性 | **删除** — 从未被引用 |
| `redis_broker_url_with_auth` 属性 | **删除** — 从未被引用 |
| `import os` | **删除** |
| `from typing import Optional` | **删除** |

---

### 2.8 [M8] 删除死 Celery 任务

**文件**: `worker/tasks.py`  
**删除** (行 63-74): `preprocess_task` 和 `ocr_task` 两个空壳 stub

**文件**: `worker/celery_app.py`  
**删除**: 上述两个任务的 `task_routes` 注册（已在 M5 中处理）

---

### 2.9 [M9] 处理 TaskStep.output_path

**决策**: 标注 `# TODO: 待后续阶段使用（当前未读写）`

**原因**: 删除列需要创建迁移，影响范围大于标注保留。待确认该列无业务需求后再删除。

**文件**: `db/models.py` 行 112
```python
    # TODO: 待后续阶段使用（当前未读写）
    output_path: Mapped[str | None] = mapped_column(String(1000), default=None)
```

---

### 2.10 [M10] OCR 引擎基类提取

**新建文件**: `services/ocr/base.py`

```python
"""OCR 引擎基类，提供共享方法"""
from __future__ import annotations

import json
from pathlib import Path
from loguru import logger


class BaseOCREngine:
    """OCR 引擎基类"""

    def save_result(self, results: list[dict], output_path: Path) -> None:
        """保存 OCR 结果到 JSON 文件"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    def recognize_batch(self, image_paths: list[Path]) -> list[list[dict]]:
        """批量 OCR 识别（顺序执行）"""
        results = []
        for i, path in enumerate(image_paths):
            logger.debug(f"OCR batch {i+1}/{len(image_paths)}: {path.name}")
            results.append(self.recognize(path))
        return results
```

**修改**:
- `services/ocr/engine.py`: `OCREngine(BaseOCREngine)` — 删除 `save_result` 和 `recognize_batch`
- `services/ocr/bailian_engine.py`: `BailianOCREngine(BaseOCREngine)` — 同上

**验证**: `pytest tests/test_ocr_engine.py tests/test_bailian_ocr.py tests/test_ocr_batch_processor.py -q`

---

## Phase 3 — Low (持续清理)

### 3.1 批量删除未用导入 (11处)

| # | 文件 | 删除 |
|---|------|------|
| 1 | `config/settings.py:16` | `import os` |
| 2 | `config/settings.py:18` | `from typing import Optional` → 只保留 `Literal` |
| 3 | `worker/tasks.py:9` | `import json` |
| 4 | `services/exporter/docx_exporter.py:9` | `import re` |
| 5 | `services/exporter/docx_exporter.py:14` | `Inches` 从 `from docx.shared import ...` |
| 6 | `services/exporter/docx_exporter.py:16` | `from docx.enum.style import WD_STYLE_TYPE` |
| 7 | `services/ocr/engine.py:12` | `from typing import Optional` |
| 8 | `services/preprocessor/pdf_splitter.py:7` | `import io` |
| 9 | `services/preprocessor/text_pdf_extractor.py:8` | `from typing import Optional` |
| 10 | `services/scan_in/validator.py:7` | `import os` |
| 11 | `services/structurer/header_footer_cleaner.py:8` | `from collections import Counter` |

---

### 3.2 删除未用常量/单例 (5处)

| # | 文件 | 删除 |
|---|------|------|
| 1 | `services/constants.py:20` | `BASE_DPI = 72` |
| 2 | `services/constants.py:35` | `TABLE_DENSITY_THRESHOLD = 0.25` |
| 3 | `services/ocr/bailian_engine.py:28` | `OCR_SIMPLE_PROMPT` |
| 4 | `services/ocr/bailian_engine.py:282` | `bailian_ocr_engine` 单例 |
| 5 | `services/structurer/list_detector.py:46-50` | `CONTINUATION_PATTERN` |

---

### 3.3 删除未用工具函数

**文件**: `services/utils/bbox.py`
- 删除: `normalize_bbox()`, `rect_to_bbox()`, `bbox_overlap_y()`, `rect_center()`, `rect_distance_y()`
- 保留: `bbox_to_rect()` (唯一被引用的函数)

**文件**: `services/utils/__init__.py`
- 删除: 所有重导出（`from .bbox import ...` / `from .text_patterns import ...`）
- 保留: 空文件作为包标记

**文件**: `services/utils/text_patterns.py`
- 删除: `ends_with_terminal()` — 未被任何生产代码引用

---

### 3.4 删除未用属性

| # | 文件 | 删除 |
|---|------|------|
| 1 | `api/schemas/common.py:20-24` | `PaginatedResponse.pages` 属性 |
| 2 | `config/settings.py:261-262` | `is_production` 属性 |
| 3 | `config/settings.py:290-293` | `redis_broker_url_with_auth` 属性 |

**保留** (仅测试引用但属于接口完整性):
- `OCREngine.is_ready` / `BailianOCREngine.is_ready`
- `LayoutDetector.detect_all_pages()`
- `PDFSplitter.split_to_bytes()`

---

### 3.5 修复 conftest.py fixture

**文件**: `conftest.py`

1. **行7**: 删除 `import io`
2. **行202**: `processing_task` fixture 中 `TaskStep.status="running"` → 改为 `"processing"`（CHECK 约束不允许 `"running"`）

**文件**: `tests/test_pipeline.py`
3. **行21**: 删除 `MagicMock as Mock` 别名，使用顶层已导入的 `MagicMock`

**文件**: `worker/tasks.py`
4. **行631**: 删除 `_fail_task` 内冗余 `from db.models import ScanTask`

---

### 3.6 提取状态枚举常量

**文件**: `db/models.py`

```python
# 任务/步骤状态枚举（CHECK 约束共享）
VALID_TASK_STATUSES = "'pending','received','processing','completed','failed','cancelled','retrying'"
```

**ScanTask.__table_args__** 和 **TaskStep.__table_args__** 中的 CHECK 约束引用此常量：

```python
CheckConstraint(
    f"status IN ({VALID_TASK_STATUSES})",
    name="ck_scan_tasks_status",
),
```

---

### 3.7 ALLOWED_EXTENSIONS 集中

**文件**: `config/settings.py` 添加:
```python
    allowed_extensions: list[str] = [".pdf"]  # 允许上传的文件扩展名
```

**文件**: `api/routes/scan.py` 行59:
```python
ALLOWED_EXTENSIONS = set(settings.allowed_extensions)  # 冻结为集合加速查找
```

**文件**: `services/scan_in/validator.py` 行31:
```python
self.allowed_extensions = set(settings.allowed_extensions)
```

---

## 验证检查清单

每个 Phase 完成后执行：

```bash
# 1. 语法检查
E:\OCRScanStruct\.venv\Scripts\python.exe -m py_compile <修改的文件>

# 2. 导入检查
E:\OCRScanStruct\.venv\Scripts\python.exe -c "import <模块>"

# 3. 测试套件
E:\OCRScanStruct\.venv\Scripts\python.exe -m pytest tests/ -q --tb=short

# 4. 预期结果
# Phase 1: 430 passed, 0 failed（test_pipeline.py 和 test_reading_order.py 可能需删除）
# Phase 2: ≥425 passed, 0 failed
# Phase 3: ≥425 passed, 0 failed
```

---

## 变更影响矩阵

| Phase | 修改文件数 | 新建文件 | 删除文件 | 影响模块 |
|-------|-----------|---------|---------|---------|
| 1 | 8 | 1 (迁移) | 2 (pipeline.py, reading_order.py) + 1测试 | db, api, services, config |
| 2 | 7 | 1 (base.py) | 0 | api, worker, services/ocr, config |
| 3 | 11 | 0 | 0 | 全局清理 |

---

*计划由 WorkBuddy 生成 @ 2026-05-19*
