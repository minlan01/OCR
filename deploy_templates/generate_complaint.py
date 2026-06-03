#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
医疗损害责任纠纷民事起诉状 — 自动生成引擎

基于 10 份真实诉状+病历对照的模板规则，从结构化 JSON 数据生成诉状。
排版格式：仿宋14pt、左对齐（法律文书标准格式）

用法：
    python generate_complaint.py input.json [output.txt|output.md|output.docx]

输入格式参见 complaint_schema.json
"""

import json
import re
import sys
import os
from typing import Dict, List, Any


class ComplaintGenerator:
    """诉状生成器"""

    TITLE = "民事起诉状"
    LAW_BASIS = "《中华人民共和国民法典》《中华人民共和国民事诉讼法》"

    DAMAGE_ITEMS_DEATH = [
        "医疗费", "误工费", "护理费", "住院伙食补助费", "营养费",
        "死亡赔偿金", "被扶养人生活费", "丧葬费", "交通费", "住宿费",
        "精神损害抚慰金"
    ]
    DAMAGE_ITEMS_DISABILITY = [
        "医疗费", "护理费", "住院伙食补助费", "营养费",
        "残疾赔偿金", "交通住宿费", "精神损害抚慰金"
    ]
    DAMAGE_ITEMS_NEONATAL_DEATH = [
        "医疗费", "护理费", "住院伙食补助费", "营养费",
        "死亡赔偿金", "丧葬费", "交通费", "病案复印费",
        "精神损害抚慰金"
    ]

    def __init__(self, data: dict):
        self.d = data
        self._validate()

    def _validate(self):
        required = ["case_type", "plaintiffs", "defendants", "adm_info", "medical_process", "result", "court"]
        for key in required:
            if key not in self.d:
                raise ValueError(f"缺少必填字段: {key}")

    def _extract_rel(self, relationship: str) -> str:
        if not relationship or relationship == "患者本人":
            return ""
        rel = relationship
        if rel.startswith("系"):
            rel = rel[1:]
        if rel.startswith("患者"):
            rel = rel[2:]
        return rel

    def _format_plaintiff_rel(self, relationship: str) -> tuple:
        raw = self._extract_rel(relationship)
        if not raw:
            return ("", False)
        is_death = self.d["result"].get("type") == "death"
        if is_death:
            patient_name = self.d.get("patient", {}).get("name", "")
            return (f"系死者{patient_name}之{raw}", True)
        return (f"系患者{raw}", False)

    CN_DIGITS = "〇一二三四五六七八九"

    def _num_to_cn(self, n: int) -> str:
        if n <= 10:
            return self.CN_DIGITS[n]
        elif n < 20:
            return "十" + (self.CN_DIGITS[n - 10] if n > 10 else "")
        elif n == 20:
            return "二十"
        elif n < 30:
            return "二十" + self.CN_DIGITS[n - 20]
        elif n == 30:
            return "三十"
        elif n < 40:
            return "三十" + self.CN_DIGITS[n - 30]
        return str(n)

    def _format_date_cn(self, date_str: str) -> str:
        if not date_str or 'X' in date_str:
            return date_str
        m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
        if not m:
            return date_str
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year_cn = ''.join(self.CN_DIGITS[int(d)] for d in str(year))
        return f"{year_cn}年{self._num_to_cn(month)}月{self._num_to_cn(day)}日"

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'(.{2,8}?)[。；，]\1', r'\1', text)
        text = re.sub(r'术后[。]*术后', '术后', text)
        text = re.sub(r'[。]{2,}', '。', text)
        text = re.sub(r'。，', '，', text)
        text = re.sub(r'，。', '，', text)
        text = re.sub(r'，\s*，', '，', text)
        return text

    def gen_title(self) -> str:
        return self.TITLE

    PLACEHOLDER = "________"

    def _val(self, v: str, fallback: str = "") -> str:
        if not v or v.strip() in ("[待补充]", "[未知]", "null", "None", "undefined"):
            return fallback or self.PLACEHOLDER
        return v.strip()

    def _gen_person_line(self, prefix: str, p: dict, rel_suffix: str = "") -> str:
        line1_parts = [f"　　　{prefix}{self._val(p.get('name', ''))}{rel_suffix}"]
        gender = self._val(p.get('gender', ''), '')
        ethnicity = self._val(p.get('ethnicity', ''), '')
        birth_date = self._val(p.get('birth_date', ''), '')
        if gender:
            line1_parts.append(gender)
        if ethnicity:
            line1_parts.append(ethnicity)
        if birth_date:
            line1_parts.append(f"{birth_date}出生")

        detail_parts = []
        address = self._val(p.get('address', ''), '')
        if address:
            detail_parts.append(f"住址：{address}")
        id_number = self._val(p.get('id_number', ''), '')
        if id_number:
            detail_parts.append(f"公民身份号码：{id_number}")
        phone = self._val(p.get('phone', ''), '')
        if phone:
            detail_parts.append(f"联系电话：{phone}")

        if detail_parts:
            lines = ["，".join(line1_parts) + "，"]
            for i, part in enumerate(detail_parts):
                if i == len(detail_parts) - 1:
                    lines.append(part + "。")
                else:
                    lines.append(part + "，")
            return "\n".join(lines)
        else:
            return "，".join(line1_parts) + "。"

    def gen_plaintiffs(self) -> str:
        lines = []
        for p in self.d["plaintiffs"]:
            if p.get("is_legal_guardian"):
                rel = self._val(p.get('ward_relationship', ''), '原告' + self._val(p.get('ward_name', '')))
                rel_suffix = f"（系{rel}）"
                line = self._gen_person_line("法定代理人：", p, rel_suffix)
            else:
                rel_text, use_parens = self._format_plaintiff_rel(p.get("relationship", ""))
                if use_parens:
                    rel_suffix = f"（{rel_text}）"
                elif rel_text:
                    rel_suffix = f"，{rel_text}"
                else:
                    rel_suffix = ""
                line = self._gen_person_line("原告：", p, rel_suffix)
            lines.append(line)
        return "\n".join(lines)

    def gen_defendants(self) -> str:
        lines = []
        for d in self.d["defendants"]:
            alias = f"（{d['alias']}）" if d.get("alias") and self._val(d['alias'], '') != self.PLACEHOLDER else ""
            lines.append(f"　　　被告：{self._val(d.get('hospital_name', ''))}{alias}")
            legal_rep = d.get('legal_rep', '')
            if legal_rep and legal_rep.strip() not in ("[待补充]", "[未知]", "null", "None", "", "undefined"):
                lines.append(f"　　　法定代表人：{legal_rep.strip()}")
            credit_code = d.get('credit_code', '')
            if credit_code and credit_code.strip() not in ("[待补充]", "[未知]", "null", "None", "", "undefined"):
                lines.append(f"　　　统一社会信用代码：{credit_code.strip()}")
            address = d.get('address', '')
            if address and address.strip() not in ("[待补充]", "[未知]", "null", "None", "", "undefined"):
                lines.append(f"　　　地址：{address.strip()}")
            phone = d.get('phone', '')
            if phone and phone.strip() not in ("[待补充]", "[未知]", "null", "None", "", "undefined"):
                lines.append(f"　　　联系电话：{phone.strip()}")
        return "\n".join(lines)

    def gen_claims(self) -> str:
        comp = self.d.get("compensation", {})
        items = comp.get("items", [])
        if not items:
            ct = self.d["case_type"]
            if ct in ("adult_death",):
                items = [{"name": i} for i in self.DAMAGE_ITEMS_DEATH]
            elif ct in ("neonatal_death",):
                items = [{"name": i} for i in self.DAMAGE_ITEMS_NEONATAL_DEATH]
            else:
                items = [{"name": i} for i in self.DAMAGE_ITEMS_DISABILITY]

        normalized = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"name": item})
            else:
                normalized.append(item)

        has_any_amount = any(item.get("amount") for item in normalized)
        if has_any_amount:
            item_parts = []
            for item in normalized:
                name = item["name"]
                amount = item.get("amount")
                if amount:
                    item_parts.append(f"{name}{amount:.2f}元")
                else:
                    item_parts.append(name)
            items_str = "、".join(item_parts)
            total_prefix = "，以上共计"
        else:
            items_str = "、".join(item["name"] for item in normalized)
            total_prefix = "等，"

        amount = comp.get("total_amount", 0)
        if amount <= 0:
            amount = 200000
        amount_type = comp.get("amount_type", "暂计")
        supplement = comp.get("supplement_note", "")
        if supplement:
            supplement = "，" + supplement

        claim1 = (
            f"　　　一、判令被告赔偿原告"
            f"{items_str}{total_prefix}{amount_type}人民币{amount:.2f}元{supplement}；"
        )

        has_appraisal_fee = comp.get("has_appraisal_fee", False)
        appraisal_fee = comp.get("appraisal_fee", 0)
        if has_appraisal_fee and appraisal_fee:
            claim2 = (
                f"　　　二、判令本案诉讼费、"
                f"鉴定费（尸检鉴定费{appraisal_fee:.2f}元）由被告承担。"
            )
        else:
            claim2 = "　　　二、判令本案诉讼费、鉴定费由被告承担。"

        return f"　　　诉讼请求：\n{claim1}\n\n{claim2}"

    def gen_facts_intro(self) -> str:
        adm = self.d["adm_info"]
        ct = self.d["case_type"]
        defendants_names = "、".join(d["hospital_name"] for d in self.d["defendants"])

        if ct in ("neonatal_death", "neonatal_disability"):
            mother = self.d.get("mother", {})
            m_name = mother.get("name", "[产妇姓名]")
            m_date = mother.get("admission_date", adm.get("admission_date", ""))
            m_complaint = mother.get("chief_complaint", "")
            result = f"　　　{m_date}，产妇{m_name}因\"{m_complaint}\"到被告{defendants_names}就诊"
        else:
            p_name = self.d.get("patient", {}).get("name", "[患者姓名]")
            adm_date = adm["admission_date"]
            complaint = adm["chief_complaint"]
            result = f"　　　{adm_date}，患者{p_name}因\"{complaint}\"到被告{defendants_names}就诊"

        if adm.get("admission_diagnosis"):
            result += f"，入院诊断为{adm['admission_diagnosis']}"

        result += "。"
        return result

    def gen_medical_process(self) -> str:
        processes = self.d.get("medical_process", [])
        if not processes:
            return ""

        adm = self.d.get("adm_info", {})
        aux_exam = adm.get("aux_exam_summary", "")
        is_death = self.d["result"].get("type") == "death"
        parts = []

        if aux_exam:
            if is_death:
                parts.append(f"　　　入院检查提示{aux_exam}，但被告未充分评估、未及时有效干预。")
            else:
                parts.append(f"　　　入院检查提示{aux_exam}，但被告未充分评估与针对性干预。")

        for i, proc in enumerate(processes):
            desc = proc.get("description", "")
            details = proc.get("details", {})

            if proc.get("type") == "surgery":
                surgery_name = details.get("surgery_name", "")
                post_op = details.get("post_op_condition", "")
                if post_op.startswith("术后"):
                    post_op = post_op[2:]
                if is_death and post_op:
                    fault_suffix = "，被告围术期管理失当、延误救治。"
                    if "围术期管理" in post_op or "管理失当" in post_op:
                        fault_suffix = "。"
                    parts.append(
                        f"　　　{proc['date']}，被告为患者行"
                        f"{surgery_name}。术后{post_op}{fault_suffix}"
                    )
                else:
                    suffix = "。" if post_op else "。"
                    parts.append(
                        f"　　　{proc['date']}，被告为患者行"
                        f"{surgery_name}。术后{post_op}{suffix}"
                    )
            elif proc.get("type") == "deterioration":
                parts.append(f"　　　{desc}")
            elif proc.get("type") == "rescue":
                parts.append(f"　　　{desc}")
            elif proc.get("type") == "transfer":
                parts.append(f"　　　为寻求进一步治疗，{desc}")
            elif proc.get("type") == "discharge":
                discharge_cond = details.get("discharge_condition", "")
                rtype = self.d["result"].get("type", "")
                if rtype == "death" and discharge_cond:
                    cond = discharge_cond
                    if cond.startswith("呈"):
                        cond = cond[1:]
                    if cond.endswith("状态"):
                        cond = cond[:-2]
                    parts.append(f"　　　{proc['date']}，患者出院时呈{cond}状态，并于当日死亡。")
                elif discharge_cond:
                    parts.append(f"　　　经治疗，于{proc['date']}办理出院，出院时情况：{discharge_cond}。")
                else:
                    parts.append(f"　　　经治疗，于{proc['date']}办理出院。")
            elif proc.get("type") == "death":
                parts.append(f"　　　{desc}")
            else:
                parts.append(f"　　　{desc}")

        return "\n".join(parts)

    def gen_result(self) -> str:
        result = self.d["result"]
        rtype = result.get("type", "death")

        if rtype == "death":
            has_discharge_death = any(
                p.get("type") == "discharge" and self.d["result"].get("type") == "death"
                for p in self.d.get("medical_process", [])
            )
            if has_discharge_death:
                return ""
            if result.get("is_death_on_discharge_day", True):
                p_name = self.d.get("patient", {}).get("name", "[患者姓名]")
                d_date = result.get("death_date", "")
                return f"　　　患者{p_name}于出院当日{d_date}死亡。"
            else:
                return result.get("death_description", "")

        elif rtype == "disability" or rtype == "ongoing_treatment":
            return "　　　截至起诉之日原告仍在持续康复治疗中。"

        return ""

    def gen_appraisal(self) -> str:
        app = self.d.get("appraisal", {})
        if not app.get("has_appraisal"):
            return ""

        return (
            f"　　　{app['appraisal_date']}{app['institution']}"
            f"对{app.get('subject', '患者')}进行{app.get('type', '尸体解剖检验及死亡原因鉴定')}，"
            f"并于{app['report_date']}出具{app['report_number']}"
            f"《司法鉴定意见书》"
            f"{'，明确鉴定意见为：' + app['conclusion'] if app.get('conclusion') else ''}。"
        )

    def gen_qualification_issue(self) -> str:
        qi = self.d.get("qualification_issue", {})
        if not qi.get("has_issue"):
            return ""

        personnel = qi.get("personnel_list", "")
        if qi.get("is_confirmed", True):
            return (
                f"　　　另，本案参与为患者提供诊疗服务的{personnel}"
                f"未能查询到相关资质，被告存在使用非卫生技术人员"
                f"从事诊疗活动的违反法律、行政法规相关规定的行为。"
            )
        else:
            return (
                f"　　　此外，被告在为原告提供诊疗服务的医务人员中，{personnel}"
                f"的相关执业注册信息未在中华人民共和国国家卫生健康委员会官网上进行公示，"
                f"不排除被告存在聘用非卫生技术人员从事卫生技术诊疗活动的违法情形。"
            )

    def gen_additional_claims(self) -> str:
        claims = self.d.get("additional_claims", "")
        if not claims:
            return ""
        return f"　　　{claims}"

    def gen_conclusion(self) -> str:
        ct = self.d["case_type"]

        if ct in ("neonatal_death", "neonatal_disability"):
            subject = "产妇及患儿"
        else:
            subject = "患者"

        if self.d["result"].get("type") == "death":
            damage_desc = (
                f"与{subject}死亡存在直接因果关系，"
                f"给原告造成巨大经济损失与精神痛苦"
            )
        else:
            damage_desc = "给原告造成巨大经济损失与精神痛苦"

        return (
            f"　　　被告诊疗行为违反规范，未尽审慎注意义务，"
            f"存在明显医疗过错，{damage_desc}。"
            f"现依法诉至贵院，望判如所请。"
        )

    def gen_footer(self) -> str:
        court = self.d["court"]["name"]
        filing_date = self.d.get("filing_date", "")
        if filing_date:
            date_str = self._format_date_cn(filing_date)
        else:
            date_str = "XXXX年XX月XX日"
        return (
            f"　　　此致\n"
            f"{court}\n"
            f"\n"
            f"                                       具状人：\n"
            f"                                       {date_str}"
        )

    def generate(self) -> str:
        sections = [
            self.gen_title(),
            "",
            self.gen_plaintiffs(),
            "",
            self.gen_defendants(),
            "",
            self.gen_claims(),
            "",
            "事实及理由：",
            "",
        ]

        sections.append(self.gen_facts_intro())
        sections.append("")

        sections.append(self.gen_medical_process())
        sections.append("")

        result_text = self.gen_result()
        if result_text:
            sections.append(result_text)
            sections.append("")

        appraisal = self.gen_appraisal()
        if appraisal:
            sections.append(appraisal)
            sections.append("")

        qualification = self.gen_qualification_issue()
        if qualification:
            sections.append(qualification)
            sections.append("")

        additional = self.gen_additional_claims()
        if additional:
            sections.append(additional)
            sections.append("")

        sections.append(self.gen_conclusion())
        sections.append("")

        sections.append(self.gen_footer())

        result = "\n".join(sections)
        result = self._clean_text(result)
        return result


def load_sample(which: str) -> dict:
    samples = {
        "death1": {
            "case_type": "adult_death",
            "plaintiffs": [
                {
                    "name": "XXX", "relationship": "配偶",
                    "gender": "女", "ethnicity": "汉族",
                    "birth_date": "1965年10月08日",
                    "address": "贵州省黔西南布依族苗族自治州晴隆县",
                    "id_number": "XXXXXXXXXXXXXXXXXX",
                    "phone": "18084295520（赵怀勇律师）"
                },
                {
                    "name": "XXX", "relationship": "子女",
                    "gender": "女", "ethnicity": "汉族",
                    "birth_date": "XXXX年XX月XX日",
                    "address": "贵州省黔西南布依族苗族自治州晴隆县",
                    "id_number": "XXXXXXXXXXXXXXXXXX",
                    "phone": ""
                },
                {
                    "name": "XXX", "relationship": "父母",
                    "gender": "女", "ethnicity": "汉族",
                    "birth_date": "XXXX年XX月XX日",
                    "address": "贵州省黔西南布依族苗族自治州晴隆县",
                    "id_number": "XXXXXXXXXXXXXXXXXX",
                    "phone": ""
                }
            ],
            "defendants": [
                {
                    "hospital_name": "兴义市人民医院",
                    "legal_rep": "刘胜江",
                    "credit_code": "XXXXXXXXXXXXXXXXXX",
                    "address": "贵州省黔西南布依族苗族自治州兴义市XXXX路XX号",
                    "phone": "0859-3222120"
                }
            ],
            "patient": {
                "name": "陈历英", "gender": "女",
                "birth_date": "1965年10月8日"
            },
            "adm_info": {
                "admission_date": "2026年01月26日",
                "chief_complaint": "胸闷、气促10余年，加重伴纳差1月",
                "aux_exam_summary": "患者存在心肌损伤、电解质紊乱、低氧血症、肝肾功能异常等多项高危异常指标",
                "admission_diagnosis": "缺血性心肌病、冠状动脉粥样硬化性心脏病、高血压病3级（极高危）、心力衰竭、低钾血症等多项严重病症"
            },
            "medical_process": [
                {
                    "date": "2026年02月04日",
                    "type": "surgery",
                    "description": "行CABG手术",
                    "details": {
                        "surgery_name": "冠状动脉旁路移植术",
                        "anesthesia": "全麻",
                        "post_op_condition": "患者迅速出现心包积液、胸腔积液、阵发性室上性心动过速、ST-T改变等严重并发症，提示围术期管理严重失当，被告未及时识别并有效处理循环衰竭先兆"
                    }
                },
                {
                    "date": "2026年02月06日",
                    "type": "discharge",
                    "description": "办理出院",
                    "details": {
                        "discharge_condition": "呈深昏迷状态"
                    }
                }
            ],
            "result": {
                "type": "death",
                "death_date": "2026年02月06日",
                "is_death_on_discharge_day": True
            },
            "compensation": {
                "items": [
                    {"name": "医疗费"},
                    {"name": "误工费"},
                    {"name": "护理费"},
                    {"name": "住院伙食补助费"},
                    {"name": "营养费"},
                    {"name": "死亡赔偿金"},
                    {"name": "被扶养人生活费"},
                    {"name": "丧葬费"},
                    {"name": "交通费"},
                    {"name": "住宿费"},
                    {"name": "精神损害抚慰金"}
                ],
                "total_amount": 200000,
                "amount_type": "暂计"
            },
            "court": {"name": "兴义市人民法院"}
        }
    }
    return samples.get(which, samples["death1"])


def main():
    if len(sys.argv) < 2:
        print("用法：python generate_complaint.py <input.json> [output.txt]")
        print("       python generate_complaint.py --sample death1 [output.txt]")
        sys.exit(1)

    if sys.argv[1] == "--sample":
        sample_name = sys.argv[2] if len(sys.argv) > 2 else "death1"
        data = load_sample(sample_name)
        output_file = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        input_file = sys.argv[1]
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        output_file = sys.argv[2] if len(sys.argv) > 2 else None

    gen = ComplaintGenerator(data)
    complaint_text = gen.generate()

    if output_file:
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(complaint_text)
        print(f"诉状已生成: {output_file}")
    else:
        print(complaint_text)


if __name__ == "__main__":
    main()
