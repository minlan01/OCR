import sys
sys.path.insert(0, r'E:\OCRScanStruct\deploy_templates')
from generate_complaint import ComplaintGenerator

data_with_placeholders = {
    "case_type": "adult_death",
    "plaintiffs": [
        {
            "name": "[待补充]", "relationship": "配偶",
            "gender": "男", "ethnicity": "汉族",
            "birth_date": "[待补充]",
            "address": "[待补充]",
            "id_number": "[待补充]",
            "phone": "18084295520（赵怀勇律师）"
        },
        {
            "name": "[待补充]", "relationship": "父亲",
            "gender": "[待补充]", "ethnicity": "汉族",
            "birth_date": "[待补充]",
            "address": "[待补充]",
            "id_number": "[待补充]",
            "phone": "[待补充]"
        }
    ],
    "defendants": [
        {
            "hospital_name": "兴义市人民医院",
            "legal_rep": "[待补充]",
            "credit_code": "[待补充]",
            "address": "[待补充]",
            "phone": "0859-3222120"
        }
    ],
    "patient": {"name": "陈历英", "gender": "女", "birth_date": "1965年10月8日"},
    "adm_info": {
        "admission_date": "2026年01月26日",
        "chief_complaint": "胸闷、气促10余年，加重伴纳差1月",
        "aux_exam_summary": "心肌损伤、电解质紊乱等多项高危异常指标",
        "admission_diagnosis": "缺血性心肌病、冠状动脉粥样硬化性心脏病"
    },
    "medical_process": [
        {
            "date": "2026年02月04日",
            "type": "surgery",
            "description": "行CABG手术",
            "details": {
                "surgery_name": "冠状动脉旁路移植术",
                "anesthesia": "全麻",
                "post_op_condition": "患者出现严重并发症，被告未及时有效处置"
            }
        },
        {
            "date": "2026年02月06日",
            "type": "discharge",
            "description": "办理出院",
            "details": {"discharge_condition": "呈深昏迷状态"}
        }
    ],
    "result": {"type": "death", "death_date": "2026年02月06日", "is_death_on_discharge_day": True},
    "compensation": {
        "items": [{"name": "医疗费"}, {"name": "误工费"}, {"name": "护理费"}, {"name": "住院伙食补助费"}, {"name": "营养费"}, {"name": "死亡赔偿金"}, {"name": "被扶养人生活费"}, {"name": "丧葬费"}, {"name": "交通费"}, {"name": "住宿费"}, {"name": "精神损害抚慰金"}],
        "total_amount": 200000,
        "amount_type": "暂计"
    },
    "court": {"name": "兴义市人民法院"}
}

gen = ComplaintGenerator(data_with_placeholders)
output = gen.generate()
print(output)
