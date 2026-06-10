# 多OCR引擎集成 — 实现计划

> 创建时间: 2026-06-08  
> 状态: 待实施  
> 涉及文件: 3 新建 + 3 修改 = 6 个文件

---

## 一、背景与目标

### 当前状态
- 仅支持两套引擎: `paddle`（本地 PaddleOCR）和 `bailian`（阿里云百炼 Qwen-OCR）
- 百炼调用成本高，需要更多廉价/免费备选

### 目标
新增 **百度云 OCR**（`baidu`）和 **GLM-4V-Flash**（`glm`）两套引擎，并增加一个统一的**多引擎回退包装器**（`multi` 模式），实现 `baidu → glm → bailian → paddle` 四级回退链。

---

## 二、文件清单

### 新建文件 (3)

| # | 文件路径 | 说明 |
|---|----------|------|
| 1 | `services/ocr/baidu_engine.py` | 百度云 OCR 引擎（baidu-aip SDK） |
| 2 | `services/ocr/glm_engine.py` | GLM-4V-Flash OCR 引擎（OpenAI 兼容接口） |
| 3 | `services/ocr/multi_engine.py` | 多引擎回退包装器（链式 try/except） |

### 修改文件 (3)

| # | 文件路径 | 修改内容 |
|---|----------|----------|
| 4 | `config/settings.py` | 新增: baidu/glm 配置项 + `ocr_engine_type` 增加 `baidu`/`glm`/`multi` 字面量 + 对应的 field_validator |
| 5 | `services/ocr/engine.py` | 工厂函数 `get_ocr_engine()` 增加 baidu/glm/multi 分支 |
| 6 | `services/ocr/__init__.py` | 导出新增的引擎类 |

---

## 三、技术设计细节

### 3.1 BaiduOCREngine (`baidu_engine.py`)

**定位**: 主力 OCR 引擎，成本最低  
**成本**: 通用高精度版 0.006 元/次起，每月 1000 次免费额度  
**局限**: 
- 不返回 bbox 坐标（纯文字输出）→ bbox 填 `[[0,0],[0,0],[0,0],[0,0]]`
- 不解析表格结构 → 每个检测区域返回一行文字
- 不支持 markdown 输出

**实现要点**:
- 继承 `BaseOCREngine`
- 使用 `baidu-aip` SDK（`pip install baidu-aip`）
- `load_model()`: 初始化 `AipOcr(app_id, api_key, secret_key)`，设置超时
- `recognize()`: 读文件 → `client.basicAccurate(image_bytes)` → `_parse_baidu_result()`
- `_parse_baidu_result()`: 将 `{"words_result": [{"words": "..."}]}` 转为统一的 `list[dict]` 格式
- `recognize_batch()`: 用 `ThreadPoolExecutor` 并发处理，并发数从配置读取
- 错误码处理: 17(配额超限)/18(QPS超限)/100(认证失败) → 返回空列表
- `__str__()` 返回 `"BaiduOCR(basicAccurate)"` 用于日志

**参数来源**:
- `app_id`: `settings.baidu_ocr_app_id`
- `api_key`: `settings.baidu_ocr_api_key`  
- `secret_key`: `settings.baidu_ocr_secret_key`

---

### 3.2 GlmOCREngine (`glm_engine.py`)

**定位**: 免费降级引擎，百度不可用时的第一备选  
**成本**: GLM-4V-Flash 完全免费（智谱开放平台）  
**局限**:
- 免费模型 QPS 极低 → `recognize_batch()` 顺序处理，不用并发
- 响应解析逻辑与 BailianOCREngine 相同（复用 `_parse_response` 逻辑）

**实现要点**:
- 继承 `BaseOCREngine`
- 使用 `openai` 库（已安装），OpenAI 兼容接口调用智谱 API
- `load_model()`: `OpenAI(api_key=..., base_url="https://open.bigmodel.cn/api/paas/v4", timeout=...)`
- `recognize()`: 本地图片转 Base64 data URL → OpenAI vision API → 解析 JSON 响应
- `_call_api()`: 调用 chat.completions.create，messages 格式与百炼一致（image_url + text system prompt）
- 429 重试: 最多 3 次，指数退避（2^attempt * 3s，max 30s）
- 无多模型回退（GLM 是免费备用引擎，不做复杂回退链）
- 图片压缩: 复用百炼的 `_compress_jpeg/_compress_png_to_jpeg`（长边 > 1800px 时压缩）
- `recognize_batch()`: 循环顺序调用 `recognize()`，不并发
- `__str__()` 返回 `"GlmOCR({model})"`

**参数来源**:
- `api_key`: `settings.glm_api_key_plain`
- `base_url`: `settings.glm_base_url`（默认 `https://open.bigmodel.cn/api/paas/v4`）
- `model`: `settings.glm_model`（默认 `glm-4v-flash`）
- `timeout`: `settings.glm_timeout`（默认 60s）

---

### 3.3 MultiOCREngine (`multi_engine.py`)

**定位**: 多引擎顺序回退包装器  
**成本**: 取决于实际使用的引擎  
**局限**: 最慢（按顺序尝试，每个失败才转下一个）

**实现要点**:
- 继承 `BaseOCREngine`
- 构造函数接收 `list[BaseOCREngine]` 引擎列表
- `load_model()`: 遍历列表，依次调用 `engine.load_model()`，全部失败则标记未就绪
- `recognize()`: 遍历引擎列表，`engine.recognize(path)` → 非空结果立即返回，空结果继续下一个
- `recognize_batch()`: 对每张图遍历引擎链
- `is_ready`: 至少有一个引擎就绪
- `__str__()`: 返回 `"MultiOCR(engine1 → engine2 → ...)"` 带箭头链

**默认回退链**（从 settings 读取 `multi_engine_order` 配置）:
```
baidu → glm → bailian → paddle
```

**日志规范**:
- INFO: 当前引擎成功，不暴露内部细节
- WARNING: 引擎失败但已回退到下一个
- ERROR: 全部引擎均失败

---

### 3.4 配置新增 (`config/settings.py`)

```python
# ==================== 百度云 OCR ====================
baidu_ocr_app_id: str = ""
baidu_ocr_api_key: str = ""
baidu_ocr_secret_key: str = ""
baidu_ocr_timeout: int = 30
baidu_ocr_max_concurrent: int = 5

# ==================== GLM-4V-Flash OCR (智谱) ====================
glm_api_key: SecretStr = SecretStr("")
glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
glm_model: str = "glm-4v-flash"
glm_timeout: int = 60

# ==================== 多引擎回退 ====================
multi_engine_order: list[str] = ["baidu", "glm", "bailian", "paddle"]
```

`ocr_engine_type` 字面量扩展:
```python
ocr_engine_type: Literal["paddle", "bailian", "baidu", "glm", "multi"] = "paddle"
```

**validator 修改**:
- 现有 `require_bailian_key_if_selected` → 扩展条件: engine_type 为 bailian/multi 时需要检查 bailian key
- 新增 `require_baidu_credentials_if_selected`: engine_type 为 baidu/multi 时检查 app_id/api_key/secret_key
- 新增 `require_glm_key_if_selected`: engine_type 为 glm/multi 时检查 glm_api_key
- 新增 plain 属性: `@property glm_api_key_plain`

---

### 3.5 工厂函数修改 (`services/ocr/engine.py`)

```python
def get_ocr_engine():
    engine_type = settings.ocr_engine_type.lower()

    if engine_type == "bailian":
        from services.ocr.bailian_engine import BailianOCREngine
        return BailianOCREngine()

    elif engine_type == "baidu":
        from services.ocr.baidu_engine import BaiduOCREngine
        return BaiduOCREngine()

    elif engine_type == "glm":
        from services.ocr.glm_engine import GlmOCREngine
        return GlmOCREngine()

    elif engine_type == "multi":
        from services.ocr.multi_engine import MultiOCREngine
        return MultiOCREngine()  # 内部根据 multi_engine_order 构建引擎链

    else:  # paddle (default)
        return OCREngine()
```

---

### 3.6 导出更新 (`services/ocr/__init__.py`)

```python
from services.ocr.baidu_engine import BaiduOCREngine
from services.ocr.glm_engine import GlmOCREngine
from services.ocr.multi_engine import MultiOCREngine
```

---

## 四、配置示例 (.env)

```bash
# 选择多引擎回退模式（推荐生产环境用 multi）
OCR_ENGINE_TYPE=multi

# 回退顺序（可选，默认 baidu→glm→bailian→paddle）
MULTI_ENGINE_ORDER=["baidu","glm","bailian","paddle"]

# 百度云 OCR（主力，最便宜）
BAIDU_OCR_APP_ID=your_app_id
BAIDU_OCR_API_KEY=your_api_key
BAIDU_OCR_SECRET_KEY=your_secret_key

# GLM-4V-Flash（免费备选）
GLM_API_KEY=your_glm_api_key

# 百炼（已配置，无需修改）
BAILIAN_API_KEY=your_bailian_api_key
```

---

## 五、依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| `baidu-aip` | 百度云 OCR SDK | `pip install baidu-aip` |
| `openai` | GLM-4V-Flash API 调用 | 已安装 |
| `Pillow` | 图片压缩 | 已安装 |

---

## 六、测试要点

1. **BaiduOCREngine**: Mock `AipOcr.basicAccurate`，验证正常返回 + 错误码处理 + 并发
2. **GlmOCREngine**: Mock `OpenAI.chat.completions.create`，验证正常返回 + 429 重试 + 图片压缩
3. **MultiOCREngine**: 3 个 Mock 引擎，验证链式回退 + 全部失败 + 部分就绪
4. **工厂函数**: 验证 5 种 engine_type 各返回正确引擎实例
5. **settings validator**: 验证 multi 模式下的密钥检查逻辑

---

## 七、实施顺序

```
Step 1: config/settings.py          ← 先加配置
Step 2: services/ocr/baidu_engine.py ← 百度引擎
Step 3: services/ocr/glm_engine.py   ← GLM 引擎
Step 4: services/ocr/multi_engine.py ← 多引擎包装器
Step 5: services/ocr/engine.py       ← 工厂函数
Step 6: services/ocr/__init__.py     ← 导出
Step 7: 测试验证                      ← QA 阶段
```
