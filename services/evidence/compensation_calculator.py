"""
赔偿金额计算引擎
根据《民法典》及最高法司法解释计算各项赔偿费用
使用 Decimal 确保金额精度
"""
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# ── 默认参数（2025年度参考标准）──
DEFAULT_PARAMS: Dict[str, Any] = {
    "annual_income": Decimal("49283"),       # 上年度城镇居民人均可支配收入(元/年)
    "annual_consumption": Decimal("33382"),   # 上年度城镇居民人均消费支出(元/年)
    "monthly_salary": Decimal("8500"),        # 上年度职工月平均工资(元/月)
    "daily_food_subsidy": Decimal("100"),     # 住院伙食补助日标准(元/天)
    "daily_nutrition": Decimal("30"),         # 营养费日标准(元/天)
    "compensation_years": 20,                 # 赔偿年限(年)
    "disability_coefficient": Decimal("1.0"), # 伤残系数(100%=一级伤残)
    "hospital_days": 0,                       # 住院天数
    "lost_wage_days": 0,                      # 误工天数
    "nursing_days": 0,                        # 护理天数
    "nutrition_days": 0,                      # 营养期天数
}

# ── 伤残案件赔偿项目（8项）──
INJURY_ITEMS: List[str] = [
    "medical_fee",          # 医疗费
    "lost_wages",           # 误工费
    "nursing_fee",          # 护理费
    "food_subsidy",         # 住院伙食补助费
    "nutrition_fee",        # 营养费
    "disability_compensation",  # 残疾赔偿金
    "transport_fee",        # 交通住宿费
    "spiritual_damage",     # 精神损害抚慰金
]

# ── 死亡案件赔偿项目（9项）──
DEATH_ITEMS: List[str] = [
    "medical_fee",          # 医疗费
    "lost_wages",           # 误工费
    "nursing_fee",          # 护理费
    "food_subsidy",         # 住院伙食补助费
    "nutrition_fee",        # 营养费
    "death_compensation",   # 死亡赔偿金
    "funeral_fee",          # 丧葬费
    "transport_fee",        # 交通费
    "spiritual_damage",     # 精神损害抚慰金
]

FEE_NAMES: Dict[str, str] = {
    "medical_fee": "医疗费",
    "lost_wages": "误工费",
    "nursing_fee": "护理费",
    "food_subsidy": "住院伙食补助费",
    "nutrition_fee": "营养费",
    "disability_compensation": "残疾赔偿金",
    "death_compensation": "死亡赔偿金",
    "funeral_fee": "丧葬费",
    "transport_fee": "交通住宿费",
    "spiritual_damage": "精神损害抚慰金",
    "dependent_living": "被扶养人生活费",
}


def merge_params(user_params: Optional[Dict] = None, hospital_days: int = 0) -> Dict:
    """合并默认参数和用户自定义参数"""
    params = dict(DEFAULT_PARAMS)
    if hospital_days > 0:
        params["hospital_days"] = hospital_days
    if user_params:
        for k, v in user_params.items():
            if v is not None:
                params[k] = v
    return params


def calculate_all(
    case_type: str,
    params: Dict,
    fee_items: Optional[list] = None,
) -> Dict[str, Any]:
    """
    计算所有赔偿项目

    Args:
        case_type: "injury" 或 "death"
        params: 计算参数（含默认值和用户覆盖）
        fee_items: 从 OCR 提取的费用列表

    Returns:
        完整的赔偿计算结果
    """
    items_template = INJURY_ITEMS if case_type == "injury" else DEATH_ITEMS
    result_items: List[Dict[str, Any]] = []

    # 确保参数类型正确
    p: Dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, float):
            p[k] = Decimal(str(v))
        else:
            p[k] = v

    for fee_type in items_template:
        item = calculate_item(fee_type, p, fee_items or [])
        result_items.append(item)

    # 序列化 Decimal → float/str（JSONB 兼容）
    def _serialize_item(item: Dict) -> Dict:
        out = dict(item)
        for k, v in out.items():
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, list):
                out[k] = [{kk: float(vv) if isinstance(vv, Decimal) else vv for kk, vv in d.items()} for d in v] if v and isinstance(v[0], dict) else v
        return out

    serialized_items = [_serialize_item(item) for item in result_items]

    # 计算合计
    total = sum(
        Decimal(str(item.get("manual_amount") or item.get("amount", 0)))
        for item in result_items
    )

    return {
        "items": serialized_items,
        "total_amount": float(total),
        "params": {k: str(v) if isinstance(v, Decimal) else v for k, v in p.items()},
        "calculated_at": datetime.now().isoformat(),
    }


def calculate_item(fee_type: str, params: Dict, fee_items: list) -> Dict:
    """计算单项赔偿费用"""
    calc_funcs: Dict[str, Any] = {
        "medical_fee": _calc_medical_fee,
        "lost_wages": _calc_lost_wages,
        "nursing_fee": _calc_nursing_fee,
        "food_subsidy": _calc_food_subsidy,
        "nutrition_fee": _calc_nutrition_fee,
        "disability_compensation": _calc_disability_compensation,
        "death_compensation": _calc_death_compensation,
        "funeral_fee": _calc_funeral_fee,
        "transport_fee": _calc_transport_fee,
        "spiritual_damage": _calc_spiritual_damage,
    }

    func = calc_funcs.get(fee_type)
    if func:
        return func(params, fee_items)

    return {
        "fee_type": fee_type,
        "fee_name": FEE_NAMES.get(fee_type, fee_type),
        "amount": Decimal("0"),
        "manual_amount": None,
        "calculation_basis": "",
        "is_manual": True,
        "sources": [],
    }


# ── 各项费用计算函数 ──

def _calc_medical_fee(params: Dict, fee_items: list) -> Dict:
    """医疗费 = 从 OCR 发票自动提取合计"""
    total = Decimal("0")
    sources: List[Dict[str, str]] = []

    for item in fee_items:
        ft = getattr(item, 'fee_type', '') if hasattr(item, 'fee_type') else item.get('fee_type', '')
        if ft in ('medical_fee', 'hospital_fee', 'outpatient_fee', 'pharmacy_fee'):
            amt = getattr(item, 'amount', 0) if hasattr(item, 'amount') else item.get('amount', 0)
            total += Decimal(str(amt))
            sources.append({
                "material_id": getattr(item, 'source_material_id', '') if hasattr(item, 'source_material_id') else item.get('source_material_id', ''),
                "filename": getattr(item, 'source_filename', '') if hasattr(item, 'source_filename') else item.get('source_filename', ''),
                "ocr_snippet": getattr(item, 'ocr_snippet', '') if hasattr(item, 'ocr_snippet') else item.get('ocr_snippet', ''),
            })

    basis = f"{len(sources)}份发票合计" if sources else "需手动输入或从发票提取"

    return {
        "fee_type": "medical_fee",
        "fee_name": "医疗费",
        "amount": total,
        "manual_amount": None,
        "calculation_basis": basis,
        "is_manual": total == 0,
        "sources": sources,
    }


def _calc_lost_wages(params: Dict, fee_items: list) -> Dict:
    """误工费 = 日均收入 × 误工天数"""
    days = int(params.get("lost_wage_days", 0) or params.get("hospital_days", 0))
    annual_income = Decimal(str(params.get("annual_income", 49283)))
    daily_income = (annual_income / 365).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amount = daily_income * days

    return {
        "fee_type": "lost_wages",
        "fee_name": "误工费",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"日均收入{daily_income}元 × {days}天" if days > 0 else "需输入误工天数",
        "is_manual": days == 0,
        "sources": [],
    }


def _calc_nursing_fee(params: Dict, fee_items: list) -> Dict:
    """护理费 = 住院天数 × 日护理费标准"""
    days = int(params.get("nursing_days", 0) or params.get("hospital_days", 0))
    monthly_salary = Decimal(str(params.get("monthly_salary", 8500)))
    daily_rate = (monthly_salary / 30).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amount = daily_rate * days

    return {
        "fee_type": "nursing_fee",
        "fee_name": "护理费",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"日均{daily_rate}元 × {days}天" if days > 0 else "需输入护理天数",
        "is_manual": days == 0,
        "sources": [],
    }


def _calc_food_subsidy(params: Dict, fee_items: list) -> Dict:
    """住院伙食补助费 = 住院天数 × 日标准"""
    days = int(params.get("hospital_days", 0))
    daily_std = Decimal(str(params.get("daily_food_subsidy", 100)))
    amount = daily_std * days

    return {
        "fee_type": "food_subsidy",
        "fee_name": "住院伙食补助费",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"{daily_std}元/天 × {days}天" if days > 0 else "需输入住院天数",
        "is_manual": days == 0,
        "sources": [],
    }


def _calc_nutrition_fee(params: Dict, fee_items: list) -> Dict:
    """营养费 = 营养期天数 × 日标准"""
    days = int(params.get("nutrition_days", 0) or params.get("hospital_days", 0))
    daily_std = Decimal(str(params.get("daily_nutrition", 30)))
    amount = daily_std * days

    return {
        "fee_type": "nutrition_fee",
        "fee_name": "营养费",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"{daily_std}元/天 × {days}天" if days > 0 else "需输入营养期天数",
        "is_manual": days == 0,
        "sources": [],
    }


def _calc_disability_compensation(params: Dict, fee_items: list) -> Dict:
    """残疾赔偿金 = 年收入 × 赔偿年限 × 伤残系数"""
    annual_income = Decimal(str(params.get("annual_income", 49283)))
    years = int(params.get("compensation_years", 20))
    coefficient = Decimal(str(params.get("disability_coefficient", 1.0)))
    amount = annual_income * years * coefficient

    return {
        "fee_type": "disability_compensation",
        "fee_name": "残疾赔偿金",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"{annual_income}元/年 × {years}年 × {coefficient}",
        "is_manual": False,
        "sources": [],
    }


def _calc_death_compensation(params: Dict, fee_items: list) -> Dict:
    """死亡赔偿金 = 年收入 × 赔偿年限"""
    annual_income = Decimal(str(params.get("annual_income", 49283)))
    years = int(params.get("compensation_years", 20))
    amount = annual_income * years

    return {
        "fee_type": "death_compensation",
        "fee_name": "死亡赔偿金",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"{annual_income}元/年 × {years}年",
        "is_manual": False,
        "sources": [],
    }


def _calc_funeral_fee(params: Dict, fee_items: list) -> Dict:
    """丧葬费 = 职工月均工资 × 6个月"""
    monthly_salary = Decimal(str(params.get("monthly_salary", 8500)))
    amount = monthly_salary * 6

    return {
        "fee_type": "funeral_fee",
        "fee_name": "丧葬费",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"{monthly_salary}元/月 × 6个月",
        "is_manual": False,
        "sources": [],
    }


def _calc_transport_fee(params: Dict, fee_items: list) -> Dict:
    """交通住宿费 = 手动输入"""
    return {
        "fee_type": "transport_fee",
        "fee_name": "交通住宿费",
        "amount": Decimal("0"),
        "manual_amount": None,
        "calculation_basis": "根据实际票据手动填写",
        "is_manual": True,
        "sources": [],
    }


def _calc_spiritual_damage(params: Dict, fee_items: list) -> Dict:
    """精神损害抚慰金 = 根据伤残等级估算"""
    coefficient = Decimal(str(params.get("disability_coefficient", 1.0)))
    # 上限5万，按伤残系数比例
    base = Decimal("50000")
    amount = (base * coefficient).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    return {
        "fee_type": "spiritual_damage",
        "fee_name": "精神损害抚慰金",
        "amount": amount,
        "manual_amount": None,
        "calculation_basis": f"按伤残系数{coefficient}估算（上限5万元）",
        "is_manual": False,
        "sources": [],
    }
