"""
CSM计息逻辑 (CSM Interest Accretion)

对应文档：第6节 CSM计息

核心功能：
1. 使用加权初始确认利率（锁定利率）进行计息（文档 Sec 6.1）
2. 需区分期初有效合同 (IF) 与当年新增合同 (NB)
3. 新增合同需根据初始确认时点（月末）进行计息调整（文档 Sec 6.5）

修改要点：
1. 期初有效合同CSM计息：使用期初CSM余额，使用签单年月的Wlk利率曲线，从签单日期到当前评估月的月数差计算期数
2. 新增合同CSM计息：使用签单年月的Wlk利率曲线，从签单月到当前评估月，逐月累乘
3. 止期判断：如果保单止期在当前评估年，且止期月份 < 当前评估月，则计息只到止期月份

注意：所有利率曲线必须从PV原材料数据中读取签单年月的Wlk曲线，确保数据一致性。
"""

from decimal import Decimal
from datetime import datetime, date
from typing import Tuple, Optional
from dateutil.relativedelta import relativedelta
from BBA_dev.models import CohortState, PolicyState
from BBA_dev.utils.math_tools import get_accretion_rate_factor
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data
from BBA_dev.assumptions import get_discount_factors


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


def months_from_uw_to_target(uw_date: date, target_month_str: str) -> int:
    """
    计算从签单日期到目标月份的月数差
    
    示例：2021年5月签单，2022年3月评估
    - 202201是签单后第8个月（202105 -> 202201 = 8个月）
    - 202202是签单后第9个月
    - 202203是签单后第10个月
    
    Args:
        uw_date: 签单日期
        target_month_str: 目标月份（YYYYMM格式）
    
    Returns:
        从签单日期到目标月份的月数差（从1开始计数，即第1个月、第2个月...）
    """
    if not uw_date or not target_month_str:
        return 0
    
    try:
        target_date = datetime.strptime(target_month_str, '%Y%m').date()
        # 计算到目标月份最后一天
        if target_date.month == 12:
            target_date = date(target_date.year, 12, 31)
        else:
            target_date = (target_date + relativedelta(months=1) - relativedelta(days=1))
        
        # 计算月数差
        delta = relativedelta(target_date, uw_date)
        months = delta.years * 12 + delta.months
        # 如果目标日期在签单日期之后，至少是1个月
        if target_date > uw_date and months == 0:
            months = 1
        return max(months, 0)
    except Exception:
        return 0


def get_wlk_curve_from_pv_data(context, uw_month_str: str):
    """
    从PV原材料数据获取签单年月的Wlk利率曲线
    
    Args:
        context: 计算上下文
        uw_month_str: 签单年月（YYYYMM格式）
    
    Returns:
        利率曲线DataFrame，如果无法获取则返回None
    """
    if not context.pv_source_data:
        return None
    
    # 尝试从PV原材料数据的metadata获取签单月份信息
    pv_data_init = context.pv_source_data.get_data(uw_month_str)
    if pv_data_init and pv_data_init.metadata:
        rate_locked_month = pv_data_init.metadata.get('rate_locked_month')
        if rate_locked_month:
            try:
                # 从数据库获取该月份的锁定利率曲线
                return get_discount_factors("locked", rate_locked_month)
            except Exception:
                pass
    
    # 如果metadata中没有，直接使用签单月份
    try:
        return get_discount_factors("locked", uw_month_str)
    except Exception:
        return None


def calculate_interest_with_stop_date(
    principal: Decimal,
    rates_df,
    start_term: int,
    end_term: int,
    stop_date: Optional[date] = None,
    val_month_str: Optional[str] = None,
    uw_date: Optional[date] = None
) -> Tuple[Decimal, Decimal]:
    """
    使用锁定利率曲线计算利息，支持止期判断
    
    Args:
        principal: 本金（CSM余额）
        rates_df: 利率曲线DataFrame
        start_term: 起始期数（从签单日期起算，从1开始）
        end_term: 结束期数（从签单日期起算）
        stop_date: 保单止期（可选）
        val_month_str: 当前评估月（YYYYMM格式，可选）
        uw_date: 签单日期（可选）
    
    Returns:
        (利息金额, 计息因子)
    """
    if rates_df is None or rates_df.empty:
        return Decimal('0'), Decimal('0')
    
    # 止期判断：如果保单止期在当前评估年，且止期月份 < 当前评估月，则计息只到止期月份
    actual_end_term = end_term
    if stop_date and val_month_str and uw_date:
        try:
            val_date = datetime.strptime(val_month_str, '%Y%m').date()
            # 如果止期在当前评估年，且止期月份 < 当前评估月
            if stop_date.year == val_date.year and stop_date.month < val_date.month:
                # 计算止期月份对应的期数
                stop_month_str = stop_date.strftime('%Y%m')
                stop_term = months_from_uw_to_target(uw_date, stop_month_str)
                if stop_term > 0 and stop_term < actual_end_term:
                    actual_end_term = stop_term
        except Exception:
            pass
    
    # 计算计息因子
    factor = get_accretion_rate_factor(rates_df, start_term - 1, actual_end_term)
    if principal is None or principal == Decimal('0') or factor == 0:
        return Decimal('0'), factor
    return principal * factor, factor


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

    # 强制要求PV原材料数据必须存在（确保系统一致性）
    if context.pv_source_data is None:
        ensure_pv_source_data(context)
    
    if context.pv_source_data is None:
        policy_no = getattr(context.policy_data, 'policy_no', None) or getattr(context, 'policy_no', 'UNKNOWN')
        raise ValueError(
            f"❌ 错误: PV原材料数据不可用！\n"
            f"   保单号: {policy_no}\n"
            f"   请先运行 pv_calculator.py 生成PV原材料数据文件: logs/pv_source_data_{policy_no}.json\n"
            f"   系统要求必须使用PV原材料数据，确保数据完整性和准确性。"
        )

    # 确定评估日期
    if not hasattr(context, 'eop_date') or context.eop_date is None:
        context.eop_date = datetime(context.year, 12, 31).date()
    
    # 获取签单日期和签单年月
    uw_date = getattr(context, 'under_write_date', None)
    if not uw_date:
        raise ValueError("❌ 错误: context.under_write_date 未设置，无法计算CSM计息")
    uw_month_str = uw_date.strftime('%Y%m')
    
    # 获取当前评估月
    val_month_str = getattr(context, 'val_month_str', None)
    if not val_month_str:
        val_month_str = context.eop_date.strftime('%Y%m')
    
    # [Sec 6.1] 从PV原材料数据获取签单年月的Wlk利率曲线
    wlk_curve = get_wlk_curve_from_pv_data(context, uw_month_str)
    if wlk_curve is None or wlk_curve.empty:
        logger.log_item(
            "锁定利率曲线缺失",
            "[Sec 6.1] 无法从PV原材料数据获取签单年月的Wlk利率曲线",
            f"UW Month: {uw_month_str}",
            {},
            Decimal('0'),
            note="请确保PV原材料数据包含签单月份的利率曲线信息"
        )
        return
    
    # 获取保单止期（用于止期判断）
    stop_date = None
    if policy_state and hasattr(policy_state, 'end_date'):
        stop_date = policy_state.end_date
    elif hasattr(context, 'end_date'):
        stop_date = context.end_date
    
    bop_csm = getattr(context, 'bop_csm', None)
    bop_lc = getattr(context, 'bop_lc', None)
    if bop_csm is None and cohort_state:
        bop_csm = cohort_state.bop_csm
    if bop_lc is None and cohort_state:
        bop_lc = cohort_state.bop_lc
    nb_initial_csm = context.nb_initial_csm or Decimal('0')
    nb_initial_lc = context.nb_initial_lc or Decimal('0')
    
    # ==========================================================================================
    # 期初有效合同CSM计息
    # ==========================================================================================
    # 使用期初CSM余额（bop_csm）
    # 使用签单年月的Wlk利率曲线
    # 期数计算：从签单日期到当前评估月的月数差
    # 示例：2021年5月签单，2022年3月计息
    #   - 取2022年初CSM余额
    #   - 使用202105的Wlk利率曲线
    #   - 202201是签单后第8个月 → 用r8
    #   - 202202是签单后第9个月 → 用r9
    #   - 202203是签单后第10个月 → 用r10
    #   - 计息因子 = (1+r8)(1+r9)(1+r10) - 1
    
    # 计算年初对应的期数（从签单日期起算）
    bop_month_str = date(context.year, 1, 1).strftime('%Y%m')
    start_term_if = months_from_uw_to_target(uw_date, bop_month_str)
    # 计算期末对应的期数
    end_term_if = months_from_uw_to_target(uw_date, val_month_str)
    
    # 期初有效合同CSM计息
    if_interest_csm, if_factor = calculate_interest_with_stop_date(
        bop_csm or Decimal('0'),
        wlk_curve,
        start_term_if,
        end_term_if,
        stop_date=stop_date,
        val_month_str=val_month_str,
        uw_date=uw_date
    )
    
    # ==========================================================================================
    # 新增合同CSM计息
    # ==========================================================================================
    # 使用签单年月的Wlk利率曲线
    # 从签单月到当前评估月，逐月累乘
    # 示例：5月签单
    #   - 6月：CSM × ((1+r1) - 1)
    #   - 7月：CSM × ((1+r1)(1+r2) - 1)
    
    # 计算从签单日期到当前评估月的期数
    start_term_nb = 1  # 新增合同从签单后第1个月开始计息
    end_term_nb = months_from_uw_to_target(uw_date, val_month_str)
    
    # 新增合同CSM计息
    nb_interest_csm, nb_factor = calculate_interest_with_stop_date(
        nb_initial_csm,
        wlk_curve,
        start_term_nb,
        end_term_nb,
        stop_date=stop_date,
        val_month_str=val_month_str,
        uw_date=uw_date
    )
    
    # 选择代表性的因子值用于日志显示（优先使用IF因子，如果没有则使用NB因子）
    representative_factor = if_factor if (bop_csm and bop_csm != Decimal('0')) else (nb_factor if nb_initial_csm > 0 else Decimal('0'))
    
    logger.log_item(
        "锁定利率曲线（计息）",
        "[Sec 6.1] 从PV原材料数据读取签单年月的Wlk利率曲线进行累乘计息",
        "Factor = Π(1 + r_i) - 1",
        {
            "签单年月": uw_month_str,
            "Curve Points": len(wlk_curve),
            "Representative Factor": representative_factor,
            "IF Factor": if_factor if (bop_csm and bop_csm != Decimal('0')) else None,
            "NB Factor": nb_factor if nb_initial_csm > 0 else None
        },
        representative_factor,
        note=f"r_i 为签单年月({uw_month_str})的Wlk利率曲线的月度远期利率，乘积区间取决于从签单日期到当前评估月的期数"
    )
    
    if bop_csm and bop_csm != Decimal('0'):
        logger.log_item(
            "期初存量_CSM计息",
            "[Sec 6.4] 期初有效合同CSM随时间推移产生的利息（使用签单年月Wlk曲线）",
            "IF_CSM_beg × (PRODUCT(1 + r_t) - 1)",
            {
                "IF_CSM_beg": bop_csm,
                "签单年月": uw_month_str,
                "年初期数": start_term_if,
                "期末期数": end_term_if,
                "计息期数": end_term_if - start_term_if,
                "Factor": if_factor,
                "止期": stop_date.strftime('%Y-%m-%d') if stop_date else None
            },
            if_interest_csm,
            note=f"计息期间：从签单日期起第{start_term_if}个月到第{end_term_if}个月；r_t 为签单年月({uw_month_str})的Wlk利率曲线"
        )
    
    if nb_initial_csm > 0:
        logger.log_item(
            "当年新增合同_CSM计息",
            "[Sec 6.5] 新增合同CSM随时间推移产生的利息（使用签单年月Wlk曲线）",
            "NB_CSM_new × (PRODUCT(1 + r_t) - 1)",
            {
                "NB_CSM_new": nb_initial_csm,
                "签单年月": uw_month_str,
                "起始期数": start_term_nb,
                "结束期数": end_term_nb,
                "计息期数": end_term_nb - start_term_nb + 1,
                "Factor": nb_factor,
                "止期": stop_date.strftime('%Y-%m-%d') if stop_date else None
            },
            nb_interest_csm,
            note=f"计息期间：从签单日期起第{start_term_nb}个月到第{end_term_nb}个月；r_t 为签单年月({uw_month_str})的Wlk利率曲线"
        )
    
    # ==========================================================================================
    # LC变化说明
    # ==========================================================================================
    # LC不直接计息，LC的变化通过IFIE分摊实现（在ifie.py中处理）
    # IF_分摊后IFIE后LC = IF_年初LC + IF_LC分摊IFIE
    # NB_分摊后IFIE后LC = NB_年初LC + NB_LC分摊IFIE
    # 其中：
    # - IF_LC分摊IFIE = (IF_待分摊IFIE_计息 + IF_待分摊IFIE_利率变化影响) × IF_LC IFIE分摊比例
    # - NB_LC分摊IFIE = (NB_待分摊IFIE_计息 + NB_待分摊IFIE_利率变化影响) × NB_LC IFIE分摊比例
    # 
    # 因此，在interest_accretion.py中不计算LC计息，LC的变化在IFIE模块中处理
    
    # 设置LC计息为0（LC不直接计息）
    if_interest_lc = Decimal('0')
    nb_interest_lc = Decimal('0')
    
    logger.log_item(
        "LC变化说明",
        "[说明] LC不直接计息，LC的变化通过IFIE分摊实现",
        "LC变化 = 年初LC + LC分摊IFIE",
        {
            "IF_年初LC": bop_lc or Decimal('0'),
            "NB_年初LC": nb_initial_lc,
            "说明": "LC的变化在IFIE模块（ifie.py）中通过IFIE分摊计算"
        },
        Decimal('0'),
        note="IF_分摊后IFIE后LC = IF_年初LC + IF_LC分摊IFIE；NB_分摊后IFIE后LC = NB_年初LC + NB_LC分摊IFIE"
    )
    
    context.if_interest_csm = if_interest_csm
    context.if_interest_lc = if_interest_lc  # 设置为0，LC变化在IFIE中处理
    context.nb_interest_csm = nb_interest_csm
    context.nb_interest_lc = nb_interest_lc  # 设置为0，LC变化在IFIE中处理
    total_csm_interest = if_interest_csm + nb_interest_csm
    context.total_csm_interest = total_csm_interest
    
    # RA 计息系数（优先使用IF因子，如果没有则使用NB因子）
    if bop_csm and bop_csm != Decimal('0') and if_factor != 0:
        context.accretion_factor = if_factor
    elif nb_initial_csm > 0 and nb_factor != 0:
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
            "NB_Interest": nb_interest_csm,
            "签单年月": uw_month_str,
            "评估年月": val_month_str
        },
        total_csm_interest,
        note=f"所有计息均使用签单年月({uw_month_str})的Wlk利率曲线（加权初始确认利率）"
    )

