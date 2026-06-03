# ScanStruct — 扫描件智能结构化处理系统

> PDF 扫描件 → OCR 文字识别 → 证据自动分类 → 民事起诉状生成 → 文档导出打包
>
> 一站式法律文档智能处理平台，专为医疗损害责任纠纷案件设计。

## 项目概览

ScanStruct 是一个面向法律实务的智能文档处理系统，核心解决**医疗损害责任纠纷案件中证据材料的整理与诉状生成**问题。用户只需上传扫描件 PDF 和照片，系统自动完成 OCR 识别、证据分类、费用提取、民事起诉状 DOCX 生成、证据目录 PDF 编制，最终输出完整的诉讼材料包。

### 核心流程

```
用户上传扫描件/照片
        ↓
   OCR 多引擎识别（PaddleOCR / 阿里云百炼 / 硅基流动）
        ↓
   证据自动分类（身份证/户口本/病历/发票/鉴定报告/...）
        ↓
   定向信息提取（被告信息 / 死亡诊断 / 原告身份）
        ↓
   ┌─────────────────────────────────────┐
   │  民事起诉状 DOCX 生成               │
   │  证据目录 PDF 生成                  │
   │  证据材料 PDF 合并（1张/页）         │
   │  医疗费用汇总 Excel                 │
   └─────────────────────────────────────┘
        ↓
   ZIP 打包下载（诉状 + 证据目录 + 证据材料 + 费用汇总）
```

### 支持的案件类型

| 类型 | 说明 | 特殊要求 |
|------|------|---------|
| `injury` | 医疗损害（伤残） | 伤残等级鉴定 |
| `death` | 医疗损害（死亡） | 死亡医学证明书、死因鉴定 |
| `neonatal` | 医疗损害（新生儿） | 出生医学证明（必填）、法定代理人信息 |

---

## 技术架构

```
┌──────────────────────────────────────────────────────────┐
│                     Vue 3 + Naive UI                      │
│              (TypeScript · Vite · Pinia)                  │
├──────────────────────────────────────────────────────────┤
│                      FastAPI (API 层)                      │
│          (Pydantic · SQLAlchemy 2.0 async)                │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│ Celery   │ PaddleOCR│ 百炼 OCR │ 硅基流动 │ python-docx  │
│ Worker   │ 3.5.0    │ Qwen-VL  │ OCR API  │ reportlab    │
├──────────┴──────────┴──────────┴──────────┴──────────────┤
│  PostgreSQL 16  │  Redis  │  MinIO (S3 兼容对象存储)      │
└──────────────────────────────────────────────────────────┘
```

### 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|---------|
| **后端框架** | FastAPI | 异步高性能，自动 OpenAPI 文档 |
| **数据库** | PostgreSQL 16 + SQLAlchemy 2.0 async | 可靠的关系型存储，异步 ORM |
| **任务队列** | Celery + Redis | 耗时 OCR 任务异步处理 |
| **对象存储** | MinIO | S3 兼容，本地部署，不依赖云服务 |
| **OCR 引擎** | PaddleOCR 3.5 + 百炼 Qwen-VL-OCR | 多引擎冗余，本地+云端双通道 |
| **PDF 处理** | PyMuPDF (fitz) | 高性能 PDF 渲染与文本提取 |
| **DOCX 生成** | python-docx | 模板化法律文书生成 |
| **PDF 生成** | reportlab | 证据目录/证据材料 PDF 精确排版 |
| **前端** | Vue 3 + Naive UI + TypeScript | 现代响应式 SPA，组件丰富 |
| **部署** | Docker Compose (5 服务) | 一键部署，环境隔离 |

---

## 项目结构

```
OCRScanStruct/
├── api/                          # FastAPI 应用
│   ├── main.py                   # 入口：CORS、静态文件挂载、lifespan
│   ├── middleware.py             # API Key 认证中间件
│   ├── routes/                   # 路由层
│   │   ├── scan.py              # OCR 扫描任务（上传/处理/结果）
│   │   ├── evidence.py          # 证据整理（案件/素材/分类/导出）
│   │   ├── complaint.py         # 诉状生成（配置/生成/下载）
│   │   └── admin.py             # 管理后台（统计/队列）
│   └── schemas/                  # Pydantic 请求/响应模型
├── services/                     # 业务逻辑层
│   ├── ocr/                      # OCR 引擎
│   │   ├── base.py              # BaseOCREngine 抽象基类
│   │   ├── ocr_engine.py        # PaddleOCR 本地引擎
│   │   └── bailian_ocr.py       # 阿里云百炼引擎
│   ├── evidence/                 # 证据处理
│   │   ├── pdf_generator.py     # 证据材料 PDF 生成（6组结构+智能页面选择）
│   │   ├── catalog_generator.py # 证据目录 PDF 生成
│   │   ├── excel_generator.py   # 医疗费用汇总 Excel
│   │   ├── word_generator.py    # 证据清单 Word
│   │   └── classifier.py        # 证据自动分类（文件名+内容）
│   ├── complaint/                # 诉状生成
│   │   └── doc_generator.py     # 民事起诉状 DOCX 生成
│   ├── storage/                  # MinIO 对象存储
│   └── exporter/                 # 导出与回调
├── worker/                       # Celery 异步任务
│   ├── celery_app.py            # Celery 配置
│   ├── tasks.py                 # OCR 处理任务
│   ├── evidence_tasks.py        # 证据整理任务
│   └── complaint_tasks.py       # 诉状生成任务
├── db/                           # 数据库
│   ├── models.py                # ORM 模型（Task/TaskStep）
│   ├── models_evidence.py       # 证据相关模型 + 种子数据
│   ├── session.py               # 异步数据库会话
│   └── migrations/              # Alembic 迁移
├── config/                       # 配置
│   ├── settings.py              # pydantic-settings 统一配置
│   └── logging.py               # loguru 日志配置
├── static/                       # Vue 3 前端
│   └── src/
│       ├── views/               # 页面组件
│       │   ├── EvidencePage.vue # 证据整理主页面（4步骤流程）
│       │   ├── TaskList.vue     # OCR 任务列表
│       │   ├── TaskDetail.vue   # 任务详情
│       │   └── ProcessDocuments.vue  # 文档处理
│       ├── components/complaint/ # 诉状生成组件
│       │   └── CaseConfigStep.vue
│       ├── stores/              # Pinia 状态管理
│       └── api/                 # API 调用封装
├── tests/                        # 测试（28 个测试文件，403 个用例）
├── docker-compose.yml            # 5 服务编排
├── Dockerfile                    # API 服务镜像
├── Dockerfile.worker             # Celery Worker 镜像
├── deploy.sh                     # 一键部署脚本
└── requirements.txt              # Python 依赖
```

---

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 22+
- Docker & Docker Compose（部署用）
- PostgreSQL 16 + Redis + MinIO（本地开发或 Docker）

### 本地开发

```bash
# 1. 克隆项目
git clone https://github.com/minlan01/OCR.git
cd OCR

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入数据库/Redis/MinIO/OCR API 密钥

# 5. 初始化数据库
cd db/migrations && alembic -c alembic.ini upgrade head && cd ../..

# 6. 启动后端
uvicorn api.main:app --host 0.0.0.0 --port 8900 --reload

# 7. 启动 Celery Worker（新终端）
celery -A worker.celery_app worker --pool=solo --loglevel=info  # Windows
# celery -A worker.celery_app worker --loglevel=info  # Linux

# 8. 前端开发
cd static
npm install
npm run dev  # http://localhost:5173

# 9. 构建前端
npm run build  # 输出到 static/dist/
```

### Docker 部署

```bash
# 1. 配置环境
cp .env.example .env.docker
# 编辑 .env.docker，修改密码和 API KEY

# 2. 一键启动
docker-compose --env-file .env.docker up -d --build

# 3. 初始化数据库
docker exec -w /app/db/migrations scanstruct-api python -m alembic -c alembic.ini upgrade head

# 4. 访问
# http://localhost:8900
```

### 服务器部署（Ubuntu / 阿里云）

```bash
# 详见 deploy.sh 脚本
chmod +x deploy.sh
./deploy.sh            # 完整部署
./deploy.sh --update   # 更新代码
./deploy.sh --status   # 查看状态
```

---

## 核心功能详解

### 1. OCR 多引擎管线

系统内置三套 OCR 引擎，支持自动降级：

| 引擎 | 类型 | 特点 |
|------|------|------|
| PaddleOCR 3.5 | 本地 | 零网络依赖，离线可用 |
| 阿里云百炼 Qwen-VL-OCR | 云端 | 高精度，支持复杂版面 |
| 硅基流动 OCR API | 云端 | 备用通道，限流保护 |

处理流程：PDF 预处理（DPI 调整/裁边/去噪）→ 文本/扫描 PDF 分类 → OCR 识别 → 结果结构化存储

### 2. 证据自动分类

基于文件名规则 + 内容特征的双重分类策略：

- **第一层**：`classify_by_filename` — 文件名关键词匹配（身份证、户口本、死亡证明等）
- **第二层**：`classify_with_filename_fallback` — 落入"其他"时再次尝试
- **优先级体系**：`CATEGORY_PRIORITY` 解决跨类别冲突
- **特殊处理**：身份证正反面自动配对（通过 `original_filename` 判断）

### 3. 民事起诉状 DOCX 生成

严格按照法律文书格式规范：
- 标题：黑体二号，居中
- 正文：仿宋四号，行距 28.5 磅
- 首行缩进 2 字符
- 原告信息：姓名+性别+民族+出生日期+住址+身份证号+联系方式
- 被告信息：医疗机构名称+住所+法定代表人+统一社会信用代码
- 司法鉴定段落模板：自动适配伤残/死亡/新生儿案件
- 具状日期：中文格式（二〇二六年六月三日）

### 4. 证据材料 PDF 生成

- 智能页面选择：每种证据类别最优展示（不重复、不遗漏）
- 6 组结构化输出：按类别分组，每组包含封面页+证据页
- 1 张/页完整展示，DPI 150
- ZIP 打包：诉状 + 证据目录 + 证据材料 + 费用汇总

---

## 开发历程与收获

### 项目时间线

| 阶段 | 时间 | 内容 |
|------|------|------|
| 基础架构 | 2026.04 | FastAPI + PostgreSQL + Celery + MinIO 脚手架搭建 |
| OCR 管线 | 2026.05 上旬 | PaddleOCR 集成、PDF 预处理、文本/扫描 PDF 分类 |
| 代码审计 | 2026.05 中旬 | 三轮冗余代码审计（33 项修复）+ 安全审计（12 项修复） |
| 证据整理 | 2026.05 下旬 | 证据分类、PDF 生成、费用汇总、ZIP 打包 |
| 诉状生成 | 2026.05-06 | 民事起诉状 DOCX 生成、被告信息提取、格式规范化 |
| 功能完善 | 2026.06 上旬 | 新生儿案件类型、上传逻辑重构、步骤条交互、Docker 部署准备 |

### 关键技术攻关

1. **PaddleOCR on Windows + CPU**
   - oneDNN PIR 属性转换错误 → `enable_mkldnn=False` 解决
   - Windows 下 Celery 不支持 prefork → `--pool=solo` 模式
   - Python 3.14 不兼容 PaddlePaddle → 独立 Python 3.12 虚拟环境

2. **OCR 限流与污染**
   - 百炼 API 429 限流 → 指数退避重试 + 多引擎降级
   - OCR 结果跨页污染 → 文本清洗管道（去页眉页脚、去水印、去页码）
   - 文本截断 → 分段处理 + 结果拼接

3. **法律文书格式精确控制**
   - python-docx 中文字体设置（仿宋/黑体需精确指定 family + style）
   - 行距控制（28.5 磅固定值 vs 最小值 vs 多倍行距的区别）
   - 东亚字体回退链（SimSun → MS Gothic → Batang）
   - 首行缩进（`Pt(28)` = 2 个四号汉字宽度）

4. **前端上传竞态**
   - `n-upload multiple` 每个文件单独触发 `custom-request`
   - 100ms 延迟队列收集存在竞态，导致文件重复上传
   - 解决：原生 `<input type="file" multiple>` + `onchange` 一次获取全部文件

5. **Docker 化部署**
   - 中文字体缺失（Linux 无 Windows 字体）→ Dockerfile 安装 `fonts-noto-cjk`
   - 数据库迁移 `id` 类型不匹配（UUID vs serial）→ 迁移脚本省略 id 让数据库自增
   - 安全：SSRF 防护（回调 URL 拦截内网 IP）、API Key 认证、CORS 白名单

### 工程实践收获

- **测试驱动**：403 个测试用例，三轮审计修复后保持 0 失败
- **配置外部化**：`.env` 管理所有环境变量，`pydantic-settings` 统一校验
- **多引擎容灾**：OCR 三引擎自动降级，核心服务不依赖单一供应商
- **安全意识**：SSRF 防护、SQL 注入防护（SQLAlchemy ORM）、上传文件类型校验、错误日志去敏
- **Docker 优先**：开发即容器化，消除"我本地能跑"的问题

---

## 数据

- **代码规模**：243 个文件，45,000+ 行代码
- **后端**：139 个 Python 文件
- **前端**：26 个 Vue/TypeScript 组件
- **测试**：28 个测试文件，403 个用例通过
- **数据库迁移**：7 个版本
- **Docker 镜像**：API + Worker 各约 2.6GB（含 PaddlePaddle + OpenCV）

---

## License

Private — 个人/团队内部使用
