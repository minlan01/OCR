# 大 PDF 分片 OCR 真实端到端验证设计

> 状态：已认可，待写实现计划
> 日期：2026-06-30
> 关联：`docs/superpowers/specs/2026-06-29-large-pdf-shard-ocr-design.md`（分片实现 spec，已落地）
> 范围：**只验证 + 修复，不提交功能代码**

## 1. 背景与目标

### 1.1 现状

大 PDF 分片 OCR 的实现已落地（`services/evidence/ocr_shard.py` + `worker/evidence_tasks.py` 4 个新 task + `ocr_storage.py` 改造 + `config/settings.py` 6 个配置项 + `celery_app.py` task_annotations + `api/routes/evidence.py` 续传/进度透传 + `EvidencePage.vue` 分片进度展示），共 19 文件 +1329/-289 行改动，**尚未提交**。

测试层面：`tests/test_ocr_shard.py`（24 用例）+ `tests/test_ocr_shard_e2e.py`（6 用例）全绿，但 e2e 用的是 mock MinIO + mock DB + mock OCR，**没有真实大 PDF + 真实 worker + 真实百炼 OCR 的端到端验证**。

### 1.2 目标

- 用真实医疗扫描件 PDF + 真实 Celery worker + 真实百炼 Qwen-VL OCR，验证分片编排全链路跑通
- 验证断点续传（worker 崩溃后重启）与并发限流（Redis 信号量）的真实行为
- 修复验证中暴露的问题，确保单元/集成测试不回归
- 产出验证报告记录跑通的命令、产物校验、发现并修复的问题

### 1.3 非目标

- **不做 git commit**（用户明确要求只验证 + 修复，先不提交功能代码）
- 不重构分片编排架构（spec 已定型，仅在暴露 bug 时做针对性修复）
- 不处理架构审查 P0/P1 中与 OCR 无关的债务
- 不做 3000+ 页压测（用户只有 564 页 PDF）

### 1.4 约束

| 维度 | 决定 |
|------|------|
| 验证方式 | 真实大 PDF + 真实 Celery worker 端到端 |
| 基础设施 | docker-compose 全起、worker 在跑（需确认加载最新代码） |
| OCR 引擎 | 云端百炼 Qwen-VL（有费用 + QPS 限流） |
| 测试 PDF | 用户提供的真实医疗扫描件，564 页（> 500 阈值，切 3 批） |
| 提交策略 | 不提交功能代码；本设计文档单独提交 |

---

## 2. 验证架构：三阶段策略

```
阶段 1：冒烟验证（564 页真实 PDF，真实百炼）
  进入：基础设施全在线、worker 加载最新代码、百炼 key 配置、PDF 就位
  流程：上传 → process_evidence_full → dispatch → batch×3 → finalize → check_case_ocr_done → 分类
  退出：MinIO 产物齐全 + DB ocr_status=completed + 前端进度可见 + 无未捕获异常

阶段 2：断点续传 + 并发限流验证（同一 564 页 PDF）
  2a 断点续传：批 1 完成后 docker stop worker → 重启 → 续传 → 校验未重写已完成页
  2b 并发限流：临时 ocr_batch_max_concurrent_per_material=2，观察批 2 排队 retry
  2c 内存观察：docker stats 记录 worker 内存峰值基线
  退出：断点续传未重做已完成工作 + 信号量计数正确 + 最终 completed

阶段 3：修复与回归
  对阶段 1/2 暴露的问题逐个修复，每修一个跑单元+集成测试确保不回归
  产出验证报告 docs/ocr_shard_verification_report_2026-06-30.md
  退出：所有暴露问题已修 + 单元/集成测试全绿 + 报告写完
```

**关键设计决策**：
- **不新建测试文件**，验证脚本放 `scripts/`（依赖真实 PDF + 百炼密钥，不进 CI）
- **不修改生产代码做 mock 钩子**——验证用真实链路，避免"验证的是改造版"的失真
- **监控用 `docker stats` + worker 日志 + DB 查询**，不引入额外监控设施
- **564 页不构成压测**，阶段 2 定位为"故障注入与边界验证"而非"压测"

---

## 3. 阶段 1：冒烟验证详细执行

### 3.1 前置检查

1. **worker 代码新鲜度**：`worker/evidence_tasks.py` 改了 628 行，Celery `--pool=solo` 不热重载。检查 worker 启动时间 vs 文件 mtime，必要时 `docker restart scanstruct-worker`
2. **百炼配置**：`.env` 中 `BAILIAN_API_KEY` 非空、`OCR_ENGINE=bailian`（或对应配置）、余额充足
3. **PDF 就位**：用户提供的 564 页 PDF 放到约定路径，用 `fitz` 确认 `page_count=564 > 500`（触发分片）

### 3.2 执行步骤（通过 API 真实触发，不绕过任何层）

1. **建案件 + 上传材料**：`POST /api/evidence/cases`（或用现有 case）→ `POST /api/evidence/cases/{case_id}/materials` 上传真实 PDF 到 MinIO
2. **触发 OCR**：`POST /api/evidence/cases/{case_id}/ocr` → `process_evidence_full` → 内部对 PDF 派发 `dispatch_material_ocr`
3. **轮询进度**：`GET /api/evidence/cases/{case_id}/progress`，观察 `ocr_shard_progress`（completed_batches 从 0 → 3 递增）
4. **等待终态**：轮询直到 case 状态进入 `catalog_ready`（说明 `check_case_ocr_done` 推进了分类）
5. **产物校验**：
   - DB：`SELECT ocr_status, ocr_result FROM evidence_materials WHERE id=?` → `ocr_status=completed`、`ocr_result.storage=minio`、`ocr_result.source_type=pdf_ocr_shard`、`ocr_result.page_count=564`
   - MinIO：`evidence/{case_id}/ocr/{material_id}/` 下 564 个 `pages/page_NNNN.json` + 1 个 `full_text.txt` + 1 个 `manifest.json` + 3 个 `checkpoints/batch_NNNN.json`
   - `full_text.txt` 内容合理（真实 OCR 文本，非空，按页号顺序）
6. **前端验证**：浏览器打开 EvidencePage，确认分片进度卡片显示 `已完成批次/总批次` 进度条

### 3.3 退出条件

以上 6 项全过；任一失败 → 记录问题 → 进入阶段 3 修复 → 修复后回到阶段 1 复验。

### 3.4 预期风险点（重点观察）

- **worker 未加载新代码**：dispatch task 不存在 → 任务直接失败（celery 抛 `NotRegistered`）
- **百炼 QPS 限流**：批次并发 4 × 每批 200 页可能触发 429 → 批次 task retry 风暴（观察 worker 日志 `batch N failed` 频率）
- **`_get_case_id_for_material` 同步引擎反复创建/销毁**：每个 checkpoint 操作都 `create_engine + dispose`，高频调用可能拖慢
- **`process_evidence_full` 是否真的不阻塞**：spec 设计派发后立即返回，验证 DB step 是否迅速进入 `ocr_shard` 状态而非卡在 `ocr` step

---

## 4. 阶段 2：断点续传与并发限流验证

### 4.1 2a 断点续传验证

**操作**：
1. 触发 OCR（同阶段 1）
2. 轮询进度，等批 0（页 1-200）完成（`completed_batches` 含 0）
3. 批 1 进行中时，`docker stop scanstruct-worker` 模拟崩溃
4. 校验崩溃瞬间状态：
   - DB：`material.ocr_status` 仍为 `processing`（acks_late，任务重回队列）
   - MinIO：批 0 的 200 个 `pages/page_0001-0200.json` 已存在；`checkpoints/batch_0000.json` status=completed
5. `docker start scanstruct-worker` 重启
6. 观察续传路径：
   - 路径 A（优先）：Celery `acks_late` 自动 redeliver 原 batch task，幂等检查跳过批 0、重跑批 1/2
   - 路径 B（兜底）：若原 task 状态丢失，调 `POST /api/evidence/cases/{case_id}/materials/{material_id}/retry-ocr` 触发 `dispatch_material_ocr` 续传
7. 校验续传结果：
   - 批 0 的 200 个 page json **未被重写**（用 MinIO etag 或 mtime 对比崩溃前快照）
   - `checkpoints/batch_0000.json` 仍 status=completed
   - 最终 `ocr_status=completed`，MinIO 564 个 page json 齐全 + full_text + manifest

**退出**：断点续传未重做已完成工作 + 最终 completed。

### 4.2 2b 并发限流验证

**操作**：
1. 临时设置 `ocr_batch_max_concurrent_per_material=2`：改 `.env` + `docker restart scanstruct-worker`（用真实配置，避免 monkeypatch 失真）
2. 触发 OCR（564 页 = 3 批）
3. 观察批次调度：
   - 批 0、批 1 获得许可并行跑
   - 批 2 `acquire_batch_slot` 失败 → worker 日志出现 `batch 2 slot full, retry in 10s` → `self.retry(countdown=10)`
4. Redis 抽查：`redis-cli GET scanstruct:ocr_batch_concurrent:{material_id}`，值始终 ≤ 2
5. 最终全部完成（批 2 排队等到前面释放后执行）
6. 跑完后该 key 归零或不存在
7. **恢复配置** `ocr_batch_max_concurrent_per_material=4` + 重启 worker

**退出**：信号量限流生效 + 最终 completed + key 归零。

### 4.3 2c 内存观察（轻量）

564 页不构成压测，但仍记录：
- `docker stats scanstruct-worker --no-stream` 在 OCR 进行中采样几次，记录内存峰值
- 确认无异常增长（如连接泄漏导致内存持续涨）——若峰值稳定，作为后续真实压测的基线参考

**退出**：内存峰值合理（预期 < 400MB，564 页规模）+ 无持续增长趋势。

### 4.4 预期风险点

- **`pdf_local_path` 跨重启可靠性**：worker 重启后 `OCR_WORK_DIR` 下的临时 PDF 可能已被 `_cleanup_tmp_dir` 1 小时过期逻辑清理（若崩溃后等太久）→ dispatch 重试时幂等检查（文件存在 + 大小匹配 MinIO）会触发重新下载
- **批 1 进行中被中断**：该批 checkpoint 可能 status=processing（未写 completed）→ 重启后重跑该批，但已写的部分页会因 checkpoint `pages_written` 记录而跳过（验证 `append_checkpoint_page` 的幂等性）
- **路径 A vs B 的触发条件**：Celery `visibility_timeout` 内原 task 会被 redeliver（路径 A）；若超过 visibility_timeout 才重启，原 task 失效，需手动 retry（路径 B）。验证两种路径都能工作

---

## 5. 阶段 3：修复与回归

### 5.1 修复原则

- 阶段 1/2 暴露的每个问题单独定位、单独修复
- 每修一个，立即跑回归测试命令：
  ```powershell
  python -m pytest tests/test_ocr_shard.py tests/test_ocr_shard_e2e.py -q
  ```
- 若问题涉及生产代码改动，修复后用阶段 1 冒烟流程快速复验（不必重跑断点续传）

### 5.2 预期可能暴露的问题类型（按概率排序）

1. **worker 未加载新代码** → 重启 worker（操作类，非代码修复）
2. **百炼 QPS 限流** → 可能需要调小 `ocr_batch_max_concurrent_per_material` 或给批次 task 间加退避
3. **`_get_case_id_for_material` 同步引擎反复创建/销毁** → 改为模块级复用 engine 或缓存 case_id
4. **`pdf_local_path` 跨重启丢失** → dispatch 重试时幂等检查会重新下载，验证此路径确实工作
5. **前端 `EvidencePage.vue` 分片进度展示**渲染异常 → 针对性修 Vue 组件

### 5.3 完成标准

- 阶段 1 冒烟全过
- 阶段 2a 断点续传 + 2b 并发限流 + 2c 内存观察全过
- 暴露的所有问题已修复
- `tests/test_ocr_shard.py` + `tests/test_ocr_shard_e2e.py` 全绿
- 验证报告 `docs/ocr_shard_verification_report_2026-06-30.md` 写完

---

## 6. 验证报告（产出物）

**路径**：`docs/ocr_shard_verification_report_2026-06-30.md`

**内容结构**：
1. 执行环境（docker-compose 版本、worker 配置、百炼配置、PDF 信息）
2. 阶段 1 冒烟结果：
   - 执行命令清单
   - 产物校验结果（DB 查询截图/输出、MinIO 对象列表、full_text 前 500 字预览）
   - 前端进度卡片截图
3. 阶段 2 结果：
   - 2a 断点续传：崩溃时刻状态快照、续传后 etag 对比、最终产物
   - 2b 并发限流：worker 日志片段、Redis key 抽查值
   - 2c 内存：`docker stats` 采样数据
4. 发现的问题清单：每个问题含「现象 / 根因 / 修复 / 回归结果」
5. 结论：分片 OCR 是否达到可提交标准

**不提交**：报告本身作为本次工作记录，不进 git（与"不提交功能代码"约束一致；如用户后续要提交，报告可一并提交）。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 百炼 OCR 产生费用 | 564 页 × 1 次冒烟 + 1 次断点续传（部分重跑）+ 1 次限流验证 ≈ 1500 页 OCR 调用，费用可控；如超预算，2b 用 mock 引擎替代 |
| worker 重启影响其他在跑任务 | 验证前确认无其他活跃任务；`docker stop` 仅影响 worker 容器，API/DB/Redis/MinIO 不动 |
| 断点续传验证中 PDF 临时文件被清理 | 崩溃后立即重启（< 1 小时），不触发 1 小时过期逻辑；若触发，dispatch 会重新下载（幂等） |
| 百炼 QPS 限流导致 retry 风暴 | 观察 worker 日志，若 429 频繁，临时调小 `ocr_batch_max_concurrent_per_material` |
| 验证脚本本身有 bug 误报 | 脚本尽量薄，核心校验用直接 DB 查询 + MinIO API，不引入复杂逻辑 |

---

## 8. 不做的事（YAGNI）

- 不做 3000+ 页压测（无此 PDF）
- 不做真实崩溃注入（不用 `kill -9`，用 `docker stop` 优雅停止即可验证 acks_late）
- 不做跨材料并发验证（单材料足够覆盖编排逻辑）
- 不做前端交互的自动化测试（手动浏览器查看即可）
- 不做百炼 OCR 质量评估（识别质量不在分片编排验证范围）
- 不提交任何功能代码（用户明确要求）
