# ScanStruct 系统全面审查报告

> **审查日期**: 2026-06-22
> **审查方法**: 三视角并行审查（产品经理/架构师/QA工程师）
> **上次修复**: 2026-06-18 修复 63 个 bug（P0-P3），17/17 测试通过
> **当前状态**: 代码干净无未提交修改，Docker 5 容器 healthy

---

## 总览

| 视角 | P0 | P1 | P2 | 合计 |
|------|-----|-----|-----|------|
| 用户视角 (PM) | 3 | 10 | 8 | 21 |
| 系统视角 (架构师) | 5 | 7 | — | 12 |
| 代码/测试视角 (QA) | 6 | 10 | 8 | 24 |
| **去重合并后** | **11** | **18** | **14** | **43** |

---

## P0 严重问题（11 个）— 必须立即修复

### 🔴 安全类（4 个）

| # | 问题 | 视角 | 影响 |
|---|------|------|------|
| P0-1 | **Celery 任务撤销用错 ID** — `celery_app.control.revoke(str(task_id))` 用的是 ScanTask UUID，但 Celery 内部 task_id 是另一个值。重试/删除时旧任务仍在跑，两个任务并发操作同一条记录 | QA | 数据竞争 |
| P0-2 | **batch-upload 缺少 SSRF 防护** — `upload_scan` 有 callback_url 校验，但 `batch_upload` 直接放行。攻击者可探测内网 Redis/PostgreSQL 端口 | QA + 架构 | 内网探测 |
| P0-3 | **API Key 模式注入 super_admin 角色** — 一个 API Key 泄露 = 全部租户数据泄露，租户隔离形同虚设 | 架构 | 全量数据泄露 |
| P0-4 | **SSRF 黑名单遗漏 IPv6 和 DNS Rebinding** — `::ffff:127.0.0.1`、`fe80::`、`fc00::` 未拦截；不防御 DNS rebinding | QA | SSRF 绕过 |

### 🔴 数据完整性类（3 个）

| # | 问题 | 视角 | 影响 |
|---|------|------|------|
| P0-5 | **JSONB 深拷贝铁律再次违反** — `export_complaint` 和 `download_bundle` 中 `analysis_result = case.analysis_result or {}` 获取引用后直接修改，导出操作可能意外修改案件数据 | QA | 数据被污染 |
| P0-6 | **MD5 去重未排除 failed 任务** — 文件首次处理失败后，重新上传同一文件被判定为 duplicate，返回旧 failed 任务，用户无法重试 | QA | 用户阻断 |
| P0-7 | **upload_materials 中途失败导致 MinIO 孤儿对象** — 批量上传第 N 个文件失败时，前 N-1 个已上传到 MinIO 的文件不会被清理 | QA | 存储泄漏 |

### 🔴 可靠性类（4 个）

| # | 问题 | 视角 | 影响 |
|---|------|------|------|
| P0-8 | **process_scan 缺少并发信号量保护** — evidence 有信号量，scan 没有。2 个重量级管线并发 → Worker OOM → 任务死循环重试 | 架构 | 服务崩溃 |
| P0-9 | **证据模块跳过租户并发配额检查** — 任何租户可无限并发，挤占全局资源 | 架构 | 资源耗尽 |
| P0-10 | **process_scan 在新 Event Loop 中使用全局 Session Factory** — asyncpg 跨 Loop 绑定 → 连接泄漏 | 架构 | 连接池耗尽 |
| P0-11 | **单 Worker 容器 + 单队列 = 单点故障** — Worker 宕机时所有任务堆积无人处理 | 架构 | 服务不可用 |

---

## P1 体验与性能问题（18 个）

### 用户阻断/卡死（6 个）

| # | 问题 | 视角 | 场景 |
|---|------|------|------|
| P1-1 | 路由守卫 `requiresAdmin` 检查的 `ss_user_info` 从未写入 localStorage → member 可进入 /admin | PM | 安全绕过 |
| P1-2 | OCR 超时后 `ocrRunning` 保持 true，UI 永久 spinner | PM | 用户卡死 |
| P1-3 | 生成超时后不通知用户，页面回到初始状态 | PM | 用户困惑 |
| P1-4 | Complaint 模块所有上传错误只 `console.error`，用户完全无感知 | PM | 数据静默丢失 |
| P1-5 | 赔偿金额保存失败静默吞错 | PM | 法律文件金额错误 |
| P1-6 | 案件列表写死 `listCases(1, 50)`，超 50 条后无法翻页 | PM | 旧案件不可见 |

### 系统性能/可靠性（7 个）

| # | 问题 | 视角 | 影响 |
|---|------|------|------|
| P1-7 | Redis Pub/Sub 同步调用阻塞异步管线 | 架构 | 延迟增加 |
| P1-8 | LLM Rate Limiter 的 INCR+EXPIRE 非原子（task_concurrency 已用 Lua 修复） | 架构 | 限流不准 |
| P1-9 | 租户配额 Check-then-Act 竞态 | 架构 | 超卖 |
| P1-10 | 500MB PDF 全量加载内存 | 架构 | OOM 风险 |
| P1-11 | 临时文件无自动清理（异常退出后泄漏） | 架构 | 磁盘满 |
| P1-12 | Redis 至少 5 处独立连接碎片化 | 架构 | 连接浪费 |
| P1-13 | Celery 重试幂等性不完整 | 架构 | 数据不一致 |

### 体验优化（5 个）

| # | 问题 | 视角 |
|---|------|------|
| P1-14 | member 角色登录后看到大量无权限菜单 | PM |
| P1-15 | sessionStorage 恢复案件状态时步骤数据缺失 | PM |
| P1-16 | 普通成员 Dashboard 页面完全空白，无引导 | PM |
| P1-17 | 上传无实时进度条（boolean loading） | PM |
| P1-18 | ProcessDocuments `page_count` null 时显示 "null 页" | PM |

---

## P2 优化建议（14 个，摘要）

| # | 问题 | 视角 |
|---|------|------|
| P2-1 | 素材表格在 Step 1/3/4 三处复制（~180 行重复） | PM |
| P2-2 | 多处 `catch {}` 静默吞错 | PM+QA |
| P2-3 | OCR 状态显示英文原始值，无中文映射 | PM |
| P2-4 | TaskList 无排序功能 | PM |
| P2-5 | 批量删除素材逐个 API 调用 | PM |
| P2-6 | UsageView "总用户" 实际取 active_users | PM |
| P2-7 | `hasSavedCredentials` 逻辑矛盾（永远返回 false） | PM+QA |
| P2-8 | `downloadBlob` 无 401 自动刷新 | QA |
| P2-9 | 硬编码 `_MAX_CONCURRENT_CASES = 3` | QA |
| P2-10 | `except (S3Error, Exception)` 冗余捕获 | QA |
| P2-11 | TypeScript `any` 类型使用（evidence.ts） | QA |
| P2-12 | `get_db` commit 在 yield 之后 | QA |
| P2-13 | scan upload 缺文件魔数校验（evidence 有） | QA |
| P2-14 | TODO/FIXME 遗留未清理 | QA |

---

## 测试覆盖盲区（QA 发现 10 个模块零覆盖）

| 模块 | 缺失测试 | 风险等级 |
|------|---------|---------|
| 🔴 认证中间件 | JWT/API Key/开发模式三模式切换、过期/无效 token | **致命** |
| 🔴 多租户隔离 | 跨租户访问、API Key+X-Tenant-Id | **致命** |
| 🟡 Celery 任务 | 失败/重试/超时/撤销 | 高 |
| 🟡 文件上传校验 | 魔数/大小/扩展名伪装/SSRF | 高 |
| 🟡 并发控制 | 信号量排队/降级/TTL | 高 |
| 🟡 赔偿计算 | 标准计算/空素材/参数缺失 | 高 |
| 🟢 Admin 路由 | 用户CRUD/租户管理/配额 | 中 |
| 🟢 OCR 多引擎 | 置信度分档/区域重识 | 中 |
| 🟢 Template 生成器 | 沙箱安全/恶意代码拦截 | 中 |
| 🟢 数据迁移 | 幂等性/级联删除 | 中 |

---

## 建议修复路线图

```
第一阶段 (1-2天): 紧急安全 + 防崩溃
  P0-8  process_scan 加信号量          → 防 OOM 崩溃
  P0-10 统一 Worker DB 引擎            → 防连接泄漏
  P0-1  修复 Celery revoke ID          → 防数据竞争
  P0-5  JSONB 深拷贝                   → 防数据污染
  P0-6  MD5 去重排除 failed            → 防用户阻断
  P0-7  MinIO 孤儿对象清理             → 防存储泄漏

第二阶段 (2-3天): 安全加固
  P0-2  batch-upload 加 SSRF 校验
  P0-3  API Key 模式角色降级
  P0-4  SSRF 补 IPv6 + DNS rebinding
  P0-9  证据模块加并发配额
  P1-1  路由守卫修复

第三阶段 (3-5天): 用户体验
  P1-2~P1-6 超时/静默失败/分页修复
  P1-14~P1-18 角色体验优化

第四阶段 (持续): 测试补全
  认证中间件测试 (最高优先)
  多租户隔离测试 (最高优先)
  其余模块逐步补全
```
