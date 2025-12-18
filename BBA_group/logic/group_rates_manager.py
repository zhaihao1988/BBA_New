"""
组级利率曲线管理器 (Group Rate Curve Manager)

核心功能：
1. 构建合同组维度的多期利率曲线（基于CSM权重）
2. 递归更新组级利率曲线（跨月份加权平均）
3. 根据评估月份获取对应的组级利率

对应文档：第1.5节（扩展版）
"""

from decimal import Decimal
from typing import Dict, Optional, Any, List
import pandas as pd
from BBA_group.models.group_cohort_state import GroupCohortState
from BBA_group.models.group_policy_state import GroupPolicyState


def build_group_rate_curve(
    cohort_state: GroupCohortState,
    policies: List[GroupPolicyState],
    rates_history: Dict[str, pd.DataFrame],
    logger: Optional[Any] = None
) -> Dict[int, Decimal]:
    """
    构建合同组维度的利率曲线
    
    算法：
    1. 找到组内第一个保单的签单月份，作为第一期
    2. 使用该保单签单月份的利率曲线作为初始组级利率曲线
    3. 按签单月份顺序，递归更新组级利率曲线
    
    Args:
        cohort_state: 组级合同组状态
        policies: 组内所有保单的状态列表（按签单月份排序）
        rates_history: 历史利率曲线字典（月份 -> DataFrame）
        logger: 日志记录器（可选）
        
    Returns:
        Dict[int, Decimal]: 组级利率曲线（期数 -> 利率）
    """
    if not policies:
        return {}
    
    # 过滤出有CSM的保单（CSM > 0），只有盈利保单才参与利率曲线构建
    profitable_policies = [p for p in policies if p.initial_csm_for_weight > 0]
    
    if not profitable_policies:
        if logger:
            logger.log_item(
                "组级利率曲线构建失败",
                "组内没有盈利保单（CSM > 0），无法构建组级利率曲线",
                "",
                {},
                Decimal('0'),
                note="只有盈利保单（CSM > 0）才参与利率曲线构建"
            )
        return {}
    
    # 按签单月份排序
    sorted_policies = sorted(profitable_policies, key=lambda p: p.uw_month_str or '')
    
    # 初始化：使用第一个盈利保单的签单月份作为基准
    first_policy = sorted_policies[0]
    base_month = first_policy.uw_month_str
    
    if not base_month:
        if logger:
            logger.log_item(
                "组级利率曲线构建失败",
                "第一个保单缺少签单月份信息",
                "",
                {},
                Decimal('0'),
                note="无法构建组级利率曲线"
            )
        return {}
    
    cohort_state.group_rate_curve_base_month = base_month
    
    # 获取第一个保单签单月份的利率曲线
    if base_month not in rates_history:
        if logger:
            logger.log_item(
                "组级利率曲线构建失败",
                f"缺少{base_month}月份的利率曲线数据",
                "",
                {},
                Decimal('0'),
                note="无法构建组级利率曲线"
            )
        return {}
    
    first_rates_df = rates_history[base_month]
    
    # 初始化组级利率曲线（使用第一个盈利保单的利率曲线）
    group_curve = {}
    group_csm_weights = {}
    
    for _, row in first_rates_df.iterrows():
        term = int(row['term_month'])
        rate = Decimal(str(row['forward_disrate_value']))
        group_curve[term] = rate
        # 初始权重为该保单的CSM
        group_csm_weights[term] = first_policy.initial_csm_for_weight
    
    cohort_state.group_rate_curve = group_curve
    cohort_state.group_rate_curve_csm_weights = group_csm_weights.copy()
    cohort_state.total_csm_weight = first_policy.initial_csm_for_weight
    cohort_state.policy_csm_weights[first_policy.policy_no] = first_policy.initial_csm_for_weight
    
    if logger:
        logger.log_item(
            "组级利率曲线初始化",
            f"使用{base_month}月份作为基准月份",
            f"基准月份: {base_month}, 初始CSM权重: {first_policy.initial_csm_for_weight}",
            {
                "基准月份": base_month,
                "初始CSM权重": first_policy.initial_csm_for_weight,
                "利率曲线期数": len(group_curve)
            },
            Decimal('0'),
            note=f"组级利率曲线已初始化，共{len(group_curve)}期"
        )
    
    # 递归更新：处理后续盈利保单
    for policy in sorted_policies[1:]:
        # 只处理有CSM的保单
        if policy.initial_csm_for_weight > 0:
            update_group_rate_curve(
                cohort_state,
                policy,
                rates_history,
                logger
            )
    
    return cohort_state.group_rate_curve


def update_group_rate_curve(
    cohort_state: GroupCohortState,
    new_policy: GroupPolicyState,
    rates_history: Dict[str, pd.DataFrame],
    logger: Optional[Any] = None
) -> Dict[int, Decimal]:
    """
    递归更新组级利率曲线
    
    算法：
    对于第N期（N = 新保单签单月份 - 基准月份 + 1）：
    - 旧曲线第N期利率 × 旧CSM权重 + 新曲线第1期利率 × 新CSM权重
    - 除以总CSM权重
    
    对于后续期数，需要对应调整
    
    Args:
        cohort_state: 组级合同组状态
        new_policy: 新加入的保单
        rates_history: 历史利率曲线字典
        logger: 日志记录器（可选）
        
    Returns:
        Dict[int, Decimal]: 更新后的组级利率曲线
    """
    if not cohort_state.group_rate_curve_base_month:
        # 如果还没有初始化，先初始化
        return build_group_rate_curve(cohort_state, [new_policy], rates_history, logger)
    
    # 只处理有CSM的保单
    if new_policy.initial_csm_for_weight <= 0:
        if logger:
            logger.log_item(
                "组级利率曲线更新跳过",
                f"保单{new_policy.policy_no}为亏损保单（CSM <= 0），不参与利率曲线更新",
                "",
                {},
                Decimal('0'),
                note="只有盈利保单（CSM > 0）才参与利率曲线构建"
            )
        return cohort_state.group_rate_curve
    
    new_month = new_policy.uw_month_str
    if not new_month:
        return cohort_state.group_rate_curve
    
    if new_month not in rates_history:
        if logger:
            logger.log_item(
                "组级利率曲线更新失败",
                f"缺少{new_month}月份的利率曲线数据",
                "",
                {},
                Decimal('0'),
                note=f"保单{new_policy.policy_no}无法更新组级利率曲线"
            )
        return cohort_state.group_rate_curve
    
    # 计算新保单对应的期数
    base_year = int(cohort_state.group_rate_curve_base_month[:4])
    base_month = int(cohort_state.group_rate_curve_base_month[4:])
    new_year = int(new_month[:4])
    new_month_num = int(new_month[4:])
    
    new_term = (new_year - base_year) * 12 + (new_month_num - base_month) + 1
    
    # 获取新保单签单月份的利率曲线
    new_rates_df = rates_history[new_month]
    
    # 旧CSM权重
    old_csm_weight = cohort_state.total_csm_weight
    # 新CSM权重
    new_csm_weight = new_policy.initial_csm_for_weight
    # 总CSM权重
    total_csm_weight = old_csm_weight + new_csm_weight
    
    # 更新组级利率曲线
    updated_curve = {}
    updated_weights = {}
    
    # 获取新曲线第一期的利率
    new_rate_first = Decimal('0')
    if not new_rates_df.empty:
        first_row = new_rates_df.iloc[0]
        if int(first_row['term_month']) == 1:
            new_rate_first = Decimal(str(first_row['forward_disrate_value']))
    
    # 更新每一期
    max_term = max(
        max(cohort_state.group_rate_curve.keys()) if cohort_state.group_rate_curve else 0,
        max(new_rates_df['term_month']) if not new_rates_df.empty else 0
    )
    
    for term in range(1, int(max_term) + 1):
        # 旧曲线该期利率
        old_rate = cohort_state.group_rate_curve.get(term, Decimal('0'))
        old_weight = cohort_state.group_rate_curve_csm_weights.get(term, Decimal('0'))
        
        # 新曲线对应期数
        # 如果term == new_term，使用新曲线第一期
        # 如果term > new_term，使用新曲线的(term - new_term + 1)期
        if term == new_term:
            new_rate = new_rate_first
        elif term > new_term:
            # 查找新曲线中对应的期数
            new_curve_term = term - new_term + 1
            new_rate_row = new_rates_df[new_rates_df['term_month'] == new_curve_term]
            if not new_rate_row.empty:
                new_rate = Decimal(str(new_rate_row.iloc[0]['forward_disrate_value']))
            else:
                new_rate = Decimal('0')
        else:
            # term < new_term，新曲线不贡献该期
            new_rate = Decimal('0')
        
        # 加权平均
        if total_csm_weight > 0:
            updated_rate = (old_rate * old_weight + new_rate * new_csm_weight) / total_csm_weight
        else:
            updated_rate = old_rate if old_weight > 0 else new_rate
        
        updated_curve[term] = updated_rate
        updated_weights[term] = total_csm_weight
    
    # 更新cohort_state
    cohort_state.group_rate_curve = updated_curve
    cohort_state.group_rate_curve_csm_weights = updated_weights
    cohort_state.total_csm_weight = total_csm_weight
    cohort_state.policy_csm_weights[new_policy.policy_no] = new_csm_weight
    
    if logger:
        logger.log_item(
            f"组级利率曲线更新（{new_month}）",
            f"新保单{new_policy.policy_no}加入，更新第{new_term}期及后续期数",
            f"旧CSM权重: {old_csm_weight}, 新CSM权重: {new_csm_weight}, 总权重: {total_csm_weight}",
            {
                "新保单签单月份": new_month,
                "对应期数": new_term,
                "旧CSM权重": old_csm_weight,
                "新CSM权重": new_csm_weight,
                "总CSM权重": total_csm_weight
            },
            Decimal('0'),
            note=f"组级利率曲线已更新，共{len(updated_curve)}期"
        )
    
    return cohort_state.group_rate_curve


def get_group_rate_for_term(
    cohort_state: GroupCohortState,
    term: int
) -> Decimal:
    """
    根据期数获取组级利率
    
    Args:
        cohort_state: 组级合同组状态
        term: 期数（从1开始）
        
    Returns:
        Decimal: 该期数的组级利率
    """
    return cohort_state.get_rate_for_term(term)


def get_group_rate_for_valuation_month(
    cohort_state: GroupCohortState,
    valuation_month: str
) -> Decimal:
    """
    根据评估月份获取对应的组级利率
    
    Args:
        cohort_state: 组级合同组状态
        valuation_month: 评估月份（格式：YYYYMM）
        
    Returns:
        Decimal: 对应的组级利率
    """
    return cohort_state.get_rate_for_valuation_month(valuation_month)

