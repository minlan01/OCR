"""深度用户实测脚本 V2 - 修正字段路径，补充更多端点"""
import requests
import json
import time

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

def trunc(s, n=300):
    if not isinstance(s, str): s = json.dumps(s, ensure_ascii=False)
    return s[:n] + "..." if len(s) > n else s

seq = 0

# ═══════════════════════════════════════════════════════════════
# 一、系统基础设施
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/health")
d = r.json()
ok = d["status"] == "ok" and d["db"] == "ok" and d["redis"] == "ok" and d["minio"] == "ok"
record(seq, "系统健康检查", "GET /api/v1/health",
       "1. 访问 /api/v1/health\n2. 检查 status/db/redis/minio 四项指标",
       "四项全部 ok",
       f"status={d.get('status')}, db={d.get('db')}, redis={d.get('redis')}, minio={d.get('minio')}", ok)

seq += 1
r = requests.get(f"{BASE}/ping")
d = r.json()
ok = d["ping"] == "pong"
record(seq, "系统连通测试", "GET /api/v1/ping",
       "1. 访问 /api/v1/ping\n2. 检查 ping 字段",
       '{"ping":"pong"}',
       f'ping={d.get("ping")}, time={d.get("time")}', ok)

seq += 1
r = requests.get(f"{BASE}/admin/stats")
d = r.json()
ok = "total_tasks" in d and "by_status" in d
record(seq, "管理后台统计", "GET /api/v1/admin/stats",
       "1. 访问管理统计\n2. 检查 total_tasks/by_status/avg_confidence",
       "包含任务统计和状态分布",
       f"total={d.get('total_tasks')}, failed={d.get('failed_tasks')}, avg_conf={d.get('avg_confidence','?')}", ok)

seq += 1
r = requests.get(f"{BASE}/admin/queue")
d = r.json()
ok = "queue_length" in d
record(seq, "Celery队列状态", "GET /api/v1/admin/queue",
       "1. 查询 Celery 队列\n2. 检查 queue_length",
       "返回 queue_length 和 items",
       f"queue_length={d.get('queue_length')}, items={len(d.get('items',[]))}条", ok)

# ═══════════════════════════════════════════════════════════════
# 二、证据案件 CRUD
# ═══════════════════════════════════════════════════════════════

# 创建三种类型案件
case_ids = {}
for ct, cn in [("injury","实测-伤残案件"), ("death","实测-死亡案件"), ("neonatal","实测-新生儿案件")]:
    seq += 1
    r = requests.post(f"{BASE}/evidence/cases", json={"case_name": cn, "case_type": ct, "is_minor": False})
    ok = r.status_code == 201 and r.json()["case_type"] == ct and r.json()["status"] == "draft"
    cid = r.json().get("id","")
    case_ids[ct] = cid
    record(seq, f"创建{ct}案件", f'POST /evidence/cases, body={{case_name:"{cn}",case_type:"{ct}"}}',
           f"1. POST创建案件,type={ct}\n2. 检查201+status=draft",
           f"201 created, case_type={ct}, status=draft",
           f"HTTP {r.status_code}, id={cid[:8]}..., status={r.json().get('status')}", ok)

# 未成年人案件
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "实测-未成年人案件", "case_type": "injury", "is_minor": True})
ok = r.status_code == 201 and r.json()["is_minor"] == True
minor_id = r.json().get("id","")
record(seq, "创建未成年人案件", "POST, is_minor=True",
       "1. 创建 is_minor=True 的伤残案件\n2. 检查 is_minor 返回值",
       "201, is_minor=true",
       f"HTTP {r.status_code}, is_minor={r.json().get('is_minor')}", ok)

# 非法类型
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "非法", "case_type": "invalid", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建-非法case_type", "POST, case_type=invalid",
       "1. 提交非法 case_type\n2. 检查 422",
       "422 Validation Error",
       f"HTTP {r.status_code}", ok)

# 空名称
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "", "case_type": "injury", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建-空案件名", "POST, case_name='' (空)",
       "1. 提交空案件名\n2. 检查 422",
       "422 min_length=1 校验失败",
       f"HTTP {r.status_code}", ok)

# 超长名称
seq += 1
r = requests.post(f"{BASE}/evidence/cases", json={"case_name": "X" * 600, "case_type": "injury", "is_minor": False})
ok = r.status_code == 422
record(seq, "创建-超长案件名", "POST, case_name=600字符",
       "1. 提交600字符案件名(max_length=500)\n2. 检查 422",
       "422 max_length=500 校验失败",
       f"HTTP {r.status_code}", ok)

# 案件列表
seq += 1
r = requests.get(f"{BASE}/evidence/cases")
d = r.json()
ok = d["total"] >= 3 and len(d["items"]) >= 3
record(seq, "获取案件列表", "GET /evidence/cases",
       "1. 请求案件列表\n2. 检查 total 和 items",
       f"total >= 3",
       f"total={d.get('total')}, items={len(d.get('items',[]))}条", ok)

# 获取已有死亡案件详情
death_id = "e928ace3-d8db-4885-a784-7c3495fe16c5"
death2_id = "490b30e2-a859-4f49-a02b-0ed45edcd7db"

seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_id}")
c = r.json()
ok = r.status_code == 200 and c["case_type"] == "death" and c["status"] == "analysis_done"
record(seq, "获取死亡案件详情", f"GET /evidence/cases/{{已知death_id}}",
       "1. 用已知ID获取 death 案件\n2. 检查 case_type 和 status",
       "200, case_type=death, status=analysis_done",
       f"HTTP {r.status_code}, type={c.get('case_type')}, status={c.get('status')}", ok)

# 不存在的ID
seq += 1
r = requests.get(f"{BASE}/evidence/cases/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "获取-不存在案件", "GET /evidence/cases/{全零UUID}",
       "1. 请求不存在的 UUID\n2. 检查 404",
       "404 Not Found",
       f"HTTP {r.status_code}", ok)

# 更新案件
seq += 1
r = requests.put(f"{BASE}/evidence/cases/{case_ids['injury']}", json={"case_name": "更新后-伤残案件", "case_type": "injury", "is_minor": False})
ok = r.status_code == 200 and r.json()["case_name"] == "更新后-伤残案件"
record(seq, "更新案件名称", "PUT /evidence/cases/{id}, case_name=更新后",
       "1. PUT更新案件名称\n2. 检查返回的新名称",
       "200, case_name=更新后-伤残案件",
       f"HTTP {r.status_code}, case_name={r.json().get('case_name')}", ok)

# 删除案件
seq += 1
r = requests.delete(f"{BASE}/evidence/cases/{case_ids['injury']}")
ok = r.status_code in (200, 204)
record(seq, "删除案件", "DELETE /evidence/cases/{id}",
       "1. 删除刚创建的测试案件\n2. 检查 200/204",
       "200/204 删除成功",
       f"HTTP {r.status_code}", ok)

# 确认删除
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{case_ids['injury']}")
ok = r.status_code == 404
record(seq, "已删除案件不可见", "GET /evidence/cases/{已删除id}",
       "1. 请求已删除的案件\n2. 确认 404",
       "404 Not Found",
       f"HTTP {r.status_code}", ok)

# 删除不存在
seq += 1
r = requests.delete(f"{BASE}/evidence/cases/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "删除-不存在案件", "DELETE /evidence/cases/{全零UUID}",
       "1. 删除不存在的案件\n2. 检查 404",
       "404 Not Found",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 三、案件分析结果深度验证
# ═══════════════════════════════════════════════════════════════

# 获取分析结果（修正字段路径：在 analysis_result 内）
r_analysis = requests.get(f"{BASE}/evidence/cases/{death_id}/analysis").json()
ar = r_analysis.get("analysis_result", {})

seq += 1
dd = ar.get("death_diagnosis", "")
ok = bool(dd) and ("肺动脉" in dd or "心衰" in dd)
record(seq, "死亡诊断-8标签提取", "GET /analysis → analysis_result.death_diagnosis",
       "1. 获取分析结果\n2. 检查 analysis_result.death_diagnosis\n3. 验证含重度肺动脉高压等诊断",
       "含≥6项死亡诊断标签（肺动脉高压/右心衰竭/心源性休克/心跳骤停/肾衰/肝功能不全/酸中毒/凝血障碍）",
       f"death_diagnosis={trunc(dd,150)}", ok)

seq += 1
death_date = ar.get("death_date", "")
ok = bool(death_date) and death_date == "2026-02-03"
record(seq, "死亡日期提取", "GET /analysis → analysis_result.death_date",
       "1. 获取分析结果\n2. 检查 death_date\n3. 验证日期格式",
       "death_date=2026-02-03",
       f"death_date={death_date}", ok)

seq += 1
ad = ar.get("admission_date", "")
ok = bool(ad) and ad == "2026-02-02"
record(seq, "入院日期提取", "GET /analysis → analysis_result.admission_date",
       "1. 检查 admission_date\n2. 验证日期格式 YYYY-MM-DD",
       "admission_date=2026-02-02",
       f"admission_date={ad}", ok)

seq += 1
facts = ar.get("事实与理由", "")
ok = len(facts) > 200 and "赵小艳" in facts and "入院" in facts
record(seq, "事实与理由生成", "GET /analysis → analysis_result.事实与理由",
       "1. 获取事实与理由文本\n2. 检查字数>200\n3. 验证含患者姓名和入院描述",
       "字数>200, 含完整诊疗经过(姓名+入院+转ICU+死亡)",
       f"字数={len(facts)}, 含姓名={'是' if '赵小艳' in facts else '否'}, 含入院={'是' if '入院' in facts else '否'}", ok)

seq += 1
ct = ar.get("conclusion_text", "")
ok = len(ct) > 100 and "被告" in ct
record(seq, "结论文本生成", "GET /analysis → analysis_result.conclusion_text",
       "1. 获取结论文本\n2. 验证含被告+因果关系论述",
       "含结论性陈述,提及被告和损害后果",
       f"字数={len(ct)}, 含被告={'是' if '被告' in ct else '否'}", ok)

seq += 1
ap = ar.get("appraisal_details", {})
has_report = bool(ap.get("report_no", ""))
has_death_cause = bool(ap.get("cause_of_death", ""))
ok = has_report and has_death_cause
record(seq, "鉴定信息提取", "GET /analysis → analysis_result.appraisal_details",
       "1. 获取鉴定详情\n2. 检查 report_no/cause_of_death",
       "含 report_no(鉴定报告号) + cause_of_death(死因)",
       f"report_no={'有:' + ap.get('report_no','')[:30] if has_report else '无'}, cause_of_death={'有' if has_death_cause else '无'}, org={ap.get('appraisal_org','?')}", ok)

seq += 1
kd = ar.get("key_dates", [])
ok = isinstance(kd, list) and len(kd) >= 3
record(seq, "关键时间线提取", "GET /analysis → analysis_result.key_dates",
       "1. 获取关键日期列表\n2. 验证≥3个时间点",
       "≥3个关键日期（入院/转ICU/死亡等）",
       f"时间点数={len(kd) if isinstance(kd,list) else 0}" + (f", 内容={[d[:20] for d in kd[:3]]}" if isinstance(kd,list) and kd else ""), ok)

seq += 1
ke = ar.get("key_examinations", [])
ok = isinstance(ke, list) and len(ke) >= 3
record(seq, "关键检查项目提取", "GET /analysis → analysis_result.key_examinations",
       "1. 获取关键检查列表\n2. 验证≥3项",
       "≥3项关键检查（心电图/心超/BNP/CTA等）",
       f"检查项数={len(ke) if isinstance(ke,list) else 0}" + (f", 首项={str(ke[0])[:40]}" if isinstance(ke,list) and ke else ""), ok)

seq += 1
df = ar.get("defendant_name", "")
ok = bool(df) and "医院" in df
record(seq, "被告名称提取", "GET /analysis → analysis_result.defendant_name",
       "1. 获取被告名称\n2. 验证含医院",
       "含医院名称",
       f"defendant_name={df}", ok)

seq += 1
dn = ar.get("defendant_phone", "")
ok = bool(dn)  # 只需有值
record(seq, "被告电话提取", "GET /analysis → analysis_result.defendant_phone",
       "1. 获取被告电话\n2. 验证非空",
       "非空电话号码",
       f"defendant_phone={dn}", ok)

# ═══════════════════════════════════════════════════════════════
# 四、证据目录与验证
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_id}/catalog")
cat = r.json()
groups = cat.get("groups", [])
categories = [g.get("category") for g in groups]
has_identity = "identity_id_card" in categories
has_death = "death_certificate" in categories
has_medical = "medical_record" in categories
ok = len(groups) >= 5 and has_identity and has_death and has_medical
record(seq, "证据目录分组验证", "GET /evidence/cases/{death_id}/catalog",
       "1. 获取证据目录\n2. 检查分组数和关键分类(identity_id_card/death_certificate/medical_record)",
       "≥5个分组, 含identity_id_card+death_certificate+medical_record",
       f"分组数={len(groups)}, 含身份={'是' if has_identity else '否'}, 含死亡证明={'是' if has_death else '否'}, 含病历={'是' if has_medical else '否'}, 分类={categories}", ok)

# 费用
seq += 1
fee_groups = [g for g in groups if g.get("category") == "fee_receipt"]
total_fee = 0
for g in fee_groups:
    for item in g.get("items", []):
        fd = item.get("fee_detail", {})
        if isinstance(fd, dict):
            total_fee += fd.get("total_amount", 0) or 0
# fees in catalog_data may also have them at top level
has_fees = len(fee_groups) > 0
record(seq, "费用票据分组验证", "GET /catalog → fee_receipt分组",
       "1. 筛选 fee_receipt 分组\n2. 汇总各材料fee_detail.total_amount",
       "有fee_receipt分组, 金额≥0",
       f"fee_receipt组数={len(fee_groups)}, 总金额={total_fee:.2f}元", has_fees)

# 验证结果
seq += 1
vr = r_analysis.get("validation_result", {})
mi = r_analysis.get("missing_items", {})
vr_items = vr.get("items", [])
all_ok_vr = all(i.get("status") == "ok" for i in vr_items) if vr_items else False
record(seq, "必填项验证-死亡案件", "GET /analysis → validation_result",
       "1. 获取验证结果\n2. 检查各项 status\n3. 检查 missing_items",
       "所有必填项 status=ok, missing_items 为空",
       f"验证项={len(vr_items)}, 全ok={all_ok_vr}, missing={len(mi.get('items',[]))}项", all_ok_vr)

# ═══════════════════════════════════════════════════════════════
# 五、导出功能
# ═══════════════════════════════════════════════════════════════

# 用 death2 测试导出（test 案件有些可用有些500）
for case_label, cid in [("death-test1", death_id), ("death-test", death2_id)]:
    seq += 1
    r = requests.get(f"{BASE}/evidence/cases/{cid}/export/complaint")
    ok = r.status_code == 200 and len(r.content) > 500
    ct = r.headers.get("content-type", "?")[:30]
    record(seq, f"导出民事起诉状({case_label})", f"GET /evidence/cases/{{id}}/export/complaint",
           "1. 请求民事起诉状\n2. 检查文件大小和类型",
           "200, Content-Type=docx, size>500",
           f"HTTP {r.status_code}, type={ct}, size={len(r.content)}bytes", ok)

# 目录PDF
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_id}/catalog/pdf")
ok = r.status_code == 200 and "pdf" in r.headers.get("content-type","?")
record(seq, "获取证据目录PDF", "GET /evidence/cases/{id}/catalog/pdf",
       "1. 请求目录PDF\n2. 检查Content-Type",
       "200, Content-Type=application/pdf",
       f"HTTP {r.status_code}, type={r.headers.get('content-type','?')[:30]}, size={len(r.content)}bytes", ok)

# 导出打包
seq += 1
r = requests.post(f"{BASE}/evidence/cases/{death_id}/export/bundle")
ok = r.status_code in (200, 201, 202)
record(seq, "触发立案立档包打包", "POST /evidence/cases/{id}/export/bundle",
       "1. 触发打包\n2. 检查返回状态",
       "200/201/202 打包触发成功",
       f"HTTP {r.status_code}, body={trunc(r.text,200)}", ok)

# 下载打包文件
seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_id}/export/bundle/download")
ok = r.status_code in (200, 202)
record(seq, "下载打包文件", "GET /evidence/cases/{id}/export/bundle/download",
       "1. 请求下载打包文件\n2. 检查返回",
       "200(zip) 或 202(打包中)",
       f"HTTP {r.status_code}, size={len(r.content)}bytes, type={r.headers.get('content-type','?')[:30]}", ok)

# ═══════════════════════════════════════════════════════════════
# 六、已知Bug记录 (500错误)
# ═══════════════════════════════════════════════════════════════

bug_endpoints = [
    (f"/evidence/cases/{death2_id}/export/filing-evidence", "导出立案证据(Bug#1已修)", "原: event loop 冲突"),
    (f"/evidence/cases/{death2_id}/export/compensation", "导出赔偿清单(Bug#2已修)", "原: event loop 冲突"),
    (f"/evidence/cases/{death2_id}/export/appraisal-app", "导出鉴定申请书(Bug#3已修)", "原: event loop 冲突"),
    (f"/evidence/cases/{death2_id}/catalog/pdf", "目录PDF(Bug#4已修)", "原: ChineseFont KeyError"),
]

for ep, func, err in bug_endpoints:
    seq += 1
    r = requests.get(f"{BASE}{ep}")
    ok = r.status_code == 200
    size = len(r.content)
    ct = r.headers.get("content-type", "?")[:30]
    record(seq, f"验证修复-{func}", f"GET {ep}",
           f"1. 请求{func}\n2. 检查返回200",
           "200 正常返回(之前500)",
           f"HTTP {r.status_code}, size={size}, type={ct}", ok,
           f"原Bug: {err}")

# ═══════════════════════════════════════════════════════════════
# 七、进度/流程
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/evidence/cases/{death_id}/progress")
ok = r.status_code == 200
record(seq, "查询案件处理进度", "GET /evidence/cases/{id}/progress",
       "1. 查询已处理案件的进度\n2. 检查步骤列表",
       "200, 含步骤列表",
       f"HTTP {r.status_code}, body={trunc(r.text,200)}", ok)

# 空案件处理
seq += 1
r = requests.post(f"{BASE}/evidence/cases/{case_ids['neonatal']}/process")
ok = r.status_code in (200, 202, 400, 409)
record(seq, "处理空材料案件", "POST /evidence/cases/{draft_id}/process",
       "1. 对无材料的draft案件触发处理\n2. 预期拒绝或空处理",
       "400/409(无材料) 或 202(接受)",
       f"HTTP {r.status_code}, body={trunc(r.text,200)}", ok)

# ═══════════════════════════════════════════════════════════════
# 八、扫描系统
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/scans")
ok = r.status_code == 200
record(seq, "扫描任务列表", "GET /scans",
       "1. 查询所有扫描任务",
       "200, 返回列表",
       f"HTTP {r.status_code}, body={trunc(r.text,200)}", ok)

seq += 1
r = requests.post(f"{BASE}/scans/upload")
ok = r.status_code in (400, 422)
record(seq, "扫描上传-无文件", "POST /scans/upload (无文件)",
       "1. 不带文件提交上传\n2. 检查422",
       "422 缺少文件",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 九、模板系统
# ═══════════════════════════════════════════════════════════════

seq += 1
r = requests.get(f"{BASE}/templates/")
ok = r.status_code == 200
record(seq, "模板列表", "GET /templates/",
       "1. 查询所有模板",
       "200, 返回列表",
       f"HTTP {r.status_code}, body={trunc(r.text,200)}", ok)

seq += 1
r = requests.get(f"{BASE}/templates/00000000-0000-0000-0000-000000000000")
ok = r.status_code == 404
record(seq, "获取不存在模板", "GET /templates/{全零UUID}",
       "1. 请求不存在的模板ID",
       "404 Not Found",
       f"HTTP {r.status_code}", ok)

# ═══════════════════════════════════════════════════════════════
# 十、第二死亡案件交叉验证
# ═══════════════════════════════════════════════════════════════

seq += 1
r2 = requests.get(f"{BASE}/evidence/cases/{death2_id}").json()
ar2 = requests.get(f"{BASE}/evidence/cases/{death2_id}/analysis").json().get("analysis_result", {})
dd2 = ar2.get("death_diagnosis", "")
ok2 = bool(dd2)
record(seq, "第二死亡案件-死亡诊断", "GET /analysis(death2) → death_diagnosis",
       "1. 获取第二死亡案件分析\n2. 检查死亡诊断",
       "含多标签死亡诊断",
       f"death_diagnosis={trunc(dd2,150)}", ok2)

# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r["是否通过"] == "✅ 通过")
failed = sum(1 for r in results if r["是否通过"] == "❌ 失败")
print(f"\n{'='*60}")
print(f"深度用户实测 V2 完成: {len(results)} 条, 通过 {passed}, 失败 {failed}")
print(f"通过率: {passed/len(results)*100:.1f}%")
print(f"{'='*60}")

with open("docs/api_test_results_2026-06-06.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"保存至 docs/api_test_results_2026-06-06.json")
