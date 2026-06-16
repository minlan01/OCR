# ScanStruct SaaS 改造方案

> 目标：4核8G 云服务器支持 10 人并发，不卡死
> 原则：先救命（资源管控），再加锁（认证+租户）

---

## 现状分析

| 组件 | 现状 | 风险 |
|------|------|------|
| 认证 | 仅 X-API-Key（单密钥共享） | 10人共用1个key，无法区分身份 |
| 数据隔离 | 无 tenant_id | 所有人看到所有数据 |
| Celery Worker | 单 worker，无并发上限 | 10人同时提交 → 内存 OOM |
| OCR 引擎 | 每次任务独立加载模型 | ~600MB × 多任务 = 爆内存 |
| PG 连接池 | pool_size=5, overflow=10 | 基本够用但需调优 |
| 限流 | slowapi 100/min 按IP | 无法按用户限流 |
| 并发控制 | `task_concurrency.py` 限制3案件 | 已有基础，但不是按用户限制 |

---

## 第一层：资源管控（救命 — 解决卡死）

### 1.1 Celery Worker 并发优化

**文件**: `worker/celery_app.py`, `docker-compose.yml`

- Worker 并发数设为 `--concurrency=2`（4核运行2个worker进程）
- `worker_prefetch_multiplier=1`（已有，保留）
- 超时时间保持 1800s
- docker-compose 增加 `cpu_count: 2` 限制

### 1.2 OCR 引擎单例化 + 请求队列

**文件**: `services/ocr/rapid_engine.py`, `services/ocr/engine.py`

- OCR 引擎改为 **进程级单例**（模块加载时初始化，所有任务共享）
- 增加 `threading.Semaphore(1)` — 同一时刻只允许1个 OCR 调用（4核8G 不够并行跑2个ONNX推理）
- 模型预加载已在 `celery_app.py` `on_worker_ready` 实现，保留

### 1.3 API 限流升级

**文件**: `api/rate_limit.py`, `api/routes/evidence.py`

- 保留 slowapi，升级为**按用户**限流（当前按 IP）
- OCR 触发端点：5次/分钟/用户
- 普通查询：60次/分钟/用户
- 全局限流兜底：200次/分钟

### 1.4 PG 连接池调优

**文件**: `config/settings.py`, `db/session.py`

- API 进程: `pool_size=10, max_overflow=20`（已在settings中，确认生效）
- Worker 进程: `poolclass=NullPool`（已有，保留）
- docker-compose PG: `max_connections=50`（已有，够用）

### 1.5 LLM 调用超时 + 降级

**文件**: `config/settings.py`

- DeepSeek 超时: 30s（从120s降下来）
- 降级链: DeepSeek(V3) → GLM(免费) → Bailian(备用)
- 已有 `llm_rate_limiter_text=2` 限制全局2并发（保守，但安全）

### 1.6 任务排队提示

**文件**: `api/routes/evidence.py`, 前端组件

- `/evidence/cases/{id}/progress` 返回 `queue_position` 字段
- 前端轮询时显示 "排队中，前面有 N 人"
- Redis 存队列信息: `scanstruct:queue:{case_id}`

### 1.7 Docker 资源配额调整

**文件**: `docker-compose.yml`

```
api:     memory: 1G → 1.5G  (JWT + 限流增加微小开销)
worker:  memory: 3G → 4G    (OCR模型~600MB + 处理缓冲)
redis:   memory: 128MB → 192MB (队列信息)
PG:      保持 512MB
minio:   保持 512MB
```

4核8G 分配:
- 系统: ~0.5G
- PG: 0.5G
- Redis: 0.2G
- MinIO: 0.5G
- API: 1.5G
- Worker: 4G
- 余量: 0.8G

---

## 第二层：用户认证 + 租户隔离

### 2.1 用户模型

**新增文件**: `db/models_auth.py`
**迁移文件**: `db/migrations/versions/20260616_001_auth.py`

```python
class Tenant(Base):
    """租户表"""
    __tablename__ = "tenants"
    id: UUID (PK)
    name: str         # 租户名/公司名
    plan: str         # free/pro/enterprise
    max_cases: int    # 最大案件数（free=5, pro=50, enterprise=无限）
    max_concurrent: int  # 最大并发处理数（free=1, pro=2, enterprise=3）
    storage_quota_mb: int  # 存储配额
    status: str       # active/suspended
    created_at: datetime

class User(Base):
    """用户表"""
    __tablename__ = "users"
    id: UUID (PK)
    tenant_id: FK(tenants.id)
    email: str (unique)
    hashed_password: str
    display_name: str
    role: str         # super_admin / tenant_admin / member
    is_active: bool
    last_login: datetime
    created_at: datetime
```

### 2.2 JWT 认证

**新增文件**: `api/auth.py`

- 注册: `POST /api/v1/auth/register` — 创建租户+管理员用户
- 登录: `POST /api/v1/auth/login` — 返回 access_token + refresh_token
- 刷新: `POST /api/v1/auth/refresh`
- JWT payload: `{user_id, tenant_id, role, exp}`
- Token 有效期: access=30min, refresh=7d
- 密码哈希: bcrypt
- 依赖: `python-jose[cryptography]`, `passlib[bcrypt]`

### 2.3 认证中间件改造

**文件**: `api/middleware.py`

- 现有 `APIKeyMiddleware` 改为 `AuthMiddleware`
- 逻辑: 优先检查 JWT Bearer token → 兜底检查 X-API-Key
- 公开路径: `/api/v1/auth/*`, `/api/v1/health`
- JWT 解析后将 `user_id` / `tenant_id` 注入 `request.state`

### 2.4 租户隔离（tenant_id）

**需要改造的表**: `evidence_cases`, `evidence_materials`(通过case关联), `evidence_steps`(通过case关联), `scan_tasks`, `scan_files`(通过task关联), `task_steps`(通过task关联), `output_templates`

**改造方式**: 只改主表，子表通过 JOIN 过滤

| 表 | 改动 |
|----|------|
| `evidence_cases` | + `tenant_id UUID FK(tenants.id)` + Index |
| `scan_tasks` | + `tenant_id UUID FK(tenants.id)` + Index |
| `output_templates` | + `tenant_id UUID FK(tenants.id)` + Index (null=全局模板) |
| `evidence_materials` | 无改动（通过 evidence_case_id JOIN 过滤） |
| `evidence_steps` | 无改动（通过 case_id JOIN 过滤） |
| `scan_files` | 无改动（通过 task_id JOIN 过滤） |
| `task_steps` | 无改动（通过 task_id JOIN 过滤） |

**查询过滤**: FastAPI 依赖注入 `get_current_tenant()` 自动在 SELECT 中加 `WHERE tenant_id = :tid`

### 2.5 FastAPI 依赖项

**新增文件**: `api/dependencies.py`

```python
async def get_current_user(request: Request) -> User:
    """从 JWT token 解析当前用户"""

async def get_current_tenant(request: Request) -> Tenant:
    """从 JWT token 解析当前租户"""

async def require_role(role: str):
    """角色检查装饰器"""
```

### 2.6 API 路由改造

**文件**: 所有 `api/routes/*.py`

- 每个 endpoint 加 `Depends(get_current_user)`
- 查询自动加 `tenant_id` 过滤
- 创建时自动填 `tenant_id`
- 管理员端点加 `Depends(require_role("tenant_admin"))`

### 2.7 租户配额限流

**文件**: `api/dependencies.py`, `services/utils/task_concurrency.py`

- 每租户并发上限: 从 `Tenant.max_concurrent` 读取
- Redis key: `scanstruct:tenant_concurrent:{tenant_id}`
- 上传存储配额检查: 上传前检查 `Tenant.storage_quota_mb`

### 2.8 前端改造

**新增文件**:
- `static/src/views/Login.vue` — 登录页
- `static/src/views/Register.vue` — 注册页
- `static/src/stores/auth.ts` — 认证状态管理

**改造文件**:
- `static/src/router/index.ts` — 增加 auth guard
- `static/src/api/client.ts` — 自动注入 Bearer token
- `static/src/App.vue` — 根据登录状态切换布局

---

## 实施顺序

### Phase 1 — 资源管控（1-2天，立竿见影）

1. ✅ Celery Worker 并发调优
2. ✅ OCR 引擎单例+信号量
3. ✅ API 限流升级（按用户）
4. ✅ PG 连接池确认
5. ✅ LLM 超时降级
6. ✅ 任务排队提示
7. ✅ Docker 资源配额

### Phase 2 — 用户认证（2-3天）

8. ✅ 用户模型 + 迁移
9. ✅ JWT 认证 API
10. ✅ 认证中间件改造
11. ✅ FastAPI 依赖项
12. ✅ API 路由改造（加认证）
13. ✅ 前端登录页 + auth guard
14. ✅ API client 注入 token

### Phase 3 — 租户隔离（2-3天）

15. ✅ 主表加 tenant_id + 迁移
16. ✅ 查询自动过滤
17. ✅ 租户配额限流
18. ✅ 管理员端点
19. ✅ 数据迁移脚本（现有数据归入默认租户）

---

## 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| JWT | python-jose | FastAPI 生态标准 |
| 密码哈希 | passlib[bcrypt] | 业界标准 |
| 数据库迁移 | Alembic | 已在用 |
| 前端状态 | Pinia | 已在用 |
| 限流 | slowapi | 已在用，升级即可 |

## 依赖新增

```
# requirements.txt 追加
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9  # 登录表单
```
