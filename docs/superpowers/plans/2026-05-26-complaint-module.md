# 民事起诉状生成模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 ScanStruct 系统中新增独立的"民事起诉状生成"模块，支持伤残/死亡案件类型的向导式起诉状生成。

**Architecture:** 方案 A — 共享后端 + 逻辑隔离。新增独立路由前缀 `/api/v1/complaint/`、独立数据库表、独立 services 目录，复用现有 PostgreSQL/Redis/MinIO/Celery/百炼 API。

**Tech Stack:** FastAPI, SQLAlchemy, Celery, 百炼 Qwen-VL-OCR + Qwen-Plus, python-docx, Vue 3 + Naive UI + TypeScript

---

## File Structure

### Backend — New Files
- `services/complaint/__init__.py` — 模块入口
- `services/complaint/ocr_service.py` — 复用 bailian_engine 做 OCR
- `services/complaint/llm_extractor.py` — 百炼 Qwen-Plus 文本提取
- `services/complaint/template_manager.py` — 4 套诉状模板 + Prompt
- `services/complaint/doc_generator.py` — DOCX 生成
- `api/schemas/complaint.py` — Pydantic 请求/响应模型
- `api/routes/complaint.py` — 8 个 API 端点
- `worker/complaint_tasks.py` — Celery 异步任务

### Backend — Modified Files
- `db/models.py` — 追加 ComplaintCase, ComplaintUpload, ComplaintStep
- `config/settings.py` — 追加百炼文本模型配置
- `api/main.py` — 注册 complaint router

### Frontend — New Files
- `static/src/views/Complaint.vue` — 向导主页面
- `static/src/components/complaint/CaseConfigStep.vue` — Step 1
- `static/src/components/complaint/InfoUploadStep.vue` — Step 2
- `static/src/components/complaint/OcrProgressStep.vue` — Step 3
- `static/src/components/complaint/OptionalStep.vue` — Step 4
- `static/src/components/complaint/GenerateStep.vue` — Step 5
- `static/src/stores/complaint.ts` — 状态管理

### Frontend — Modified Files
- `static/src/router/index.ts` — 追加 /complaint 路由
- `static/src/layouts/AdminLayout.vue` — 追加侧边栏菜单
- `static/src/api/client.ts` — 追加 complaint API

---

## Task List

### Task 1: 数据库模型
- Modify `db/models.py` — 追加 ComplaintCase, ComplaintUpload, ComplaintStep 三个模型

### Task 2: 配置扩展
- Modify `config/settings.py` — 追加百炼文本模型配置项

### Task 3: OCR 服务
- Create `services/complaint/__init__.py`
- Create `services/complaint/ocr_service.py` — 复用 bailian_engine

### Task 4: LLM 信息提取
- Create `services/complaint/llm_extractor.py` — 百炼 Qwen-Plus 调用

### Task 5: 诉状模板管理
- Create `services/complaint/template_manager.py` — 4 套模板 + Prompt

### Task 6: DOCX 生成器
- Create `services/complaint/doc_generator.py` — python-docx 起诉状生成

### Task 7: API Schemas
- Create `api/schemas/complaint.py` — Pydantic 模型

### Task 8: API 路由
- Create `api/routes/complaint.py` — 8 个端点
- Modify `api/main.py` — 注册路由

### Task 9: Celery 任务
- Create `worker/complaint_tasks.py` — 异步 OCR + 生成任务

### Task 10: 前端状态管理 + API
- Create `static/src/stores/complaint.ts`
- Modify `static/src/api/client.ts`

### Task 11: 前端向导页面
- Create `static/src/views/Complaint.vue`
- Create `static/src/components/complaint/*.vue` (5 个子组件)

### Task 12: 前端路由 + 导航
- Modify `static/src/router/index.ts`
- Modify `static/src/layouts/AdminLayout.vue`

### Task 13: 数据库迁移 + Docker 重建
- Alembic 迁移 + Docker 重建验证
