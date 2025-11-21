"""
CSM计息逻辑 (CSM Interest Accretion)

对应文档：第6节 CSM计息

核心功能：
1. 使用加权初始确认利率（锁定利率）进行计息（文档 Sec 6.1）
2. 需区分期初有效合同 (IF) 与当年新增合同 (NB)
3. 新增合同需根据初始确认时点（月末）进行计息调整（文档 Sec 6.5）
"""

from decimal import Decimal
from datetime import datetime, date
from typing import Tuple
from dateutil.relativedelta import relativedelta
from bba_model.models import CohortState, PolicyState
from bba_model.utils.math_tools import get_accretion_rate_factor


def calculate_interest_with_curve(
    principal: Decimal,
    rates_df,
    start_month: int,
    end_month: int
) -> Tuple[Decimal, Decimal]:
    """
    使用锁定利率曲线分段累乘计算利息
    """
    factor = get_accretion_rate_factor(rates_df, start_month, end_month)
    if principal is None or principal == Decimal('0') or factor == 0:
        return Decimal('0'), factor
    return principal * factor, factor


def months_between(start_date: date, end_date: date) -> int:
    """
    计算两个日期之间包含的自然月数（按月粒度）
    """
    if not start_date or not end_date or start_date >= end_date:
        return 0
    delta = relativedelta(end_date, start_date)
    months = delta.years * 12 + delta.months
    if end_date.day >= start_date.day:
        months += 1
    return max(months, 0)


def run(context, logger, cohort_state: CohortState = None, policy_state: PolicyState = None):
    """
    执行CSM计息
    
    对应文档：第6节
    
    关键修正：必须使用 CohortState.weighted_locked_rate（加权锁定利率）进行计息，
    而不是即期利率。
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态（包含加权锁定利率）
        policy_state: 保单状态（可选，用于判断合同是否失效）
    """
    logger.log_section("Part 3: CSM计息 (Interest Accretion) [Sec 6]")
    _ = policy_state  # 参数保留以兼容旧接口

    # 确定评估日期
    if not hasattr(context, 'eop_date') or context.eop_date is None:
        context.eop_date = datetime(context.year, 12, 31).date()
    
    # [Sec 6.1] 获取锁定利率曲线（初始确认）
    locked_curve = getattr(context, 'rates_df_locked', None)
    if locked_curve is None:
        locked_curve = getattr(context, 'rates_df', None)
    if locked_curve is None:
        logger.log_item(
            "锁定利率曲线缺失",
            "[Sec 6.1] 未提供锁定利率曲线，计息结果为0",
            "Locked Curve = None",
            {},
            Decimal('0'),
            note="请检查 context.rates_df_locked 的赋值"
        )
        return
    
    logger.log_item(
        "锁定利率曲线（计息）",
        "[Sec 6.1] 使用初始锁定利率曲线进行累乘计息",
        "Factor = Π(1 + r_i) - 1",
        {
            "Curve Points": len(locked_curve)
        },
        Decimal('0'),
        note="r_i 为锁定曲线的月度远期利率，乘积区间取决于本期服务月份"
    )

    bop_csm = getattr(context, 'bop_csm', None)
    bop_lc = getattr(context, 'bop_lc', None)
    if bop_csm is None and cohort_state:
        bop_csm = cohort_state.bop_csm
    if bop_lc is None and cohort_state:
        bop_lc = cohort_state.bop_lc
    nb_initial_csm = context.nb_initial_csm or Decimal('0')
    nb_initial_lc = context.nb_initial_lc or Decimal('0')
    
    months_if = context.months_passed or 0
    start_idx_if = getattr(context, 'cumulative_months_start', 0)
    end_idx_if = getattr(context, 'cumulative_months_end', start_idx_if + months_if)
    nb_months = months_between(getattr(context, 'under_write_date', None), context.eop_date)
    if context.eop_date and getattr(context, 'under_write_date', None):
        if context.under_write_date.year != context.eop_date.year:
            nb_months = 0
    
    if_interest_csm, if_factor = calculate_interest_with_curve(bop_csm or Decimal('0'), locked_curve, start_idx_if, end_idx_if)
    nb_interest_csm, nb_factor = calculate_interest_with_curve(nb_initial_csm, locked_curve, 0, nb_months)
    
    if bop_csm and bop_csm != Decimal('0'):
        logger.log_item(
            "期初存量_CSM计息",
            "[Sec 6.4] 期初有效合同CSM随时间推移产生的利息",
            "IF_CSM_beg × (PRODUCT(1 + r_t) - 1)",
            {
                "IF_CSM_beg": bop_csm,
                "Start Month": start_idx_if,
                "End Month": end_idx_if,
                "Months": months_if,
                "Factor": if_factor
            },
            if_interest_csm,
            note="计息期间：年初至年末；r_t 为锁定曲线上对应期间的月度远期利率"
        )
    
    if nb_initial_csm > 0:
        logger.log_item(
            "当年新增合同_CSM计息",
            "[Sec 6.5] 新增合同CSM随时间推移产生的利息（使用锁定利率）",
            "NB_CSM_new × (PRODUCT(1 + r_t) - 1)",
            {
                "NB_CSM_new": nb_initial_csm,
                "Start Month": 0,
                "End Month": nb_months,
                "Months (t_init)": nb_months,
                "Factor": nb_factor
            },
            nb_interest_csm,
            note="计息期间：初始确认日 → 年底；r_t 为锁定曲线上对应期间的月度远期利率"
        )
    
    # LC 计息
    if_interest_lc, if_factor_lc = calculate_interest_with_curve(bop_lc or Decimal('0'), locked_curve, start_idx_if, end_idx_if)
    nb_interest_lc, nb_factor_lc = calculate_interest_with_curve(nb_initial_lc, locked_curve, 0, nb_months)
    
    if bop_lc and bop_lc != Decimal('0'):
        logger.log_item(
            "期初存量_LC计息",
            "[Sec 6.4] 期初亏损成分随时间推移产生的利息",
            "IF_LC_beg × (PRODUCT(1 + r_t) - 1)",
            {
                "IF_LC_beg": bop_lc,
                "Start Month": start_idx_if,
                "End Month": end_idx_if,
                "Months": months_if,
                "Factor": if_factor_lc
            },
            if_interest_lc
        )
    
    if nb_initial_lc > 0:
        logger.log_item(
            "当年新增合同_LC计息",
            "[Sec 6.5] 新增合同亏损成分随时间推移产生的利息（使用锁定利率）",
            "NB_LC_new × (PRODUCT(1 + r_t) - 1)",
            {
                "NB_LC_new": nb_initial_lc,
                "Start Month": 0,
                "End Month": nb_months,
                "Months (t_init)": nb_months,
                "Factor": nb_factor_lc
            },
            nb_interest_lc
        )
    
    context.if_interest_csm = if_interest_csm
    context.if_interest_lc = if_interest_lc
    context.nb_interest_csm = nb_interest_csm
    context.nb_interest_lc = nb_interest_lc
    total_csm_interest = if_interest_csm + nb_interest_csm
    context.total_csm_interest = total_csm_interest
    
    # RA 计息系数
    if months_if > 0:
        context.accretion_factor = if_factor
    elif nb_months > 0:
        context.accretion_factor = nb_factor
    else:
        context.accretion_factor = Decimal('0')
    
    if cohort_state:
        cohort_state.csm_interest = if_interest_csm
    
    logger.log_item(
        "CSM计息合计",
        "[Sec 6] 期初有效合同和新增合同CSM计息之和",
        "IF_Interest + NB_Interest",
        {
            "IF_Interest": if_interest_csm,
            "NB_Interest": nb_interest_csm
        },
        total_csm_interest,
        note="所有计息均使用加权初始确认利率（锁定利率）"
    )

