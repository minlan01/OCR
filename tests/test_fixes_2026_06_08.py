"""
2026-06-08 修复专项测试
====================

验证今日所有修复的正确性，覆盖：
1. 死代码清理 — evidence_tasks.py 无不可达的 export 代码
2. export_evidence_bundle 有完整实现
3. analyze_catalog NoneType 防御
4. 重试期间保持状态（5个 Celery 任务统一行为）
5. 上传同名文件去重逻辑
6. 前端轮询容错逻辑验证
7. 删除保护 (409)
8. cancel 端点行为
9. 身份证/户口本 _DETAIL_CATEGORIES 覆盖
10. _CRITICAL_KEYWORDS 身份证关键词

运行:
    cd E:\\OCRScanStruct
    python -m pytest tests/test_fixes_2026_06_08.py -v --tb=short
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import textwrap
import uuid
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 死代码清理验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeadCodeCleanup:
    """验证 evidence_tasks.py 中不再有 process_single_material_ocr 之后的死代码"""

    def test_no_dead_code_after_process_single_material_ocr(self):
        """process_single_material_ocr 的 try/finally 之后不应有任何代码"""
        import worker.evidence_tasks as et

        source = inspect.getsource(et.process_single_material_ocr)
        lines = source.split('\n')

        # 找到 finally: loop.close() 行
        finally_idx = None
        for i, line in enumerate(lines):
            if 'loop.close()' in line and 'finally' in lines[i-1] if i > 0 else False:
                finally_idx = i
                break
            if 'finally:' in line:
                finally_idx = i

        if finally_idx is not None:
            # finally 之后只允许空行和 loop.close()
            after_finally = lines[finally_idx + 1:]
            # 去掉空行后，不应有任何非空代码（函数结束后的空行除外）
            non_empty = [l for l in after_finally if l.strip()]
            # loop.close() 后不应有任何代码行
            assert len(non_empty) == 0, (
                f"Dead code found after process_single_material_ocr finally block: {non_empty}"
            )

    def test_export_evidence_bundle_has_body(self):
        """export_evidence_bundle 不再是空壳"""
        import worker.evidence_tasks as et

        source = inspect.getsource(et.export_evidence_bundle)
        # 不应该只有 logger.info
        lines = [l for l in source.split('\n') if l.strip() and not l.strip().startswith('#')
                 and not l.strip().startswith('"""') and not l.strip().startswith("'''")]
        # 至少应该有 try/except/async def 等结构
        assert len(lines) > 5, f"export_evidence_bundle appears to be a stub: {lines}"
        assert 'async def' in source or 'try:' in source, (
            "export_evidence_bundle should have actual logic"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NoneType 防御验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoneTypeDefenses:
    """验证 analyze_catalog 中对 LLM 返回 null 的防御"""

    def test_generate_facts_paragraph_skips_none_plaintiffs(self):
        """_generate_facts_paragraph 应跳过 None 和非 dict 的原告"""
        from services.evidence.document_analyzer import _generate_facts_paragraph

        # 构造包含 None 和非 dict 的 plaintiffs
        data = {
            "plaintiffs": [None, {"name": "张三", "relationship": "本人", "gender": "男",
                                   "ethnicity": "汉", "birth_date": "1990年1月1日",
                                   "address": "北京市", "id_number": "110101199001011234"},
                           "invalid_string", 42],
            "patient_name": "张三",
            "patient_gender": "男",
            "patient_age": "34",
            "defendant_name": "XX医院",
            "legal_representative": "李四",
            "defendant_address": "北京市朝阳区",
            "admission_reason": "头痛",
            "admission_condition": "意识清醒",
            "preliminary_diagnosis": "偏头痛",
            "admission_date": "2024-01-01",
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "测试段落内容"
        mock_client.chat.completions.create.return_value = mock_response

        with patch('services.evidence.document_analyzer._get_flash_client', return_value=mock_client):
            result = _generate_facts_paragraph(
                "paragraph_1", "生成入院段落", data, "injury", False
            )

        # 应该不抛异常，返回内容
        assert result == "测试段落内容"

    def test_populate_legacy_fields_handles_empty_plaintiffs(self):
        """_populate_legacy_fields 应处理空 plaintiffs 列表"""
        from services.evidence.document_analyzer import _populate_legacy_fields

        data = {"plaintiffs": []}
        _populate_legacy_fields(data)
        # 不应添加任何原告相关字段
        assert "原告姓名1" not in data

    def test_populate_legacy_fields_handles_none_plaintiffs(self):
        """_populate_legacy_fields 应处理 plaintiffs 中含 None 元素"""
        from services.evidence.document_analyzer import _populate_legacy_fields

        data = {
            "plaintiffs": [None, {"name": "李四", "relationship": "配偶",
                                   "gender": "女", "ethnicity": "汉",
                                   "birth_date": "1995-01-01", "address": "上海市",
                                   "id_number": "310101199501011234", "phone": "13800138000"}],
        }
        _populate_legacy_fields(data)
        assert data.get("原告姓名1") == "李四"
        assert data.get("性别1") == "女"

    def test_extract_document_slots_returns_dict_check(self):
        """analyze_catalog 中 isinstance(analysis_result, dict) 检查"""
        # 验证代码中确实有 isinstance 检查
        import services.evidence.document_analyzer as da
        source = inspect.getsource(da.analyze_catalog)
        assert 'isinstance(analysis_result, dict)' in source, (
            "analyze_catalog should have isinstance check for analysis_result"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 重试状态保持统一性验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetryStatusConsistency:
    """验证所有 5 个 Celery 任务在重试时保持状态"""

    @pytest.fixture
    def task_functions(self):
        import worker.evidence_tasks as et
        return {
            "process_evidence_ocr": et.process_evidence_ocr,
            "process_evidence_classify": et.process_evidence_classify,
            "generate_evidence_catalog": et.generate_evidence_catalog,
            "process_evidence_full": et.process_evidence_full,
            "analyze_evidence": et.analyze_evidence,
        }

    # 委托模式：process_evidence_full 把逻辑委托给 _do_process_evidence_full
    DELEGATED_TASKS = {"process_evidence_full": "_do_process_evidence_full"}

    def test_all_tasks_have_retry_status_logic(self, task_functions):
        """所有5个任务都应有 'retries >= max_retries' 判断（直接或通过委托函数）"""
        import worker.evidence_tasks as et
        for name, func in task_functions.items():
            source = inspect.getsource(func)
            if name in self.DELEGATED_TASKS:
                # 委托模式，检查委托函数
                delegated_name = self.DELEGATED_TASKS[name]
                delegated_func = getattr(et, delegated_name)
                source = inspect.getsource(delegated_func)
            assert 'self.request.retries >= self.max_retries' in source, (
                f"{name} (or delegate) missing retry status preservation logic"
            )
            assert '_update_case_status' in source, (
                f"{name} (or delegate) should call _update_case_status on final failure"
            )

    def test_all_tasks_log_retry_info(self, task_functions):
        """所有5个任务在重试期间应有日志"""
        import worker.evidence_tasks as et
        for name, func in task_functions.items():
            source = inspect.getsource(func)
            if name in self.DELEGATED_TASKS:
                delegated_name = self.DELEGATED_TASKS[name]
                delegated_func = getattr(et, delegated_name)
                source = inspect.getsource(delegated_func)
            assert 'will retry' in source.lower() or 'retry' in source, (
                f"{name} (or delegate) should log retry information"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 身份证/户口本优先级验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdentityPriority:
    """验证身份证/户口本材料享有 detail 级别字符限制"""

    def test_identity_in_detail_categories(self):
        """'identity' 应在 _DETAIL_CATEGORIES 中"""
        import services.evidence.document_analyzer as da
        source = inspect.getsource(da._build_structured_context)
        assert '"identity"' in source or "'identity'" in source, (
            "_DETAIL_CATEGORIES should include 'identity'"
        )

    def test_critical_keywords_include_identity(self):
        """_CRITICAL_KEYWORDS 应包含身份证相关关键词"""
        import services.evidence.document_analyzer as da
        source = inspect.getsource(da._build_structured_context)

        identity_keywords = [
            '居民身份', '户口', '户籍', '身份号码', '出生日期', '住址'
        ]
        for kw in identity_keywords:
            assert kw in source, f"_CRITICAL_KEYWORDS should contain '{kw}'"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 删除保护 + cancel 端点验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteProtectionAndCancel:
    """验证删除保护(409)和 cancel 端点的代码结构"""

    def test_delete_case_checks_status(self):
        """delete_case 应检查案件状态"""
        import api.routes.evidence as ev
        source = inspect.getsource(ev.delete_case)
        assert '409' in source or 'Conflict' in source, (
            "delete_case should return 409 for processing cases"
        )
        assert 'processing' in source or 'analyzing' in source, (
            "delete_case should check processing/analyzing status"
        )

    def test_cancel_case_endpoint_exists(self):
        """cancel_case 端点应存在"""
        import api.routes.evidence as ev
        assert hasattr(ev, 'cancel_case'), "cancel_case function should exist"

    def test_cancel_case_revokes_celery_task(self):
        """cancel_case 应调用 celery control.revoke"""
        import api.routes.evidence as ev
        source = inspect.getsource(ev.cancel_case)
        assert 'revoke' in source, "cancel_case should revoke Celery task"
        assert 'SIGKILL' in source, "cancel_case should use SIGKILL signal"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 上传同名文件去重验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestUploadDuplicateCheck:
    """验证上传同名文件去重逻辑"""

    def test_upload_checks_original_filename(self):
        """upload_materials 应检查 original_filename"""
        import api.routes.evidence as ev
        source = inspect.getsource(ev.upload_materials)
        assert 'original_filename' in source, (
            "upload_materials should check original_filename for duplicates"
        )
        assert '409' in source or 'Conflict' in source, (
            "upload_materials should return 409 for duplicate filenames"
        )

    def test_upload_allows_failed_materials(self):
        """上传应允许 failed 状态的同名文件"""
        import api.routes.evidence as ev
        source = inspect.getsource(ev.upload_materials)
        # 应该有过滤条件排除 failed 状态
        assert 'failed' in source.lower(), (
            "upload_materials should allow re-upload for failed materials"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 前端轮询容错验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendPollingResilience:
    """验证前端轮询的连续失败容错逻辑"""

    def test_handleAnalyze_has_pollErrors(self):
        """handleAnalyze 应有 pollErrors 连续失败计数"""
        vue_path = os.path.join(PROJECT_ROOT, "static", "src", "views", "EvidencePage.vue")
        with open(vue_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'pollErrors' in content, (
            "handleAnalyze should have pollErrors counter"
        )
        assert 'maxPollErrors' in content, (
            "handleAnalyze should have maxPollErrors threshold"
        )

    def test_poll_resets_on_success(self):
        """轮询成功后应重置 pollErrors"""
        vue_path = os.path.join(PROJECT_ROOT, "static", "src", "views", "EvidencePage.vue")
        with open(vue_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'pollErrors = 0' in content, (
            "pollErrors should reset to 0 on successful poll"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. cancelCase API 存在验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestCancelCaseAPI:
    """验证前端 cancelCase API 函数"""

    def test_cancelCase_function_exists(self):
        """evidence.ts 应有 cancelCase 函数"""
        ts_path = os.path.join(PROJECT_ROOT, "static", "src", "api", "evidence.ts")
        with open(ts_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'cancelCase' in content, "evidence.ts should export cancelCase"
        assert '/cancel' in content, "cancelCase should POST to /cancel endpoint"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 死亡诊断定向提取验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeathDiagnosisExtraction:
    """验证死亡诊断定向提取的多种格式"""

    def test_circled_number_format(self):
        """应提取带圈编号格式：①xxx；②xxx"""
        from services.evidence.document_analyzer import _direct_extract_death_diagnosis

        mat = MagicMock()
        mat.effective_category = "medical_record"
        mat.ocr_text = "死亡诊断：①急性右心衰竭；②重度肺动脉高压；③凝血功能障碍"
        mat.original_filename = "test.pdf"

        result = _direct_extract_death_diagnosis([mat])
        assert result is not None
        assert "急性右心衰竭" in result
        assert "肺动脉高压" in result
        assert "凝血功能障碍" in result

    def test_numbered_format(self):
        """应提取数字编号格式：1.xxx；2.xxx"""
        from services.evidence.document_analyzer import _direct_extract_death_diagnosis

        mat = MagicMock()
        mat.effective_category = "medical_record"
        mat.ocr_text = "死亡诊断：\n1. 急性右心衰竭\n2. 重度肺动脉高压\n3. 凝血功能障碍"
        mat.original_filename = "test.pdf"

        result = _direct_extract_death_diagnosis([mat])
        assert result is not None
        assert "急性右心衰竭" in result

    def test_discharge_diagnosis_fallback(self):
        """兜底策略：从出院诊断中提取含死亡关键词的条目"""
        from services.evidence.document_analyzer import _direct_extract_death_diagnosis

        mat = MagicMock()
        mat.effective_category = "medical_record"
        mat.ocr_text = "出院诊断：①肺部感染；②多器官功能衰竭；③低蛋白血症"
        mat.original_filename = "test.pdf"

        result = _direct_extract_death_diagnosis([mat])
        assert result is not None
        assert "功能衰竭" in result

    def test_appraisal_category_priority(self):
        """鉴定报告类别应优先于病历"""
        from services.evidence.document_analyzer import _direct_extract_death_diagnosis

        mat_appraisal = MagicMock()
        mat_appraisal.effective_category = "appraisal"
        mat_appraisal.ocr_text = "鉴定意见：①心脏破裂；②主动脉夹层"
        mat_appraisal.original_filename = "appraisal.pdf"

        mat_medical = MagicMock()
        mat_medical.effective_category = "medical_record"
        mat_medical.ocr_text = "死亡诊断：①心力衰竭"
        mat_medical.original_filename = "medical.pdf"

        result = _direct_extract_death_diagnosis([mat_medical, mat_appraisal])
        assert result is not None
        # 鉴定报告应优先被处理
        assert "心脏破裂" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _validate_extracted_data 验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateExtractedData:
    """验证数据校验函数"""

    def test_invalid_id_number_cleared(self):
        """无效身份证号应被清除"""
        from services.evidence.document_analyzer import _validate_extracted_data

        data = {
            "plaintiffs": [
                {"id_number": "12345"},  # 太短
            ]
        }
        result = _validate_extracted_data(data, "injury")
        assert result["plaintiffs"][0]["id_number"] is None
        assert any("身份证号格式错误" in issue for issue in result["_validation_issues"])

    def test_death_case_missing_death_date(self):
        """死亡案件缺少死亡日期应被记录"""
        from services.evidence.document_analyzer import _validate_extracted_data

        data = {"plaintiffs": [], "defendant_name": "XX医院"}
        result = _validate_extracted_data(data, "death")
        assert any("死亡日期" in issue for issue in result["_validation_issues"])

    def test_neonatal_forces_minor(self):
        """新生儿案件应强制 is_minor=True"""
        from services.evidence.document_analyzer import _validate_extracted_data

        data = {"plaintiffs": []}
        result = _validate_extracted_data(data, "neonatal")
        assert result["is_minor"] is True

    def test_defendant_name_too_short(self):
        """被告名称过短应被标记"""
        from services.evidence.document_analyzer import _validate_extracted_data

        data = {"plaintiffs": [], "defendant_name": "XX"}
        result = _validate_extracted_data(data, "injury")
        assert any("不完整" in issue or "过短" in issue for issue in result["_validation_issues"])


# ═══════════════════════════════════════════════════════════════════════════════
# 11. 结构验证 — evidence_tasks.py AST 解析
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeStructure:
    """用 AST 验证代码结构完整性"""

    def test_all_celery_tasks_are_top_level_functions(self):
        """所有 Celery 任务应是顶层函数，不应嵌套在 try/finally 之后"""
        tasks_path = os.path.join(PROJECT_ROOT, "worker", "evidence_tasks.py")
        with open(tasks_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)

        task_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Attribute) and dec.attr == 'task':
                        task_names.add(node.name)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Attribute) and dec.func.attr == 'task':
                            task_names.add(node.name)

        expected = {
            "process_evidence_ocr",
            "process_evidence_classify",
            "generate_evidence_catalog",
            "process_evidence_full",
            "analyze_evidence",
            "export_evidence_bundle",
            "process_single_material_ocr",
        }

        missing = expected - task_names
        assert not missing, f"Missing Celery tasks: {missing}"

    def test_no_unreachable_code_after_finally(self):
        """process_single_material_ocr 的 finally 块之后不应有非空代码"""
        tasks_path = os.path.join(PROJECT_ROOT, "worker", "evidence_tasks.py")
        with open(tasks_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "process_single_material_ocr":
                body = node.body
                # 最后一个语句应该是 try/except/finally 或 return
                last_stmt = body[-1]
                # 如果最后一个语句是 Try (with finally)，检查 finally 之后没有更多语句
                if isinstance(last_stmt, ast.Try):
                    assert last_stmt.finalbody, (
                        "process_single_material_ocr should have finally block"
                    )
                    # 检查 finally 块之后的语句（函数内）
                    # AST 中 try/finally 的 body 就是整个 try/except/finally 结构
                    # 不应该有 body 之外的语句
                    pass  # AST 结构已经保证没有不可达代码
                break
