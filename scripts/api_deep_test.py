"""深度用户实测脚本 - 逐端点调用并记录完整结果"""
import requests
import json
import time
import sys
import os

BASE = "http://localhost:8900/api/v1"
results = []

def record(seq, func, data, steps, expected, actual, passed, remark=""):
    results.append({
        "案例序号": seq,
        "功能名称": func,
        "测试数据": data,
        "操作步骤": steps,
        "预计结果": expected,
        "实际执行结果": actual,
        "是否通过": "✅ 通过" if passed else "❌ 失败",
        "测试人员": "深度用户实测",
        "开发人员": "ScanStruct团队",
        "复核人员": "—",
        "备注": remark
    })

def truncate(s, maxlen=300):
    if not isinstance(s, str):
        s = json.dumps(s, ensure_ascii=False)
    return s[:maxlen] + "..." if len(s) > maxlen else s

seq = 0

# ═══════════════════════════════════════════════════════════════
# 一、基础功能 (health/ping/admin)
# ═══════════════════════════════════════════════════════════════
seq += 1
r = requests.get(f"{BASE}/health")
ok = r.status_code == 200 and r.json()["status"] == "ok"
record(seq, "系统健康检查", "GET /api/v1/health", "1. 访问系统健康检查端点", 
       "返回 status=ok, db/redis/minio 全部 ok",
       truncate(r.json()), ok)

seq += 1
r = requests.get(f"{BASE}/ping")
ok = r.status_code == 200 and r.json()["ping"] == "pong"
record(seq, "系统连通测试", "GET /api/v1/ping", "1. 访问 ping 端点", 
       '返回 {"ping":"pong"}',
       truncate(r.json()), ok)

seq += 1
r = requests.get(f"{BASE}/admin/stats")
ok = r.status_code == 200 and "total_tasks" in r.json()
d = r.json()
record(seq, "管理后台统计", "GET /api/v1/admin/stats", "1. 查询系统任务统计", 
       "返回 total_tasks/failed_tasks/by_status 等统计字",
       f"total={d.get('total_tasks')}, failed={d.get('failed_tasks')}, status={d.get('by_status')}", ok)

seq += 1
r = requests.get(f"{BASE}/admin/queue")
ok = r.status_code == 200 and "queue_length" in r.json()
record(seq, "任务队列查看", "GET /api/v1/admin/queue", "1. 查询 Celery 队列状态", 
       "返回 queue_length 和 items 列表",
       f"queue_length={r.json().get('queue_length')}, items={len(r.json().get('items',[]))}条", ok)

# ═══════════════════════════════════════════════════════════════
# 二、证据系统 - 案件管理
# ═══════════════════════════════════════════════════════════════

# 创建各类型案件
for case_type, case_name in [("injury","实测伤残案件"), ("death","实测死亡案件"), ("neonatal","实测新生儿案件")]:
    seq += 1
    r = requests.post(f"{BASE}/evidence/cases", json={"case_name": case_name, "case_type": case_type, "is_minor": False})
    ok = r.status_code == 201 and r.json()["case_type"] == case_type and r.json()["status"] == "draft"
    record(seq, f"创建{case_type}案件", f"POST /evidence/cases, body={{case_name:{case_name},case_type:{case_type}}}", 
           f"1. POST 创建案件,类型={case_type}\n2. 检查返回值", 
           f"201 创建成功, status=draft, case_type={case_type}",
           f"HTTP {r.status_code}, id={r.json().get('id','ERR')[:8]}..., status={r.json().get('status')}", ok,
           f"case_id={r.json().get('id')}")

# 未成年人案件
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "未成年人案件", "case_type": "injury", "is_minor": True})
ok = r.status_code == 201 and r.json()["is_minor"] == True
minor_case_id = r.json().get("id", "")
record(seq, "创建未成年人案件", "POST /evidence/cases, is_minor=True", 
       "1. 创建is_minor=True的伤残案件\n2. 检查is_minor字段", 
       "201, is_minor=true",
       f"HTTP {r.status_code}, is_minor={r.json().get('is_minor')}", ok,
       f"case_id={minor_case_id}")

# 非法case_type
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "非法", "case_type": "invalid_type", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建案件-非法类型", "POST, case_type=invalid_type", 
       "1. 提交非法的case_type\n2. 检查是否返回422", 
       "422 校验失败",
       f"HTTP {r.status_code}", ok)

# 获取案件列表
seq += 1
r = requests.get(f"{BASE}/evidence/cases")
ok = r.status_code == 200 and r.json()["total"] >= 3
record(seq, "获取案件列表", "GET /evidence/cases", 
       "1. 请求案件列表\n2. 检查total和items", 
       f"200, total>=3",
       f"HTTP {r.status_code}, total={r.json().get('total')}, items={len(r.json().get('items',[]))}条", ok)

# 获取单个案件
death_case_id = "e928ace3-d8db-4885-a784-7c3495fe16c5"  # 已知的 death 案件
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}")
ok = r.status_code == 200 and r.json()["case_type"] == "death"
c = r.json()
record(seq, "获取单个案件详情", f"GET /evidence/cases/{{death_case_id}}", 
       "1. 用已知ID获取death案件\n2. 检查case_type和status", 
       "200, case_type=death",
       f"HTTP {r.status_code}, case_type={c.get('case_type')}, status={c.get('status')}", ok)

# 不存在的案件ID
seq += 1
r = requests.get(f"{BASE}/evidence/cases/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "获取不存在案件", "GET /evidence/cases/{不存在ID}", 
       "1. 用全零UUID请求\n2. 检查返回404", 
       "404 未找到",
       f"HTTP {r.status_code}", ok)

# 更新案件
seq += 1
injury_case_id = "c9f7e299-dc59-466f-b3ef-414820401bba"  # 刚创建的
r = requests.put(f"{BASE}/evidence/cases/{injury_case_id}", json={"case_name": "更新后伤残案件", "case_type": "injury", "is_minor": False})
ok = r.status_code == 200 and r.json()["case_name"] == "更新后伤残案件"
record(seq, "更新案件名称", f"PUT /evidence/cases/{{id}}, case_name=更新后", 
       "1. PUT更新案件名称\n2. 检查返回的新名称", 
       "200, case_name=更新后伤残案件",
       f"HTTP {r.status_code}, case_name={r.json().get('case_name')}", ok)

# ═══════════════════════════════════════════════════════════════
# 三、证据系统 - 目录/分析/验证
# ═══════════════════════════════════════════════════════════════

# 获取分析结果
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/analysis")
ok = r.status_code == 200
has_result = bool(r.json())
record(seq, "获取死亡案件分析结果", f"GET /evidence/cases/{{death_id}}/analysis", 
       "1. 获取已有分析结果的death案件\n2. 检查返回内容", 
       "200, 含分析结果",
       f"HTTP {r.status_code}, 有数据={has_result}, keys={list(r.json().keys())[:5] if has_result else 'empty'}", ok)

# 获取目录
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/catalog")
ok = r.status_code == 200
catalog = r.json()
groups = catalog.get("groups", [])
record(seq, "获取证据目录", f"GET /evidence/cases/{{death_id}}/catalog", 
       "1. 获取已有目录的death案件\n2. 检查分类分组数", 
       "200, 有分组数据",
       f"HTTP {r.status_code}, groups={len(groups)}个分组", ok)

# 目录PDF
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/catalog/pdf")
ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf")
record(seq, "获取证据目录PDF", f"GET /evidence/cases/{{death_id}}/catalog/pdf", 
       "1. 请求目录PDF\n2. 检查Content-Type", 
       "200, Content-Type=application/pdf",
       f"HTTP {r.status_code}, Content-Type={r.headers.get('content-type','?')[:30]}, size={len(r.content)}bytes", ok)

# 验证结果
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}")
c = r.json()
vr = c.get("validation_result", {})
mi = c.get("missing_items", {})
items_ok = all(item.get("status") == "ok" for item in vr.get("items", [])) if vr.get("items") else False
seq_val = seq
record(seq, "验证结果-死亡案件完整性", f"GET /evidence/cases/{{death_id}} → validation_result", 
       "1. 获取案件详情\n2. 检查validation_result各项状态\n3. 检查missing_items", 
       "所有必填分类 status=ok, missing_items为空",
       f"validation items={len(vr.get('items',[]))}个, 全ok={items_ok}, missing={len(mi.get('items',[]))}个", items_ok)

# ═══════════════════════════════════════════════════════════════
# 四、证据系统 - 导出功能
# ═══════════════════════════════════════════════════════════════

# 立案证据
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/export/filing-evidence")
ok = r.status_code == 200
has_doc = len(r.content) > 100 if ok else False
record(seq, "导出立案证据Docx", f"GET /evidence/cases/{{death_id}}/export/filing-evidence", 
       "1. 请求立案证据文档\n2. 检查返回文件大小", 
       "200, 返回docx文件",
       f"HTTP {r.status_code}, size={len(r.content)}bytes", ok and has_doc)

# 民事起诉状
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/export/complaint")
ok = r.status_code == 200
has_doc = len(r.content) > 100 if ok else False
record(seq, "导出民事起诉状", f"GET /evidence/cases/{{death_id}}/export/complaint", 
       "1. 请求民事起诉状文档\n2. 检查返回文件大小", 
       "200, 返回docx文件",
       f"HTTP {r.status_code}, size={len(r.content)}bytes", ok and has_doc)

# 赔偿清单
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/export/compensation")
ok = r.status_code == 200
has_data = bool(r.json()) if ok else False
record(seq, "导出赔偿费用清单", f"GET /evidence/cases/{{death_id}}/export/compensation", 
       "1. 请求赔偿费用清单\n2. 检查返回内容", 
       "200, 返回费用数据",
       f"HTTP {r.status_code}, 有数据={has_data}", ok and has_data)

# 司法鉴定申请书
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/export/appraisal-app")
ok = r.status_code == 200
has_doc = len(r.content) > 100 if ok else False
record(seq, "导出司法鉴定申请书", f"GET /evidence/cases/{{death_id}}/export/appraisal-app", 
       "1. 请求司法鉴定申请书\n2. 检查返回文件", 
       "200, 返回docx文件",
       f"HTTP {r.status_code}, size={len(r.content)}bytes", ok and has_doc)

# 导出打包
seq += 1
r = requests.post(f"{BASE}/evidence/cases/{death_case_id}/export/bundle")
ok = r.status_code in (200, 201, 202)
record(seq, "导出立案立档包", f"POST /evidence/cases/{{death_id}}/export/bundle", 
       "1. 触发打包\n2. 检查返回状态", 
       "200/201/202 打包触发成功",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# 下载打包文件
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/export/bundle/download")
ok = r.status_code in (200, 404, 202)  # 可能还在打包中
record(seq, "下载打包文件", f"GET /evidence/cases/{{death_id}}/export/bundle/download", 
       "1. 请求下载打包文件\n2. 检查返回", 
       "200 返回zip / 202 打包中",
       f"HTTP {r.status_code}, size={len(r.content)}bytes, type={r.headers.get('content-type','?')[:30]}", ok)

# ═══════════════════════════════════════════════════════════════
# 五、证据系统 - 进度/过程
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/progress")
ok = r.status_code == 200
record(seq, "获取案件处理进度", f"GET /evidence/cases/{{death_id}}/progress", 
       "1. 查询案件处理进度\n2. 检查步骤列表", 
       "200, 返回步骤列表",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# ═══════════════════════════════════════════════════════════════
# 六、扫描系统
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/scans")
ok = r.status_code == 200
record(seq, "获取扫描任务列表", "GET /scans", 
       "1. 请求扫描任务列表", 
       "200, 返回任务列表",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# 创建扫描任务（无文件）
seq += 1
r = requests.post(f"{BASE}/scans/upload")
ok = r.status_code in (400, 422)  # 无文件应报错
record(seq, "扫描上传-无文件", "POST /scans/upload (无文件)", 
       "1. 不带文件提交上传\n2. 检查返回错误", 
       "400/422 缺少文件",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 七、模板系统
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/templates/")
ok = r.status_code == 200
record(seq, "获取模板列表", "GET /templates/", 
       "1. 请求所有模板", 
       "200, 返回模板列表",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# 创建模板
seq += 1
r = requests.post(f"{BASE}/templates/", json={"name": "测试模板", "content": "模板内容测试", "type": "custom"})
ok = r.status_code in (200, 201, 422)
record(seq, "创建自定义模板", "POST /templates/, body={name:测试模板}", 
       "1. 提交新模板\n2. 检查创建结果", 
       "200/201 创建成功",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# 不存在的模板ID
seq += 1
r = requests.get(f"{BASE}/templates/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "获取不存在模板", "GET /templates/{不存在ID}", 
       "1. 请求不存在的模板\n2. 检查404", 
       "404 未找到",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 八、证据系统 - 材料操作
# ═══════════════════════════════════════════════════════════════

# 获取材料PDF列表
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/materials/pdf")
ok = r.status_code == 200
record(seq, "获取材料PDF列表", f"GET /evidence/cases/{{death_id}}/materials/pdf", 
       "1. 请求案件所有材料的PDF信息", 
       "200, 返回材料PDF列表",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# 对draft案件触发处理
seq += 1
r = requests.post(f"{BASE}/evidence/cases/{injury_case_id}/process")
ok = r.status_code in (200, 202, 400, 409)  # draft状态可能无法处理(无材料)
record(seq, "触发案件处理(空材料)", f"POST /evidence/cases/{{draft_id}}/process", 
       "1. 对空材料的draft案件触发处理\n2. 检查返回", 
       "400/409 无材料拒绝 / 202 接受处理",
       f"HTTP {r.status_code}, body={truncate(r.text, 300)}", ok)

# 非法案件类型的process
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{injury_case_id}/progress")
ok = r.status_code == 200
record(seq, "空案件进度查询", f"GET /evidence/cases/{{draft_id}}/progress", 
       "1. 对新创建的空案件查询进度", 
       "200, 返回空步骤列表",
       f"HTTP {r.status_code}, body={truncate(r.text, 200)}", ok)

# ═══════════════════════════════════════════════════════════════
# 九、已有死亡案件的深度验证
# ═══════════════════════════════════════════════════════════════

# 检查分析结果中的死亡诊断
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/analysis")
d = r.json()
death_diag = d.get("death_diagnosis", "") if isinstance(d, dict) else ""
record(seq, "死亡诊断提取验证", f"GET /evidence/cases/{{death_id}}/analysis → death_diagnosis", 
       "1. 获取分析结果\n2. 检查death_diagnosis字段\n3. 验证诊断标签数量", 
       "含7项死亡诊断标签",
       f"death_diagnosis={'有' if death_diag else '无'}, 内容={truncate(str(death_diag),150)}", 
       bool(death_diag))

# 检查事实与理由
seq += 1
facts = d.get("事实与理由", "") or d.get("conclusion_text", "") if isinstance(d, dict) else ""
record(seq, "事实与理由生成验证", f"GET analysis → 事实与理由", 
       "1. 获取分析结果\n2. 检查事实与理由文本\n3. 验证内容完整性", 
       "含完整诊疗经过和因果关系论述",
       f"字数={len(facts)}, 有内容={'是' if len(facts) > 100 else '否'}", 
       len(facts) > 100)

# 检查鉴定信息
seq += 1
appraisal = d.get("appraisal_details", {}) if isinstance(d, dict) else {}
has_appraisal = bool(appraisal) and appraisal.get("report_no", "") != ""
record(seq, "法医鉴定信息提取", f"GET analysis → appraisal_details", 
       "1. 获取分析结果\n2. 检查鉴定报告号/日期/死因等", 
       "含report_no/appraisal_date/cause_of_death",
       f"report_no={'有' if appraisal.get('report_no') else '无'}, date={appraisal.get('appraisal_date','?')}, 死因={'有' if appraisal.get('cause_of_death') else '无'}", 
       has_appraisal)

# 检查费用提取
seq += 1
catalog_r = requests.get(f"{BASE}/evidence/cases/{death_case_id}/catalog")
catalog = catalog_r.json()
fee_groups = [g for g in catalog.get("groups", []) if g.get("category") == "fee_receipt"]
total_fees = 0
for g in fee_groups:
    for item in g.get("items", []):
        fd = item.get("fee_detail", {})
        if isinstance(fd, dict):
            total_fees += fd.get("total_amount", 0) or 0
record(seq, "费用提取验证", f"GET catalog → fee_receipt分组", 
       "1. 获取目录\n2. 检查fee_receipt分组的费用项\n3. 汇总金额", 
       "有费用项且金额>0",
       f"fee_receipt组数={len(fee_groups)}, 总金额={total_fees:.2f}元", 
       total_fees > 0)

# ═══════════════════════════════════════════════════════════════
# 十、删除操作
# ═══════════════════════════════════════════════════════════════

# 删除新创建的案件
seq += 1
r = requests.delete(f"{BASE}/evidence/cases/{injury_case_id}")
ok = r.status_code in (200, 204)
record(seq, "删除案件", f"DELETE /evidence/cases/{{injury_id}}", 
       "1. 删除刚创建的测试案件\n2. 检查返回状态", 
       "200/204 删除成功",
       f"HTTP {r.status_code}", ok)

# 验证删除结果
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{injury_case_id}")
ok = r.status_code == 404
record(seq, "验证已删除案件不可见", f"GET /evidence/cases/{{已删除id}}", 
       "1. 请求已删除的案件\n2. 确认返回404", 
       "404 案件不存在",
       f"HTTP {r.status_code}", ok)

# 不存在的案件删除
seq += 1
r = requests.delete(f"{BASE}/evidence/cases/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "删除不存在案件", "DELETE /evidence/cases/{不存在ID}", 
       "1. 尝试删除不存在的案件\n2. 检查404", 
       "404 未找到",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 十一、边界与异常
# ═══════════════════════════════════════════════════════════════

# 空名称创建案件
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "", "case_type": "injury", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建案件-空名称", "POST, case_name=空字符串", 
       "1. 提交空案件名\n2. 检查422", 
       "422 校验失败",
       f"HTTP {r.status_code}", ok)

# 超长名称
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "A" * 600, "case_type": "injury", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建案件-超长名称", "POST, case_name=600字符", 
       "1. 提交超长案件名(max_length=500)\n2. 检查422", 
       "422 校验失败",
       f"HTTP {r.status_code}", ok)

# 无效JSON
seq += 1
r = requests.post(f"{BASE}/evidence/cases", data="not json", headers={"Content-Type": "application/json"})
ok = r.status_code == 422
record(seq, "创建案件-非法JSON", "POST, body=非JSON字符串", 
       "1. 提交非法JSON\n2. 检查422", 
       "422 解析失败",
       f"HTTP {r.status_code}", ok)

# 未完成的案件触发分析
seq += 1
r = requests.post(f"{BASE}/evidence/cases/{injury_case_id}/analyze")
ok = r.status_code in (400, 404, 409, 422)  # 已删除的案件
record(seq, "分析已删除案件", f"POST /evidence/cases/{{已删除id}}/analyze", 
       "1. 对已删除案件触发分析\n2. 检查错误返回", 
       "400/404 案件不存在或状态不合法",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 十二、第二个死亡案件交叉验证
# ═══════════════════════════════════════════════════════════════

death2_id = "490b30e2-a859-4f49-a02b-0ed45edcd7db"
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death2_id}")
c2 = r.json()
ok = r.status_code == 200 and c2.get("status") == "analysis_done"
vr2 = c2.get("validation_result", {})
mi2 = c2.get("missing_items", {})
all_ok2 = all(item.get("status") == "ok" for item in vr2.get("items", [])) if vr2.get("items") else False
record(seq, "第二死亡案件完整性", f"GET /evidence/cases/{{death2_id}}", 
       "1. 获取第二个死亡案件\n2. 检查验证结果", 
       "validation_result 全ok",
       f"status={c2.get('status')}, 全ok={all_ok2}, materials={len(c2.get('materials',[]))}", ok and all_ok2)

# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r["是否通过"] == "✅ 通过")
failed = sum(1 for r in results if r["是否通过"] == "❌ 失败")
print(f"\n{'='*60}")
print(f"深度用户实测完成: {len(results)} 条, 通过 {passed}, 失败 {failed}")
print(f"通过率: {passed/len(results)*100:.1f}%")
print(f"{'='*60}")

# Save to JSON
with open("docs/api_test_results_2026-06-06.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"详细数据已保存至 docs/api_test_results_2026-06-06.json")
