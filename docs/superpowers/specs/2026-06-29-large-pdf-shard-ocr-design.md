# 大 PDF 分片 OCR 设计

> 状态：已认可，待写实现计划
> 日期：2026-06-29
> 关联：`services/evidence/ocr_storage.py`（OCR offload 基础设施，已落地）

## 1. 背景与目标

### 1.1 现状

当前 OCR offload 机制（`EvidenceOCRStore` 逐页写 MinIO、DB 只存 8KB 预览）已让单材料 3000 页 PDF 在内存层面跑通：上传流式落盘、`fitz.open(磁盘)`、分批拆页、逐页写 MinIO。

但存在两个硬上限：

1. **Celery 单任务超时**：`task_time_limit=1800s`（30 分钟）。3000 页云端 OCR 已逼近超时，5000+ 页必然超时 → 整个材料从头重跑。
2. **单任务原子性**：`_ocr_single_material` 一个 task 跑完整个材料所有页。中途失败/超时/worker 崩溃 → 从第 1 页重跑，无断点续传。

### 1.2 目标

- 支持单 PDF **5000-10000+ 页**不超时
- 失败/超时/崩溃后能**断点续传**，不从头重跑
- 不破坏前端"一份材料"的语义
- 改动集中在编排层，分类/目录/导出层透明

### 1.3 非目标

- 不处理单文件 > 10GB 的极端场景（那是 PDF 物理拆分方案，破坏材料语义）
- 不做实时进度推送（前端轮询 DB 已够）
- 不做分片队列独立 worker（先复用单队列）

---

## 2. 编排模型

### 2.1 三段式架构

把"OCR 一份材料"从单 task 跑完所有页，改为**派发器 + 批次 worker + 收口器**三段式：

```
process_evidence_full(case_id)
        │
        │  对每个 material：
        ├─→ dispatch_material_ocr(material_id)        [派发器，秒级]
        │       │
        │       │  读总页数 → 按 200 页/批切分
        │       │  为每批派发：
        │       ├─→ process_ocr_batch(m_id, 0, 1,   200)   ┐
        │       ├─→ process_ocr_batch(m_id, 1, 201, 400)   ├─ N 批并行
        │       └─→ process_ocr_batch(m_id, 49, 9801, 10000) ┘
        │                  │
        │                  │  每批：拆页→OCR→写 MinIO pages/page_NNNN.json
        │                  │  完成后更新进度（已完成的批次 index）
        │                  ▼
        └─→ finalize_material_ocr(material_id)        [收口器]
                │  检查是否所有批次都完成
                │  是 → 拼接 full_text.txt + 写 manifest.json
                │       更新 material.ocr_status=completed
                │  否 → 找出缺失/失败批次，重新派发；自身 retry
```

### 2.2 三个新 Celery task

| Task | 输入 | 职责 | 耗时 | max_retries |
|---|---|---|---|---|
| `dispatch_material_ocr` | `material_id` | 读页数、切批、派发批次 task、派发收口 task | <5s | 2 |
| `process_ocr_batch` | `material_id, batch_index, batch_start, batch_end` | 拆指定页段→OCR→写 MinIO→更新进度 | 30s-2min | 3 |
| `finalize_material_ocr` | `material_id` | 检查进度、补缺、拼接 full_text、写 manifest、更新 material | 10-60s | 5 |

### 2.3 为什么用"派发器 + 收口器"而不是 Celery chord

- **chord 要求所有批次 task 在同一进程组内可被跟踪**，worker 重启/崩溃会丢 chord 状态
- 收口器是**独立 task**，靠**查 DB 进度**判断是否全完成，无状态依赖，crash-safe
- 收口器发现缺批次就**重新派发**，自身 retry——天然断点续传

### 2.4 批次大小

- `ocr_batch_size`（现有配置=100）：单批内拆页数，不变
- `ocr_batch_page_size`（新，默认 200）：一个 task 处理多少页
- 10000 页 = 50 个 task，每个 task 内部再按 100 页拆图

### 2.5 并发控制

- 复用现有 `try_acquire_case` / `try_acquire_tenant`，但**只在派发器和收口器**加锁
- 批次 task **不加全局锁**（否则失去并行意义），用 `worker_concurrency=2` 自然限流
- 新增 Redis 信号量 `ocr_batch_concurrent:{material_id}` 限每材料同时 N 批（默认 4），防止单材料占满整个 worker 池

### 2.6 与现有流程的衔接

- `process_evidence_full` 里 `_run_ocr_pipeline` 改为：对所有 material 调 `dispatch_material_ocr.delay()`，然后**轮询 DB** 等所有 material 的 `ocr_status` 变成 `completed`/`failed`，再进分类阶段
- `process_single_material_ocr`（单素材重试）改为调 `dispatch_material_ocr.delay(material_id)`，复用同一套分片逻辑
- 小文件（docx/xlsx/image/页数 < 阈值）走**老路径**（单 task 内 inline），不进分片

### 2.7 分片阈值

```python
SHARD_THRESHOLD_PAGES = settings.ocr_shard_threshold_pages  # 默认 500
if file_type == "pdf" and total_pages > SHARD_THRESHOLD_PAGES:
    走分片路径
else:
    走现有 ocr_upload_path 单 task 路径
```

500 页以下保持现状走老路径。500 页以上（含现有 3000 页场景）走分片路径——分片对 3000 页同样适用且更稳，相当于把现有 3000 页能力升级为"任意页数"。

---

## 3. 断点续传与失败处理

### 3.1 进度记录：两层结构

不新建表。进度记录分两层：

**层 1：DB `EvidenceStep.step_metadata`**（材料级总览，前端轮询用）

```json
{
  "step_name": "ocr_shard",
  "total_pages": 10000,
  "batch_size": 200,
  "total_batches": 50,
  "completed_batches": [0, 1, 2, 5, 6],
  "failed_batches": [{"index": 3, "error": "...", "retries": 2}],
  "pending_batches": [4, 7, 8],
  "status": "sharding" | "finalizing" | "completed" | "partial_failed",
  "cancelled": false
}
```

**层 2：MinIO 每批 checkpoint**（批次级幂等性）

```
evidence/{case_id}/ocr/{material_id}/
  checkpoints/batch_0000.json   {"start":1,"end":200,"pages_written":[1..200],"status":"completed"}
  checkpoints/batch_0001.json   {"start":201,"end":400,"pages_written":[201..400],"status":"completed"}
  checkpoints/batch_0003.json   {"start":601,"end":800,"status":"failed","error":"..."}
  pages/page_0001.json          ← 真正的 OCR 结果
  pages/page_0002.json
  ...
  full_text.txt                 ← finalize 阶段才生成
  manifest.json                 ← finalize 阶段才生成
```

**为什么两层**：
- DB 层给前端轮询看进度（`getProgress` 已有 `step_metadata` 透传）
- MinIO 层给批次 task 做幂等判断——重跑时先读 checkpoint，已完成的页跳过

### 3.2 断点续传触发场景

| 场景 | 触发 | 续传机制 |
|---|---|---|
| 单批 task 失败 | OCR 异常/超时 | Celery `max_retries=3` 自动重试该批 |
| 单批 task 重试耗尽 | 3 次重试都失败 | 该批标记 `failed`，收口器决定是否再给机会 |
| worker 崩溃 | 进程死亡 | `acks_late` 让任务重回队列；checkpoint 保证不重写已完成页 |
| 整个材料 OCR 中断 | 派发器没派发完就崩 | 用户点"重试" → 新派发器读 DB 进度，只派发 `pending_batches` |
| 收口器发现缺批次 | 批次 task 全完成但 DB 记录不全 | 收口器重新派发缺失批次，自身 retry |

### 3.3 批次 task 幂等写法

批次 task 的 `ocr_status` 规则：派发器把 material 置 `processing` 后，整个分片流程期间保持 `processing`，**批次 task 不改 `material.ocr_status`**。只有收口器在 finalize 成功时置 `completed`、不可救时置 `failed`。

```python
@celery_app.task(bind=True, name="process_ocr_batch", max_retries=3)
def process_ocr_batch(self, material_id, batch_index, batch_start, batch_end):
    # 1. 读 MinIO checkpoint，已完成则直接返回（幂等）
    checkpoint = _load_checkpoint(material_id, batch_index)
    if checkpoint and checkpoint["status"] == "completed":
        return {"skipped": "already_completed"}

    # 2. 协作式取消检查
    if _is_material_cancelled(material_id):
        return {"skipped": "cancelled"}

    # 3. 写 checkpoint 占位（status=processing）
    _write_checkpoint(material_id, batch_index, status="processing")

    # 4. 拆页 → OCR → 逐页写 MinIO pages/page_NNNN.json
    #    用 fitz 只打开 [batch_start, batch_end] 页
    #    每页写完后追加到 checkpoint.pages_written
    try:
        already_written = set(checkpoint.get("pages_written", [])) if checkpoint else set()
        for page_num in range(batch_start, batch_end + 1):
            if page_num in already_written:
                continue
            ... ocr ...
            store.write_page(page_num, results)  # 复用现有 EvidenceOCRStore.write_page
            _append_checkpoint_page(material_id, batch_index, page_num)
    except Exception as e:
        # checkpoint 标 failed 并累加 retries 计数（供收口器判断是否可救）
        _write_checkpoint(material_id, batch_index, status="failed",
                          error=str(e), retries=self.request.retries + 1)
        raise self.retry(exc=e)

    # 5. 标记批次完成 + 更新 DB EvidenceStep.completed_batches
    _write_checkpoint(material_id, batch_index, status="completed")
    _mark_batch_completed(material_id, batch_index)
```

**`failed_batches[].retries` 的更新时机**：批次 task catch 块写 checkpoint 时记录 `retries = self.request.retries + 1`（当前已重试次数）。收口器读 checkpoint 汇总到 DB `failed_batches`。

### 3.4 `EvidenceOCRStore` 改造

`EvidenceOCRStore` 不再是单 material 一个实例从创建活到 finalize，而是**每批 task 各自创建**，只负责 `write_page`。`finalize` 移到收口器。

需要的改造：
- 拆出 `_write_full_text_and_manifest(full_text_path, full_text_len, preview, summary)` 静态方法，供收口器复用
- 新增 `load_page_results(material_id, page_num)` 类方法，供 finalize 按页读回拼接
- 收口器流式拼接 full_text：临时文件累加各页文本 → 上传 MinIO，不全进内存

### 3.5 收口器失败处理策略

```python
@celery_app.task(bind=True, name="finalize_material_ocr", max_retries=5)
def finalize_material_ocr(self, material_id):
    progress = _load_progress(material_id)  # 从 EvidenceStep.step_metadata
    failed = [b for b in progress["failed_batches"] if b["retries"] < 3]
    missing = [i for i in range(total_batches)
               if i not in progress["completed_batches"]
               and i not in {b["index"] for b in failed}]

    if failed or missing:
        # 还有希望救的批次：重新派发
        for b in failed + missing:
            process_ocr_batch.delay(material_id, b["index"], ...)
        # 自身 60s 后重试，给批次留时间
        raise self.retry(countdown=60)

    # 检查是否真有不可救药的批次（retries >= 3）
    unrecoverable = [b for b in progress["failed_batches"] if b["retries"] >= 3]
    if unrecoverable:
        # 标记 material 失败，但已完成的页保留在 MinIO（用户可手动重试单批）
        material.ocr_status = "failed"
        material.ocr_result = {
            "error": f"{len(unrecoverable)} batches failed after max retries",
            "failed_batches": unrecoverable,
        }
        return

    # 全部完成 → 拼接 full_text + 写 manifest
    _assemble_full_text(material_id)   # 按 page_NNNN.json 顺序读、拼接、上传
    _write_manifest(material_id)
    material.ocr_status = "completed"
```

### 3.6 三种失败的区分

| 失败类型 | material.ocr_status | 用户看到 | 恢复方式 |
|---|---|---|---|
| 批次重试中 | `processing` | 进度条卡在 N/total，前端轮询继续 | 自动恢复 |
| 部分批次不可救 | `failed` | 错误提示"X 批失败" | 前端"重试"按钮 → 重新派发失败批次 |
| 收口器自身耗尽 retry | `failed` | 错误提示 | 前端"重试"按钮 → 重新派发 |

### 3.7 取消正在跑的大材料

现有 `/cases/{id}/cancel` 用 `inspect().active()` 找 Celery task_id 然后 revoke。分片后一个材料有 N+2 个 task，采用**协作式取消**：

- 在 DB 进度 `step_metadata.cancelled=True` 打标记
- 批次 task 开头检查此标记，是则直接 return
- 派发器/收口器开头也检查
- 不依赖 revoke（task 可能正在跑，revoke 不可靠）

### 3.8 数据一致性兜底

- **MinIO 写页是幂等的**：`page_NNNN.json` 覆盖写，重跑同一页结果一致
- **checkpoint 写采用 read-modify-write**：并发同批次重跑概率极低（Celery 同 task_id 不会并发），用 MinIO etag 做乐观锁兜底
- **full_text 拼接顺序**：finalize 时按 `page_NNNN.json` 的 N 排序，不依赖批次完成顺序
- **material.ocr_status 状态机**：`processing` 期间任何 finalize 失败都保持 `processing`，只有 finalize 成功才置 `completed`，避免半成品被分类器读到

---

## 4. 配置

### 4.1 新增配置项（`config/settings.py`）

```python
# ── 大 PDF 分片 OCR ──
# 触发分片的页数阈值；以下走单 task 老路径，以上走分片
ocr_shard_threshold_pages: int = 500
# 每个批次 task 处理的页数
ocr_batch_page_size: int = 200
# 单材料同时允许并行跑的批次数（Redis 信号量限流，0=不限）
ocr_batch_max_concurrent_per_material: int = 4
# 收口器轮询间隔（秒），重试 countdown
ocr_finalize_retry_countdown: int = 60
# 批次最大重试次数（覆盖 Celery 默认 3，给云端 OCR 更多机会）
ocr_batch_max_retries: int = 3
```

默认值开箱即用支持 10000 页。`ocr_batch_max_concurrent_per_material=4` 防止单材料把整个 worker 池占满。

### 4.2 Celery 配置调整（`worker/celery_app.py`）

```python
task_annotations = {
    "process_ocr_batch": {
        "soft_time_limit": 300,   # 5 分钟，200 页 OCR 足够
        "time_limit": 360,
    },
    "finalize_material_ocr": {
        "soft_time_limit": 120,
        "time_limit": 150,
    },
    "dispatch_material_ocr": {
        "soft_time_limit": 60,
        "time_limit": 90,
    },
}
```

不调全局 `task_time_limit`，避免影响 scan/analyze/export 等其他 task。

---

## 5. 改动范围

### 5.1 新增文件（1 个）

| 文件 | 职责 |
|---|---|
| `services/evidence/ocr_shard.py` | 分片编排核心：派发器/批次/收口器的纯函数 + DB 进度读写 + checkpoint 读写 + full_text 拼接 |

> 放 services 层而非 worker 层，理由：编排逻辑可被单测覆盖（mock Celery task），worker 只做 `delay()` 调用 + DB session 管理。

### 5.2 修改文件（5 个）

| 文件 | 改动 |
|---|---|
| `services/evidence/ocr_storage.py` | `EvidenceOCRStore` 拆出 `_write_full_text_and_manifest` 静态方法供收口器复用；新增 `load_page_results(material_id, page_num)` 类方法供 finalize 按页读回 |
| `worker/evidence_tasks.py` | 新增 3 个 `@celery_app.task`：`dispatch_material_ocr`、`process_ocr_batch`、`finalize_material_ocr`；`_run_ocr_pipeline` 改为派发 `dispatch_material_ocr` 后轮询 DB 等所有 material 完成；`process_single_material_ocr` 改为调派发器；`_ocr_single_material` 保留给小文件路径 |
| `config/settings.py` | 新增 6 个配置项 |
| `api/routes/evidence.py` | `retry-ocr` 端点：若材料走过分片且 DB 有进度记录，调 `dispatch_material_ocr` 走续传（只派发缺失批次）而非从头；`progress` 端点：透传 `step_metadata.completed_batches/total_batches` 给前端 |
| `static/src/views/EvidencePage.vue` | Step 1 进度卡片：分片材料显示 `已完成批次/总批次` 进度条；"重试 OCR"按钮文案分片失败时改为"重试失败批次" |

### 5.3 不动的文件（关键）

- `services/complaint/ocr_service.py` — `ocr_pdf_path` 已支持 `store` 参数 + `start_page/end_page`，分片 task 复用
- `services/preprocessor/pdf_splitter.py` — `split_to_images` 已支持 `start_page/end_page`
- 分类器、目录生成器、bundle_packager — 都走 `get_material_ocr_text` 懒加载，对分片透明
- DB 模型 — 不新增表/列，复用 `EvidenceStep.step_metadata`

---

## 6. 测试方案

### 6.1 单元测试（新增 `tests/test_ocr_shard.py`）

| 测试 | 覆盖点 |
|---|---|
| `test_batch_plan` | 10000 页 → 50 批，每批 200 页，最后一批可能不足 200 |
| `test_checkpoint_idempotent` | 同一批次重跑 → 读到 checkpoint completed → 直接返回，不重写 page_NNNN.json |
| `test_checkpoint_partial_retry` | checkpoint 记录 pages_written=[1..100]，重跑只处理 [101..200] |
| `test_finalize_assemble_order` | 批次乱序完成（批 3 先于批 1），finalize 仍按页号拼接 full_text |
| `test_finalize_detect_missing` | 缺批 2 → finalize 重新派发批 2 + 自身 retry |
| `test_finalize_unrecoverable` | 批 2 retries >= 3 → material 标 failed，已完成批次保留 |
| `test_cancel_cooperative` | DB 打 cancelled=True → 批次 task 开头检查直接 return |
| `test_small_file_skip_shard` | 300 页 → 不进分片路径，走 `_ocr_single_material` 老逻辑 |
| `test_progress_reporting` | 派发器写 total_batches，批次完成更新 completed_batches，前端可读 |

用 mock MinIO + mock Celery task（直接调函数，不真起 worker）。

### 6.2 集成测试（新增 `tests/test_ocr_shard_e2e.py`）

仿照现有 `scripts/test_ocr_offload_e2e.py`：

- 构造 600 页 PDF（越过 500 阈值，触发分片，3 批）
- 用真实 MinIO + mock OCR 引擎（返回固定文本）
- 跑完整 `dispatch → batch × 3 → finalize` 流程
- 校验：MinIO 有 600 个 `page_NNNN.json` + 1 个 `full_text.txt` + 1 个 `manifest.json`
- 校验：DB `material.ocr_status=completed`，`ocr_result.storage=minio`
- 校验：`get_material_ocr_text` 返回完整 600 页文本

### 6.3 断点续传测试（同 e2e 文件）

- 跑批 0、批 1 后模拟 worker 崩溃（mock 抛异常耗尽 retry）
- DB `material.ocr_status=failed`，MinIO 有 400 个 page_NNNN.json + 2 个 checkpoint
- 调 `retry-ocr` → 新派发器只派发批 2 → finalize → 全部完成
- 校验：MinIO 最终 600 个 page_NNNN.json，前 400 个未被覆盖重写（用 etag 对比）

### 6.4 现有回归

- `tests/test_ocr_storage.py` — `EvidenceOCRStore` 改造后仍须全绿
- `tests/test_evidence.py` — 端到端分类/目录/bundle 不受影响（分片对它们透明）
- 跑一遍现有 3000 页 e2e（< 500 阈值的场景走老路径，应无变化）

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 批次 task 并发把 worker 池占满，饿死其他 task | `ocr_batch_max_concurrent_per_material=4` Redis 信号量；后续可配 `task_routes` 路由到独立 queue |
| MinIO 小文件爆炸（10000 页 = 10000 个 page json + 50 个 checkpoint） | 已有 `delete_material_ocr` 清理；finalize 后可删 checkpoints（保留 pages 用于重试） |
| full_text.txt 拼接 10000 页内存峰值 | finalize 流式拼接：临时文件累加 → 上传 MinIO，不全进内存 |
| 用户重复点"重试"导致多个派发器并发 | 派发器开头检查 DB 是否已有 `step_name=ocr_shard` 且 status=sharding 的 step，有则直接 return |
| 分类器读 `get_material_ocr_text` 拉 10000 页全文 → LLM 截断 | 现有 `llm_context_material_detail_limit=12000` 已截断；不在本设计范围，记为后续优化点 |

---

## 8. 不做的事（YAGNI）

- 不做分片队列独立 worker（先复用单队列，容量不够再说）
- 不做批次优先级调度（按 index 顺序派发即可）
- 不做实时进度推送（前端轮询 DB 已够，不引入 WebSocket）
- 不做跨材料批次协调（每材料独立分片，互不干扰）
- 不做分片结果压缩（page_NNNN.json 单页本来就小）
- 不做单文件 > 10GB 的物理拆分（破坏材料语义，另一方案）
