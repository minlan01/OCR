# ScanStruct 第二阶段开发计划

> **版本**: v1.0  
> **日期**: 2026-06-06  
> **状态**: 待实施（等 GLM 模型恢复后启动）  
> **基准**: 511 passed, 0 failed / 服务器 5 容器 healthy / 磁盘 20%

---

## 目录

1. [总体目标与依赖关系](#1-总体目标与依赖关系)
2. [Phase 1: 完善伤残案件类型 (injury)](#2-phase-1-完善伤残案件类型-injury)
3. [Phase 2: 完善新生儿案件类型 (neonatal)](#3-phase-2-完善新生儿案件类型-neonatal)
4. [Phase 3: 系统容灾处理](#4-phase-3-系统容灾处理)
5. [Phase 4: 并发数增加](#5-phase-4-并发数增加)
6. [附录 A: 死亡案件完整实现链路（参考基准）](#附录-a-死亡案件完整实现链路参考基准)
7. [附录 B: 当前三种案件类型实现差距对比](#附录-b-当前三种案件类型实现差距对比)
8. [附录 C: 全部可调配置项清单](#附录-c-全部可调配置项清单)

---

## 1. 总体目标与依赖关系

### 1.1 四大方向

| 方向 | 目标 | 预计工时 | 前置依赖 |
|------|------|----------|----------|
| 完善伤残案件类型 | 达到与死亡案件同等的定向提取+校验+结论完整度 | ~5h | 无 |
| 完善新生儿案件类型 | 达到与死亡案件同等的定向提取+校验+结论完整度 | ~5h | 无 |
| 系统容灾处理 | 死信队列+MinIO重试+LLM断路器+监控告警 | ~4h | 无 |
| 并发数增加 | Worker prefork -c 2~3 + 资源评估 + 压测 | ~3h | Phase 3 的 Worker 连接池评估 |

### 1.2 实施顺序建议

```
Phase 1 (伤残) ──┐
Phase 2 (新生儿) ─┤── 可并行
Phase 3 (容灾) ──┘
                          ↓
Phase 4 (并发) ──── 依赖 Phase 3.4 (连接池评估)
```

- **Phase 1 + 2 + 3 可并行**，互不依赖
- **Phase 4 必须等 3.4 完成**（并发增加前需确认连接管理方案）
- 每个 Phase 完成后：全量测试 → push → 部署验证

### 1.3 每步完成后的验收标准

1. `pytest tests/ -v` — 0 failed
2. `git push origin main` — CI/CD 绿灯
3. 服务器 `docker ps` — 5 容器 healthy
4. 对应案件类型的端到端验证（上传PDF → 分析 → 结构化输出正确）

---

## 2. Phase 1: 完善伤残案件类型 (injury)

### 参考基准：死亡案件的 6 层实现链路

死亡案件的完整实现覆盖了：定向提取 → LLM 增强 → 校验 → 段落注入 → 结论模板 → 要件配置。伤残案件当前缺少「定向提取」「校验增强」「段落注入」三个关键环节。

### 2.1 伤残等级定向提取

| 属性 | 说明 |
|------|------|
| **任务** | 新增 `_direct_extract_injury_diagnosis()` 函数 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **插入位置** | `_direct_extract_death_diagnosis()` 函数之后（约第 1198 行） |
| **参考** | `_direct_extract_death_diagnosis()` 的 5 层递进提取模式 |
| **依赖** | 无 |

**详细设计**:

```python
# 优先类别顺序（与 death 相同，但无 death_certificate）
_INJURY_DIAG_PRIORITY_CATEGORIES = ["appraisal", "medical_record", "fee_receipt"]

# 诊断标签定义（伤残案件特有）
_INJURY_DIAG_LABELS = [
    r'伤残等级[：:]\s*',
    r'伤残程度[：:]\s*',
    r'劳动能力鉴定[：:]\s*',
    r'损伤程度[：:]\s*',
    r'鉴定意见[：:]\s*',
    r'鉴定结论[：:]\s*',
    r'住院诊断[：:]\s*',
    r'入院诊断[：:]\s*',
    r'出院诊断[：:]\s*',
    r'诊断意见[：:]\s*',
]

# 伤残等级正则（核心提取目标）
_DISABILITY_LEVEL_PATTERNS = [
    r'[一二三四五六七八九十]+级伤残',
    r'[1-9]级伤残',
    r'伤残等级[：:]\s*[一二三四五六七八九十1-9]+级',
    r'构成[一二三四五六七八九十1-9]+级伤残',
]

def _direct_extract_injury_diagnosis(materials: list) -> str | None:
    """从 OCR 原文定向提取伤残等级和入院/出院诊断。
    
    提取策略（5 层递进）:
    1. 带圈编号项提取（①②③...），含页码污染检测与跳过
    2. 数字编号格式（1.xxx；2.xxx...），检查序号连续性
    3. 分号/句号分隔的段落式结论
    4. 简单兜底：取标签后到句号/换行的整段
    5. 出院诊断兜底：筛选含损伤/骨折/功能障碍关键词的条目
    
    Returns: 诊断文本，或 None
    """
```

**调用入口**（在 `analyze_catalog()` 中，与 death 平行）:

```python
# 约 document_analyzer.py 第 99-111 行附近
if case.case_type == "death":
    direct_dd = _direct_extract_death_diagnosis(materials)
    if direct_dd:
        analysis_result["death_diagnosis"] = direct_dd
    ...
elif case.case_type == "injury":
    direct_id = _direct_extract_injury_diagnosis(materials)
    if direct_id:
        analysis_result["injury_diagnosis"] = direct_id
    # 伤残等级单独提取
    disability_level = _direct_extract_disability_level(materials)
    if disability_level:
        analysis_result["disability_level"] = disability_level
```

### 2.2 伤残等级单独提取

| 属性 | 说明 |
|------|------|
| **任务** | 新增 `_direct_extract_disability_level()` 函数 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **插入位置** | 紧接 `_direct_extract_injury_diagnosis()` 之后 |
| **依赖** | 无 |

**详细设计**:

```python
def _direct_extract_disability_level(materials: list) -> str | None:
    """从鉴定意见书 OCR 原文定向提取伤残等级。

    搜索策略：
    1. 只搜索 appraisal 类别材料（鉴定意见书）
    2. 使用 _DISABILITY_LEVEL_PATTERNS 匹配"X级伤残"
    3. 返回最高伤残等级（伤残等级数字越小越严重）

    Returns: 如 "九级伤残" / "3级伤残"，或 None
    """
```

### 2.3 LLM 提取增强（case_specific_note 补充）

| 属性 | 说明 |
|------|------|
| **任务** | 增强 `_extract_document_slots()` 中 injury 的 `case_specific_note` |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 553-562 行，injury 分支的 `case_specific_note` |
| **当前内容** | 4 条提示（入院/出院日期、损害后果、伤残等级、后续治疗） |
| **依赖** | 2.1 |

**修改内容**:

```python
# 现有 4 条 + 新增以下内容
case_specific_note = (
    "【伤残案件特别注意】\n"
    "1. 患者因医疗损害导致伤残，需要从鉴定意见书中提取完整伤残等级\n"
    "2. 伤残等级必须从司法鉴定意见书中提取，格式通常为'X级伤残'\n"
    "3. adverse_outcome应包含伤残经过及当前伤残状况\n"
    "4. 如有后续治疗费评估，必须提取后续治疗费金额及依据\n"       # 新增
    "5. 如有误工期限鉴定，必须提取误工期限及收入标准\n"            # 新增
    "6. 如有护理依赖程度鉴定，必须提取护理依赖等级\n"              # 新增
    "7. 后续治疗费/误工费/护理费是伤残案件赔偿的核心组成部分\n"      # 新增
)
```

同时，参照 death 的 `death_section`，新增 injury 的专属 Slot 段落：

```python
# 约第 546-552 行之后
injury_section = (
    "\n### 九、伤残信息（仅伤残案件）\n"
    "- disability_level: 伤残等级（如'九级伤残'、'3级伤残'）\n"
    "- injury_diagnosis: 完整伤残诊断（从鉴定意见书或入院/出院病历中提取）\n"
    "- subsequent_treatment_fee: 后续治疗费（如有鉴定）\n"
    "- loss_of_earning_period: 误工期限（如有鉴定）\n"
    "- nursing_dependence: 护理依赖程度（如有鉴定）\n"
)
```

### 2.4 伤残案件必填校验

| 属性 | 说明 |
|------|------|
| **任务** | `_validate_extracted_data()` 增加 injury 专属校验 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 1532-1536 行，`if case_type == "death":` 块之后 |
| **依赖** | 2.3 |

**修改内容**:

```python
# 在 death 校验之后添加
elif case_type == "injury":
    if not data.get("preliminary_diagnosis") and not data.get("admission_diagnosis"):
        issues.append("伤残案件缺少入院/初步诊断")
    if data.get("has_appraisal") and not data.get("disability_level"):
        issues.append("伤残案件有鉴定材料但缺少伤残等级")
    if not data.get("adverse_outcome"):
        issues.append("伤残案件缺少损害后果描述")
```

### 2.5 段落生成上下文注入

| 属性 | 说明 |
|------|------|
| **任务** | `_generate_facts_paragraph()` 中为 injury 注入专属上下文 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 785-800 行，death 的 `paragraph_2` 专属注入之后 |
| **当前内容** | injury 无任何专属上下文注入 |
| **依赖** | 2.1 |

**修改内容**:

```python
# 在 death 专属注入之后，添加 injury 专属注入
elif case_type == "injury":
    disability_level = extracted_data.get("disability_level", "")
    injury_diag = extracted_data.get("injury_diagnosis", "")
    if disability_level:
        context_parts.append(f"【伤残等级】{disability_level}")
    if injury_diag:
        context_parts.append(f"【伤残诊断】{injury_diag}")
    # 鉴定结论原文注入（与 death 同逻辑）
    appraisal = extracted_data.get("appraisal_details", {})
    conclusion_original = appraisal.get("appraisal_conclusion_original", "")
    if conclusion_original:
        context_parts.append(f"【鉴定结论原文（请逐字引用，不要改写）】{conclusion_original}")
```

### 2.6 伤残模板 Prompt 精调

| 属性 | 说明 |
|------|------|
| **任务** | 精调 `template_manager.py` 的 injury_adult / injury_minor 模板 |
| **涉及文件** | `services/complaint/template_manager.py` |
| **修改位置** | TEMPLATE_REGISTRY 的 injury_adult（约55-148行）和 injury_minor（约149-243行） |
| **依赖** | 2.3 |

**精调要点**:

| 段落 | 当前 | 改动 |
|------|------|------|
| **paragraph_1** | 无特殊 | 无需改动 |
| **paragraph_2** | "诊疗过程及损害发生" | 段末要求："段末必须列明伤残等级鉴定结论或当前伤残状况"（类似 death 的"段末必须列完整死亡诊断"） |
| **paragraph_3** | 通用 | 增加："如仍在住院需说明截至起诉之日仍在治疗的情况" |
| **paragraph_4** | "伤残等级鉴定" | 增加："如有多处伤残，需分别列明各处伤残等级" |
| **conclusion** | "导致原告伤残" | 增加："伤残赔偿金按伤残等级对应赔偿系数计算"指引 |

### 2.7 结论模板增强

| 属性 | 说明 |
|------|------|
| **任务** | `_generate_conclusion()` 的 injury 分支增加伤残等级描述 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 882-890 行 |
| **依赖** | 2.2 |

**修改内容**:

```python
# 当前 injury 结论模板
else:  # injury
    disability_level = ""
    if extracted_data.get("disability_level"):
        disability_level = f"（经鉴定构成{extracted_data['disability_level']}）"
    return (
        f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
        f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
        f"并由此造成了患者伤残{disability_level}的严重损害后果，"
        f"给原告造成了重大的物质损害及带来了极大的精神痛苦。"
        f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
        f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
    )
```

### 2.8 测试 + 验证

| 属性 | 说明 |
|------|------|
| **任务** | 编写单元测试 + 端到端验证 |
| **涉及文件** | `tests/test_document_analyzer.py`（新增/补充测试用例） |
| **依赖** | 2.1-2.7 全部完成 |

**测试用例清单**:

| 测试 | 覆盖内容 |
|------|----------|
| `test_direct_extract_injury_diagnosis_circled_numbers` | 带圈编号 ①②③ 诊断提取 |
| `test_direct_extract_injury_diagnosis_numbered_list` | 数字编号 1.xxx 2.xxx 提取 |
| `test_direct_extract_injury_diagnosis_discharge_fallback` | 出院诊断兜底 |
| `test_direct_extract_disability_level` | "九级伤残" / "3级伤残" 提取 |
| `test_validate_injury_missing_diagnosis` | 缺少入院/初步诊断时报 issue |
| `test_validate_injury_missing_disability_level` | 有鉴定但缺伤残等级时报 issue |
| `test_injury_conclusion_with_level` | 结论含伤残等级描述 |
| `test_injury_paragraph2_context_injection` | paragraph_2 注入伤残等级+鉴定结论 |

**端到端验证**: 上传 1-2 份伤残案件 PDF（需含鉴定意见书），确认输出的 `disability_level` 和 `injury_diagnosis` 正确。

---

## 3. Phase 2: 完善新生儿案件类型 (neonatal)

### 与伤残案件的差异

新生儿案件的核心数据是 **Apgar 评分**和**分娩/产程信息**，与死亡/伤残的诊断提取模式不同。Apgar 评分是结构化的数字（1/5/10 分钟各项得分），需要更精确的解析逻辑。

### 3.1 Apgar 评分定向提取

| 属性 | 说明 |
|------|------|
| **任务** | 新增 `_direct_extract_apgar_scores()` 函数 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **插入位置** | `_direct_extract_death_diagnosis()` 之后 |
| **依赖** | 无 |

**详细设计**:

```python
# Apgar 评分 5 项指标
_APGAR_ITEMS = ["心率", "呼吸", "肌张力", "反射", "肤色"]
# 也可能用英文缩写: HR/R/M/Rf/Color

# 搜索正则
_APGAR_PATTERNS = [
    # 格式1: "1分钟Apgar评分：8分（心率2+呼吸2+肌张力2+反射1+肤色1）"
    r'(\d+)\s*分钟\s*[Aa]pgar\s*评[分价][：:]\s*(\d+)\s*分',
    # 格式2: "Apgar 1min: 8, 5min: 9, 10min: 10"
    r'[Aa]pgar\s+(\d+)\s*(?:min|分钟)[：:]\s*(\d+)',
    # 格式3: 表格中的 "1min 8分 / 5min 9分"
    r'(\d+)\s*(?:min|分钟)\s*(\d+)\s*分',
]

def _direct_extract_apgar_scores(materials: list) -> dict | None:
    """从 OCR 原文定向提取 Apgar 评分。

    搜索策略：
    1. 优先搜索 medical_record 和 identity_other 类别材料
    2. 匹配 "1分钟/5分钟/10分钟 Apgar评分 X分" 格式
    3. 尝试解析各项得分（心率/呼吸/肌张力/反射/肤色）
    4. 如无法解析各项，至少提取总分

    Returns: 
    {
        "apgar_1min": {"total": 8, "items": {"心率": 2, "呼吸": 2, ...}},
        "apgar_5min": {"total": 9, ...},
        "apgar_10min": {"total": 10, ...},  # 可选
    }
    或 None
    """
```

**调用入口**:

```python
elif case.case_type == "neonatal":
    apgar = _direct_extract_apgar_scores(materials)
    if apgar:
        analysis_result["apgar_scores"] = apgar
    birth_info = _direct_extract_birth_records(materials)
    if birth_info:
        analysis_result.update(birth_info)
```

### 3.2 分娩/产程信息定向提取

| 属性 | 说明 |
|------|------|
| **任务** | 新增 `_direct_extract_birth_records()` 函数 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **插入位置** | 紧接 `_direct_extract_apgar_scores()` 之后 |
| **依赖** | 无 |

**详细设计**:

```python
# 分娩方式
_DELIVERY_METHODS = [
    r'顺产', r'自然分娩', r'剖宫产', r'剖腹产', r'产钳助产',
    r'胎吸助产', r'臀位助产', r'阴道助产',
]

# 关键指标
_BIRTH_INFO_PATTERNS = {
    "gestational_weeks": r'孕\s*(\d+)\s*[周\+][^年]',  # "孕38+2周"
    "birth_weight": r'(?:出生体重|体重)[：:]\s*(\d+)\s*[kgt克]',  # "出生体重：3200g"
    "delivery_method": r'(顺产|自然分娩|剖宫产|剖腹产|产钳助产|胎吸助产)',
    "amniotic_fluid": r'(?:羊水|胎膜)[：:]\s*([^\n,，；;]+)',
    "umbilical_cord": r'(?:脐带)[：:]\s*([^\n,，；;]+)',
    "fetal_heart": r'(?:胎心(?:监护)?)[：:]\s*([^\n,，；;]+)',
}

def _direct_extract_birth_records(materials: list) -> dict | None:
    """从 OCR 原文定向提取分娩/产程信息。

    搜索策略：
    1. 优先搜索 medical_record 和 identity_other（出生证明）类别材料
    2. 逐项匹配 _BIRTH_INFO_PATTERNS 中的正则
    3. 返回结构化产程信息

    Returns:
    {
        "delivery_method": "剖宫产",
        "gestational_weeks": "38+2",
        "birth_weight": "3200g",
        "amniotic_fluid": "清",
        "umbilical_cord": "正常",
        "fetal_heart": "正常",
    }
    或 None
    """
```

### 3.3 HIE 分级定向提取

| 属性 | 说明 |
|------|------|
| **任务** | 在 `_direct_extract_birth_records()` 中增加 HIE 分级提取 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **依赖** | 3.2 |

**HIE 分级关键词**:

```python
_HIE_GRADE_PATTERNS = [
    r'HIE[（(]缺血缺氧性脑病[)）][：:]*\s*(轻度|中度|重度)',
    r'新生儿缺血缺氧性脑病[（(]HIE[)）][：:]*\s*(轻度|中度|重度)',
    r'(轻度|中度|重度)\s*HIE',
    r'(轻度|中度|重度)\s*缺血缺氧性脑病',
]
```

### 3.4 LLM 提取增强（neonatal_section 新增）

| 属性 | 说明 |
|------|------|
| **任务** | 在 `_extract_document_slots()` 中为 neonatal 新增 `neonatal_section` |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 546-552 行，`death_section` 之后 |
| **当前内容** | neonatal 的 `case_specific_note` 已有 7 条提示（行 524-534），但无独立 Slot 段 |
| **依赖** | 3.1, 3.2 |

**新增内容**:

```python
neonatal_section = (
    "\n### 九、新生儿信息（仅新生儿案件）\n"
    "- apgar_scores: Apgar评分（结构化：1分钟/5分钟/10分钟，含各项得分）\n"
    "- birth_weight: 出生体重（单位g）\n"
    "- gestational_weeks: 孕周（如'38+2周'）\n"
    "- delivery_method: 分娩方式（顺产/剖宫产/产钳助产等）\n"
    "- hie_grade: HIE分级（轻度/中度/重度，如有）\n"
    "- maternal_labor: 母亲产程描述（产程时长、胎膜早破、羊水污染等）\n"
    "- nicu_stay: NICU住院信息（住院天数、主要治疗）\n"
)
```

### 3.5 新生儿必填校验

| 属性 | 说明 |
|------|------|
| **任务** | `_validate_extracted_data()` 增加 neonatal 专属校验 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 1539-1541 行，`if case_type == "neonatal":` 块内 |
| **当前内容** | 仅 `data["is_minor"] = True` |
| **依赖** | 3.4 |

**修改内容**:

```python
if case_type == "neonatal":
    data["is_minor"] = True  # 已有
    # 新增校验
    if not data.get("birth_weight") and data.get("has_birth_certificate"):
        issues.append("新生儿案件有出生证明但缺少出生体重")
    if not data.get("delivery_method"):
        issues.append("新生儿案件缺少分娩方式")
    # HIE 相关诊断时建议填写分级
    diagnosis_text = " ".join([
        data.get("admission_diagnosis", ""),
        data.get("discharge_diagnosis", ""),
        data.get("preliminary_diagnosis", ""),
    ])
    if "HIE" in diagnosis_text or "缺血缺氧性脑病" in diagnosis_text:
        if not data.get("hie_grade"):
            issues.append("新生儿案件有HIE诊断但缺少HIE分级")
```

### 3.6 段落生成上下文注入

| 属性 | 说明 |
|------|------|
| **任务** | `_generate_facts_paragraph()` 中为 neonatal 注入专属上下文 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 785-800 行，death 和 injury 专属注入之后 |
| **依赖** | 3.1 |

**修改内容**:

```python
elif case_type == "neonatal":
    apgar = extracted_data.get("apgar_scores", {})
    if apgar:
        apgar_text = "、".join(
            f"{k}：{v.get('total', '?')}分" for k, v in apgar.items()
        )
        context_parts.append(f"【Apgar评分】{apgar_text}")
    birth_weight = extracted_data.get("birth_weight", "")
    if birth_weight:
        context_parts.append(f"【出生体重】{birth_weight}")
    delivery = extracted_data.get("delivery_method", "")
    if delivery:
        context_parts.append(f"【分娩方式】{delivery}")
    hie = extracted_data.get("hie_grade", "")
    if hie:
        context_parts.append(f"【HIE分级】{hie}")
```

### 3.7 模板 Prompt 精调

| 属性 | 说明 |
|------|------|
| **任务** | 精调 `template_manager.py` 的 neonatal_adult / neonatal_minor 模板 |
| **涉及文件** | `services/complaint/template_manager.py` |
| **修改位置** | TEMPLATE_REGISTRY 的 neonatal_adult（约431-531行）和 neonatal_minor（约533-637行） |
| **依赖** | 3.4 |

**精调要点**:

| 段落 | 改动 |
|------|------|
| **paragraph_2** | 增加："段末必须列明Apgar评分（如有）及HIE分级" |
| **paragraph_3** | 增加："需说明母亲产程经过，包括是否有胎膜早破、羊水污染、产程延长等" |
| **paragraph_4** | 增加："如有多项伤残/损伤，需分别列明" |

### 3.8 neonatal_adult 逻辑确认

| 属性 | 说明 |
|------|------|
| **任务** | 确认 neonatal_adult 是否有实际使用场景，决定保留或清理 |
| **涉及文件** | `db/models_evidence.py` + 前端 |
| **依赖** | 无 |

**分析**:

- 新生儿案件固定 `is_minor=True`（`_validate_extracted_data` 行 1539-1541 强制设置）
- `TEMPLATE_REGISTRY` 中有 `neonatal_adult` 和 `neonatal_minor` 两套模板
- 如果前端选 neonatal 时 `is_minor` 只能选 True/被强制为 True，则 `neonatal_adult` 永远不会走

**决策方案**:

| 方案 | 说明 | 建议 |
|------|------|------|
| A: 保留 | 允许极端场景（如成年人在新生儿时期发生的损害追诉） | 不推荐，逻辑矛盾 |
| B: 清理 | 删除 `neonatal_adult`，只保留 `neonatal_minor`，前端强制 `is_minor=True` | ✅ 推荐 |
| C: 限制 | 数据库层面加 CHECK 约束 `neonatal → is_minor = true` | 安全但需改 |

### 3.9 结论模板增强

| 属性 | 说明 |
|------|------|
| **任务** | `_generate_conclusion()` 的 neonatal 分支增加 HIE/Apgar 描述 |
| **涉及文件** | `services/evidence/document_analyzer.py` |
| **修改位置** | 约 873-881 行 |
| **依赖** | 3.1 |

**修改内容**:

```python
elif case_type == "neonatal":
    hie_desc = ""
    hie = extracted_data.get("hie_grade", "")
    if hie:
        hie_desc = f"（经诊断为{hie}HIE）"
    return (
        f"综上所述，被告{defendant_name}在为患儿{patient_name}提供诊疗服务过程中，"
        f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
        f"并由此造成了新生儿遭受严重损害{hie_desc}的后果，"
        f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
        f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
        f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
    )
```

### 3.10 测试 + 验证

| 属性 | 说明 |
|------|------|
| **任务** | 编写单元测试 + 端到端验证 |
| **涉及文件** | `tests/test_document_analyzer.py` |
| **依赖** | 3.1-3.9 全部完成 |

**测试用例清单**:

| 测试 | 覆盖内容 |
|------|----------|
| `test_direct_extract_apgar_scores_full` | 完整 Apgar 评分（1/5/10min）提取 |
| `test_direct_extract_apgar_scores_total_only` | 仅总分提取 |
| `test_direct_extract_apgar_scores_missing` | 无 Apgar 评分返回 None |
| `test_direct_extract_birth_records` | 分娩方式+出生体重+孕周提取 |
| `test_direct_extract_hie_grade` | HIE 分级提取 |
| `test_validate_neonatal_missing_birth_weight` | 有出生证明但缺体重时报 issue |
| `test_validate_neonatal_missing_delivery` | 缺分娩方式时报 issue |
| `test_validate_neonatal_hie_without_grade` | 有 HIE 诊断但缺分级时报 issue |
| `test_neonatal_conclusion_with_hie` | 结论含 HIE 分级描述 |
| `test_neonatal_paragraph2_context_injection` | paragraph_2 注入 Apgar+分娩信息 |

**端到端验证**: 上传 1-2 份新生儿案件 PDF（需含出生证明+分娩记录），确认 Apgar 评分和产程信息正确提取。

---

## 4. Phase 3: 系统容灾处理

### 3.1 Celery 死信队列

| 属性 | 说明 |
|------|------|
| **任务** | 失败 3 次的任务移入死信表，而非丢弃 |
| **涉及文件** | 新增 `db/models_dead_letter.py`，新增 `api/routes/admin_dead_letters.py`，修改 `worker/evidence_tasks.py`，新增 migration |
| **依赖** | 无 |

**数据模型**:

```python
# db/models_dead_letter.py
class DeadLetterTask(Base):
    __tablename__ = "dead_letter_tasks"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    original_task_id = Column(String(255), nullable=False, index=True)
    task_name = Column(String(255), nullable=False)
    case_id = Column(UUID, nullable=True)
    retry_count = Column(Integer, nullable=False)
    last_error = Column(Text, nullable=True)
    last_error_code = Column(String(50), nullable=True)
    original_args = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(100), nullable=True)
```

**触发逻辑**（在 `evidence_tasks.py` 各 task 的 `on_retry` / `on_failure` 回调中）:

```python
@analyze_evidence.on_failure
def _on_analysis_failure(task_id, exc, traceback, *args, **kwargs):
    """任务最终失败后移入死信表"""
    # 如果重试次数 >= max_retries，移入 dead_letter_tasks
    ...
```

**API 端点**:

```
GET  /api/v1/admin/dead-letters          # 列表（分页、筛选）
GET  /api/v1/admin/dead-letters/{id}     # 详情
POST /api/v1/admin/dead-letters/{id}/retry  # 重新入队
DELETE /api/v1/admin/dead-letters/{id}    # 删除
```

**Migration**:

```python
# db/migrations/versions/2026060x_001_dead_letter_tasks.py
def upgrade():
    op.create_table('dead_letter_tasks', ...)
def downgrade():
    op.drop_table('dead_letter_tasks')
```

### 3.2 MinIO 下载重试装饰器

| 属性 | 说明 |
|------|------|
| **任务** | 为 MinIO 下载操作增加应用层重试 |
| **涉及文件** | `services/storage/minio_client.py` |
| **当前状态** | 上传有重试（3次+指数退避），下载**无重试**，直接抛异常 |
| **依赖** | 无 |

**详细设计**:

```python
import functools
import time
from minio.error import S3Error

# 可重试的 S3 错误码（Transient）
_TRANSIENT_S3_CODES = {"NoSuchUpload", "InternalError", "ServiceUnavailable", "SlowDown"}

def _is_transient_error(exc: Exception) -> bool:
    """判断是否为可重试的临时错误"""
    if isinstance(exc, S3Error):
        return exc.code in _TRANSIENT_S3_CODES
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    if "timed out" in str(exc).lower() or "connection" in str(exc).lower():
        return True
    return False

def minio_retry(max_retries: int = 3, base_delay: float = 1.0):
    """MinIO 操作重试装饰器（指数退避）"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if not _is_transient_error(e):
                        raise  # Permanent 错误立即抛出
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)  # 1s, 2s, 4s
                        logger.warning(
                            f"MinIO transient error (attempt {attempt+1}/{max_retries+1}), "
                            f"retrying in {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
```

**应用**（在现有下载方法上加装饰器）:

```python
@minio_retry(max_retries=3, base_delay=1.0)
def download_bytes(self, bucket: str, object_key: str) -> bytes:
    ...

@minio_retry(max_retries=3, base_delay=1.0)
def download_file(self, bucket: str, object_key: str, file_path: str) -> None:
    ...
```

### 3.3 LLM 断路器

| 属性 | 说明 |
|------|------|
| **任务** | 新增 CircuitBreaker 类，集成到 `call_llm_with_retry()` |
| **涉及文件** | `services/llm/rate_limiter.py` |
| **当前状态** | 有 429 自适应降级（降级到基础值一半），但无断路器 |
| **依赖** | 无 |

**详细设计**:

```python
import time
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断，暂停调用
    HALF_OPEN = "half_open" # 半开，允许1次探测

class CircuitBreaker:
    """LLM 断路器
    
    状态转换：
    CLOSED → （连续N次失败）→ OPEN → （等待T秒）→ HALF_OPEN → （探测成功）→ CLOSED
                                                               → （探测失败）→ OPEN
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,     # 连续N次失败触发熔断
        recovery_timeout: float = 30.0,  # OPEN 状态等待T秒后转 HALF_OPEN
        half_open_max_calls: int = 1,    # HALF_OPEN 最多允许1次探测
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state
    
    def allow_call(self) -> bool:
        """是否允许发起调用"""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False  # OPEN
    
    def record_success(self):
        """记录调用成功"""
        self._failure_count = 0
        self._state = CircuitState.CLOSED
    
    def record_failure(self):
        """记录调用失败"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker OPEN after {self._failure_count} consecutive failures"
            )

# 全局实例（per model_type）
_circuit_breakers: dict[str, CircuitBreaker] = {}

def get_circuit_breaker(model_type: str) -> CircuitBreaker:
    if model_type not in _circuit_breakers:
        _circuit_breakers[model_type] = CircuitBreaker()
    return _circuit_breakers[model_type]
```

**集成到 `call_llm_with_retry()`**:

```python
async def call_llm_with_retry(call_fn, model_type: str = "text", ...):
    breaker = get_circuit_breaker(model_type)
    if not breaker.allow_call():
        raise CircuitBreakerOpenError(
            f"LLM circuit breaker is OPEN for {model_type}, "
            f"retry after {breaker.recovery_timeout}s"
        )
    try:
        result = await call_fn()
        breaker.record_success()
        return result
    except Exception as e:
        if _is_429_or_5xx(e):
            breaker.record_failure()
        raise
```

### 3.4 Worker 连接池评估

| 属性 | 说明 |
|------|------|
| **任务** | 评估 Worker 是否应从 NullPool 切换到小连接池 |
| **涉及文件** | `worker/evidence_tasks.py`, `config/settings.py` |
| **当前状态** | `_create_worker_engine()` 使用 `NullPool`，每次任务创建+销毁连接 |
| **依赖** | 无 |

**分析**:

| 方案 | 优点 | 缺点 |
|------|------|------|
| **NullPool（当前）** | 无连接泄漏风险 | 每次任务创建/销毁 TCP 连接，延迟 ~50ms |
| **SmallPool（pool_size=2, max_overflow=3）** | 连接复用，减少延迟 | prefork 子进程各自持池，需确保 `engine.dispose()` |

**建议方案**:

```python
# config/settings.py 新增
worker_db_pool_size: int = 2       # Worker 进程内连接池大小
worker_db_pool_max_overflow: int = 3  # 最大溢出

# worker/evidence_tasks.py 修改
def _create_worker_engine():
    from sqlalchemy.pool import QueuePool
    return create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=QueuePool,
        pool_size=settings.worker_db_pool_size,
        max_overflow=settings.worker_db_pool_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,  # 30分钟回收
    )
```

**连接数计算**:

```
API:              pool_size=5 × 1进程 = 5 连接
Worker prefork:   pool_size=2 × 2子进程 = 4 连接
Overflow (worst): max_overflow=10 (API) + max_overflow=3×2 (Worker) = 16
总计: 5 + 4 + 16 = 25 连接
PG max_connections = 50  →  充足 ✅
```

### 3.5 简单监控告警

| 属性 | 说明 |
|------|------|
| **任务** | cron + curl healthcheck + 通知 |
| **涉及文件** | 新增 `scripts/healthcheck_alert.sh`，修改 `docker-compose.yml` |
| **依赖** | 无 |

**设计方案**:

```bash
#!/bin/bash
# scripts/healthcheck_alert.sh

HEALTH_URL="http://localhost:8900/api/v1/health"
MAX_FAIL=3
INTERVAL=60  # 每60秒检查一次
WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"  # 企微/飞书 Webhook

fail_count=0

while true; do
    status=$(curl -sf -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null)
    if [ "$status" != "200" ]; then
        fail_count=$((fail_count + 1))
        if [ $fail_count -ge $MAX_FAIL ]; then
            msg="🚨 ScanStruct 健康检查连续失败 ${fail_count} 次 (HTTP ${status:-N/A})"
            if [ -n "$WEBHOOK_URL" ]; then
                curl -sf -X POST "$WEBHOOK_URL" \
                    -H 'Content-Type: application/json' \
                    -d "{\"content\": \"$msg\"}" 2>/dev/null
            fi
            echo "$(date): $msg"
            # 重启 API 容器
            docker restart scanstruct-api
        fi
    else
        if [ $fail_count -gt 0 ]; then
            echo "$(date): Health check recovered after $fail_count failures"
        fi
        fail_count=0
    fi
    sleep $INTERVAL
done
```

**docker-compose.yml 集成**:

```yaml
  healthcheck-monitor:
    image: alpine:3.20
    restart: unless-stopped
    volumes:
      - ./scripts/healthcheck_alert.sh:/app/healthcheck.sh:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - ALERT_WEBHOOK_URL=${ALERT_WEBHOOK_URL:-}
    entrypoint: ["/bin/sh", "/app/healthcheck.sh"]
    deploy:
      resources:
        limits:
          memory: 32M
```

### 3.6 测试 + 验证

| 属性 | 说明 |
|------|------|
| **任务** | 新增容灾组件的单元测试 |
| **涉及文件** | 新增 `tests/test_dead_letter.py`, `tests/test_minio_retry.py`, `tests/test_circuit_breaker.py` |
| **依赖** | 3.1-3.3 |

**测试用例清单**:

| 测试文件 | 覆盖内容 |
|---------|----------|
| `test_dead_letter.py` | 模型 CRUD、API 端点、重试入队 |
| `test_minio_retry.py` | Transient 错误重试 3 次、Permanent 错误立即抛出、指数退避时序 |
| `test_circuit_breaker.py` | CLOSED→OPEN、OPEN 等待→HALF_OPEN、HALF_OPEN 成功→CLOSED、HALF_OPEN 失败→OPEN |

---

## 5. Phase 4: 并发数增加

> ⚠️ Phase 4 依赖 Phase 3.4（Worker 连接池评估）完成后再启动

### 4.1 Worker 进程模型优化

| 属性 | 说明 |
|------|------|
| **任务** | 从 `--pool=solo` 单进程切换到 `--pool=prefork -c 2`（Dockerfile.worker 已有，但 docker-compose 未启用） |
| **涉及文件** | `Dockerfile.worker`, `docker-compose.yml` |
| **当前状态** | Dockerfile 中 `CMD` 写了 `--concurrency=2`，但实际运行需确认 |
| **依赖** | Phase 3.4 |

**当前 Dockerfile.worker**:

```bash
CMD ["python", "-m", "celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
```

**需确认/调整**:

1. 确认当前运行是否已使用 prefork -c 2（检查 `docker exec scanstruct-worker celery -A worker.celery_app inspect active`）
2. 如果是 solo，确认切换到 prefork 后的内存影响
3. 添加 `--max-tasks-per-child=50` 防止内存泄漏

**内存评估**:

```
prefork -c 2 模式下：
- 主进程: ~300MB (Celery + OCR模型)
- 子进程1: ~300MB (处理任务时)
- 子进程2: ~300MB (处理任务时)
- 峰值: ~900MB
- Docker 限制: 2G → 充足 ✅

但需要注意：
- OCR 模型加载（PaddleOCR ~200MB）是在主进程中，子进程 fork 后共享
- 每个子进程处理 PDF 时 /tmp 下会产生临时文件（tmpfs 512M 共享）
- 两个子进程同时处理大 PDF 时：2×128MB = 256MB → 512M tmpfs 基本够用 ✅
```

### 4.2 OCR/LLM 并发数调优

| 属性 | 说明 |
|------|------|
| **任务** | 评估提高 OCR 和 LLM 并发数上限 |
| **涉及文件** | `.env.production` / `docker-compose.yml` 环境变量 |
| **依赖** | 4.1 |

**当前配置 vs 建议调整**:

| 配置项 | 当前值 | 建议值 | 说明 |
|--------|--------|--------|------|
| `BAILIAN_OCR_MAX_CONCURRENT` | 10 | 15 | 百炼 API 配额允许，但需实测 |
| `BAILIAN_TEXT_MAX_CONCURRENT` | 5 | 8 | 文本分析并发，受 DashScope 配额限制 |
| `LLM_RATE_LIMITER_TEXT` | 5 | 8 | 与 TEXT_MAX_CONCURRENT 一致 |
| `LLM_RATE_LIMITER_OCR` | 10 | 15 | 与 OCR_MAX_CONCURRENT 一致 |
| `LLM_RATE_LIMITER_FLASH` | 15 | 20 | 快速模型配额通常较宽松 |

**注意**: 需要在实际环境中逐步调高，每次调高后观察 429 错误率。如果 429 频繁出现，断路器（Phase 3.3）会自动降级。

### 4.3 tmpfs 容量评估

| 属性 | 说明 |
|------|------|
| **任务** | 评估并发增加后 tmpfs 512M 是否够用 |
| **涉及文件** | `docker-compose.yml` |
| **依赖** | 4.1 |

**分析**:

```
prefork -c 2 模式下，最坏情况：
- 子进程1 处理 128MB PDF → 临时文件 ~128MB
- 子进程2 处理 128MB PDF → 临时文件 ~128MB
- OCR 页面图片 → 每页 ~1MB × 100页 = ~100MB
- 总计: ~356MB → 512M 够用 ✅

但如果出现 3 个以上大于 100MB 的 PDF 同时处理：
- 可能超 512M
- 已有 TemporaryDirectory 自动清理（Phase 1/2 优化后）
- 保险方案：提升到 1G

权衡：512M → 1G 意味着 worker 容器多占 512M 内存，总内存限制需从 2G → 3G
```

**决策**:

- 如果 worker 切换 `prefork -c 2`：保持 **512M tmpfs + 2G 内存限制**
- 如果后续切 `prefork -c 3`：升级到 **1G tmpfs + 3G 内存限制**
- 当前建议：保持 512M，观察实际峰值使用率

### 4.4 PostgreSQL 连接数调优

| 属性 | 说明 |
|------|------|
| **任务** | 确认并发增加后 PG 连接数是否充足 |
| **涉及文件** | `config/settings.py`, PostgreSQL 配置 |
| **依赖** | 4.1, Phase 3.4 |

**连接数计算（prefork -c 2 + SmallPool）**:

```
组件                      常驻连接  最大溢出  最大可能
API (1进程)               5        10       15
Worker 子进程1 (QueuePool) 2       3        5
Worker 子进程2 (QueuePool) 2       3        5
─────────────────────────────────────────────────
合计                       9       16       25

PG max_connections = 50 → 充足 ✅
预留 25 给管理/监控等 → 安全 ✅
```

如果后续切 `prefork -c 3`:

```
3 × (2 + 3) = 15 Worker 连接
API + Worker = 5 + 15 = 20 常驻, 最多 30
PG 50 → 仍充足 ✅
```

### 4.5 压测验证

| 属性 | 说明 |
|------|------|
| **任务** | 提交 2-3 个案件同时处理，确认无资源争抢 |
| **涉及文件** | 手动测试 |
| **依赖** | 4.1-4.4 |

**压测清单**:

| 检查项 | 验证方法 | 达标标准 |
|--------|---------|---------|
| CPU 使用率 | `docker stats scanstruct-worker` | < 80% |
| 内存使用 | `docker stats scanstruct-worker` | < 1.5G (2G限制的75%) |
| tmpfs 使用率 | `docker exec scanstruct-worker df -h /tmp` | < 70% |
| PG 活跃连接 | `SELECT count(*) FROM pg_stat_activity` | < 30 |
| LLM 429 错误率 | 查看 worker 日志 | < 5% |
| 任务成功率 | 3 个案件全部 analysis_done | 100% |
| 总处理时间 | 从上传到完成 | < 单个案件的 1.5 倍 |

---

## 附录 A: 死亡案件完整实现链路（参考基准）

### A.1 定向提取 `_direct_extract_death_diagnosis()`

**文件**: `services/evidence/document_analyzer.py`，行 978-1197

**函数签名**:
```python
def _direct_extract_death_diagnosis(materials: list) -> str | None:
```

**5 层递进提取策略**:

| 层级 | 提取方式 | 行号 |
|------|---------|------|
| 1 | 带圈编号项提取（①②③...），含页码污染检测与跳过 | 1046-1103 |
| 2 | 数字编号格式（1.xxx；2.xxx...），检查序号连续性 | 1112-1136 |
| 3 | 分号/句号分隔的段落式结论 | 1138-1151 |
| 4 | 简单兜底：取标签后到句号/换行的整段 | 1153-1161 |
| 5 | 出院诊断兜底：筛选含死亡/衰竭关键词的条目 | 1163-1197 |

**优先类别顺序**:
```python
_DEATH_DIAG_PRIORITY_CATEGORIES = ["appraisal", "medical_record", "death_certificate"]
```

**11 种诊断标签**（按优先级排序）:
```python
_DIAG_LABELS = [
    r'死亡诊断意见[：:]\s*',
    r'死亡诊断[：:]\s*',
    r'尸检诊断[：:]\s*',
    r'解剖诊断[：:]\s*',
    r'病理诊断[：:]\s*',
    r'死因分析[：:]\s*',
    r'死亡原因分析[：:]\s*',
    r'死亡原因[：:]\s*',
    r'鉴定意见[：:]\s*',
    r'鉴定结论[：:]\s*',
    r'检验结果[：:]\s*',
]
```

**兜底关键词**:
```python
_DEATH_KEYWORDS = re.compile(
    r'死亡|衰竭|濒死|无效|心跳骤停|呼吸骤停|循环衰竭|多器官功能衰竭|肺栓塞'
)
```

### A.2 LLM 增强 (`_extract_document_slots` 中的 death 分支)

**case_specific_note**（行 537-544）:
```python
case_specific_note = (
    "【死亡案件特别注意】\n"
    "1. 患者已死亡，需要从死亡证明/尸检报告/病历中提取完整死亡诊断\n"
    "2. 死亡诊断必须从住院病历或尸检报告/司法鉴定意见书中提取完整编号列举式诊断\n"
    "3. 不要使用死亡证明书上的简略'死亡原因'，那不是完整的死亡诊断\n"
    "4. adverse_outcome应包含死亡经过及具体时间\n"
)
```

**death_section**（行 546-552）:
```python
death_section = (
    "\n### 九、死亡信息（仅死亡案件）\n"
    "- death_date: 死亡日期\n"
    "- death_diagnosis: 完整死亡诊断（重要：必须从住院病历或尸检报告...格式。）\n"
)
```

### A.3 校验逻辑 (`_validate_extracted_data` 中 death 分支)

**行 1532-1536**:
```python
if case_type == "death":
    if not data.get("death_date"):
        issues.append("死亡案件缺少死亡日期")
    if not data.get("death_diagnosis"):
        issues.append("死亡案件缺少死亡诊断")
```

### A.4 结论模板 (`_generate_conclusion` 中 death 分支)

**行 864-872**:
```python
if case_type == "death":
    return (
        f"综上所述，被告{defendant_name}在为患者{patient_name}提供诊疗服务过程中，"
        f"未尽到注意及相应的诊疗义务，违反诊疗常规、疏忽大意，"
        f"并由此造成了患者死亡的严重损害后果，"
        f"给原告及其家庭造成了巨大的物质损害及带来了极大的精神痛苦。"
        f"因此，为维护原告的合法权益，特根据《中华人民共和国民法典》"
        f"《中华人民共和国民事诉讼法》等有关规定将本案诉至人民法院，望贵院依法裁判。"
    )
```

### A.5 段落注入 (`_generate_facts_paragraph` 中 paragraph_2)

**行 785-800**:
```python
# 死亡案件加死亡信息
death_date = extracted_data.get("death_date", "")
death_diag = extracted_data.get("death_diagnosis", "")
if death_date:
    context_parts.append(f"【死亡信息】死亡日期：{death_date}，死亡诊断：{death_diag}")
appraisal = extracted_data.get("appraisal_details", {})
conclusion_original = appraisal.get("appraisal_conclusion_original", "")
if conclusion_original:
    context_parts.append(f"【鉴定结论原文（请逐字引用，不要改写）】{conclusion_original}")
```

### A.6 要件配置 (`DEFAULT_REQUIREMENTS` 中 death 条目)

| category | is_required | death 特殊说明 |
|----------|------------|---------------|
| identity_id_card | True | 原告身份证正反面 |
| identity_hukou | False | 户口本 |
| identity_other | False | 出生医学证明等 |
| identity_defendant | True | 被告身份信息 |
| **death_certificate** | **True** | **死亡案件独有** |
| medical_record | True | 病历资料 |
| appraisal | False | 死因鉴定 |
| fee_receipt | True | 医疗费用票据 |
| other_evidence | False | 其他 |

---

## 附录 B: 当前三种案件类型实现差距对比

```
                          death                injury              neonatal
                          ─────                ──────              ────────
Step 1.5 定向提取         ═══════════════      ─────────────       ─────────────
                         _direct_extract_     (无等价函数)         (无等价函数)
                         death_diagnosis()
                         5层递进+兜底

Step 1 LLM增强           ═══════════════      ══════════════      ══════════════
  case_specific_note     4条death提示          4条injury提示        7条neonatal提示
  专属Slot段落            death_section ✅      (无) ❌              (无) ❌
  appraisal_note         cause_of_death        disability_level     disability_level
  system_prompt          死亡诊断完整提取       (无特殊)             Apgar逐项提取

Step 1.8 校验             ══════               ──────               ──
  必填检查                death_date ✅          (无) ❌              is_minor=True ✅
                         death_diagnosis ✅                          (缺Apgar/HIE) ❌

Step 2 段落注入           ══════════           ────────             ────────
  paragraph_2专属         注入死亡信息 ✅        (无) ❌              (无) ❌
                         注入鉴定结论原文 ✅

Step 3 结论模板           ══════               ══                   ══
  conclusion_text        "患者死亡" ✅          "患者伤残" ✅         "新生儿损害" ✅
  专属增强               死亡信息描述 ✅         (无等级描述) ❌       (无HIE描述) ❌

═══ = 完整实现   ─── = 缺失/不完整
```

---

## 附录 C: 全部可调配置项清单

### C.1 Celery 相关

| 环境变量 | 代码配置项 | 默认值 | 说明 |
|---------|-----------|-------|------|
| `CELERY_QUEUE_NAME` | `settings.celery_queue_name` | `"scanstruct"` | 队列名 |
| `CELERY_TASK_TIMEOUT_SECONDS` | `settings.celery_task_timeout_seconds` | `7200` (2h) | 任务硬超时 |

### C.2 LLM 限流相关

| 环境变量 | 代码配置项 | 默认值 |
|---------|-----------|-------|
| `LLM_RATE_LIMITER_TEXT` | `settings.llm_rate_limiter_text` | `5` |
| `LLM_RATE_LIMITER_OCR` | `settings.llm_rate_limiter_ocr` | `10` |
| `LLM_RATE_LIMITER_FLASH` | `settings.llm_rate_limiter_flash` | `15` |
| `LLM_RETRY_MAX` | `settings.llm_retry_max` | `3` |
| `LLM_RETRY_BASE_DELAY` | `settings.llm_retry_base_delay` | `2.0` |

### C.3 LLM 上下文限制

| 环境变量 | 代码配置项 | 默认值 |
|---------|-----------|-------|
| `LLM_CONTEXT_MATERIAL_DETAIL_LIMIT` | `settings.llm_context_material_detail_limit` | `12000` |
| `LLM_CONTEXT_MATERIAL_NORMAL_LIMIT` | `settings.llm_context_material_normal_limit` | `5000` |
| `LLM_CONTEXT_MERGED_LIMIT` | `settings.llm_context_merged_limit` | `60000` |
| `LLM_CONTEXT_SLOT_LIMIT` | `settings.llm_context_slot_limit` | `15000` |

### C.4 百炼 OCR 相关

| 环境变量 | 代码配置项 | 默认(Docker) | 说明 |
|---------|-----------|-------------|------|
| `BAILIAN_OCR_MAX_CONCURRENT` | `settings.bailian_ocr_max_concurrent` | 25(10) | OCR并发线程数 |
| `BAILIAN_OCR_TIMEOUT` | `settings.bailian_ocr_timeout` | `120` | OCR请求超时(秒) |
| `BAILIAN_OCR_MAX_RPS` | `settings.bailian_ocr_max_rps` | `25.0` | OCR每秒最大请求数 |
| `BAILIAN_OCR_RETRY_MAX` | `settings.bailian_ocr_retry_max` | `3` | OCR最大重试次数 |
| `BAILIAN_TEXT_MAX_CONCURRENT` | `settings.bailian_text_max_concurrent` | `5` | 文本模型并发数 |
| `BAILIAN_TEXT_TIMEOUT` | `settings.bailian_text_timeout` | `60` | 文本模型超时(秒) |

### C.5 数据库相关

| 环境变量 | 代码配置项 | 默认(Docker) | 说明 |
|---------|-----------|-------------|------|
| `DB_POOL_SIZE` | `settings.db_pool_size` | 10(5) | API连接池大小 |
| `DB_POOL_MAX_OVERFLOW` | `settings.db_pool_max_overflow` | 20(10) | 连接池最大溢出 |

### C.6 回调/重试

| 环境变量 | 代码配置项 | 默认值 |
|---------|-----------|-------|
| `CALLBACK_TIMEOUT_SECONDS` | `settings.callback_timeout_seconds` | `10` |
| `CALLBACK_RETRY_DELAYS` | `settings.callback_retry_delays` | `[10, 30, 60]` |
| `MAX_RETRY_COUNT` | `settings.max_retry_count` | `3` |

### C.7 Docker 资源限制

| 服务 | 内存上限 | 内存预留 | tmpfs |
|------|---------|---------|-------|
| postgres | 512M | 256M | — |
| redis | 192M | 64M | — |
| minio | 512M | 256M | — |
| api | 1G | 512M | /tmp:512M |
| worker | 2G | 512M | /tmp:512M |

---

> **文档结束** — 等待 GLM 模型恢复后启动实施 🚀
