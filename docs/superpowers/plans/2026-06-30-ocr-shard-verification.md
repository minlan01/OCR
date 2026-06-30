# 大 PDF 分片 OCR 真实端到端验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实 564 页 PDF + 真实 Celery worker + 真实百炼 OCR 端到端验证分片 OCR 编排全链路，修复暴露的问题，产出验证报告（不提交功能代码）。

**Architecture:** 三阶段验证：①冒烟（564 页完整跑通）②断点续传 + 并发限流（故障注入）③修复 + 回归 + 验证报告。验证通过 API 真实触发，不绕过任何层；修复针对性进行，每修一个跑单元/集成测试确保不回归。

**Tech Stack:** FastAPI + Celery + Redis + MinIO + PostgreSQL + 百炼 Qwen-VL-OCR + Docker Compose + pytest

## Global Constraints

- **不提交功能代码**（用户明确要求；仅验证 + 修复，git commit 仅用于设计文档/验证报告/回归测试新增）
- 验证用真实链路，**不在生产代码加 mock 钩子**（避免验证改造版失真）
- 564 页真实 PDF（用户提供的医疗扫描件），切 3 批（200+200+164）
- OCR 引擎：百炼 Qwen-VL（云端，有费用 + QPS 限流）
- 基础设施：docker-compose 全起；container 名为 `scanstruct-postgres`/`scanstruct-redis`/`scanstruct-minio`/`scanstruct-api`/`scanstruct-worker`/`scanstruct-worker-backup`
- **关键约束**：worker 跑的是 Docker 镜像（源码未 volume 挂载，仅挂 `logs/` 和 `scanstruct_ocrwork` 卷），分片代码改动（+628 行）未被运行的 worker 加载——Task 0 必须先解决
- **关键约束**：存在备用 worker `scanstruct-worker-backup`，stop 主 worker 会让 backup 接管队列而非停滞——断点续传测试设计需考虑此点
- 回归测试命令：`python -m pytest tests/test_ocr_shard.py tests/test_ocr_shard_e2e.py -q`
- 平台：Windows / PowerShell（命令不用 `&&` 连接，用 `;` 或分步执行）

---

## File Structure

**新建文件**：
- `scripts/verify_shard_e2e.py` — 真实端到端验证脚本（薄封装：上传→触发→轮询→校验产物；依赖真实 PDF + 百炼密钥，不进 CI）— **已在 Task 1 Step 2 创建**
- `docs/ocr_shard_verification_report_2026-06-30.md` — 验证报告

**可能修改的文件**（仅在暴露 bug 时）：
- `services/evidence/ocr_shard.py` — 编排纯函数
- `worker/evidence_tasks.py` — 4 个新 task
- `services/evidence/ocr_storage.py` — EvidenceOCRStore
- `config/settings.py` — 配置项
- `api/routes/evidence.py` — 续传/进度端点
- `static/src/views/EvidencePage.vue` — 前端进度展示

**不新建测试文件**：验证脚本非回归测试；若修复引入新单测，追加到 `tests/test_ocr_shard.py`。

---

## Task 0: 解决 worker 代码新鲜度问题

**Files:**
- Read: `docker-compose.yml:220-270`（worker 服务定义）
- Read: `Dockerfile.worker`

**背景**：worker 跑 Docker 镜像 `scanstruct-worker:latest`，源码未 volume 挂载。分片代码改动未被加载。若不解决，Task 1 冒烟会因 `dispatch_material_ocr` task 未注册而直接失败（Celery 抛 `NotRegistered`）。

- [ ] **Step 1: 检查 worker 当前加载的代码版本**

Run:
```powershell
docker exec scanstruct-worker python -c "from worker.evidence_tasks import dispatch_material_ocr; print('shard task registered:', dispatch_material_ocr.name)"
```

Expected（三种情况之一）:
- `shard task registered: dispatch_material_ocr` → worker 已有分片代码，跳到 Step 5
- `ImportError: cannot import name 'dispatch_material_ocr'` → 镜像旧，继续 Step 2
- `not registered` 类报错 → 镜像旧，继续 Step 2

- [ ] **Step 2: 若镜像旧，重建 worker 镜像**

Run:
```powershell
docker compose build worker worker-backup
```

Expected: 构建成功，输出 `naming to docker.io/library/scanstruct-worker:latest`

- [ ] **Step 3: 重启 worker 加载新镜像**

Run:
```powershell
docker compose up -d --force-recreate worker worker-backup
```

Expected: 两个 worker 容器 recreate，状态 `Started`

- [ ] **Step 4: 确认新代码已加载 + worker 健康**

Run:
```powershell
docker exec scanstruct-worker python -c "from worker.evidence_tasks import dispatch_material_ocr, process_ocr_batch, finalize_material_ocr, check_case_ocr_done; print('all 4 shard tasks registered')"
docker exec scanstruct-worker celery -A worker.celery_app inspect ping
```

Expected: `all 4 shard tasks registered` + `-> pong`

- [ ] **Step 5: 确认百炼配置就绪**

Run:
```powershell
docker exec scanstruct-worker python -c "from config.settings import settings; print('engine:', settings.ocr_engine_type); print('bailian_key_set:', bool(settings.bailian_api_key_plain))"
```

Expected: `engine: bailian`（或 `multi`）+ `bailian_key_set: True`

若 `bailian_key_set: False`：检查 `.env` 的 `BAILIAN_API_KEY`，必要时在 `docker-compose.yml` 的 `common-env` 锚点补充环境变量后重建。若 `engine` 不是 `bailian`/`multi`：与用户确认是否切引擎（影响验证真实性）。

- [ ] **Step 6: 记录 Task 0 结果到验证报告**

创建 `docs/ocr_shard_verification_report_2026-06-30.md`，写入 Task 0 小节：worker 镜像是否重建、引擎配置、4 task 注册确认结果。

---

## Task 1: 阶段 1 冒烟验证 — 564 页真实 PDF 完整跑通

**Files:**
- Created: `scripts/verify_shard_e2e.py`（已在 plan 编写阶段创建）
- Modify: `docs/ocr_shard_verification_report_2026-06-30.md`

**Interfaces:**
- Consumes: API endpoints `POST /api/evidence/cases`, `POST /api/evidence/cases/{id}/upload`, `POST /api/evidence/cases/{id}/process`, `GET /api/evidence/cases/{id}/progress`
- Produces: 一个真实 case + material，MinIO 产物齐全，验证报告 §1 内容

**前提**：Task 0 完成（worker 加载分片代码 + 百炼就绪）。用户已提供 564 页 PDF 路径。

- [ ] **Step 1: 确认 PDF 就位 + 页数**

Run:
```powershell
python -c "import fitz; doc=fitz.open(r'<用户提供的PDF路径>'); print('pages:', doc.page_count); doc.close()"
```

Expected: `pages: 564`（若 ≠ 564，记录实际页数，调整后续断言）

- [ ] **Step 2: 确认验证脚本就绪**

`scripts/verify_shard_e2e.py` 已创建。检查其内容：建 case → 上传 → 触发 process → 轮询 progress（看 `ocr_shard_progress.completed_batches` 递增）→ 校验产物（DB ocr_status + MinIO page json 数 + full_text + manifest）。

若 API 需认证：编辑脚本顶部 `API_KEY` / `TENANT_ID`，或从 `.env` 读取。

- [ ] **Step 3: 运行冒烟验证脚本**

Run:
```powershell
python scripts/verify_shard_e2e.py "<用户提供的PDF路径>"
```

Expected: 输出 `[1/6]`...`[6/6]` 逐步推进，最后 `冒烟验证 SUCCESS`。预计耗时 5-15 分钟（564 页 × 百炼 OCR，3 批并发 4）。

- [ ] **Step 4: 若失败，定位并记录问题**

若 Step 3 输出 `[FAIL]`，记录：
- 失败发生在哪一步（上传/触发/轮询/产物校验）
- 完整错误信息（从 `docker logs scanstruct-worker --tail 100` 取）
- 失败时 DB material.ocr_status 和 ocr_result

不要立即修复——收集完现象后，所有修复集中在 Task 4 处理。把问题记入验证报告 §1「发现的问题」。

- [ ] **Step 5: 前端进度展示验证**

脚本跑通后（或跑的过程中），浏览器打开 `http://localhost:8900`，进入对应 case 的 EvidencePage：
- 确认 Step 1（OCR）进度卡片显示「已完成批次/总批次」进度条
- 确认进度条随批次完成递增
- 截图或文字描述记入验证报告

- [ ] **Step 6: 把冒烟结果写入验证报告 §1**

在 `docs/ocr_shard_verification_report_2026-06-30.md` 追加 §1：
- 执行命令
- 分片进度时间线（批 0/1/2 完成时刻）
- 产物校验结果（DB 字段 + MinIO 对象数 + full_text 前 100 字）
- 前端观察
- 发现的问题（若有）

---

## Task 2: 阶段 2a 断点续传验证

**Files:**
- Modify: `docs/ocr_shard_verification_report_2026-06-30.md`

**Interfaces:**
- Consumes: Task 1 的验证脚本（复用流程）+ `docker stop/start scanstruct-worker` + MinIO etag 对比
- Produces: 验证报告 §2a 内容

**关键设计点**：存在 `scanstruct-worker-backup` 备用 worker。`docker stop scanstruct-worker` 后，backup 会接管队列（Celery `task_acks_late`）。为真正模拟「队列停滞 + 续传」，需同时 stop 两个 worker；或只 stop 主 worker 观察 backup 接管行为。两条路径都验证。

- [ ] **Step 1: 触发新一次 OCR（新 case + 新 material）**

用 Task 1 的脚本触发，但**不轮询到完成**——跑到批 0 完成后就介入。可以先开一个终端跑脚本，另一终端操作 docker。

或手动分步：
```powershell
# 建 case + 上传 + 触发 process（用 curl 或 python requests，参考 verify_shard_e2e.py 前 4 步）
```

- [ ] **Step 2: 等批 0 完成，记录崩溃前快照**

轮询 `GET /api/evidence/cases/{case_id}/progress`，等 `ocr_shard_progress.completed_batches` 含 0。

记录崩溃前快照（用于 etag 对比）：
```powershell
docker exec scanstruct-minio mc ls --recursive local/scan-result/evidence/{case_id}/ocr/{material_id}/pages/ > before_crash.txt
```

或用 python 记录每个 page json 的 etag：
```python
from services.storage.minio_client import minio_client
from config.settings import settings
prefix = f"evidence/{case_id}/ocr/{material_id}"
etags_before = {}
for obj in minio_client.list_objects(settings.minio_bucket_result, prefix=f"{prefix}/pages/"):
    etags_before[obj.object_name] = obj.etag
```

- [ ] **Step 3: 模拟崩溃 — 同时 stop 两个 worker**

```powershell
docker stop scanstruct-worker scanstruct-worker-backup
```

校验：DB `material.ocr_status` 仍为 `processing`（acks_late，任务重回队列）：
```powershell
docker exec scanstruct-postgres psql -U postgres -d scanstruct -c "SELECT ocr_status FROM evidence_materials WHERE id = '<material_id>';"
```

Expected: `processing`

- [ ] **Step 4: 重启 worker，观察续传**

```powershell
docker start scanstruct-worker scanstruct-worker-backup
```

观察 worker 日志：
```powershell
docker logs scanstruct-worker --tail 50 -f
```

期望看到：Celery redeliver 原 batch task；批 0 的 task 开头读 checkpoint `status=completed` 直接 return（幂等跳过）；批 1/2 继续跑。

- [ ] **Step 5: 若路径 A（自动 redeliver）失败，走路径 B（手动 retry-ocr）**

若 worker 重启后任务没有自动恢复（visibility_timeout 未到，原 task 仍被占有），调：
```powershell
curl -X POST http://localhost:8900/api/evidence/cases/{case_id}/materials/{material_id}/retry-ocr -H "Accept: application/json"
```

期望：触发 `dispatch_material_ocr`，dispatch_plan 发现已有 `status=sharding` 的 step，只派发 `pending_batches`。

- [ ] **Step 6: 等待完成，校验断点续传未重写已完成页**

轮询到 `case_status=catalog_ready`。

对比 etag：
```python
etags_after = {}
for obj in minio_client.list_objects(bucket, prefix=f"{prefix}/pages/"):
    etags_after[obj.object_name] = obj.etag
# 批 0 的 200 个 page（page_0001-0200）etag 应完全一致
unchanged = [k for k in etags_before if etags_after.get(k) == etags_before[k]]
assert len(unchanged) == len(etags_before), f"已有 page 被重写: {set(etags_before) - set(unchanged)}"
```

校验：
- 批 0 的 `checkpoints/batch_0000.json` 仍 `status=completed`
- 最终 `ocr_status=completed`
- MinIO 564 个 page json 齐全

- [ ] **Step 7: 把断点续传结果写入验证报告 §2a**

记录：崩溃时刻状态、续传路径（A/B）、etag 对比结果、最终产物。

---

## Task 3: 阶段 2b 并发限流验证

**Files:**
- Modify: `.env`（临时改 `OCR_BATCH_MAX_CONCURRENT_PER_MATERIAL=2`）
- Modify: `docs/ocr_shard_verification_report_2026-06-30.md`

**Interfaces:**
- Consumes: Task 1 验证脚本 + Redis CLI
- Produces: 验证报告 §2b 内容

- [ ] **Step 1: 临时调小并发限制**

编辑 `.env`，添加或修改：
```
OCR_BATCH_MAX_CONCURRENT_PER_MATERIAL=2
```

重建 + 重启 worker（配置走环境变量）：
```powershell
docker compose up -d --force-recreate worker worker-backup
```

确认配置生效：
```powershell
docker exec scanstruct-worker python -c "from config.settings import settings; print('max_concurrent:', settings.ocr_batch_max_concurrent_per_material)"
```

Expected: `max_concurrent: 2`

- [ ] **Step 2: 触发 OCR，观察批次排队**

触发新 case + 564 页 PDF 的 OCR（复用 Task 1 脚本，但跑到中途就观察）。

观察 worker 日志：
```powershell
docker logs scanstruct-worker --tail 100 -f
```

期望看到：
- 批 0、批 1 获得许可并行跑
- 批 2 `acquire_batch_slot` 失败 → 日志 `batch 2 slot full, retry in 10s` → `self.retry(countdown=10)`

- [ ] **Step 3: Redis 抽查信号量值**

在批次跑的过程中：
```powershell
docker exec scanstruct-redis redis-cli KEYS "scanstruct:ocr_batch_concurrent:*"
docker exec scanstruct-redis redis-cli GET "scanstruct:ocr_batch_concurrent:<material_id>"
```

Expected: key 存在，值始终 ≤ 2（批 0、1 跑时为 2；一个完成释放后变 1；批 2 获得后又变 2）

- [ ] **Step 4: 等待完成，校验信号量归零**

轮询到 `case_status=catalog_ready`。

```powershell
docker exec scanstruct-redis redis-cli GET "scanstruct:ocr_batch_concurrent:<material_id>"
```

Expected: key 不存在或值为 0（release 正确）

- [ ] **Step 5: 恢复配置**

编辑 `.env`，改回 `OCR_BATCH_MAX_CONCURRENT_PER_MATERIAL=4`（或删除该行用默认值）。

```powershell
docker compose up -d --force-recreate worker worker-backup
```

确认恢复：
```powershell
docker exec scanstruct-worker python -c "from config.settings import settings; print('max_concurrent:', settings.ocr_batch_max_concurrent_per_material)"
```

Expected: `max_concurrent: 4`

- [ ] **Step 6: 把并发限流结果写入验证报告 §2b**

记录：worker 日志片段（slot full retry）、Redis key 抽查值、最终归零确认、配置已恢复。

---

## Task 4: 阶段 3 修复暴露的问题 + 回归

**Files:**
- Modify（视问题而定）: `services/evidence/ocr_shard.py`, `worker/evidence_tasks.py`, `services/evidence/ocr_storage.py`, `config/settings.py`, `api/routes/evidence.py`, `static/src/views/EvidencePage.vue`
- Modify: `tests/test_ocr_shard.py`（若新增回归测试）
- Modify: `docs/ocr_shard_verification_report_2026-06-30.md`

** Interfaces:**
- Consumes: Task 1/2/3 发现的问题清单
- Produces: 修复后的代码 + 全绿回归测试 + 验证报告 §3

**原则**：每个问题单独定位、单独修复、单独跑回归。不批量改。

- [ ] **Step 1: 汇总问题清单**

从验证报告 §1/§2a/§2b 收集所有 `[FAIL]` 项和异常现象。按类型分类：
- 编排逻辑 bug（ocr_shard.py / evidence_tasks.py）
- 存储 bug（ocr_storage.py / minio 交互）
- 配置 bug（settings.py / 环境变量传递）
- API bug（evidence.py 路由）
- 前端 bug（EvidencePage.vue）

若 Task 1/2/3 全过无问题，跳到 Step 5（仅写报告结论）。

- [ ] **Step 2: 逐个修复 — 每个问题的修复循环**

对每个问题执行子循环：

- [ ] **Step 2a: 定位根因**

读相关代码，确认 bug 位置（具体文件:行号）。把根因写进验证报告 §3 该问题条目。

- [ ] **Step 2b: 写最小修复**

只改 bug 相关代码，不顺手重构。改动后用 `ReadLints` 检查引入的 lint 错误并修复。

- [ ] **Step 2c: 跑回归测试**

```powershell
python -m pytest tests/test_ocr_shard.py tests/test_ocr_shard_e2e.py -q
```

Expected: 全绿。若挂了，修复到全绿（可能需补充测试用例覆盖该 bug 场景，追加到 `tests/test_ocr_shard.py`）。

- [ ] **Step 2d: 用 Task 1 冒烟流程复验**

仅当修复涉及编排/存储核心逻辑时，重跑一次 Task 1 冒烟确认未引入回归。若修复仅是配置/前端，跳过。

- [ ] **Step 3: 预期可能的问题及预案**

基于代码审读，以下是高概率问题及其修复方向（实际以 Step 1 清单为准）：

1. **百炼 429 限流**：批次并发 4 × 200 页触发 QPS 限制 → worker 日志大量 `batch N failed (retry 1/3)`。
   - 修复方向：调小 `ocr_batch_max_concurrent_per_material` 到 2，或给 `ocr_pdf_page_range` 内的百炼调用加退避（检查 `bailian_engine.py` 是否已有 retry）。

2. **`_get_case_id_for_material` 同步引擎反复创建/销毁**：每个 checkpoint 操作都 `create_engine + dispose`，564 页高频调用可能拖慢。
   - 修复方向：在 `ocr_shard.py` 模块级缓存 case_id（dict + lock），或复用一个模块级 engine。

3. **`pdf_local_path` 跨 worker 重启丢失**：`OCR_WORK_DIR` 是 named volume `scanstruct_ocrwork`，重启不丢；但若用 tmpfs `/tmp` 会丢。检查 `docker-compose.yml:249` tmpfs 配置。
   - 修复方向：若临时文件在 tmpfs，dispatch 重试时幂等检查（文件存在 + 大小匹配）会触发重新下载——验证此路径确实工作即可，无需改代码。

4. **前端进度卡片渲染异常**：`EvidencePage.vue` 的 `ocr_shard_progress` 字段名/结构与后端不匹配。
   - 修复方向：对齐 `api/routes/evidence.py:760-786` 返回的 `ocr_shard_progress` 结构与 Vue 组件读取的字段。

- [ ] **Step 4: 把每个问题的修复写入验证报告 §3**

每个问题条目含：现象 / 根因（文件:行号）/ 修复（diff 摘要）/ 回归结果（测试命令 + 输出）。

- [ ] **Step 5: 写验证报告结论**

在报告末尾写结论段：
- 分片 OCR 是否达到可提交标准（冒烟 + 断点续传 + 并发限流是否全过）
- 遗留风险（若有）
- 建议下一步（提交 / 补压测 / 处理架构审查其他项）

- [ ] **Step 6: 最终全量回归**

```powershell
python -m pytest tests/test_ocr_shard.py tests/test_ocr_shard_e2e.py -q
```

Expected: `30 passed`（24 + 6）或更多（若 Step 2c 补了新用例）。

记录最终测试输出到验证报告。

---

## Self-Review

**1. Spec coverage**：
- spec §1 目标（真实端到端验证 + 修复 + 报告）→ Task 1/2/3/4 ✓
- spec §2 三阶段架构 → Task 1（冒烟）/ Task 2（断点续传）/ Task 3（并发限流）/ Task 4（修复+报告）✓
- spec §3 冒烟详细执行 → Task 1 全覆盖（前置检查、6 步执行、产物校验、风险点）✓
- spec §3.4 预期风险点 → Task 4 Step 3 预案覆盖 ✓
- spec §4.1 断点续传 → Task 2 全覆盖（崩溃前快照、stop、重启、etag 对比）✓
- spec §4.2 并发限流 → Task 3 全覆盖（调配置、观察排队、Redis 抽查、归零、恢复）✓
- spec §4.4 pdf_local_path 跨重启风险 → Task 4 Step 3 预案 3 覆盖 ✓
- spec §5 修复原则 → Task 4 Step 2 子循环（定位/最小修复/回归/复验）✓
- spec §6 验证报告 → Task 1/2/3/4 各自写入报告对应小节 ✓
- spec §7 风险与缓解 → Task 4 Step 3 预案覆盖主要风险 ✓
- spec §8 YAGNI（不做 3000 页压测等）→ 计划中无压测任务 ✓

**2. Placeholder scan**：无 TBD/TODO/"implement later"。`<用户提供的PDF路径>`、`<material_id>` 等是运行时变量，Step 1 都有确认命令。`<case_id>` 由脚本动态生成。✓

**3. Type/signature consistency**：
- 验证脚本调 `minio_client.list_objects` / `download_bytes` / `settings.minio_bucket_result` — 与 `ocr_storage.py`/`ocr_shard.py` 实际使用一致 ✓
- API 端点路径 `/api/evidence/cases`、`/upload`、`/process`、`/progress`、`/retry-ocr` — 与 `api/routes/evidence.py` grep 出的路由一致 ✓
- 配置项名 `ocr_batch_max_concurrent_per_material` — 与 `config/settings.py:119` 一致 ✓
- Redis key `scanstruct:ocr_batch_concurrent:{material_id}` — 与 `ocr_shard.py:36` `_BATCH_SEMAPHORE_PREFIX` 一致 ✓
- container 名 `scanstruct-worker`/`scanstruct-worker-backup`/`scanstruct-redis`/`scanstruct-minio`/`scanstruct-postgres` — 与 `docker-compose.yml` grep 出的 `container_name` 一致 ✓

无问题，计划可执行。
