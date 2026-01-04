"""
PV字段中文描述工具

用于将PV字段名转换为中文描述，供日志输出使用。
"""

SEGMENT_TRANSLATIONS = {
    "Nb": "新增合同",
    "If": "有效合同",
    "Ini": "初始确认",
    "Bop": "年初预期",
    "Eop": "期末预期",
    "Cca": "预期当期",
    "Cfa": "预期未来",
    "Rec": "初始确认现值",
    "Rep": "期末现值",
    "Beg": "年初现值",
    "Lkd": "锁定利率", # Renamed from Wlk (was "加权初始确认利率")
    "Cur": "期末利率",
    "Lcu": "上年期末利率",
    "Pre": "保费现金流",
    "Acq": "保险获取现金流",
    "Cla": "赔付现金流",
    "Mtn": "维持费用现金流",
    "Rad": "未到期非金融风险调整",
    "Ors": "新增当期过去合同",
    "Exr": "经验调整",
    "Surre": "退保合同",
}


def describe_field(field_name: str) -> str:
    """
    将PV字段名转换为中文描述
    
    Args:
        field_name: PV字段名，如 "Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt"
    
    Returns:
        中文描述，如 "新增合同 - 初始确认 - 预期未来 - 初始确认现值 - 锁定利率 - 赔付现金流"
    """
    # 移除 "Pvfl_" 前缀和 "_Amt" 后缀
    if field_name.startswith("Pvfl_"):
        field_name = field_name[5:]  # 移除 "Pvfl_"
    if field_name.endswith("_Amt"):
        field_name = field_name[:-4]  # 移除 "_Amt"
    
    parts = field_name.split("_")
    desc_parts = []
    for part in parts:
        translated = SEGMENT_TRANSLATIONS.get(part)
        if translated:
            desc_parts.append(translated)
    
    return " - ".join(desc_parts) if desc_parts else field_name


def format_pv_field_in_formula(field_name: str) -> str:
    """
    在公式中格式化PV字段，显示为中文描述
    
    Args:
        field_name: PV字段名
    
    Returns:
        格式化的公式字符串，如 "新增合同-初始确认-预期未来-初始确认现值-锁定利率-赔付现金流"
    """
    desc = describe_field(field_name)
    return desc.replace(" - ", "-")  # 在公式中使用短横线连接