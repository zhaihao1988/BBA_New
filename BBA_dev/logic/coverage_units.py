"""
覆盖单元动态比例法 (Coverage Units Dynamic Ratio)

对应文档：第8.2节 CSM摊销比例计算（覆盖单元动态比例法）

核心功能：
1. 计算本期释放的覆盖单元（CU_released）
2. 计算期末剩余服务期的覆盖单元（CU_remaining）
3. 计算CSM摊销比例：Ratio = CU_released / (CU_released + CU_remaining)

关键特性：
- 逐月动态计算，反映合同组内保单的新增、退保和期限差异
- 合同组层面聚合所有有效保单的覆盖单元
- 优先使用保额，若缺乏保额数据则使用签单保费作为替代
"""

from decimal import Decimal
from datetime import date
from typing import List, Optional, Any
from BBA_dev.models import PolicyState


def calculate_coverage_units_released(
    policies: List[PolicyState],
    valuation_date: date,
    start_of_year: date,
    logger: Optional[Any] = None,
    is_initial_year: bool = False
) -> Decimal:
    """
    计算本期释放的覆盖单元（CU_released）
    
    对应文档：第8.2节
    
    公式：
        CU_released = Σ(保额或签单保费 × 服务天数)
    
    其中：
        服务天数 = Min(评估日, 保单止期) - Max(年初日期, 保单起期) + 1
    
    Args:
        policies: 合同组内所有有效保单的状态列表
        valuation_date: 评估日期（期末日期）
        start_of_year: 年初日期（期初日期）
        is_initial_year: 是否为初始确认年度，用于追溯释放
        logger: 日志记录器（可选）
        
    Returns:
        Decimal: 本期释放的覆盖单元总和
    """
    cu_released = Decimal('0')
    
    for policy in policies:
        # 判断保单在评估期内是否有效
        if policy.end_date < start_of_year or policy.start_date > valuation_date:
            # 保单不在评估期内，跳过
            continue
        
        # 计算服务天数
        # 关键修改：使用保修结束日期（warranty_end_date）而不是起保日期（start_date）
        # 在保修期内，覆盖单元应该是0
        warranty_end = getattr(policy, 'warranty_end_date', None) or policy.start_date
        
        # 判断是否在保修期内
        is_in_warranty = valuation_date < warranty_end
        
        # 服务起期：取保修结束日期和年初日期的较大值
        if is_initial_year:
            service_start = warranty_end
        else:
            service_start = max(warranty_end, start_of_year)
        service_end = min(policy.end_date, valuation_date)
        
        # 如果评估日期在保修期内，服务天数应该是0
        if is_in_warranty:
            service_days = 0
            service_start = warranty_end  # 在保修期内，服务起期显示为保修结束日期
            service_end = valuation_date  # 服务止期显示为评估日期
        elif service_end < service_start:
            service_days = 0
        else:
            service_days = (service_end - service_start).days + 1
        
        # 获取覆盖单元基数（优先使用保额，若缺乏则使用签单保费）
        # 注意：当前 PolicyState 中没有保额字段，暂时使用签单保费
        coverage_base = policy.written_premium
        
        # 计算该保单的覆盖单元
        policy_cu = coverage_base * Decimal(service_days)
        cu_released += policy_cu
        
        if logger:
            # 构建说明信息
            if is_in_warranty:
                note = f"评估日期（{valuation_date}）在保修期内（保修结束日期：{warranty_end}），服务天数为0"
            elif service_days == 0:
                note = f"服务止期（{service_end}）早于服务起期（{service_start}），服务天数为0"
            else:
                note = f"服务期间：{service_start} 至 {service_end}"
            
            logger.log_item(
                f"保单 {policy.policy_no} 覆盖单元释放",
                "[Sec 8.2] 本期释放的覆盖单元",
                "保额（或签单保费）× 服务天数",
                {
                    "保单号": policy.policy_no,
                    "签单保费": coverage_base,
                    "服务天数": service_days,
                    "服务起期": service_start,
                    "服务止期": service_end,
                    "保修结束日期": warranty_end,
                    "评估日期": valuation_date
                },
                policy_cu,
                note=note
            )
    
    if logger:
        logger.log_item(
            "本期释放的覆盖单元合计",
            "[Sec 8.2] CU_released = Σ(保额或签单保费 × 服务天数)",
            "合同组内所有有效保单的覆盖单元之和",
            {"保单数量": len(policies)},
            cu_released,
            note=("本期（当月）该合同组内所有有效保单释放的覆盖单元之和"
                  if not is_initial_year else "首年包含起保日至评估日的累计服务（含追溯月份）")
        )
    
    return cu_released


def calculate_coverage_units_remaining(
    policies: List[PolicyState],
    valuation_date: date,
    logger: Optional[Any] = None
) -> Decimal:
    """
    计算期末剩余服务期的覆盖单元（CU_remaining）
    
    对应文档：第8.2节
    
    公式：
        CU_remaining = Σ(保额或签单保费 × 剩余服务天数)
    
    其中：
        剩余服务天数 = 保单止期 - 评估日
    
    Args:
        policies: 合同组内所有有效保单的状态列表
        valuation_date: 评估日期（期末日期）
        logger: 日志记录器（可选）
        
    Returns:
        Decimal: 期末剩余服务期的覆盖单元总和
    """
    cu_remaining = Decimal('0')
    
    for policy in policies:
        # 判断保单在期末是否仍有效
        if policy.end_date <= valuation_date:
            # 保单已满期，无剩余服务期
            continue
        
        # 关键修改：使用保修结束日期（warranty_end_date）而不是起保日期（start_date）
        # 剩余服务天数应该从保修结束日期开始计算，而不是从起保日期
        warranty_end = getattr(policy, 'warranty_end_date', None) or policy.start_date
        
        # 判断是否在保修期内
        is_in_warranty = valuation_date < warranty_end
        
        # 如果评估日期在保修期内，剩余服务天数应该从保修结束日期开始计算
        if is_in_warranty:
            # 评估日期在保修期内，剩余服务天数从保修结束日期开始
            remaining_days = (policy.end_date - warranty_end).days
            service_start_note = warranty_end
        else:
            # 评估日期在保修期后，剩余服务天数从评估日期开始
            remaining_days = (policy.end_date - valuation_date).days
            service_start_note = valuation_date
        
        if remaining_days <= 0:
            continue
        
        # 获取覆盖单元基数（优先使用保额，若缺乏则使用签单保费）
        coverage_base = policy.written_premium
        
        # 计算该保单的剩余覆盖单元
        policy_cu = coverage_base * Decimal(remaining_days)
        cu_remaining += policy_cu
        
        if logger:
            # 构建说明信息
            if is_in_warranty:
                note = f"评估日期（{valuation_date}）在保修期内（保修结束日期：{warranty_end}），剩余服务天数从保修结束日期开始计算"
            else:
                note = f"评估日期（{valuation_date}）在保修期后，剩余服务天数从评估日期开始计算"
            
            logger.log_item(
                f"保单 {policy.policy_no} 剩余覆盖单元",
                "[Sec 8.2] 期末剩余服务期的覆盖单元",
                "保额（或签单保费）× 剩余服务天数",
                {
                    "保单号": policy.policy_no,
                    "签单保费": coverage_base,
                    "剩余服务天数": remaining_days,
                    "保单止期": policy.end_date,
                    "评估日期": valuation_date,
                    "保修结束日期": warranty_end,
                    "服务起算日期": service_start_note
                },
                policy_cu,
                note=note
            )
    
    if logger:
        logger.log_item(
            "期末剩余服务期的覆盖单元合计",
            "[Sec 8.2] CU_remaining = Σ(保额或签单保费 × 剩余服务天数)",
            "合同组内所有有效保单的剩余覆盖单元之和",
            {"保单数量": len(policies)},
            cu_remaining,
            note="期末时点，该合同组内所有有效保单剩余服务期的覆盖单元之和"
        )
    
    return cu_remaining


def calculate_csm_amortization_ratio(
    policies: List[PolicyState],
    valuation_date: date,
    start_of_year: date,
    logger: Optional[Any] = None,
    is_initial_year: bool = False
) -> Decimal:
    """
    计算CSM摊销比例（覆盖单元动态比例法）
    
    对应文档：第8.2节
    
    公式：
        Ratio_Amort = CU_released / (CU_released + CU_remaining)
    
    其中：
        CU_released: 本期释放的覆盖单元
        CU_remaining: 期末剩余服务期的覆盖单元
    
    关键特性：
    - 逐月动态计算，反映合同组内保单的新增、退保和期限差异
    - 合同组层面聚合所有有效保单的覆盖单元
    - 自动适应：新单加入时自动增加权重，退保时自动减少权重
    
    Args:
        policies: 合同组内所有有效保单的状态列表
        valuation_date: 评估日期（期末日期）
        start_of_year: 年初日期（期初日期）
        is_initial_year: 是否为初始确认年度（决定是否追溯起保日）
        logger: 日志记录器（可选）
        
    Returns:
        Decimal: CSM摊销比例（0-1之间）
    """
    # 计算本期释放的覆盖单元
    cu_released = calculate_coverage_units_released(
        policies, valuation_date, start_of_year, logger, is_initial_year=is_initial_year
    )
    
    # 计算期末剩余服务期的覆盖单元
    cu_remaining = calculate_coverage_units_remaining(
        policies, valuation_date, logger
    )
    
    # 计算摊销比例
    denominator = cu_released + cu_remaining
    
    if denominator > 0:
        ratio = cu_released / denominator
    else:
        ratio = Decimal('0')
        if logger:
            logger.log_item(
                "CSM摊销比例计算（特殊情况）",
                "[Sec 8.2] 分母为0，摊销比例为0",
                "Ratio = 0 (当 CU_released + CU_remaining = 0)",
                {
                    "CU_released": cu_released,
                    "CU_remaining": cu_remaining
                },
                ratio,
                note="所有保单已满期或无效，无需摊销"
            )
    
    if logger:
        logger.log_item(
            "CSM摊销比例",
            "[Sec 8.2] Ratio_Amort = CU_released / (CU_released + CU_remaining)",
            "覆盖单元动态比例法",
            {
                "CU_released": cu_released,
                "CU_remaining": cu_remaining,
                "Denominator": denominator
            },
            ratio,
            note="逐月动态计算，反映合同组内保单的新增、退保和期限差异"
        )
    
    return ratio


