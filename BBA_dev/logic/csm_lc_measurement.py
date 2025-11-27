"""
CSM/LC计量模块 (CSM/LC Measurement)

对应文档：
- 第6节：CSM计息
- 第7节：LC分摊IFIE
- 第8.5.5节：合同组CSM/LC判断
- 第8.2节：CSM计量（摊销）
- LC计量（LC变化计算）

核心功能：
1. CSM计息：使用加权初始确认利率（Wlk）进行CSM计息
2. LC分摊IFIE：计算LC的IFIE分摊（IF和NB）
3. 合同组CSM/LC判断：确定合同组最终状态（盈利或亏损）
4. CSM计量：CSM摊销计算
5. LC计量：LC变化计算

注意：
- 使用统一字段逻辑：CSM/LC使用一个字段，>=0走CSM逻辑，<0走LC逻辑
- 所有现值必须从PV原材料数据读取
"""

from decimal import Decimal
from typing import List, Optional, Any, Tuple
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from BBA_dev.models import CohortState, PolicyState, Assumptions
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data
from BBA_dev.utils.math_tools import get_accretion_rate_factor
from BBA_dev.assumptions import get_discount_factors
from BBA_dev.logic.coverage_units import calculate_csm_amortization_ratio

DECIMAL_ZERO = Decimal('0')


def months_from_uw_to_target(uw_date: date, target_month_str: str) -> int:
    """
    计算从签单日期到目标月份的月数差
    
    Args:
        uw_date: 签单日期
        target_month_str: 目标月份（YYYYMM格式）
    
    Returns:
        从签单日期到目标月份的月数差（从1开始计数）
    """
    if not uw_date or not target_month_str:
        return 0
    
    try:
        target_date = datetime.strptime(target_month_str, '%Y%m').date()
        if target_date.month == 12:
            target_date = date(target_date.year, 12, 31)
        else:
            target_date = (target_date + relativedelta(months=1) - relativedelta(days=1))
        
        delta = relativedelta(target_date, uw_date)
        months = delta.years * 12 + delta.months
        if target_date > uw_date and months == 0:
            months = 1
        return max(months, 0)
    except Exception:
        return 0


def get_wlk_curve_from_pv_data(context, uw_month_str: str):
    """从PV原材料数据获取签单年月的Wlk利率曲线"""
    if not context.pv_source_data:
        return None
    
    pv_data_init = context.pv_source_data.get_data(uw_month_str)
    if pv_data_init and pv_data_init.metadata:
        rate_locked_month = pv_data_init.metadata.get('rate_locked_month')
        if rate_locked_month:
            try:
                return get_discount_factors("locked", rate_locked_month)
            except Exception:
                pass
    
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
    """使用锁定利率曲线计算利息，支持止期判断"""
    if rates_df is None or rates_df.empty:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    actual_end_term = end_term
    if stop_date and val_month_str and uw_date:
        try:
            val_date = datetime.strptime(val_month_str, '%Y%m').date()
            if stop_date.year == val_date.year and stop_date.month < val_date.month:
                stop_month_str = stop_date.strftime('%Y%m')
                stop_term = months_from_uw_to_target(uw_date, stop_month_str)
                if stop_term > 0 and stop_term < actual_end_term:
                    actual_end_term = stop_term
        except Exception:
            pass
    
    factor = get_accretion_rate_factor(rates_df, start_term - 1, actual_end_term)
    if principal is None or principal == DECIMAL_ZERO or factor == 0:
        return DECIMAL_ZERO, factor
    return principal * factor, factor


def _calculate_csm_interest(context, logger, cohort_state: CohortState, policy_state: PolicyState):
    """
    计算CSM计息（文档第6节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policy_state: 保单状态
    """
    logger.log_section("Part 3: CSM计息 (Interest Accretion) [Sec 6]")
    
    if context.pv_source_data is None:
        ensure_pv_source_data(context)
    
    if context.pv_source_data is None:
        policy_no = getattr(context.policy_data, 'policy_no', None) or getattr(context, 'policy_no', 'UNKNOWN')
        raise ValueError(
            f"❌ 错误: PV原材料数据不可用！\n"
            f"   保单号: {policy_no}\n"
            f"   请先运行 pv_calculator.py 生成PV原材料数据文件"
        )
    
    if not hasattr(context, 'eop_date') or context.eop_date is None:
        context.eop_date = datetime(context.year, 12, 31).date()
    
    uw_date = getattr(context, 'under_write_date', None)
    if not uw_date:
        raise ValueError("❌ 错误: context.under_write_date 未设置")
    uw_month_str = uw_date.strftime('%Y%m')
    
    val_month_str = getattr(context, 'val_month_str', None)
    if not val_month_str:
        val_month_str = context.eop_date.strftime('%Y%m')
    
    # 从PV原材料数据获取签单年月的Wlk利率曲线
    wlk_curve = get_wlk_curve_from_pv_data(context, uw_month_str)
    if wlk_curve is None or wlk_curve.empty:
        logger.log_item(
            "锁定利率曲线缺失",
            "[Sec 6.1] 无法从PV原材料数据获取签单年月的Wlk利率曲线",
            f"UW Month: {uw_month_str}",
            {},
            DECIMAL_ZERO,
            note="请确保PV原材料数据包含签单月份的利率曲线信息"
        )
        return
    
    stop_date = None
    if policy_state and hasattr(policy_state, 'end_date'):
        stop_date = policy_state.end_date
    elif hasattr(context, 'end_date'):
        stop_date = context.end_date
    
    # 获取统一的CSM/LC字段
    bop_csm_lc = getattr(context, 'bop_csm', None)
    if bop_csm_lc is None and cohort_state:
        bop_csm_lc = cohort_state.bop_csm
    if bop_csm_lc is None:
        bop_csm_lc = DECIMAL_ZERO
    
    nb_initial_csm_lc = context.nb_initial_csm or DECIMAL_ZERO
    if nb_initial_csm_lc == DECIMAL_ZERO and hasattr(context, 'nb_initial_lc'):
        nb_initial_csm_lc = context.nb_initial_lc or DECIMAL_ZERO
    
    # 分离CSM和LC
    bop_csm = bop_csm_lc if bop_csm_lc >= 0 else DECIMAL_ZERO
    nb_initial_csm = nb_initial_csm_lc if nb_initial_csm_lc >= 0 else DECIMAL_ZERO
    
    # 期初有效合同CSM计息
    bop_month_str = date(context.year, 1, 1).strftime('%Y%m')
    start_term_if = months_from_uw_to_target(uw_date, bop_month_str)
    end_term_if = months_from_uw_to_target(uw_date, val_month_str)
    
    if_interest_csm, if_factor = calculate_interest_with_stop_date(
        bop_csm,
        wlk_curve,
        start_term_if,
        end_term_if,
        stop_date=stop_date,
        val_month_str=val_month_str,
        uw_date=uw_date
    )
    
    # 新增合同CSM计息
    start_term_nb = 1
    end_term_nb = months_from_uw_to_target(uw_date, val_month_str)
    
    nb_interest_csm, nb_factor = calculate_interest_with_stop_date(
        nb_initial_csm,
        wlk_curve,
        start_term_nb,
        end_term_nb,
        stop_date=stop_date,
        val_month_str=val_month_str,
        uw_date=uw_date
    )
    
    # 保存到context
    context.if_interest_csm = if_interest_csm
    context.nb_interest_csm = nb_interest_csm
    
    # 计算计息后余额（文档要求）
    if_csm_post_interest = bop_csm + if_interest_csm
    nb_csm_post_interest = nb_initial_csm + nb_interest_csm
    
    # 更新cohort_state
    if cohort_state:
        cohort_state.csm_interest = if_interest_csm + nb_interest_csm
    
    logger.log_item(
        "CSM计息明细",
        "[Sec 6] CSM计息明细（文档对照）",
        "IF_计息后CSM = IF_年初CSM余额 + IF_CSM计息\nNB_计息后CSM = NB_新增CSM + NB_CSM计息",
        {
            "IF_年初CSM余额": bop_csm,
            "当年新增合同CSM": nb_initial_csm,
            "期初有效合同CSM计息": if_interest_csm,
            "新增合同CSM计息": nb_interest_csm,
            "IF_计息后CSM": if_csm_post_interest,
            "NB_计息后CSM": nb_csm_post_interest
        },
        if_interest_csm + nb_interest_csm,
        note="CSM计息结果，用于后续净余额试算"
    )


def _pv_amount(pv_data, field_name):
    """Helper to safely get PV amount, returning 0 if pv_data is None"""
    if pv_data is None:
        return Decimal('0')
    return pv_data.get_field(field_name)

def _get_nb_initial_pv_data(context):
    """Helper to get New Business initial PV data"""
    if not hasattr(context, 'under_write_date') or not context.under_write_date:
        return None, None
        
    # Check if it is new business year
    if context.year != context.under_write_date.year:
        return None, None
        
    uw_month_str = context.under_write_date.strftime('%Y%m')
    pv_data = context.pv_source_data.get_data(uw_month_str)
    return pv_data, uw_month_str

def _calculate_lc_ifie_allocation(context, logger, cohort_state: CohortState):
    """
    计算LC分摊IFIE（文档第7节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
    """
    logger.log_section("Part 7: LC分摊IFIE (LC IFIE Allocation) [Sec 7]")
    
    # 获取评估月和年初月份
    eop_month_str = context.val_month_str
    bop_month_str = (context.eop_date.replace(day=1) - relativedelta(months=11)).strftime('%Y%m') if hasattr(context, 'eop_date') else None
    if bop_month_str is None:
        val_date = datetime.strptime(eop_month_str, '%Y%m')
        bop_date = val_date.replace(month=1, day=1)
        bop_month_str = bop_date.strftime('%Y%m')
    
    # 获取PV数据
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    pv_data_bop = context.pv_source_data.get_data(bop_month_str) if bop_month_str else None
    
    if pv_data_eop is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 获取统一的CSM/LC字段
    bop_csm_lc = getattr(context, 'bop_csm', None)
    if bop_csm_lc is None and cohort_state:
        bop_csm_lc = cohort_state.bop_csm
    if bop_csm_lc is None:
        bop_csm_lc = DECIMAL_ZERO
    
    nb_initial_csm_lc = context.nb_initial_csm or DECIMAL_ZERO
    if nb_initial_csm_lc == DECIMAL_ZERO and hasattr(context, 'nb_initial_lc'):
        nb_initial_csm_lc = context.nb_initial_lc or DECIMAL_ZERO
    
    # ==========================================================================================
    # IF（期初有效合同）LC IFIE分摊
    # ==========================================================================================
    if_bop_lc = bop_csm_lc if bop_csm_lc < 0 else DECIMAL_ZERO
    
    # IF_LC IFIE分摊比例
    if_lc_ifie_ratio = getattr(context, 'if_lc_ifie_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    if if_bop_lc < 0 and if_lc_ifie_ratio == DECIMAL_ZERO:
        # 如果还未计算，则计算
        if pv_data_bop is None:
            denom_if = DECIMAL_ZERO
        else:
            pv_if_init_claims = (pv_data_bop.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt', DECIMAL_ZERO) +
                                pv_data_bop.get_field('Pvfl_If_Bop_Cca_Beg_Lcu_Cla_Amt', DECIMAL_ZERO))
            pv_if_init_maint = (pv_data_bop.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO) +
                               pv_data_bop.get_field('Pvfl_If_Bop_Cca_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO))
            pv_if_init_ra = (pv_data_bop.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt', DECIMAL_ZERO) +
                            pv_data_bop.get_field('Pvfl_If_Bop_Cca_Beg_Lcu_Rad_Amt', DECIMAL_ZERO))
            denom_if = pv_if_init_claims + pv_if_init_maint + pv_if_init_ra
        
        if denom_if > 0:
            if_lc_ifie_ratio = abs(if_bop_lc) / denom_if
        context.if_lc_ifie_ratio = if_lc_ifie_ratio
    
    # ==========================================================================================
    # IF（期初有效合同）待分摊IFIE计算（详细逻辑）
    # ==========================================================================================
    # 1. IF_待分摊IFIE_计息_赔付与费用
    # 公式：[Bop_Cfa_Rep_Wlk] + [Bop_Cca_Rep_Wlk] - [Bop_Cfa_Beg_Wlk]
    if_ifie_accretion_claims = (
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt') +
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt')
    )
    
    # 2. IF_待分摊IFIE_计息_非金融风险调整
    # 公式：[Bop_Cfa_Rep_Wlk] - [Bop_Cfa_Beg_Wlk] + [Bop_Cca_Rep_Wlk]
    if_ifie_accretion_ra = (
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt') +
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt')
    )
    
    # 3. IF_待分摊IFIE_利率变化的影响_赔付与费用
    # 公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])
    # 注意：文档中还要加上 [Eop_Cfa_Rep_Cur_Mtn] 等，以及年初部分的 Lcu 和 Wlk 差额
    term_end_diff = (
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    )
    term_beg_diff = (
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt') +
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt')
    )
    if_ifie_rate_change_claims = term_end_diff - term_beg_diff
    
    # 4. IF_待分摊IFIE_利率变化的影响_非金融风险调整
    # 公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])
    term_end_diff_ra = (
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
    )
    term_beg_diff_ra = (
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt') -
        _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt')
    )
    if_ifie_rate_change_ra = term_end_diff_ra - term_beg_diff_ra
    
    # 计算分摊结果
    if_lc_ifie_claims = (if_ifie_accretion_claims + if_ifie_rate_change_claims) * if_lc_ifie_ratio
    if_lc_ifie_ra = (if_ifie_accretion_ra + if_ifie_rate_change_ra) * if_lc_ifie_ratio
    if_lc_ifie_total = if_lc_ifie_claims + if_lc_ifie_ra
    
    if_lc_after_ifie = if_bop_lc + if_lc_ifie_total
    
    context.if_lc_after_ifie = if_lc_after_ifie
    context.if_lc_ifie_total = if_lc_ifie_total
    context.if_lc_ifie_cf = if_lc_ifie_claims
    context.if_lc_ifie_ra = if_lc_ifie_ra
    
    # ==========================================================================================
    # NB（新增合同）LC IFIE分摊（详细逻辑）
    # ==========================================================================================
    nb_initial_lc = nb_initial_csm_lc if nb_initial_csm_lc < 0 else DECIMAL_ZERO
    
    # NB_LC IFIE分摊比例
    nb_lc_ifie_ratio = getattr(context, 'nb_lc_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    if nb_initial_lc < 0 and nb_lc_ifie_ratio == DECIMAL_ZERO:
        denom_nb = context.init_fut_claim + context.init_fut_maint + context.init_ra
        if denom_nb > 0:
            nb_lc_ifie_ratio = abs(nb_initial_lc) / denom_nb
        context.nb_lc_ratio = nb_lc_ifie_ratio
    
    # 获取新增合同初始确认PV数据
    # 注意：pv_data_init 已经在 _calculate_csm_lc_absorption 中获取，这里可能需要重新获取或传入
    pv_data_init, _ = _get_nb_initial_pv_data(context)
    
    # 1. NB_待分摊IFIE_计息_赔付与费用
    # 公式：[Ini_Cfa_Rep_Wlk] - [Ini_Cfa_Rec_Lkd] + [Ini_Cca_Rep_Wlk]
    # 注意：Rec_Lkd 对应文档中的“初始确认现值（当月初始利率）”
    nb_ifie_accretion_claims = (
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Mtn_Amt') -
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt') -
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt') +
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt')
    )
    
    # 2. NB_待分摊IFIE_计息_非金融风险调整
    # 公式：[Ini_Cfa_Rep_Wlk] - [Ini_Cfa_Rec_Lkd] + [Ini_Cca_Rep_Wlk]
    nb_ifie_accretion_ra = (
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Rad_Amt') -
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt') +
        _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt')
    )
    
    # 3. NB_待分摊IFIE_利率变化的影响_赔付与费用
    # 公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]
    nb_ifie_rate_change_claims = (
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt') +
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    )
    
    # 4. NB_待分摊IFIE_利率变化的影响_非金融风险调整
    # 公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]
    nb_ifie_rate_change_ra = (
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt') -
        _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
    )
    
    # 计算分摊结果
    nb_lc_ifie_claims = (nb_ifie_accretion_claims + nb_ifie_rate_change_claims) * nb_lc_ifie_ratio
    nb_lc_ifie_ra = (nb_ifie_accretion_ra + nb_ifie_rate_change_ra) * nb_lc_ifie_ratio
    nb_lc_ifie_total = nb_lc_ifie_claims + nb_lc_ifie_ra
    
    nb_lc_after_ifie = nb_initial_lc + nb_lc_ifie_total
    
    context.nb_lc_after_ifie = nb_lc_after_ifie
    context.nb_lc_ifie_total = nb_lc_ifie_total
    context.nb_lc_ifie_cf = nb_lc_ifie_claims
    context.nb_lc_ifie_ra = nb_lc_ifie_ra
    
    logger.log_item(
        "LC分摊IFIE明细",
        "[Sec 7] LC分摊IFIE明细（文档对照）",
        "LC分摊IFIE = IF_LC分摊IFIE + NB_LC分摊IFIE",
        {
            # IF 部分
            "IF_年初LC": if_bop_lc,
            "IF_LC IFIE分摊比例": if_lc_ifie_ratio,
            "IF_待分摊IFIE_计息_赔付与费用": if_ifie_accretion_claims,
            "IF_待分摊IFIE_计息_非金融风险调整": if_ifie_accretion_ra,
            "IF_待分摊IFIE_利率变化的影响_赔付与费用": if_ifie_rate_change_claims,
            "IF_待分摊IFIE_利率变化的影响_非金融风险调整": if_ifie_rate_change_ra,
            "IF_LC分摊IFIE_赔付与费用": if_lc_ifie_claims,
            "IF_LC分摊IFIE_非金融风险调整": if_lc_ifie_ra,
            "IF_LC分摊IFIE": if_lc_ifie_total,
            "IF_分摊后IFIE后LC": if_lc_after_ifie,
            
            # NB 部分
            "NB_新增LC": nb_initial_lc,
            "NB_LC IFIE分摊比例": nb_lc_ifie_ratio,
            "NB_待分摊IFIE_计息_赔付与费用": nb_ifie_accretion_claims,
            "NB_待分摊IFIE_计息_非金融风险调整": nb_ifie_accretion_ra,
            "NB_待分摊IFIE_利率变化的影响_赔付与费用": nb_ifie_rate_change_claims,
            "NB_待分摊IFIE_利率变化的影响_非金融风险调整": nb_ifie_rate_change_ra,
            "NB_LC分摊IFIE_赔付与费用": nb_lc_ifie_claims,
            "NB_LC分摊IFIE_非金融风险调整": nb_lc_ifie_ra,
            "NB_LC分摊IFIE": nb_lc_ifie_total,
            "NB_分摊后IFIE后LC": nb_lc_after_ifie
        },
        if_lc_ifie_total + nb_lc_ifie_total,
        note="详细展示IF和NB的LC分摊IFIE逻辑"
    )


def _determine_cohort_status(
    cohort_state: CohortState,
    context: Any,
    logger: Any,
    policies: Optional[List[PolicyState]] = None
):
    """
    合同组状态判定（文档第8.5.5节）
    
    Args:
        cohort_state: 合同组状态
        context: 计算上下文
        logger: 日志记录器
        policies: 保单列表
    """
    logger.log_section("Part 8.5.5: 合同组状态判定 (Cohort Status Determination) [Sec 8.5.5]")
    
    # 获取统一的CSM/LC字段
    bop_csm_lc = cohort_state.bop_csm if cohort_state else DECIMAL_ZERO
    if_csm_lc_post = bop_csm_lc + (cohort_state.csm_interest if cohort_state else DECIMAL_ZERO)
    
    nb_initial_csm_lc = context.nb_initial_csm or DECIMAL_ZERO
    if nb_initial_csm_lc == DECIMAL_ZERO and hasattr(context, 'nb_initial_lc'):
        nb_initial_csm_lc = context.nb_initial_lc or DECIMAL_ZERO
    nb_csm_lc_post = nb_initial_csm_lc + (context.nb_interest_csm or DECIMAL_ZERO)
    
    # 加上LC的IFIE分摊
    if_lc_after_ifie = getattr(context, 'if_lc_after_ifie', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_after_ifie = getattr(context, 'nb_lc_after_ifie', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 计算净余额试算值（严格对齐文档图片）
    # Net_trial = IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC
    # 注意：文档公式中不包含“被CSM/LC吸收的变化”
    net_trial = if_csm_lc_post + nb_csm_lc_post + if_lc_after_ifie + nb_lc_after_ifie
    
    logger.log_item(
        "合同组净余额试算值",
        "[Sec 8.5.5] 步骤1：计算合同组净余额试算值（文档对照）",
        "Net_trial = IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC",
        {
            "IF_计息后CSM": if_csm_lc_post,
            "NB_计息后CSM": nb_csm_lc_post,
            "IF_分摊后IFIE后LC": if_lc_after_ifie,
            "NB_分摊后IFIE后LC": nb_lc_after_ifie,
            "Net_trial": net_trial
        },
        net_trial,
        note="严格按照文档公式：判定状态时不包含当期履约现金流变化（被CSM/LC吸收的变化）"
    )
    
    # 确定合同组最终状态
    if net_trial >= 0:
        cohort_csm = net_trial
        cohort_lc = DECIMAL_ZERO
        if cohort_state:
            cohort_state.is_profitable = True
        status = "盈利 (Profitable)"
    else:
        cohort_csm = DECIMAL_ZERO
        cohort_lc = net_trial
        if cohort_state:
            cohort_state.is_profitable = False
        status = "亏损 (Onerous)"
    
    logger.log_item(
        "合同组最终状态",
        "[Sec 8.5.5] 步骤2：确定合同组最终状态",
        "IF(Net_trial ≥ 0, 盈利, 亏损)",
        {
            "Net_trial": net_trial,
            "合同组 CSM": cohort_csm,
            "合同组 LC": cohort_lc
        },
        net_trial,
        note=f"判定结果: {status}"
    )
    
    # 状态回写
    if policies and cohort_state:
        for policy in policies:
            if cohort_state.is_profitable:
                policy.initial_lc = DECIMAL_ZERO
            else:
                policy.initial_csm = DECIMAL_ZERO
        
        logger.log_item(
            "状态回写",
            "[Sec 8.5.5] 步骤3：状态回写（Re-apportionment）",
            "组盈利则LC清零，组亏损则CSM清零",
            {
                "保单数量": len(policies),
                "合同组状态": status
            },
            DECIMAL_ZERO
        )
    
    # 更新期末余额（摊销前）
    cohort_csm_lc = cohort_csm + cohort_lc
    if cohort_csm_lc >= 0:
        context.end_csm_before_amort = cohort_csm_lc
        context.end_lc_before_amort = DECIMAL_ZERO
    else:
        context.end_csm_before_amort = DECIMAL_ZERO
        context.end_lc_before_amort = cohort_csm_lc
    
    if cohort_state:
        cohort_state.net_trial = net_trial


def _calculate_csm_measurement(context, logger):
    """
    计算CSM计量（文档第8.2节：CSM摊销）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
    """
    logger.log_section("Part 8.2: CSM计量 (CSM Measurement) [Sec 8.2]")
    
    # 获取必要的基础数据
    cohort_csm = getattr(context, 'end_csm_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO # 这里的end_csm_before_amort来自合同组判定，仅包含期初+新增+计息+IFIE
    cohort_lc = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    
    delta_csm_lc = getattr(context, 'exp_adj_csm_impact', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_cf_total = getattr(context, 'delta_cf_total', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_ra = delta_csm_lc - delta_cf_total
    
    # 获取LC计量结果（因为现在CSM计量在LC计量之后，所以可以获取）
    allocated_lc_exp_adj_total = getattr(context, 'lc_change', DECIMAL_ZERO) or DECIMAL_ZERO # 被LC吸收的变化_合计
    allocated_lc_exp_adj_cf = getattr(context, 'allocated_lc_exp_adj_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    allocated_lc_exp_adj_ra = getattr(context, 'allocated_lc_exp_adj_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 计算被CSM吸收的变化
    # 文档逻辑：如果合同组是CSM状态，或者虽然是LC状态但变化足够大能转回CSM，则：
    # 被CSM吸收的变化 = 总变化 - 被LC吸收的变化
    # 这里的公式推导：Total = CSM_Absorbed + LC_Absorbed => CSM_Absorbed = Total - LC_Absorbed
    
    # 验证文档中的复杂IF公式：
    # IF(OR(AND(合同组CSM>0,SUM(...)>=0),AND(合同组CSM=0,SUM(...)>=0)), SUM(被CSM/LC吸收的变化合计, 年初LC...分摊LC), -SUM(年初CSM...CSM计息))
    # 其实 SUM(被CSM/LC吸收的变化合计, 年初LC...分摊LC) 就是 剩余能给CSM的部分（即总变化 + LC转回的部分）
    # 而 -SUM(年初CSM...CSM计息) 就是 把CSM扣光
    
    # 既然我们已经有了准确的 allocated_lc_exp_adj_total (被LC吸收的变化)，我们可以直接用减法：
    # 注意：allocated_lc_exp_adj_total 在LC计量模块计算时，如果 LC 增加是负数，减少（转回）是正数？
    # 检查 LC 计量逻辑：
    # allocated_lc_exp_adj_total = -(bop_lc_total + ...) 如果不够扣
    # allocated_lc_exp_adj_total = delta_csm_lc + bop_csm... 如果转为盈利
    
    # 统一逻辑：总变化 (delta_csm_lc) = CSM吸收部分 + LC吸收部分
    # 所以：CSM吸收部分 = delta_csm_lc - LC吸收部分
    csm_absorbed_total = delta_csm_lc - allocated_lc_exp_adj_total
    
    # 被CSM吸收的现金流变化
    csm_absorbed_cf = delta_cf_total - allocated_lc_exp_adj_cf
    
    # 被CSM吸收的非金融风险调整变化
    # 注意：delta_ra 在 fulfillment_cashflow_changes 中是 (End - Beg)，代表RA增加（不利）
    # 在 csm_absorbed 公式中，不利变化会导致 CSM 减少。
    # 文档公式：被CSM吸收的非金融风险调整变化 = 非金融风险调整变化 - 被LC吸收的变化_非金融风险调整
    # 这里直接相减即可，符号会自动处理。
    # 但要注意 delta_ra 的符号定义。在 fulfillment 模块：delta_csm_lc = delta_cf - delta_ra
    # 所以“非金融风险调整变化”对 CSM 的影响是 -delta_ra
    # 文档中写的是“非金融风险调整变化”，可能指绝对值变化量？
    # 让我们看文档公式：被CSM吸收的非金融风险调整变化 = 非金融风险调整变化 - 被LC吸收的变化_非金融风险调整
    # 这里的“变化”应该是指“对盈余的影响额”。
    # 在 fulfillment 模块，我们定义 delta_ra 为 (End - Beg)，即增加量。
    # 对 CSM 的影响是负的。
    # 如果我们保持 delta_csm_lc = delta_cf - delta_ra，那么这里的“变化”就是指“影响额”。
    # 修正：fulfillment 模块计算的 delta_csm_lc 已经是“影响额”。
    # 但 delta_cf_total 是 (Prem - Claims - Exp)，也是影响额。
    # delta_ra 是 (End - Beg)，是RA增加量。
    # 所以“非金融风险调整变化”这一项，如果要作为加项，应该是 -delta_ra。
    # 让我们假设 context.delta_ra 存储的是 RA 的增加量。
    # 那么 对CSM的影响 = -delta_ra。
    # 被LC吸收的RA影响 = allocated_lc_exp_adj_ra (在LC计量中计算，应该是负数如果RA增加且被LC吸收)
    # 所以 csm_absorbed_ra = (-delta_ra) - allocated_lc_exp_adj_ra
    # 但为了与文档字面一致，如果文档说“非金融风险调整变化”，可能指的就是那个增加量。
    # 让我们回看 fulfillment 模块，context.delta_ra 存的是增加量。
    # 而 delta_csm_lc 存的是影响额 (cf - ra)。
    # 如果我们用 csm_absorbed_total (影响额) - csm_absorbed_cf (影响额)，剩下的就是 csm_absorbed_ra (影响额)。
    csm_absorbed_ra = csm_absorbed_total - csm_absorbed_cf
    
    # 更新 Context
    context.csm_absorbed = csm_absorbed_total
    
    logger.log_item(
        "被CSM吸收的变化",
        "[Sec 8.2] 被CSM吸收的变化（基于LC计量结果推导）",
        "被CSM吸收的变化 = 被CSM/LC吸收的变化合计 - 被LC吸收的变化\n被CSM吸收的现金流 = 预期现金流变化(影响额) - 被LC吸收的现金流\n被CSM吸收的RA = RA变化(影响额) - 被LC吸收的RA",
        {
            "被CSM/LC吸收的变化合计": delta_csm_lc,
            "被LC吸收的变化": allocated_lc_exp_adj_total,
            "被CSM吸收的变化": csm_absorbed_total,
            "其中：被CSM吸收的现金流变化": csm_absorbed_cf,
            "其中：被CSM吸收的RA变化": csm_absorbed_ra
        },
        csm_absorbed_total,
        note="通过总变化减去LC吸收部分得到CSM吸收部分"
    )
    
    # 计算CSM摊销比例（使用覆盖单元动态比例法）
    start_of_year = date(context.year, 1, 1)
    is_initial_year = getattr(context, 'is_initial_year', False)
    
    if hasattr(context, 'policies') and context.policies:
        csm_amort_ratio = calculate_csm_amortization_ratio(
            context.policies,
            context.eop_date,
            start_of_year,
            logger,
            is_initial_year=is_initial_year
        )
    else:
        # 兼容旧代码
        csm_amort_ratio = Decimal('0')
    
    # 计算摊销前CSM余额（含吸收的变化）
    # 这里的 cohort_csm 是从 Contract Status Determination 来的，只含 期初+新增+计息+IFIE
    # 所以要加上 被CSM吸收的变化
    csm_before_amort_adjusted = cohort_csm + csm_absorbed_total
    
    # 计算CSM摊销金额
    if csm_before_amort_adjusted <= 0:
        context.csm_amort_amount = DECIMAL_ZERO
        csm_final = csm_before_amort_adjusted
    else:
        context.csm_amort_amount = -(csm_before_amort_adjusted * csm_amort_ratio)
        csm_final = csm_before_amort_adjusted + context.csm_amort_amount
    
    context.end_csm_final = csm_final
    context.csm_amort_ratio = csm_amort_ratio # 保存供后续使用
    
    logger.log_item(
        "CSM摊销与期末余额",
        "[Sec 8.2] CSM摊销与期末余额计算",
        "摊销前CSM = 合同组CSM(判定期) + 被CSM吸收的变化\nCSM摊销 = -摊销前CSM * 摊销比例\n期末CSM = 摊销前CSM + CSM摊销",
        {
            "合同组CSM(判定期)": cohort_csm,
            "被CSM吸收的变化": csm_absorbed_total,
            "摊销前CSM": csm_before_amort_adjusted,
            "摊销比例": csm_amort_ratio,
            "CSM摊销": context.csm_amort_amount,
            "期末CSM": csm_final
        },
        csm_final
    )


def _calculate_lc_measurement(context, logger):
    """
    计算LC计量（完整的LC计量逻辑）
    
    包括：
    1. 预期现金流部分
    2. 非金融风险调整部分
    3. 合计部分
    
    Args:
        context: 计算上下文
        logger: 日志记录器
    """
    logger.log_section("Part LC: LC计量 (LC Measurement)")
    
    # 获取评估月和年初月份
    eop_month_str = context.val_month_str
    bop_month_str = (context.eop_date.replace(day=1) - relativedelta(months=11)).strftime('%Y%m') if hasattr(context, 'eop_date') else None
    if bop_month_str is None:
        val_date = datetime.strptime(eop_month_str, '%Y%m')
        bop_date = val_date.replace(month=1, day=1)
        bop_month_str = bop_date.strftime('%Y%m')
    
    # 获取PV数据
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    pv_data_bop = context.pv_source_data.get_data(bop_month_str) if bop_month_str else None
    
    if pv_data_eop is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 获取签单月份的PV数据（用于新增合同）
    uw_month_str = context.under_write_date.strftime('%Y%m') if hasattr(context, 'under_write_date') and context.under_write_date else None
    pv_data_init = context.pv_source_data.get_data(uw_month_str) if uw_month_str else None
    
    # 获取CSM摊销比例（用于LC调整判断）
    # 注意：CSM摊销比例应该在revenue模块中计算，但LC计量在revenue之前运行
    # 这里先尝试从context获取，如果没有则使用IACF摊销比例作为参考
    csm_amort_ratio = getattr(context, 'csm_amort_ratio', None)
    if csm_amort_ratio is None:
        # 尝试从csm_amort_amount和end_csm_before_amort计算
        csm_amort_amount = getattr(context, 'csm_amort_amount', None)
        end_csm_before_amort = getattr(context, 'end_csm_before_amort', None)
        if csm_amort_amount is not None and end_csm_before_amort is not None and end_csm_before_amort != 0:
            csm_amort_ratio = abs(csm_amort_amount / end_csm_before_amort)
        else:
            # 如果没有，使用IACF摊销比例作为参考
            csm_amort_ratio = getattr(context, 'iacf_amort_ratio', Decimal('0')) or Decimal('0')
    csm_amort_ratio = Decimal(str(csm_amort_ratio)) if csm_amort_ratio is not None else Decimal('0')
    
    # 获取基础数据
    bop_lc = getattr(context, 'bop_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_lc_total = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    if_lc_ifie_total = getattr(context, 'if_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_total = getattr(context, 'nb_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 获取LC分摊比例
    lc_ratio = getattr(context, 'nb_lc_ratio', DECIMAL_ZERO) or Decimal('0')
    
    # 获取被CSM/LC吸收的变化合计
    delta_csm_lc = getattr(context, 'exp_adj_csm_impact', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_cf_total = getattr(context, 'delta_cf_total', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # ==========================================================================================
    # 先计算合计部分（因为被LC吸收的变化_预期现金流需要用到合计部分的结果）
    # ==========================================================================================
    logger.log_section("LC计量_合计部分（先计算）")
    
    # 年初LC余额_合计：IF_年初LC
    bop_lc_total = bop_lc
    
    # 当年新增LC_合计：NB_新增LC
    # nb_initial_lc_total 已在上面获取
    
    # LC分摊IFIE_合计：IF_LC分摊IFIE + NB_LC分摊IFIE
    lc_ifie_total = if_lc_ifie_total + nb_lc_ifie_total
    
    # 分摊的LC_合计：负的（有效合同+新增合同的所有预期当期现金流）× LC分摊比例
    if pv_data_bop is None:
        allocated_lc_total = DECIMAL_ZERO
    else:
        pv_if_cur_claims = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_if_cur_maint = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        pv_if_cur_ra = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        pv_nb_cur_claims = DECIMAL_ZERO
        pv_nb_cur_maint = DECIMAL_ZERO
        pv_nb_cur_ra = DECIMAL_ZERO
        if pv_data_init is not None:
            pv_nb_cur_claims = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
            pv_nb_cur_maint = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
            pv_nb_cur_ra = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        allocated_lc_total = -((pv_if_cur_claims + pv_if_cur_maint + pv_if_cur_ra + 
                                pv_nb_cur_claims + pv_nb_cur_maint + pv_nb_cur_ra) * lc_ratio)
    
    # 被LC吸收的变化_合计：复杂的IF条件判断
    # IF(OR(AND(合同组LC<0,SUM(合同组LC, 分摊的LC，被CSM/LC吸收的变化合计)<0),AND(合同组LC=0,SUM(合同组CSM, 被CSM/LC吸收的变化合计)<0)),
    #     SUM(被CSM/LC吸收的变化合计, 年初CSM余额，当年新增CSM，CSM计息),
    #     -SUM(年初LC余额_合计，当年新增LC_合计，LC分摊IFIE_合计，分摊的LC_合计))
    cohort_lc = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    cohort_csm = getattr(context, 'end_csm_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    bop_csm = getattr(context, 'bop_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_csm = getattr(context, 'nb_initial_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    csm_interest = (getattr(context, 'if_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO) + (getattr(context, 'nb_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO)
    
    sum_lc_test = cohort_lc + allocated_lc_total + delta_csm_lc
    sum_csm_test = cohort_csm + delta_csm_lc
    
    if (cohort_lc < 0 and sum_lc_test < 0) or (cohort_lc == 0 and sum_csm_test < 0):
        allocated_lc_exp_adj_total = delta_csm_lc + bop_csm + nb_initial_csm + csm_interest
    else:
        allocated_lc_exp_adj_total = -(bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total)
    
    # 待调整LC余额_合计（用于判断被LC吸收的变化_预期现金流）
    lc_balance_to_adjust_total = bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total + allocated_lc_exp_adj_total
    
    # ==========================================================================================
    # 预期现金流部分
    # ==========================================================================================
    logger.log_section("LC计量_预期现金流部分")
    
    # 年初LC余额_预期现金流：直接取数（简化处理，假设年初LC余额全部为预期现金流）
    bop_lc_cf = bop_lc
    
    # 当年新增LC_预期现金流：按比例分配
    # 分母：新增合同-初始确认-预期未来-（赔付+维费+RA）-初始确认现值（当月初始利率）
    if pv_data_init is None:
        nb_initial_lc_cf = DECIMAL_ZERO
    else:
        # 获取新增合同初始确认现值（当月初始利率）
        pv_nb_init_claims = pv_data_init.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt', DECIMAL_ZERO)
        pv_nb_init_maint = pv_data_init.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt', DECIMAL_ZERO)
        pv_nb_init_ra = pv_data_init.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt', DECIMAL_ZERO)
        
        denom_nb_init = pv_nb_init_claims + pv_nb_init_maint + pv_nb_init_ra
        if denom_nb_init > 0:
            nb_initial_lc_cf = nb_initial_lc_total * (pv_nb_init_claims + pv_nb_init_maint) / denom_nb_init
        else:
            nb_initial_lc_cf = DECIMAL_ZERO
    
    # LC分摊IFIE_预期现金流：IF_LC分摊IFIE_赔付与费用 + NB_LC分摊IFIE_赔付与费用
    if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
    
    # 分摊的LC_预期现金流：负的（有效合同+新增合同的预期当期赔付和维费）× LC分摊比例
    if pv_data_bop is None:
        allocated_lc_cf = DECIMAL_ZERO
    else:
        # 有效合同-年初预期-预期当年-赔付/维费现金流-期末现值（加权初始确认利率）
        pv_if_cur_claims = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_if_cur_maint = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        
        # 新增合同-初始确认-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
        pv_nb_cur_claims = DECIMAL_ZERO
        pv_nb_cur_maint = DECIMAL_ZERO
        if pv_data_init is not None:
            pv_nb_cur_claims = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
            pv_nb_cur_maint = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        
        allocated_lc_cf = -((pv_if_cur_claims + pv_if_cur_maint + pv_nb_cur_claims + pv_nb_cur_maint) * lc_ratio)
    
    # 被LC吸收的变化_预期现金流
    # IF(待调整LC余额_合计=0, -SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC), 被LC吸收的变化_合计*IFERROR(预期现金流变化合计/被CSM/LC吸收的变化合计,0))
    if lc_balance_to_adjust_total == 0:
        # 如果待调整LC余额_合计=0，则等于负的SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC)
        allocated_lc_exp_adj_cf = -(bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total)
    else:
        # 否则按比例分配
        if delta_csm_lc != 0:
            ratio_cf = delta_cf_total / delta_csm_lc if delta_csm_lc != 0 else DECIMAL_ZERO
            allocated_lc_exp_adj_cf = allocated_lc_exp_adj_total * ratio_cf
        else:
            allocated_lc_exp_adj_cf = DECIMAL_ZERO
    
    # 待调整LC余额_预期现金流
    lc_balance_to_adjust_cf = bop_lc_cf + nb_initial_lc_cf + lc_ifie_cf + allocated_lc_cf + allocated_lc_exp_adj_cf
    
    # LC调整_预期现金流：如果CSM摊销比例=100%，则等于负的待调整LC余额_预期现金流；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_cf = -lc_balance_to_adjust_cf
    else:
        lc_adjust_cf = DECIMAL_ZERO
    
    # 期末LC余额_预期现金流
    end_lc_cf = lc_balance_to_adjust_cf + lc_adjust_cf
    
    # 保存到context（供revenue模块使用）
    context.lc_adjust_cf = lc_adjust_cf
    
    logger.log_item(
        "LC计量_预期现金流",
        "[LC计量] 预期现金流部分的LC计量",
        "待调整LC余额_预期现金流 = SUM(年初LC余额_预期现金流, 当年新增LC_预期现金流, LC分摊IFIE_预期现金流, 分摊的LC_预期现金流, 被LC吸收的变化_预期现金流)\nLC调整_预期现金流 = IF(CSM摊销比例=100%, -待调整LC余额_预期现金流, 0)\n期末LC余额_预期现金流 = 待调整LC余额_预期现金流 + LC调整_预期现金流",
        {
            "年初LC余额_预期现金流": bop_lc_cf,
            "当年新增LC_预期现金流": nb_initial_lc_cf,
            "LC分摊IFIE_预期现金流": lc_ifie_cf,
            "分摊的LC_预期现金流": allocated_lc_cf,
            "被LC吸收的变化_预期现金流": allocated_lc_exp_adj_cf,
            "待调整LC余额_预期现金流": lc_balance_to_adjust_cf,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_预期现金流": lc_adjust_cf,
            "期末LC余额_预期现金流": end_lc_cf
        },
        end_lc_cf,
        note="LC调整_预期现金流供revenue模块使用"
    )
    
    # ==========================================================================================
    # 非金融风险调整部分
    # ==========================================================================================
    logger.log_section("LC计量_非金融风险调整部分")
    
    # 年初LC余额_非金融风险调整：直接取数（简化处理，假设为0）
    bop_lc_ra = DECIMAL_ZERO
    
    # 当年新增LC_非金融风险调整：当年新增LC_合计 - 当年新增LC_预期现金流
    nb_initial_lc_ra = nb_initial_lc_total - nb_initial_lc_cf
    
    # LC分摊IFIE_非金融风险调整：IF_LC分摊IFIE_非金融风险调整 + NB_LC分摊IFIE_非金融风险调整
    if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
    
    # 分摊的LC_非金融风险调整：负的（有效合同+新增合同的预期当期非金融风险调整）× LC分摊比例
    if pv_data_bop is None:
        allocated_lc_ra = DECIMAL_ZERO
    else:
        # 有效合同-年初预期-预期当年-非金融风险调整-期末现值（加权初始确认利率）
        pv_if_cur_ra = pv_data_bop.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        # 新增合同-初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）
        pv_nb_cur_ra = DECIMAL_ZERO
        if pv_data_init is not None:
            pv_nb_cur_ra = pv_data_init.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        allocated_lc_ra = -((pv_if_cur_ra + pv_nb_cur_ra) * lc_ratio)
    
    # 被LC吸收的变化_非金融风险调整：被LC吸收的变化_合计 - 被LC吸收的变化_预期现金流
    # 注意：这里使用合计部分计算出的allocated_lc_exp_adj_total
    allocated_lc_exp_adj_ra = allocated_lc_exp_adj_total - allocated_lc_exp_adj_cf
    
    # 待调整LC余额_非金融风险调整
    lc_balance_to_adjust_ra = bop_lc_ra + nb_initial_lc_ra + lc_ifie_ra + allocated_lc_ra + allocated_lc_exp_adj_ra
    
    # LC调整_非金融风险调整：如果CSM摊销比例=100%，则等于负的待调整LC余额_非金融风险调整；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_ra = -lc_balance_to_adjust_ra
    else:
        lc_adjust_ra = DECIMAL_ZERO
    
    # 期末LC余额_非金融风险调整
    end_lc_ra = lc_balance_to_adjust_ra + lc_adjust_ra
    
    # 保存到context（供revenue模块使用）
    context.lc_adjust_ra = lc_adjust_ra
    
    logger.log_item(
        "LC计量_非金融风险调整",
        "[LC计量] 非金融风险调整部分的LC计量",
        "待调整LC余额_非金融风险调整 = SUM(年初LC余额_非金融风险调整, 当年新增LC_非金融风险调整, LC分摊IFIE_非金融风险调整, 分摊的LC_非金融风险调整, 被LC吸收的变化_非金融风险调整)\nLC调整_非金融风险调整 = IF(CSM摊销比例=100%, -待调整LC余额_非金融风险调整, 0)\n期末LC余额_非金融风险调整 = 待调整LC余额_非金融风险调整 + LC调整_非金融风险调整",
        {
            "年初LC余额_非金融风险调整": bop_lc_ra,
            "当年新增LC_非金融风险调整": nb_initial_lc_ra,
            "LC分摊IFIE_非金融风险调整": lc_ifie_ra,
            "分摊的LC_非金融风险调整": allocated_lc_ra,
            "被LC吸收的变化_非金融风险调整": allocated_lc_exp_adj_ra,
            "待调整LC余额_非金融风险调整": lc_balance_to_adjust_ra,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_非金融风险调整": lc_adjust_ra,
            "期末LC余额_非金融风险调整": end_lc_ra
        },
        end_lc_ra,
        note="LC调整_非金融风险调整供revenue模块使用"
    )
    
    # ==========================================================================================
    # 合计部分（最终汇总和记录日志）
    # ==========================================================================================
    logger.log_section("LC计量_合计部分（最终汇总）")
    
    # 注意：合计部分的主要计算已在上面完成，这里只是汇总和记录日志
    # 待调整LC余额_合计已在上面计算
    
    # LC调整_合计：如果CSM摊销比例=100%，则等于负的待调整LC余额_合计；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_total = -lc_balance_to_adjust_total
    else:
        lc_adjust_total = DECIMAL_ZERO
    
    # 期末LC余额_合计
    end_lc_total = lc_balance_to_adjust_total + lc_adjust_total
    
    # 保存到context
    context.lc_change = allocated_lc_exp_adj_total
    context.end_lc_final = end_lc_total
    
    logger.log_item(
        "LC计量_合计",
        "[LC计量] 合计部分的LC计量",
        "待调整LC余额_合计 = SUM(年初LC余额_合计, 当年新增LC_合计, LC分摊IFIE_合计, 分摊的LC_合计, 被LC吸收的变化_合计)\nLC调整_合计 = IF(CSM摊销比例=100%, -待调整LC余额_合计, 0)\n期末LC余额_合计 = 待调整LC余额_合计 + LC调整_合计",
        {
            "年初LC余额_合计": bop_lc_total,
            "当年新增LC_合计": nb_initial_lc_total,
            "LC分摊IFIE_合计": lc_ifie_total,
            "分摊的LC_合计": allocated_lc_total,
            "被LC吸收的变化_合计": allocated_lc_exp_adj_total,
            "待调整LC余额_合计": lc_balance_to_adjust_total,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_合计": lc_adjust_total,
            "期末LC余额_合计": end_lc_total
        },
        end_lc_total,
        note="完整的LC计量逻辑，包括预期现金流、非金融风险调整和合计三部分"
    )


def run(
    context,
    logger,
    cohort_state: CohortState = None,
    policy_state: PolicyState = None,
    policies: List[PolicyState] = None,
    assumptions: Assumptions = None
):
    """
    执行CSM/LC计量
    
    对应文档：
    - 第6节：CSM计息
    - 第7节：LC分摊IFIE
    - 第8.5.5节：合同组CSM/LC判断
    - 第8.2节：CSM计量
    - LC计量
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policy_state: 保单状态（用于CSM计息）
        policies: 保单列表（用于合同组状态判定和CSM摊销）
        assumptions: 精算假设（可选）
    """
    logger.log_section("Part 3-8.5.5: CSM/LC计量 (CSM/LC Measurement)")
    
    # 步骤1：CSM计息
    _calculate_csm_interest(context, logger, cohort_state, policy_state)
    
    # 步骤2：LC分摊IFIE（需要在IFIE模块之后调用，这里简化处理）
    # 注意：完整的LC IFIE分摊应在IFIE模块中完成，这里只做基础计算
    _calculate_lc_ifie_allocation(context, logger, cohort_state)
    
    # 步骤3：合同组CSM/LC判断
    if cohort_state:
        _determine_cohort_status(cohort_state, context, logger, policies)
    
    # 步骤4：LC计量（先计算，供CSM计量使用）
    _calculate_lc_measurement(context, logger)
    
    # 步骤5：CSM计量（后计算，依赖LC计量结果）
    _calculate_csm_measurement(context, logger)
    
    logger.log_item(
        "CSM/LC计量合计",
        "[汇总] CSM/LC计量合计",
        "CSM/LC计量包括：CSM计息、LC分摊IFIE、合同组判断、CSM摊销、LC变化",
        {
            "CSM计息": (context.if_interest_csm or DECIMAL_ZERO) + (context.nb_interest_csm or DECIMAL_ZERO),
            "LC分摊IFIE": (context.if_lc_ifie_total or DECIMAL_ZERO) + (context.nb_lc_ifie_total or DECIMAL_ZERO),
            "CSM摊销": context.csm_amort_amount or DECIMAL_ZERO,
            "LC变化": context.lc_change or DECIMAL_ZERO,
            "期末CSM": context.end_csm_final or DECIMAL_ZERO,
            "期末LC": context.end_lc_final or DECIMAL_ZERO
        },
        (context.if_interest_csm or DECIMAL_ZERO) + (context.nb_interest_csm or DECIMAL_ZERO),
        note="使用统一字段逻辑：>=0走CSM逻辑，<0走LC逻辑"
    )

