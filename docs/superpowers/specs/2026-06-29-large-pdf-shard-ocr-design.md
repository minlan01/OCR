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
        │       │  下载 PDF 到 OCR_WORK_DIR（一次，路径记入 DB）
        │       │  读总页数 → 按 200 页/批切分
        │       │  为每批派发（传本地 PDF 路径）：
        │       ├─→ process_ocr_batch(m_id, 0, 1,   200, pdf_path)   ┐
        │       ├─→ process_ocr_batch(m_id, 1, 201, 400, pdf_path)   ├─ N 批并行
        │       └─→ process_ocr_batch(m_id, 49, 9801, 10000, pdf_path) ┘
        │                  │
        │                  │  每批：用 fitz 打开 pdf_path 指定页段→OCR→写 MinIO pages/page_NNNN.json
        │                  │  完成后更新进度（已完成的批次 index）
        │                  ▼
        └─→ finalize_material_ocr(material_id)        [收口器]
                │  检查是否所有批次都完成
                │  是 → 拼接 full_text.txt + 写 manifest.json
                │       更新 material.ocr_status=completed
                │       删除本地 PDF 临时文件
                │       触发 check_case_ocr_done(case_id)
                │  否 → 找出缺失/失败批次，重新派发；自身 retry
```

**关键：`process_evidence_full` 不轮询等待**。它派发完所有 material 的 `dispatch_material_ocr.delay()` 后立即返回，不阻塞。最后一个 material 的收口器在 finalize 成功时触发 `check_case_ocr_done.delay(case_id)`，由它检查 case 下所有 material 是否都 `completed`/`failed`，是则推进到分类阶段（调 `_run_classify_pipeline_optimized` + `generate_catalog`）。

这避免了"`process_evidence_full` 轮询 DB 等待期间自身 30 分钟超时撞墙"的问题——派发是秒级返回，超时风险消失。

### 2.2 四个新 Celery task

| Task | 输入 | 职责 | 耗时 | max_retries |
|---|---|---|---|---|
| `dispatch_material_ocr` | `material_id` | 下载 PDF 到本地、读页数、切批、派发批次 task、派发收口 task | <30s（含下载） | 2 |
| `process_ocr_batch` | `material_id, batch_index, batch_start, batch_end, pdf_path` | 用 fitz 打开 pdf_path 指定页段→OCR→写 MinIO→更新进度 | 30s-2min | 3 |
| `finalize_material_ocr` | `material_id` | 检查进度、补缺、拼接 full_text、写 manifest、更新 material、清理本地 PDF、触发 case 检查 | 10-60s | 5 |
| `check_case_ocr_done` | `case_id` | 检查 case 下所有 material 是否终态，是则推进分类+目录阶段 | <5s | 3 |

`check_case_ocr_done` 的幂等性：多个 material 同时 finalize 会触发多次，开头检查 case 状态——若已进入 `catalog_ready`/分类中则直接 return；若仍有 material 在 `processing` 则 return（等下一个 finalize 触发）；只有全部终态才推进。

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

**信号量设计**（复用 `services/utils/task_concurrency.py` 的 Lua 脚本模式）：

```python
# acquire（Lua 原子）：INCR key → 若 > limit 则 DECR 并返回失败
# release：DECR key（不小于 0）
# key: scanstruct:ocr_batch_concurrent:{material_id}
# TTL: 7200s（与现有 task_concurrency 一致，兜底 worker 崩溃）
```

- **acquire 时机**：批次 task 开头（checkpoint 幂等检查之后、实际 OCR 之前）
- **release 时机**：批次 task 的 `finally` 块（无论成功/失败/重试都释放）
- **acquire 失败**：批次 task 走 `self.retry(countdown=10)`，短退避后重试获取
- **TTL 兜底**：worker 崩溃后信号量 2 小时自动过期，不会永久占位

### 2.6 与现有流程的衔接

- `process_evidence_full` 里 `_run_ocr_pipeline` 改为：对所有 material 调 `dispatch_material_ocr.delay()` 后**立即返回**（不轮询）。case 进入分类阶段的触发点移到 `check_case_ocr_done` task
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

### 2.8 PDF 分发策略（避免重复下载）

派发器下载一次 PDF 到 `OCR_WORK_DIR` 本地路径，各批次 task 共享这个路径（通过 task 参数 `pdf_path` 传入），收口器负责清理。

```
派发器：
  1. minio_client.download_file(bucket, key, local_path)  # 流式下载到 OCR_WORK_DIR
  2. 记录 local_path 到 DB EvidenceStep.step_metadata.pdf_local_path
  3. fitz.open(local_path).page_count 读总页数
  4. 切批，每批 process_ocr_batch.delay(material_id, idx, start, end, local_path)

批次 task：
  1. fitz.open(pdf_path) 打开本地路径（fitz 支持多进程只读打开同一文件）
  2. 只渲染 [batch_start, batch_end] 页

收口器 finalize 成功后：
  1. os.unlink(pdf_local_path)  # 清理本地 PDF
  2. delete_material_ocr 不动 pages/（保留供重试）
```

**安全性**：
- `OCR_WORK_DIR` 是磁盘卷（非 tmpfs），多 worker 进程可共享读
- 派发器失败重试时，若 `pdf_local_path` 已存在且文件大小匹配 MinIO，跳过下载（幂等）
- 收口器失败重试时，若本地 PDF 已被清理，重新从 MinIO 下载（极端情况，正常路径不会触发）
- worker 重启后 `OCR_WORK_DIR` 残留文件由现有 `_cleanup_tmp_dir` 的 1 小时过期逻辑兜底清理

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
def process_ocr_batch(self, material_id, batch_index, batch_start, batch_end, pdf_path):
    # 1. 读 MinIO checkpoint，已完成则直接返回（幂等）
    checkpoint = _load_checkpoint(material_id, batch_index)
    if checkpoint and checkpoint["status"] == "completed":
        return {"skipped": "already_completed"}

    # 2. 协作式取消检查
    if _is_material_cancelled(material_id):
        return {"skipped": "cancelled"}

    # 3. 写 checkpoint 占位（status=processing）
    _write_checkpoint(material_id, batch_index, status="processing")

    # 4. 用 fitz 打开 pdf_path 指定页段 → OCR → 逐页写 MinIO pages/page_NNNN.json
    #    每页写完后追加到 checkpoint.pages_written
    try:
        already_written = set(checkpoint.get("pages_written", [])) if checkpoint else set()
        for page_num in range(batch_start, batch_end + 1):
            if page_num in already_written:
                continue
            ... ocr (fitz 打开 pdf_path, 渲染 page_num) ...
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

**关键约束：`finalize` 方法保留，不删除**。老路径（小文件 inline + 500 页以下单 task 大文件 offload）继续用 `EvidenceOCRStore` 的 `write_page` + `finalize` 完整流程。现有 `worker/evidence_tasks.py:775-784` 调 `store.finalize()` 的代码不动。

分片路径下，每批 task 各自创建 `EvidenceOCRStore` 实例，**只调 `write_page`**（写 `pages/page_NNNN.json` + 累加本地 text 临时文件）。批次 task 完成后**不调 finalize**，直接销毁实例（`abort` 清理本地临时文件即可，MinIO pages 已写完保留）。

收口器负责 finalize 阶段的工作，但**不通过 `EvidenceOCRStore.finalize`**，而是调新拆出的静态方法：

需要的改造：
- 新增**静态方法** `_write_full_text_and_manifest(bucket, prefix, full_text_path, full_text_len, preview, summary)`：上传 full_text.txt + manifest.json 到指定 MinIO 路径。`EvidenceOCRStore.finalize` 内部也调它（代码复用，行为不变）
- 新增**类方法** `load_page_text(material_id, page_num)` → `str`：从 MinIO 读 `pages/page_NNNN.json`，提取 `text` 字段。供收口器拼接 full_text 用
- 收口器流式拼接 full_text：见 §3.5a

**对现有测试的影响**：`test_ocr_storage.py::test_evidence_ocr_store_write_and_finalize` 不受影响（`finalize` 行为不变，只是内部多调一个静态方法）。

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
        # 失败也触发 case 检查（让 check_case_ocr_done 判断是否全部终态）
        check_case_ocr_done.delay(str(material.evidence_case_id))
        return

    # 全部完成 → 拼接 full_text + 写 manifest
    _assemble_full_text(material_id)   # 见 §3.5a
    _write_manifest(material_id)
    material.ocr_status = "completed"

    # 清理本地 PDF 临时文件
    pdf_local_path = progress.get("pdf_local_path")
    if pdf_local_path:
        _cleanup_temp_files(pdf_local_path)

    # 触发 case 级检查
    check_case_ocr_done.delay(str(material.evidence_case_id))
```

### 3.5a `_assemble_full_text` 流式拼接策略

10000 页的 `page_NNNN.json` 散落在 MinIO，收口器按页号顺序读回拼接 full_text.txt：

```python
def _assemble_full_text(material_id):
    """流式拼接 full_text.txt：并发下载页 JSON → 提取 text → 追加写临时文件 → 上传 MinIO"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    progress = _load_progress(material_id)
    total_pages = progress["total_pages"]

    work_base = os.getenv("OCR_WORK_DIR") or None
    fd, tmp_path = tempfile.mkstemp(dir=work_base, suffix=".full_text.txt")
    os.close(fd)

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            # 按页号顺序的写锁 + 并发下载
            # 用 dict 收集 {page_num: text}，写时按 1..total_pages 顺序遍历
            page_texts: dict[int, str] = {}
            CONCURRENT = 10  # 并发下载数，避免 10000 次串行 GET

            def _fetch(page_num):
                return page_num, EvidenceOCRStore.load_page_text(material_id, page_num)

            with ThreadPoolExecutor(max_workers=CONCURRENT) as pool:
                futures = {pool.submit(_fetch, p): p for p in range(1, total_pages + 1)}
                for fut in as_completed(futures):
                    page_num, text = fut.result()
                    page_texts[page_num] = text

            # 按页号顺序追加写
            for p in range(1, total_pages + 1):
                text = page_texts.get(p, "")
                if text:
                    f.write(text)
                    f.write("\n")

        full_text_len = os.path.getsize(tmp_path)
        # 复用 EvidenceOCRStore 拆出的静态方法上传 + 写 manifest
        EvidenceOCRStore._write_full_text_and_manifest(
            bucket, prefix, tmp_path, full_text_len, preview, summary
        )
    finally:
        _cleanup_temp_files(tmp_path)
```

- **并发度 10**：10000 页 / 10 并发 ≈ 1000 轮，每轮 ~50ms → ~50s，可接受
- **内存峰值**：`page_texts` dict 存全部页文本（10000 页约 50-200MB），是收口器唯一内存压力点。若未来需进一步优化，可改为"每下载 N 页就 flush 到临时文件"的滑动窗口，但当前 200MB 在 4GB worker 内存预算内可接受
- **只取 text 字段**：`load_page_text` 只读 JSON 的 `text`，不读 `blocks`（blocks 留在 pages/ 供后续按需取，不进 full_text）

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
- **DB `step_metadata` 进度更新用原子 SQL**：批次完成时不用 read-modify-write，而是用 `jsonb_set` + `||` 数组拼接的原子 UPDATE：

```sql
UPDATE evidence_steps
SET step_metadata = jsonb_set(
    step_metadata,
    '{completed_batches}',
    (step_metadata->'completed_batches') || to_jsonb($batch_index::int)
)
WHERE case_id = $case_id AND step_name = 'ocr_shard'
  AND NOT ($batch_index = ANY(SELECT jsonb_array_elements_text(step_metadata->'completed_batches')::int));
```

`failed_batches` 更新同理用 `||` 拼接。`WHERE NOT ...` 防重复 append。两个批次 task 同时完成时，PostgreSQL 行级锁串行化两个 UPDATE，不会丢记录。

- **MinIO checkpoint 写采用 read-modify-write**：并发同批次重跑概率极低（Celery 同 task_id 不会并发），用 MinIO etag 做乐观锁兜底
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
        "soft_time_limit": 180,   # 3 分钟，含 10000 页 full_text 拼接
        "time_limit": 210,
    },
    "dispatch_material_ocr": {
        "soft_time_limit": 120,   # 2 分钟，含 PDF 下载
        "time_limit": 150,
    },
    "check_case_ocr_done": {
        "soft_time_limit": 30,
        "time_limit": 60,
    },
}
```

不调全局 `task_time_limit`，避免影响 scan/analyze/export 等其他 task。

**`visibility_timeout` 必须覆盖最大 task `time_limit`**。现有 `celery_app.py:54` 是 `celery_task_timeout_seconds + 600`（绑定全局超时），但分片 task 用 `task_annotations` 单独配了更短超时，全局绑定方式不再正确。

改为显式计算所有 task 超时的最大值：

```python
# visibility_timeout 必须 >= 所有 task 的 time_limit 最大值 + buffer
# 否则长任务会被 Redis 重新派发给另一个 worker，导致同任务双跑
_max_task_time_limit = max(
    settings.celery_task_timeout_seconds,  # 全局默认（scan/analyze/export 用）
    360,  # process_ocr_batch
    210,  # finalize_material_ocr
    150,  # dispatch_material_ocr
    60,   # check_case_ocr_done
)
broker_transport_options={
    "max_connections": 10,
    "health_check_interval": 30,
    "visibility_timeout": _max_task_time_limit + 600,
}
```

这样无论全局超时怎么调，`visibility_timeout` 始终 >= 任何 task 的硬超时 + 10 分钟 buffer，杜绝双跑。

---

## 5. 改动范围

### 5.1 新增文件（1 个）

| 文件 | 职责 |
|---|---|
| `services/evidence/ocr_shard.py` | 分片编排核心：派发器/批次/收口器的纯函数 + DB 进度读写 + checkpoint 读写 + full_text 拼接 |

> 放 services 层而非 worker 层，理由：编排逻辑可被单测覆盖（mock Celery task），worker 只做 `delay()` 调用 + DB session 管理。

### 5.2 修改文件（6 个）

| 文件 | 改动 |
|---|---|
| `services/evidence/ocr_storage.py` | `EvidenceOCRStore` 拆出 `_write_full_text_and_manifest` 静态方法供收口器复用；新增 `load_page_text(material_id, page_num)` 类方法供 finalize 按页读回 |
| `worker/evidence_tasks.py` | 新增 4 个 `@celery_app.task`：`dispatch_material_ocr`、`process_ocr_batch`、`finalize_material_ocr`、`check_case_ocr_done`；`_run_ocr_pipeline` 改为派发 `dispatch_material_ocr` 后立即返回（不轮询）；`process_single_material_ocr` 改为调派发器；`_ocr_single_material` 保留给小文件路径 |
| `config/settings.py` | 新增 6 个配置项 |
| `worker/celery_app.py` | 新增 `task_annotations`（4 个新 task 的独立超时）；`visibility_timeout` 改为取所有 task `time_limit` 最大值 + buffer |
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
| `test_dispatch_concurrent_idempotent` | 模拟用户连点两次"重试" → 两个派发器并发 → 第二个检查 DB status=sharding 直接 return，不重复派发批次 |
| `test_db_progress_atomic_update` | 两个批次 task 同时完成 → 并发调 `_mark_batch_completed` → DB `completed_batches` 同时含两个 index，不丢记录（用 `jsonb_set` + `||` 原子 SQL） |
| `test_selected_pages_with_shard` | 600 页 PDF + selected_pages=[10,20,30,...,100]（50 页）→ 走分片但只 OCR 选定页，full_text 只含选定页文本 |
| `test_check_case_ocr_done_idempotent` | case 下 3 个 material，前 2 个 finalize 触发 check → 仍有 processing 直接 return；第 3 个 finalize 触发 check → 全部终态 → 推进分类 |
| `test_finalize_retry_loop_progress` | 批次一直失败 → 收口器 5 次 retry（每次 countdown=60s）期间 material 保持 `processing` → 第 5 次失败置 `failed` → 前端轮询能看到 `failed_batches` 详情 |

用 mock MinIO + mock Celery task（直接调函数，不真起 worker）。

### 6.2 集成测试（新增 `tests/test_ocr_shard_e2e.py`）

仿照现有 `scripts/test_ocr_offload_e2e.py`：

- 构造 600 页 PDF（越过 500 阈值，触发分片，3 批）
- 用真实 MinIO + mock OCR 引擎（返回固定文本）
- 跑完整 `dispatch → batch × 3 → finalize → check_case_ocr_done` 流程
- 校验：MinIO 有 600 个 `page_NNNN.json` + 1 个 `full_text.txt` + 1 个 `manifest.json`
- 校验：DB `material.ocr_status=completed`，`ocr_result.storage=minio`
- 校验：`get_material_ocr_text` 返回完整 600 页文本
- 校验：本地 PDF 临时文件已被清理
- 校验：`check_case_ocr_done` 触发后 case 状态推进到 `catalog_ready`

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
| 批次 task 并发把 worker 池占满，饿死其他 task | `ocr_batch_max_concurrent_per_material=4` Redis 信号量（§2.5）；后续可配 `task_routes` 路由到独立 queue |
| MinIO 小文件爆炸（10000 页 = 10000 个 page json + 50 个 checkpoint） | 已有 `delete_material_ocr` 清理；finalize 后可删 checkpoints（保留 pages 用于重试） |
| full_text.txt 拼接 10000 页内存峰值 | §3.5a `_assemble_full_text` 并发 10 下载 + 流式写临时文件；`page_texts` dict 峰值约 200MB，在 4GB worker 预算内 |
| 用户重复点"重试"导致多个派发器并发 | 派发器开头检查 DB 是否已有 `step_name=ocr_shard` 且 status=sharding 的 step，有则直接 return；有 `test_dispatch_concurrent_idempotent` 测试覆盖 |
| 分类器读 `get_material_ocr_text` 拉 10000 页全文 → LLM 截断 | 现有 `llm_context_material_detail_limit=12000` 已截断；不在本设计范围，记为后续优化点 |
| `check_case_ocr_done` 被多个 finalize 同时触发，并发推进分类 | task 开头检查 case 状态，已 `catalog_ready` 则 return；`_run_classify_pipeline_optimized` 本身幂等（覆盖写 `extracted_data`）；有 `test_check_case_ocr_done_idempotent` 测试覆盖 |
| 收口器 retry 死循环（批次一直失败） | `max_retries=5`，每次 `countdown=60s`，最多 5 分钟；5 次后 material 置 `failed`，前端可读 `failed_batches` 详情手动重试；有 `test_finalize_retry_loop_progress` 测试覆盖 |
| 本地 PDF 临时文件残留（worker 崩溃后未清理） | 收口器 finalize 成功后清理；`_cleanup_tmp_dir` 的 1 小时过期逻辑兜底；派发器重试时检查文件大小匹配 MinIO 则跳过下载 |

---

## 8. 不做的事（YAGNI）

- 不做分片队列独立 worker（先复用单队列，容量不够再说）
- 不做批次优先级调度（按 index 顺序派发即可）
- 不做实时进度推送（前端轮询 DB 已够，不引入 WebSocket）
- 不做跨材料批次协调（每材料独立分片，互不干扰）
- 不做分片结果压缩（page_NNNN.json 单页本来就小）
- 不做单文件 > 10GB 的物理拆分（破坏材料语义，另一方案）
