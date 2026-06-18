# ScanStruct 系统 Bug 审查报告

> 审查时间：2026-06-18 14:20
> 审查范围：后端 API（9 文件）+ 前端 Vue（31 文件）+ 数据库层（5 文件 + 11 迁移）
> 发现问题：**P0 严重 10 个 | P1 高危 18 个 | P2 中危 20 个 | P3 低危 15 个**

---

## 一、用户角度（用户能感知到的问题）

### 🔴 P0 — 功能完全不可用 / 体验灾难

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| U1 | **刷新任何页面都被踢回登录页** | `router/index.ts:93` | `isFirstLoad` 逻辑导致已登录用户每次刷新/新标签页都强制跳登录页，即使有有效 token 也一样。自动登录勾选了也白搭 |
| U2 | **JWT 用户上传文件失败** | `stores/complaint.ts:98`, `api/evidence.ts:183` | 诉状生成和证据整理的文件上传请求不带 `Authorization` 头，后端直接 401 拒绝。这两大核心功能对 JWT 用户完全不可用 |
| U3 | **member 用户可直接访问 /admin** | `router/index.ts:95` | 路由守卫定义了 `requiresAdmin` 但从未检查。普通用户地址栏输入 `/admin` 就能进管理后台页面（虽然 API 会拒绝，但体验很差——满屏报错） |

### 🟠 P1 — 功能缺陷 / 数据丢失

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| U4 | **诉状生成轮询定时器永不清理** | `GenerateStep.vue:192` | 用户在生成过程中导航离开，setInterval 继续每 3 秒请求后端，直到页面关闭。`store.currentCase` 变 null 后还会触发运行时错误 |
| U5 | **OCR 轮询无超时** | `CaseConfigStep.vue:148`, `OptionalStep.vue:126` | 如果后端崩溃或网络中断，轮询永久运行，用户无限等待。组件卸载后定时器仍在跑 |
| U6 | **证据目录自动保存失效** | `EvidencePage.vue:1122` | `catalogDirty` 永远不会被设为 `true`，切换步骤时自动保存逻辑永远不触发。用户在证据目录步骤的未保存修改会丢失 |
| U7 | **赔偿计算导出报错** | `evidence.ts:450` | `exportCompensationCalc` 把 `{responseType:'blob'}` 当查询参数传给 URL，二进制响应被 JSON.parse 解析导致报错 |
| U8 | **使用原生 alert() 弹窗** | `TaskList.vue:218`, `TaskDetail.vue:293` | 错误提示用浏览器原生 `alert()`，阻塞 UI 线程，与其他页面的 Naive UI 消息风格不一致 |

### 🟡 P2 — 体验问题

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| U9 | **ProcessDocuments 列标题错误** | `ProcessDocuments.vue:54` | 列标题写"文件大小"，实际显示的是 `page_count`（页数），`formatSize` 把它格式化成"N 页"，标题与内容不匹配 |
| U10 | **登录/注册表单缺邮箱校验** | `Login.vue:155` | 只检查"必填"，不检查邮箱格式。用户输入 `abc` 也能提交，后端报错 |
| U11 | **重复请求 /auth/me** | AdminLayout/Dashboard/Admin/UsageView/Profile | 每个页面独立请求用户信息，页面间导航重复请求，且各页面的 userInfo 可能不一致 |
| U12 | **showCaseListModal 永远打不开** | `EvidencePage.vue:1094` | 定义了变量但全文件没有任何代码设为 true，"已有案件"弹窗永远不显示 |
| U13 | **sessionStorage 写了不读** | `EvidencePage.vue:2597` | 存了案件 ID 和步骤，但 onMounted 从不读取恢复，`:key="$route.fullPath"` 导致组件重建后状态丢失 |

---

## 二、系统角度（安全性 / 稳定性 / 数据一致性）

### 🔴 P0 — 严重安全漏洞

| # | 问题 | 文件 | 风险 |
|---|------|------|------|
| S1 | **generator_runner exec() 任意代码执行 (RCE)** | `services/template/generator_runner.py:156` | `exec(code, namespace)` 直接执行用户上传的 Python 代码，无沙箱。攻击者可读取数据库密码、删除文件、执行系统命令。**整个服务器可被接管** |
| S2 | **密码明文存于 localStorage** | `client.ts:42` | "记住密码"功能用 `btoa()` (base64) 编码后存入 localStorage。任何 XSS 攻击可直接 `atob()` 解码获取明文密码。base64 不是加密 |
| S3 | **delete_material 租户隔离漏洞** | `evidence.py:865` | 调用 `_check_case_exists(case_id, db)` 漏传 `tenant_id`，任何用户可探测其他租户的案件是否存在 |
| S4 | **jwt_secret_key 无生产环境强制校验** | `config/settings.py:198` | 注释说"生产必须设置"，但无 validator。若忘记配置，应用以空字符串启动，任何人可伪造任意 JWT token，**认证体系完全绕过** |
| S5 | **evidence 模块 4 张表无建表迁移** | `migrations/versions/` | evidence_cases/materials/steps/requirements 在所有迁移中无 `create_table`。全新数据库 `alembic upgrade head` 直接崩溃。当前靠 `create_all` 侥幸运行 |
| S6 | **users.tenant_id 迁移与模型矛盾** | `models_auth.py:76` vs `20260616_001:51` | 模型 `ondelete=SET NULL + nullable=True`，迁移 `ondelete=CASCADE + nullable=False`。删租户时 ORM 认为 SET NULL 但数据库 CASCADE 删用户，**行为完全相反** |
| S7 | **tenants.features 列无迁移** | `models_auth.py:50` vs `20260616_001` | 模型有 features JSONB 列，但建表迁移里没有。alembic autogenerate 持续报差异 |

### 🟠 P1 — 安全 / 稳定性

| # | 问题 | 文件 | 风险 |
|---|------|------|------|
| S8 | **认证端点完全无限流** | `auth.py` 全文件 | login/register/refresh 没有任何 `@limiter.limit()`。攻击者可无限次暴力破解密码、批量注册账号。其余所有路由都加了限流，唯独认证端点遗漏 |
| S9 | **开发模式误配导致全放行** | `middleware.py:103` | `jwt_secret_key` 为空且无 `api_key` 时，所有请求直接放行（包括 admin API）。生产环境配置错误 = 全线暴露 |
| S10 | **callback_url 未做 SSRF 校验** | `scan.py:311` | 用户可指定任意 callback_url 存入数据库，项目有 `validate_callback_url()` 函数但从未调用 |
| S11 | **模板 CRUD 可越权操作** | `template.py:142` | `tenant_id=None` 时无租户过滤，可修改/删除任意租户的模板和全局模板。开发模式 = 任何人可改所有模板 |
| S12 | **模板 generator_code 无大小限制 + exec** | `template.py:97` | 用户可上传超大 Python 文件，结合 exec() = RCE（与 S1 关联） |
| S13 | **get_current_user UUID 解析无异常处理** | `dependencies.py:34` | `uuid.UUID(user_id)` 可能抛 ValueError 导致 500（而非 401） |
| S14 | **API Key 认证不注入 tenant_id** | `middleware.py:93` | API Key 模式下 tenant_id 为 None，所有查询不加租户过滤，持 API Key 可见所有租户数据 |
| S15 | **login 未 commit last_login 更新** | `auth.py:195` | 修改了 `user.last_login` 但未 commit，get_db 依赖 rollback 导致永远不更新 |
| S16 | **register 无密码长度校验** | `auth.py:32` | `RegisterRequest.password` 无 min_length，可设置空密码。admin 的 UserCreateRequest 有 min_length=6，公开注册反而没有 |
| S17 | **super_admin 创建用户未指定租户** | `admin.py:245` | `_require_super_admin` 返回 bool 而非抛异常。super_admin 不指定 tenant_id 时创建"无租户"用户，可能导致该用户无法正常使用系统 |
| S18 | **watcher 创建的任务无 tenant_id** | `services/scan_in/uploader.py:64` | watch_folder 创建的 ScanTask 无租户归属，去重查询跨所有租户匹配 |
| S19 | **compensation_data 类型不匹配** | `models_evidence.py:63` vs `20260701_001:62` | 模型用 JSONB，迁移用 sa.JSON()（映射为 json）。类型不兼容，autogenerate 持续报差异 |

### 🟡 P2 — 性能 / 健壮性

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| S20 | **list_tenants N+1 查询** | `admin.py:484` | 每个租户分别 count，100 个租户 = 200 次查询 |
| S21 | **MinIO download_bytes 连接泄漏** | `services/storage/minio_client.py:216` | `response.read()` 抛非 S3Error 时，close/release_conn 不执行，连接池（maxsize=10）被耗尽 |
| S22 | **task_concurrency 竞态条件** | `services/utils/task_concurrency.py:54` | Redis incr + decr 非原子，进程崩溃导致计数器偏高 |
| S23 | **rate_limiter 同步 Redis 阻塞事件循环** | `services/llm/rate_limiter.py:120` | 同步 redis 库在 async 函数中直接调用，Redis 慢 = 全部协程阻塞 |
| S24 | **retry_scan 未加行锁** | `scan.py:749` | 与 Celery worker 存在竞态，对比 batch_process 正确用了 with_for_update() |
| S25 | **shutil.rmtree 阻塞事件循环** | `scan.py:767` | 同步 IO 在 async 路由中直接调用 |
| S26 | **User.tenant_id 重复索引** | `models_auth.py:80,99` | `index=True` + `Index()` 建了两个相同索引 |
| S27 | **get_db() 对只读 GET 也 commit** | `db/session.py:53` | 纯查询请求也触发 commit，产生不必要的 WAL 写入 |
| S28 | **异常信息直接返回用户** | `template.py:255` | LLM/generator 异常 detail 暴露内部路径和库版本 |
| S29 | **多个敏感密钥未用 SecretStr** | `settings.py:63,68,145` | redis_password/minio_secret_key/baidu_ocr_secret_key 是裸 str，可能被日志泄露 |
| S30 | **upload_materials 仅扩展名校验** | `evidence.py:492` | 不校验文件魔数，`malicious.pdf`（实际是脚本）可通过检查 |

---

## 三、修复优先级建议

### 立即修复（上线前必须）

| 优先级 | 问题 | 修复方案 | 工作量 |
|--------|------|---------|--------|
| **P0-1** | S1 + S12: exec() RCE | generator_code 做 AST 白名单分析，禁止 import os/subprocess | 中 |
| **P0-2** | S4: jwt_secret_key 无校验 | settings.py 加生产环境 `@field_validator`，空/短于 32 字符 = 启动失败 | 小 |
| **P0-3** | U1: 刷新跳登录页 | 移除 `isFirstLoad` 逻辑，仅未登录时跳转 | 小 |
| **P0-4** | U2: 上传不带 Token | complaint.ts + evidence.ts 复用 `apiKeyOnlyHeaders()` | 小 |
| **P0-5** | S2: 密码存 localStorage | 改为只存 refresh token，或用 Credential Management API | 中 |
| **P0-6** | S5+S6+S7: 数据库迁移 | 补写 evidence 表建表迁移；统一 tenant_id ondelete/nullable；加 features 列迁移 | 中 |
| **P0-7** | S3: 租户隔离漏洞 | evidence.py:865 补传 tenant_id 参数 | 极小 |

### 尽快修复（1-2 个迭代内）

| 优先级 | 问题 | 修复方案 |
|--------|------|---------|
| **P1-1** | S8: 认证无限流 | login 加 `@limiter.limit("5/minute")`，register `"3/minute"` |
| **P1-2** | S9: 开发模式全放行 | 生产环境强制要求 jwt_secret_key（与 P0-2 关联） |
| **P1-3** | U4+U5: 定时器泄漏 | onUnmounted 清理 setInterval；轮询加超时机制 |
| **P1-4** | U6: 自动保存失效 | handleUpdateItem 中设 `catalogDirty.value = true` |
| **P1-5** | U7: 导出报错 | 用 `api.downloadBlob()` 替代错误的 axios 调用 |
| **P1-6** | S10: SSRF | scan.py 调用 `validate_callback_url()` |
| **P1-7** | U3: Admin 路由守卫 | beforeEach 检查 `requiresAdmin` meta + 用户角色 |
| **P1-8** | S15: last_login 不更新 | login 端点 return 前加 `await db.commit()` |
| **P1-9** | S16: 密码无校验 | RegisterRequest.password 加 `min_length=6` |

### 迭代优化（P2/P3）

- 统一错误处理风格（移除 alert()，用 message.error()）
- 创建 Pinia auth store 消除重复 /auth/me 请求
- 拆分 EvidencePage.vue（2625 行 → 多个子组件）
- list_tenants 用 JOIN 聚合消除 N+1
- MinIO download_bytes 用 try/finally 确保连接释放
- rate_limiter 换用 redis.asyncio
- 敏感密钥改用 SecretStr
- 补全类型定义（移除 any）
- 统一数据库迁移（修 JSONB/JSON 类型不一致）

---

## 四、维度统计

### 按严重程度
| 级别 | 用户角度 | 系统角度 | 合计 |
|------|---------|---------|------|
| P0 严重 | 3 | 7 | **10** |
| P1 高危 | 5 | 13 | **18** |
| P2 中危 | 5 | 15 | **20** |
| P3 低危 | 0 | 15 | **15** |

### 按模块
| 模块 | 问题数 | 最严重 |
|------|--------|--------|
| 认证/安全 | 8 | P0（exec RCE, 密码存储, jwt 校验） |
| 租户隔离 | 5 | P0（delete_material, tenant_id 矛盾） |
| 前端路由/状态 | 7 | P0（刷新跳登录, 上传无 Token） |
| 证据整理 | 6 | P1（自动保存, 导出报错） |
| 诉状生成 | 4 | P1（定时器泄漏） |
| 数据库迁移 | 5 | P0（无建表迁移, 类型不匹配） |
| OCR 扫描 | 4 | P1（SSRF, 竞态） |
| 模板管理 | 3 | P0（exec RCE） |
| 管理后台 | 3 | P1（超级管理员创建用户） |
