# ScanStruct 冗余代码审计报告

**审计日期**: 2026-05-19  
**扫描范围**: 全项目 39 源文件 + 27 测试文件  
**审计方法**: 模块导入追踪 / 代码模式匹配 / 交叉引用分析 / 死代码检测

---

## 一、总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 **Critical** | 2 | 数据库 schema 不一致，可能导致运行时错误 |
| 🟠 **High** | 7 | 死代码、逻辑矛盾、配置冲突 |
| 🟡 **Medium** | 10 | 重复逻辑、未用设置、冗余定义 |
| 🔵 **Low** | 14 | 未用导入、未用属性/方法、代码风格 |
| **合计** | **33** | |

---

## 二、🔴 Critical — 必须立即修复

### C1. 迁移脚本与 ORM 模型 Numeric 精度不一致

| 位置 | 精度 |
|------|------|
| `db/models.py:48-49` | `Numeric(4, 3)` — 4位总数/3位小数 |
| `db/migrations/versions/0001_initial.py:36-37` | `Numeric(5, 4)` — 5位总数/4位小数 |

**影响**: 实际数据库列精度与 ORM 声明不同，数据写入时可能截断或 Alembic 生成迁移时产生冲突。

**修复**: 统一为 `Numeric(5, 4)`（精度更高，兼容 0.0001~9.9999 范围），并更新 `models.py`。

---

### C2. 迁移脚本缺失索引和列

| 缺失项 | models.py 定义 | 迁移中 |
|--------|---------------|--------|
| `uq_task_steps_task_step` 唯一约束 | `UniqueConstraint("task_id", "step_name")` | ❌ 缺失 |
| `idx_scan_files_task_type` 复合索引 | `Index("task_id", "file_type")` | ❌ 缺失 |
| `scan_files.updated_at` 列 | `DateTime(timezone=True)` | ❌ 缺失 |

**影响**: 从迁移创建的数据库缺少约束和索引，`retry` 端点依赖 `uq_task_steps_task_step`，若缺失会导致重复步骤插入。

**修复**: 创建 `0002_add_constraints_indexes.py` 迁移补齐。

---

## 三、🟠 High — 应尽快修复

### H1. `api/middleware.py:62-69` — 死分支逻辑

```python
is_admin = path.startswith("/api/v1/admin/")
is_callback = "/callback" in path   # 未来的回调路径

if is_admin or is_callback:
    return await self._authenticate(request, call_next)

# ── 普通 API 路径 ──
return await self._authenticate(request, call_next)   # ← 永远执行
```

两个分支调用完全相同的方法，`is_admin`/`is_callback` 变量无任何效果，是死代码。

**修复**: 删除条件分支，直接 `return await self._authenticate(request, call_next)`。

---

### H2. `api/routes/scan.py:165` — 变量遮蔽

`ALLOWED_CONTENT_TYPES` 在模块级 (行58) 和函数内 (行165) 各定义一次，值相同。函数内定义遮蔽模块级常量，若未来模块级常量更新，函数内不会同步。

**修复**: 删除行165的局部定义，直接使用模块级常量。

---

### H3. `api/routes/scan.py:262-279` — 不可达的 watch_folder 分支

```python
task = ScanTask(source_type="api_upload", ...)   # 行222 硬编码

if task.source_type == "watch_folder":            # 行262 永远为 False
    ...                                            # 18行死代码
```

**修复**: 删除此分支；如需支持 watch_folder 来源，将 `source_type` 改为参数传入。

---

### H4. `services/pipeline.py:19-105` — 整个 `PipelineOrchestrator` 类是死代码

`PipelineOrchestrator` 的 `run_sync()`/`run_async()` 从未被任何生产代码调用。Worker 直接使用 `process_scan.delay()`。

**修复**: 删除 `pipeline.py` 或将其重构为实际被调用的编排器。

---

### H5. `services/layout/reading_order.py` — 整个模块是死代码

`sort_reading_order()` 从未被生产代码调用。`LayoutDetector.detect()` 内部已自行排序。同时 `test_reading_order.py` 测试的也是死代码。

**修复**: 删除 `reading_order.py` 和 `test_reading_order.py`。

---

### H6. 文本PDF检测阈值不一致

| 位置 | 阈值 | 逻辑 |
|------|------|------|
| `services/preprocessor/pdf_classifier.py:19` | **300** 字符/页 | 多页采样，置信度评估 |
| `services/scan_in/validator.py:155` | **50** 字符/页 | 仅检查前3页 |

同一 PDF 可能被 validator 判为"文本PDF"但被 classifier 判为"扫描PDF"，导致处理路径矛盾。

**修复**: 统一使用 `pdf_classifier.py` 的 `MIN_CHARS_PER_TEXT_PAGE = 300`，validator 调用 classifier 或共享常量。

---

### H7. 上传大小限制分散且不一致

| 文件 | 变量 | 值 |
|------|------|------|
| `api/routes/scan.py:60` | `MAX_UPLOAD_SIZE` | **100 MB** |
| `api/middleware.py:94` | `MAX_BODY_SIZE` | **150 MB** |
| `services/scan_in/validator.py:32` | `MAX_FILE_SIZE` | **100 MB** |

Middleware 允许 150MB 但路由层限制 100MB，validator 也限制 100MB。三层定义应统一。

**修复**: 移入 `config/settings.py` 作为 `max_upload_size: int = 100 * 1024 * 1024`，三处引用。

---

## 四、🟡 Medium — 计划修复

### M1. `api/schemas/common.py` — 5个未使用的 Schema 类

| 类 | 行号 | 预期用途 |
|----|------|---------|
| `ErrorResponse` | 27-30 | 错误响应（实际用 inline dict） |
| `AdminStatsResponse` | 56-62 | admin 统计（实际用 plain dict） |
| `QueueItem` | 65-71 | admin 队列（实际用 plain dict） |
| `AdminQueueResponse` | 74-77 | admin 队列（实际用 plain dict） |
| `ScanResultResponse` | 80-84 | 扫描结果（实际用 raw dict） |

**修复**: 将这些 Schema 接入对应路由的 `response_model=`，或删除。

---

### M2. `api/routes/scan.py` — "标记任务失败" 模式重复 5 次

```python
task.status = "failed"
task.error_message = f"...: {e}"
task.error_code = "..."
await db.flush()
```

出现在行 243-245, 270-272, 342-344, 725-727, 742-744。

**修复**: 提取 `_mark_task_failed(task, error_code, message, db)` 辅助函数。

---

### M3. `api/routes/scan.py` — Celery 派发模式重复 3 次

`process_scan.delay()` + try/except + 失败标记，出现在行 262-279, 333-346, 734-749。

**修复**: 提取 `_dispatch_celery_task(task_id, db)` 辅助函数。

---

### M4. `api/routes/scan.py` — 结果获取逻辑重复 2 次

"状态检查 + result_path 检查 + MinIO 下载 + JSON 解码" 在 `get_scan_result` (495-526) 和 `download_scan_docx` (570-601) 中重复。

**修复**: 提取 `_fetch_completed_result_json(task, task_id)` 辅助函数。

---

### M5. Celery 配置硬编码 vs settings 未连接

| 配置项 | settings.py 定义 | 实际使用 |
|--------|-----------------|---------|
| 队列名 | `celery_queue_name = "scanstruct"` | `celery_app.py:44-46` 硬编码 `"scanstruct"` |
| 超时 | `celery_task_timeout_seconds = 3600` | `celery_app.py:38-39` 硬编码 `3300/3600` |

**修复**: `celery_app.py` 改为引用 `settings.celery_queue_name` 和 `settings.celery_task_timeout_seconds`。

---

### M6. `config/settings.py` — 3个未使用的 MinIO bucket 设置

`minio_bucket_processed`, `minio_bucket_ocr`, `minio_bucket_layout` 从未被生产代码引用，仅存在于 `all_minio_buckets` 属性中用于脚本创建桶。

**修复**: 保留（未来扩展可能使用），但添加 `# TODO: 待后续阶段使用` 注释。

---

### M7. `config/settings.py` — 3个未使用的配置项

| 设置 | 说明 |
|------|------|
| `database_url_sync` | 仅同步 Alembic 迁移使用，生产代码从未引用 |
| `celery_task_timeout_seconds` | 从未引用 |
| `is_production` 属性 | 从未引用（只用 `is_development`） |

**修复**: `database_url_sync` 保留（Alembic 需要），删除 `celery_task_timeout_seconds` 并接入 `celery_app.py`，删除 `is_production`。

---

### M8. `worker/tasks.py:63-74` — 死 Celery 任务

`preprocess_task` 和 `ocr_task` 是空壳 stub，从未被派发，仅在 `celery_app.py` 的 `task_routes` 中注册。

**修复**: 删除两个 stub 任务及其 task_routes 注册。

---

### M9. `db/models.py:112` — 未使用的 `TaskStep.output_path` 列

该列从未被读写。

**修复**: 创建迁移删除该列，或标注 `# TODO: 待后续阶段使用`。

---

### M10. OCR 引擎重复代码

`OCREngine` 和 `BailianOCREngine` 的 `save_result()` 和 `recognize_batch()` 实现完全相同。

**修复**: 提取 `BaseOCREngine` 基类或 Mixin。

---

## 五、🔵 Low — 代码清理

### 未用导入 (11处)

| 文件 | 导入 |
|------|------|
| `config/settings.py:16` | `import os` |
| `config/settings.py:18` | `from typing import Optional` |
| `worker/tasks.py:9` | `import json` |
| `services/exporter/docx_exporter.py:9` | `import re` |
| `services/exporter/docx_exporter.py:14` | `Inches` (from docx.shared) |
| `services/exporter/docx_exporter.py:16` | `WD_STYLE_TYPE` (from docx.enum.style) |
| `services/ocr/engine.py:12` | `from typing import Optional` |
| `services/preprocessor/pdf_splitter.py:7` | `import io` |
| `services/preprocessor/text_pdf_extractor.py:8` | `from typing import Optional` |
| `services/scan_in/validator.py:7` | `import os` |
| `services/structurer/header_footer_cleaner.py:8` | `from collections import Counter` |

**修复**: 逐一删除未用导入。

---

### 未用属性/方法 (7处)

| 文件 | 项目 |
|------|------|
| `api/schemas/common.py:20-24` | `PaginatedResponse.pages` 属性从未访问 |
| `config/settings.py:261-262` | `is_production` 属性从未使用 |
| `config/settings.py:290-293` | `redis_broker_url_with_auth` 属性从未使用 |
| `services/ocr/engine.py:33-35` | `OCREngine.is_ready` 仅测试引用 |
| `services/ocr/bailian_engine.py:78-80` | `BailianOCREngine.is_ready` 仅测试引用 |
| `services/layout/detector.py:290-311` | `detect_all_pages()` 仅测试引用 |
| `services/preprocessor/pdf_splitter.py:70-107` | `split_to_bytes()` 仅测试引用 |

**修复**: 测试引用的保留（接口完整性），其他删除。

---

### 未用常量/单例 (5处)

| 文件 | 项目 |
|------|------|
| `services/constants.py:20` | `BASE_DPI = 72` |
| `services/constants.py:35` | `TABLE_DENSITY_THRESHOLD = 0.25` |
| `services/ocr/bailian_engine.py:28` | `OCR_SIMPLE_PROMPT` |
| `services/ocr/bailian_engine.py:282` | `bailian_ocr_engine` 单例 |
| `services/structurer/list_detector.py:46-50` | `CONTINUATION_PATTERN` 编译正则 |

**修复**: 删除或标注 `# TODO`。

---

### 未用工具函数 (5处)

| 文件 | 函数 |
|------|------|
| `services/utils/bbox.py:11-32` | `normalize_bbox()` |
| `services/utils/bbox.py:61-71` | `rect_to_bbox()` |
| `services/utils/bbox.py:74-92` | `bbox_overlap_y()` |
| `services/utils/bbox.py:95-106` | `rect_center()` |
| `services/utils/bbox.py:109-124` | `rect_distance_y()` |

`bbox.py` 中仅 `bbox_to_rect()` 被生产代码使用，其余 5 个函数和 `utils/__init__.py` 的重导出均为死代码。

**修复**: 删除未用函数和 `__init__.py` 重导出。

---

### 其他

| 文件 | 问题 |
|------|------|
| `conftest.py:7` | 未用 `import io` |
| `conftest.py:202` | `processing_task` fixture 中 `TaskStep.status="running"` 不在 CHECK 约束允许值内 |
| `tests/test_pipeline.py:21` | `MagicMock as Mock` 冗余别名 |
| `worker/tasks.py:631` | `_fail_task` 内冗余 `from db.models import ScanTask` |
| `db/models.py:84-87, 128-131` | 状态 CHECK 约束字符串重复，应提取常量 |
| `services/layout/detector.py` vs `reading_order.py` | 列检测算法重复（相同阈值 `2.5`/`0.08`） |

---

## 六、重复逻辑汇总

| 模式 | 重复次数 | 位置 |
|------|---------|------|
| 标记任务失败 | 5× | scan.py |
| Celery 派发+错误处理 | 3× | scan.py |
| 结果获取+MinIO下载+JSON解码 | 2× | scan.py |
| Celery revoke 模式 | 2× | scan.py |
| `save_result()` 方法 | 2× | engine.py / bailian_engine.py |
| `recognize_batch()` 方法 | 2× | engine.py / bailian_engine.py |
| 列检测算法 | 2× | detector.py / reading_order.py |
| 文本PDF检测逻辑 | 2× | pdf_classifier.py / validator.py |
| `ALLOWED_EXTENSIONS` 常量 | 2× | scan.py / validator.py |
| 上传大小限制 | 3× | scan.py / middleware.py / validator.py |
| Redis URL 认证注入 | 2× | settings.py 两个属性 |
| Mock DB session fixture | 2× | conftest.py / test_pipeline.py |

---

## 七、修复优先级路线图

### Phase 1 — Critical + High (建议 1-2 天)

| 编号 | 修复项 | 预估工作量 |
|------|--------|-----------|
| C1 | 统一 Numeric 精度为 `Numeric(5,4)` | 0.5h |
| C2 | 创建迁移补齐约束/索引/列 | 1h |
| H1 | 简化 middleware 死分支 | 0.5h |
| H2 | 删除 scan.py 遮蔽变量 | 0.2h |
| H3 | 删除/重构不可达 watch_folder 分支 | 0.5h |
| H4 | 删除 PipelineOrchestrator 或接入实际调用 | 1h |
| H5 | 删除 reading_order.py 及其测试 | 0.5h |
| H6 | 统一文本PDF检测阈值 | 1h |
| H7 | 集中上传大小限制到 settings | 1h |

### Phase 2 — Medium (建议 2-3 天)

| 编号 | 修复项 |
|------|--------|
| M1 | 接入或删除未使用的 Schema 类 |
| M2-M4 | 提取 scan.py 重复逻辑辅助函数 |
| M5 | celery_app.py 接入 settings 配置 |
| M6-M7 | 清理未用设置项 |
| M8 | 删除死 Celery 任务 |
| M9 | 处理未用 TaskStep.output_path |
| M10 | OCR 引擎基类提取 |

### Phase 3 — Low (持续清理)

- 删除所有未用导入 (11处)
- 删除未用函数/常量/单例 (10处)
- 修复 conftest.py fixture 状态约束违规
- 合并重复 mock fixture

---

## 八、处理原则建议

| 冗余类型 | 推荐策略 |
|---------|---------|
| **死代码** (从未被调用) | 🔴 删除 — 代码越少，维护成本越低 |
| **未用但预留给未来** | 🟡 保留但标注 `# TODO: 待后续阶段使用` |
| **重复逻辑** | 🟢 提取辅助函数/基类，消除复制粘贴 |
| **配置不一致** | 🔴 立即统一 — 不一致是 bug 温床 |
| **Schema 定义了但未接入** | 🟡 优先接入 `response_model=`，提升 API 一致性 |

> **核心原则**: 删除 > 重构 > 标注保留。代码存在的成本是理解与维护，删除死代码永远比注释它更安全。

---

*报告由 WorkBuddy 自动生成 @ 2026-05-19*
