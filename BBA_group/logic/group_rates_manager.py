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


def _ym_to_index(ym: str) -> int:
    """
    将 'YYYYMM' 转换为整数索引（便于计算月份差）
    例如：202005 -> 2020 * 12 + 5
    """
    year = int(ym[:4])
    month = int(ym[4:])
    return year * 12 + month


def build_group_rate_curve(
    cohort_state: GroupCohortState,
    policies: List[GroupPolicyState],
    rates_history: Dict[str, pd.DataFrame],
    logger: Optional[Any] = None
) -> Dict[int, Decimal]:
    """
    构建合同组维度的 **加权锁定利率曲线（Wlk）**
    
    核心要求（与用户口径对齐）：
    - 以组内 **最早初始确认月份** 作为第1期；
    - 第k期对应：最早月份往后第 k-1 个自然月；
    - 每一期的利率 = 所有在该月之前（含当月）已初始确认的保单，
      使用各自 **初始确认CSM** 作为固定权重，
      对其利率曲线上“从自身初始确认月起算的对应期数”的月化远期利率做 **CSM 加权平均**；
    - 若某保单的利率曲线在该offset期已经没有数据，则该保单在该期不参与加权。
    
    Args:
        cohort_state: 组级合同组状态
        policies: 组内所有保单的状态列表
        rates_history: 历史利率曲线字典（'YYYYMM' -> DataFrame(term_month, forward_disrate_value)）
        logger: 日志记录器（可选）
        
    Returns:
        Dict[int, Decimal]: 组级Wlk曲线（期数 -> 月化远期利率）
    """
    if not policies:
        return {}

    # 仅盈利保单参与组级Wlk构建（CSM > 0）
    profitable_policies: List[GroupPolicyState] = [
        p for p in policies
        if getattr(p, "initial_csm_for_weight", Decimal("0")) > 0 and p.uw_month_str
    ]

    if not profitable_policies:
        if logger:
            logger.log_item(
                "组级Wlk曲线构建失败",
                "组内没有盈利保单（initial_csm_for_weight > 0），无法构建组级Wlk曲线",
                "",
                {},
                Decimal("0"),
                note="只有盈利保单（CSM > 0）才参与组级利率曲线构建"
            )
        return {}

    # 按初始确认月份排序
    profitable_policies.sort(key=lambda p: p.uw_month_str)

    # 基准月份：组内最早的初始确认月份
    base_month = profitable_policies[0].uw_month_str
    cohort_state.group_rate_curve_base_month = base_month

    # 预先检查并缓存每个参与保单的利率曲线及索引
    policy_infos = []
    base_idx = _ym_to_index(base_month)

    for p in profitable_policies:
        uw_month = p.uw_month_str
        if uw_month not in rates_history:
            if logger:
                logger.log_item(
                    "组级Wlk曲线构建警告",
                    f"缺少 {uw_month} 月份的利率曲线数据，保单 {p.policy_no} 不参与Wlk构建",
                    "",
                    {},
                    Decimal("0"),
                    note="请检查利率曲线配置"
                )
            continue

        df = rates_history[uw_month]
        if df.empty:
            continue

        uw_idx = _ym_to_index(uw_month)
        max_term = int(df["term_month"].max())
        last_idx = uw_idx + max_term - 1  # 该保单曲线能支持到的最后自然月

        rates_map = {
            int(row["term_month"]): Decimal(str(row["forward_disrate_value"]))
            for _, row in df.iterrows()
        }

        policy_infos.append(
            {
                "policy": p,
                "uw_month": uw_month,
                "uw_idx": uw_idx,
                "max_term": max_term,
                "last_idx": last_idx,
                "rates_map": rates_map,
                "csm": getattr(p, "initial_csm_for_weight", Decimal("0")),
            }
        )

    if not policy_infos:
        if logger:
            logger.log_item(
                "组级Wlk曲线构建失败",
                "所有盈利保单均缺少可用利率曲线，无法构建组级Wlk曲线",
                "",
                {},
                Decimal("0"),
                note="请检查利率曲线配置"
            )
        return {}

    # 组级曲线最大自然月：所有保单中最晚可支持的月份
    max_last_idx = max(info["last_idx"] for info in policy_infos)
    max_group_term = max_last_idx - base_idx + 1  # 组级曲线总期数

    group_curve: Dict[int, Decimal] = {}
    group_csm_weights: Dict[int, Decimal] = {}

    # 按“自然月”循环，每个自然月对应组级曲线中的一个期数
    for term in range(1, max_group_term + 1):
        current_idx = base_idx + (term - 1)
        numerator = Decimal("0")
        denom = Decimal("0")

        for info in policy_infos:
            csm = info["csm"]
            if csm <= 0:
                continue

            # 仅当该保单已在当前自然月之前初始确认时，才参与该期加权
            if current_idx < info["uw_idx"]:
                continue

            # 该保单从自身初始确认月算起的期数 offset（从1开始）
            offset = current_idx - info["uw_idx"] + 1
            if offset <= 0 or offset > info["max_term"]:
                # 超出该保单利率曲线范围，不参与该期
                continue

            rate = info["rates_map"].get(offset)
            if rate is None:
                continue

            numerator += csm * rate
            denom += csm

        if denom > 0:
            group_rate = numerator / denom
        else:
            group_rate = Decimal("0")

        group_curve[term] = group_rate
        group_csm_weights[term] = denom

    # 汇总CSM权重（用于日志和后续可能的检查）
    total_csm_weight = sum(info["csm"] for info in policy_infos)
    cohort_state.group_rate_curve = group_curve
    cohort_state.group_rate_curve_csm_weights = group_csm_weights
    cohort_state.total_csm_weight = total_csm_weight

    # 记录保单级CSM权重
    for info in policy_infos:
        p: GroupPolicyState = info["policy"]
        cohort_state.policy_csm_weights[p.policy_no] = info["csm"]

    if logger:
        logger.log_item(
            "组级Wlk利率曲线构建完成",
            "基于组内各保单初始确认CSM的加权锁定利率曲线",
            (
                "第1期 = 最早初始确认月份的加权利率；"
                "第k期对应自然月=最早月份向后第k-1个月；"
                "每期利率 = 所有已存在保单在该月对应offset期的利率，"
                "按初始确认CSM加权平均"
            ),
            {
                "基准月份（第1期）": base_month,
                "期数总数": len(group_curve),
                "参与保单数量": len(policy_infos),
                "累计CSM权重": total_csm_weight,
            },
            Decimal("0"),
            note="已将组级Wlk曲线写入 GroupCohortState.group_rate_curve（期数 -> 月化远期利率）"
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

