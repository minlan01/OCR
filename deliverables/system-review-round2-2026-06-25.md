# ScanStruct 第2轮三视角审查报告

**审查日期**: 2026-06-25
**审查团队**: 许清楚（PM）+ 高见远（架构师）+ 严过关（QA）
**上轮修复**: 43/43 全部完成（P0:11 / P1:18 / P2:14）

---

## 问题汇总

| 严重级别 | 数量 | 说明 |
|----------|------|------|
| **P0** | 7 | 阻断性问题 |
| **P1** | 17 | 高优先级 |
| **P2** | 14 | 中优先级 |
| **合计** | **38** | 去重后（3个跨视角重复问题已合并） |

---

## P0 — 阻断性问题（7个）

| # | 编号 | 维度 | 问题 | 文件 |
|---|------|------|------|------|
| 1 | QA-001 | 安全 | **callback.py SSRF 防护完全失效** — `except ValueError` 同时捕获了私有IP检测的主动raise和IP解析失败，导致所有私有IP通过校验 | `services/exporter/callback.py:71-80` |
| 2 | AR-001 | 安全 | **.env.production 真实凭据提交到仓库** — DB密码/Redis密码/MinIO密码/百度云Key/百炼Key全部明文 | `.env.production` |
| 3 | AR-002 | 安全 | **JWT_SECRET_KEY 弱默认fallback** — docker-compose提供公开已知弱密钥，绕过长度校验 | `docker-compose.yml:32` |
| 4 | AR-003/PM-002 | 可靠性 | **complaint_tasks.py 死代码** — 导入已删除模型(ImportError)+未注册到Celery+使用全局engine会dispose()掉API连接池 | `worker/complaint_tasks.py`, `worker/celery_app.py:22` |
| 5 | PM-001/QA-005 | 功能 | **自动登录功能完全失效** — 密码不再持久化但自动登录仍用空密码发请求，功能形同虚设 | `client.ts:42-61`, `Login.vue:168-183` |
| 6 | PM-003 | 功能 | **案件列表无分页控件** — 变量已声明但未绑定到表格，超过20个案件无法翻页 | `EvidencePage.vue:53,2396-2407` |
| 7 | PM-002 | 功能 | **Complaint.vue 整套死代码** — 路由未注册+后端未挂载+模型已删除，800+行空转 | `Complaint.vue`, `complaint.ts`, `components/complaint/` |

## P1 — 高优先级问题（17个）

| # | 编号 | 维度 | 问题 | 文件 |
|---|------|------|------|------|
| 8 | AR-004 | 基础设施 | Dockerfile.worker `--pool=solo` 使 `worker_concurrency=2` 失效 | `Dockerfile.worker:64` |
| 9 | AR-005/QA-010 | 性能 | `_get_scan_tenant_id` 每次调用创建新同步engine | `worker/tasks.py:107-132` |
| 10 | AR-006 | 并发 | async路由中同步MinIO调用阻塞事件循环 | `api/routes/scan.py:128,348,864-871,972-979` |
| 11 | AR-007 | 可靠性 | 上传路由将整个文件读入内存（500MB/5GB） | `api/routes/scan.py:410,509` |
| 12 | AR-008 | 一致性 | MinIO上传与DB事务非原子→失败时产生孤儿对象 | `api/routes/scan.py:333-377` |
| 13 | AR-009 | 安全 | MinIO镜像使用 `:latest` 标签 | `docker-compose.yml:138,307` |
| 14 | AR-010 | 安全 | Refresh Token 无jti/黑名单→旧token使用后仍有效 | `api/routes/auth.py:239-290` |
| 15 | AR-011 | 安全 | change-password端点无限流保护 | `api/routes/auth.py:298-321` |
| 16 | PM-004 | 错误处理 | FormData请求不触发401自动刷新token | `client.ts:257-279,281-303,452-513` |
| 17 | PM-005 | 用户体验 | member登录后先到/dashboard再跳/usage(闪烁) | `Login.vue:177,205,261` |
| 18 | PM-006 | 前端交互 | 赔偿金额blur即保存—无防抖，频繁请求 | `EvidencePage.vue:367-380,2022-2042` |
| 19 | PM-007 | 权限 | 路由守卫admin权限检查缓存竞态 | `router/index.ts:112-126` |
| 20 | PM-008 | 性能 | 案件列表API返回完整case数据(含materials/steps) | `api/routes/evidence.py:261-293` |
| 21 | PM-009 | 错误处理 | Dashboard裸try-catch静默吞错 | `Dashboard.vue:265-288` |
| 22 | QA-002 | 逻辑 | callback_retry_delays配置定义但从未使用 | `config/settings.py:194` |
| 23 | QA-003 | 配置 | MinIO bucket不一致—导出存"evidence"但读取用"scan-result" | `worker/evidence_tasks.py:422` |
| 24 | QA-004 | 依赖 | passlib[bcrypt]死依赖从未导入 | `requirements.txt:58` |

## P2 — 中优先级问题（14个）

| # | 编号 | 维度 | 问题 |
|---|------|------|------|
| 25 | AR-012 | 一致性 | tenant.storage_used_mb无自动更新 |
| 26 | AR-013 | 可靠性 | retention_days配置但无定时清理任务 |
| 27 | AR-014 | 安全 | PG log_min_duration_statement=1000暴露慢SQL(含敏感数据) |
| 28 | AR-015 | 可靠性 | Redis URL密码注入用string replace（不支持rediss://和特殊字符） |
| 29 | PM-010 | 功能 | 案件列表缺搜索和状态筛选 |
| 30 | PM-011 | 代码质量 | formatSize/getSourceLabel函数定义但未正确使用 |
| 31 | PM-012 | 移动端 | 核心操作区域窄屏溢出/不可用 |
| 32 | PM-013 | 前端交互 | 证据目录编辑无自动保存/beforeunload提醒 |
| 33 | PM-014 | 用户体验 | Profile改密码后未清除本地凭据 |
| 34 | QA-007 | 逻辑 | clean_headers_footers调用签名不一致(扫描PDF缺page_dimensions) |
| 35 | QA-008 | 测试 | callback.py缺SSRF单元测试 |
| 36 | QA-009 | 依赖 | 前端依赖未精确固定版本 |
| 37 | QA-011 | 性能 | ThreadPoolExecutor用submission order遍历 |
| 38 | QA-012 | 代码质量 | EvidenceCaseListSlimResponse未使用导入 |

---

## 修复计划

### 阶段1: P0 全部修复（7个）
1. **QA-001**: callback.py SSRF — 重构 try/except 逻辑，IP解析与私有IP检查分离
2. **AR-001**: .env.production — 创建.example模板，原文件加.gitignore，清除git历史
3. **AR-002**: JWT fallback — docker-compose改 `${JWT_SECRET_KEY:?...}` fail-fast
4. **AR-003/PM-002**: 删除 complaint_tasks.py + Complaint.vue + complaint store/components + complaint.py路由
5. **PM-001/QA-005**: 移除自动登录UI+逻辑，改为refresh token静默续期
6. **PM-003**: EvidencePage.vue 案件列表加 n-data-table pagination 绑定
7. **PM-002**: 同#4，删除整套死代码

### 阶段2: P1 全部修复（17个）
- 后端: AR-004~008, AR-010~011, QA-002~004, PM-008
- 前端: PM-004~007, PM-009

### 阶段3: P2 全部修复（14个）
- 配置/基础设施: AR-012~015, QA-009
- 前端: PM-010~014
- 代码质量: QA-007~008, QA-011~012

### 阶段4: 推送 GitHub
