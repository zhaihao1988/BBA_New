"""
被CSM/LC吸收的变化与合同组状态判定

对应文档：
- 第5节：被CSM/LC吸收的变化
- 第8.5.5节：合同组状态判定（关键步骤）

核心功能：
1. 计算被CSM/LC吸收的变化（文档 Sec 5）
2. 实现合同组状态判定（文档 Sec 8.5.5）
3. 执行状态回写（Re-apportionment）

注意：所有现值必须从PV原材料数据读取，不允许使用旧的计算方式。
"""

from decimal import Decimal
from typing import List, Optional, Any
from BBA_dev.models import CohortState, PolicyState
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data

DECIMAL_ZERO = Decimal('0')


def _pv_amount(pv_data, field_name: str) -> Decimal:
    if pv_data is None:
        return DECIMAL_ZERO
    try:
        return pv_data.get_field(field_name, DECIMAL_ZERO)
    except Exception:
        return DECIMAL_ZERO


def calculate_absorption(context, logger, cohort_state: CohortState = None, policies: List[PolicyState] = None):
    """
    计算被CSM/LC吸收的变化
    
    对应文档：第5节
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policies: 保单列表（用于合同组状态判定）
    """
    logger.log_section("Part 4: 被CSM/LC吸收的变化 (CSM/LC Absorption) [Sec 5]")
    
    # 强制要求PV原材料数据必须存在（用于验证现值来源）
    if context.pv_source_data is None:
        ensure_pv_source_data(context)
    
    if context.pv_source_data is None:
        policy_no = getattr(context.policy_data, 'policy_no', None) or getattr(context, 'policy_no', 'UNKNOWN')
        raise ValueError(
            f"❌ 错误: PV原材料数据不可用！\n"
            f"   保单号: {policy_no}\n"
            f"   请先运行 pv_calculator.py 生成PV原材料数据文件: logs/pv_source_data_{policy_no}.json\n"
            f"   系统要求必须使用PV原材料数据，不允许使用旧的计算方式。"
        )
    
    # 验证context中的现值是否已从PV原材料数据读取
    # 这些值应该在initial_recognition.py中已经设置
    if not hasattr(context, 'init_fut_claim') or context.init_fut_claim is None:
        raise ValueError(
            "❌ 错误: context.init_fut_claim 未设置！\n"
            "   请确保 initial_recognition.py 已从PV原材料数据读取赔付现值。"
        )
    if not hasattr(context, 'init_fut_maint') or context.init_fut_maint is None:
        raise ValueError(
            "❌ 错误: context.init_fut_maint 未设置！\n"
            "   请确保 initial_recognition.py 已从PV原材料数据读取维费现值。"
        )
    if not hasattr(context, 'init_ra') or context.init_ra is None:
        raise ValueError(
            "❌ 错误: context.init_ra 未设置！\n"
            "   请确保 initial_recognition.py 已从PV原材料数据读取RA现值。"
        )
    
    # 获取评估月和年初月份
    eop_month_str = context.val_month_str
    from dateutil.relativedelta import relativedelta
    from datetime import datetime
    bop_month_str = (context.eop_date.replace(day=1) - relativedelta(months=11)).strftime('%Y%m') if hasattr(context, 'eop_date') else None
    if bop_month_str is None:
        # 如果没有eop_date，尝试从val_month_str推算
        val_date = datetime.strptime(eop_month_str, '%Y%m')
        bop_date = val_date.replace(month=1, day=1)
        bop_month_str = bop_date.strftime('%Y%m')
    
    # 获取PV数据
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    pv_data_bop = context.pv_source_data.get_data(bop_month_str) if bop_month_str else None
    
    if pv_data_eop is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    uw_month_str = context.under_write_date.strftime('%Y%m') if hasattr(context, 'under_write_date') and context.under_write_date else None
    pv_data_init = context.pv_source_data.get_data(uw_month_str) if uw_month_str else None
    
    from BBA_dev.utils.pv_field_desc import describe_field
    
    # 判断是否为新增合同（第一年）
    # 优先从context获取，如果没有则根据评估年度和签单年度判断
    if hasattr(context, 'is_new_business'):
        is_new_business = context.is_new_business
    elif hasattr(context, 'under_write_date') and hasattr(context, 'year'):
        is_new_business = (context.year == context.under_write_date.year)
    else:
        is_new_business = False
    
    # [Sec 5.2] 保费现金流变化
    # 统一按文档公式使用加权初始确认利率 (Wlk)
    eff_f_end_prem = _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt')
    eff_f_beg_prem = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt')
    eff_c_year_prem = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt')
    new_f_end_prem = _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt')
    new_f_init_prem = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Wlk_Pre_Amt')
    new_c_init_prem = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt')
    actual_prem_nb = getattr(context, 'actual_premium_nb', None)
    if actual_prem_nb is None:
        actual_prem_nb = context.actual_premium if hasattr(context, 'under_write_date') and context.year == context.under_write_date.year else DECIMAL_ZERO
    actual_prem_if = getattr(context, 'actual_premium_eff', DECIMAL_ZERO)
    adj_prem = getattr(context, 'adj_prem', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_prem = ((eff_f_end_prem + new_f_end_prem) - (eff_f_beg_prem + new_f_init_prem)
                  + (actual_prem_if + actual_prem_nb) - (eff_c_year_prem + new_c_init_prem) - adj_prem)
    logger.log_item(
        "保费现金流变化",
        "[Sec 5.2] 保费现金流变化（统一Wlk公式）",
        "Δ_Prem = (Eff_F_end + New_F_end) - (Eff_F_beg + New_F_init) + (Eff_C_actual + New_C_actual) - (Eff_C_year + New_C_init) - Adj_Prem",
        {
            "Eff_F_end": eff_f_end_prem,
            "New_F_end": new_f_end_prem,
            "Eff_F_beg": eff_f_beg_prem,
            "New_F_init": new_f_init_prem,
            "Eff_C_actual": actual_prem_if,
            "New_C_actual": actual_prem_nb,
            "Eff_C_year": eff_c_year_prem,
            "New_C_init": new_c_init_prem,
            "Adj_Prem": adj_prem
        },
        delta_prem,
        note="全部使用Wlk字段并扣除经验调整"
    )

    # [Sec 5.3] IACF变化
    eff_f_end_iacf = _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt')
    eff_f_beg_iacf = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt')
    eff_c_year_iacf = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt')
    new_f_end_iacf = _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt')
    new_f_init_iacf = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Wlk_Acq_Amt')
    new_c_init_iacf = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt')
    actual_iacf_nb = getattr(context, 'actual_iacf_nb', None)
    if actual_iacf_nb is None:
        actual_iacf_nb = context.actual_iacf_incurred if hasattr(context, 'under_write_date') and context.year == context.under_write_date.year else DECIMAL_ZERO
    actual_iacf_if = getattr(context, 'actual_iacf_eff', DECIMAL_ZERO)
    adj_iacf = getattr(context, 'adj_iacf', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_iacf = ((eff_f_end_iacf + new_f_end_iacf) - (eff_f_beg_iacf + new_f_init_iacf)
                  + (actual_iacf_if + actual_iacf_nb) - (eff_c_year_iacf + new_c_init_iacf) - adj_iacf)
    logger.log_item(
        "IACF变化",
        "[Sec 5.3] IACF变化（统一Wlk公式）",
        "Δ_IACF = (Eff_F_end^I + New_F_end^I) - (Eff_F_beg^I + New_F_init^I) + (Eff_C_actual^I + New_C_actual^I) - (Eff_C_year^I + New_C_init^I) - Adj_IACF",
        {
            "Eff_F_end^I": eff_f_end_iacf,
            "New_F_end^I": new_f_end_iacf,
            "Eff_F_beg^I": eff_f_beg_iacf,
            "New_F_init^I": new_f_init_iacf,
            "Eff_C_actual^I": actual_iacf_if,
            "New_C_actual^I": actual_iacf_nb,
            "Eff_C_year^I": eff_c_year_iacf,
            "New_C_init^I": new_c_init_iacf,
            "Adj_IACF": adj_iacf
        },
        delta_iacf,
        note="全部使用Wlk字段并扣除经验调整"
    )


    # [Sec 5.4] 赔付现金流变化
    eff_f_end_claim = _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt')
    eff_f_beg_claim = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt')
    new_f_end_claim = _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt')
    new_f_init_claim = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Wlk_Cla_Amt')
    delta_claims = (eff_f_end_claim + new_f_end_claim) - (eff_f_beg_claim + new_f_init_claim)
    logger.log_item(
        "赔付与费用_预期赔付变化",
        "[Sec 5.4] 赔付现金流变化（统一Wlk公式）",
        "Δ_Claims = (Eff_F_end^Cla + New_F_end^Cla) - (Eff_F_beg^Cla + New_F_init^Cla)",
        {
            "Eff_F_end^Cla": eff_f_end_claim,
            "Eff_F_beg^Cla": eff_f_beg_claim,
            "New_F_end^Cla": new_f_end_claim,
            "New_F_init^Cla": new_f_init_claim
        },
        delta_claims
    )

    # [Sec 5.5] 维持费用现金流变化
    eff_f_end_maint = _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    eff_f_beg_maint = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt')
    new_f_end_maint = _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    new_f_init_maint = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Wlk_Mtn_Amt')
    delta_maint = (eff_f_end_maint + new_f_end_maint) - (eff_f_beg_maint + new_f_init_maint)
    logger.log_item(
        "维持费用现金流变化",
        "[Sec 5.5] 维持费用现金流变化（统一Wlk公式）",
        "Δ_Maint = (Eff_F_end^Mtn + New_F_end^Mtn) - (Eff_F_beg^Mtn + New_F_init^Mtn)",
        {
            "Eff_F_end^Mtn": eff_f_end_maint,
            "Eff_F_beg^Mtn": eff_f_beg_maint,
            "New_F_end^Mtn": new_f_end_maint,
            "New_F_init^Mtn": new_f_init_maint
        },
        delta_maint
    )

    # [Sec 5.6] 预期现金流变化合计
    delta_cf_total = delta_prem + delta_iacf + delta_claims + delta_maint
    logger.log_item(
        "预期现金流变化合计",
        "[Sec 5.6] 保费、IACF、赔付、维持费用的变化合计",
        "Δ_CF_Total = Δ_Prem + Δ_IACF + Δ_Claims + Δ_Maint",
        {
            "Δ_Prem": delta_prem,
            "Δ_IACF": delta_iacf,
            "Δ_Claims": delta_claims,
            "Δ_Maint": delta_maint
        },
        delta_cf_total,
        note="所有组成均基于加权初始确认利率 (Wlk)"
    )

    # [Sec 5.7] 非金融风险调整变化
    eff_f_end_ra = _pv_amount(pv_data_eop, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
    eff_f_beg_ra = _pv_amount(pv_data_bop, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt')
    new_f_end_ra = _pv_amount(pv_data_eop, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
    new_f_init_ra = _pv_amount(pv_data_init, 'Pvfl_Nb_Ini_Cfa_Rec_Wlk_Rad_Amt')
    delta_ra = (eff_f_end_ra + new_f_end_ra) - (eff_f_beg_ra + new_f_init_ra)
    logger.log_item(
        "非金融风险调整变化",
        "[Sec 5.7] RA变化（统一Wlk公式）",
        "Δ_RA = (Eff_F_end^RA + New_F_end^RA) - (Eff_F_beg^RA + New_F_init^RA)",
        {
            "Eff_F_end^RA": eff_f_end_ra,
            "Eff_F_beg^RA": eff_f_beg_ra,
            "New_F_end^RA": new_f_end_ra,
            "New_F_init^RA": new_f_init_ra
        },
        delta_ra
    )

    # [Sec 5.8] 被CSM/LC吸收的变化合计（含会计估计变更）
    changes_in_est = getattr(context, 'changes_in_estimates', Decimal('0')) or Decimal('0')
    delta_csm_lc = delta_cf_total + delta_ra - changes_in_est
    context.exp_adj_csm_impact = delta_csm_lc
    
    logger.log_item(
        "被CSM/LC吸收的变化合计",
        "[Sec 5.8] 当期各类现金流、风险调整与会计估计变更对合同服务边际或亏损合同的影响",
        "Δ_CSM/LC = Δ_CF_Total + Δ_RA - Δ_Estimates",
        {
            "Δ_CF_Total": delta_cf_total,
            "Δ_RA": delta_ra,
            "Δ_Estimates": changes_in_est
        },
        delta_csm_lc
    )
    
    # [Sec 7.2.2] LC IFIE分摊比例（期初有效合同）
    if_lc_ratio = Decimal('0')
    if cohort_state and cohort_state.bop_lc < 0:
        # 分母：预期赔付现金流初始确认现值 + 预期维持费用现金流初始确认现值 + 预期非金融风险调整初始确认现值
        denom_if = context.init_fut_claim + context.init_fut_maint + context.init_ra
        if denom_if > 0:
            if_lc_ratio = abs(cohort_state.bop_lc) / denom_if
    
    # [Sec 7.3.2] LC IFIE分摊比例（当年新增合同）
    nb_lc_ratio = Decimal('0')
    if context.nb_initial_lc and context.nb_initial_lc < 0:
        denom_nb = context.init_fut_claim + context.init_fut_maint + context.init_ra
        if denom_nb > 0:
            nb_lc_ratio = abs(context.nb_initial_lc) / denom_nb
    
    context.nb_lc_ratio = nb_lc_ratio
    
    # [Sec 5] 分摊到LC的变化
    context.allocated_lc_exp_adj = delta_csm_lc * nb_lc_ratio
    context.csm_absorbed = delta_csm_lc - context.allocated_lc_exp_adj
    
    # [Sec 8.5.5] 合同组状态判定（关键步骤）
    if cohort_state:
        determine_cohort_status(cohort_state, context, logger, policies)
    
    # 使用上下文中的原子数据统一计算期末余额（摊销前）
    val_bop_csm = getattr(context, 'bop_csm', Decimal('0')) or Decimal('0')
    val_bop_lc = getattr(context, 'bop_lc', Decimal('0')) or Decimal('0')
    val_nb_csm = context.nb_initial_csm or Decimal('0')
    val_nb_lc = context.nb_initial_lc or Decimal('0')
    val_if_interest_csm = getattr(context, 'if_interest_csm', Decimal('0')) or Decimal('0')
    val_if_interest_lc = getattr(context, 'if_interest_lc', Decimal('0')) or Decimal('0')
    val_nb_interest_csm = context.nb_interest_csm or Decimal('0')
    val_nb_interest_lc = context.nb_interest_lc or Decimal('0')
    val_interest_csm = val_if_interest_csm + val_nb_interest_csm
    val_interest_lc = val_if_interest_lc + val_nb_interest_lc
    val_lc_change = getattr(context, 'lc_change', Decimal('0')) or Decimal('0')

    context.end_csm_before_amort = val_bop_csm + val_nb_csm + val_interest_csm + context.csm_absorbed
    context.end_lc_before_amort = val_bop_lc + val_nb_lc + val_interest_lc + val_lc_change

def determine_cohort_status(
    cohort_state: CohortState,
    context: Any,
    logger: Any,
    policies: Optional[List[PolicyState]] = None
):
    """
    合同组状态判定（关键步骤）
    
    对应文档：第8.5.5节
    
    核心逻辑：
    1. 计算合同组净余额试算值
    2. 确定合同组最终状态（盈利或亏损）
    3. 执行状态回写（Re-apportionment）
    
    Args:
        cohort_state: 合同组状态
        context: 计算上下文
        logger: 日志记录器
        policies: 保单列表（用于状态回写）
    """
    logger.log_section("Part 4.5: 合同组状态判定 (Cohort Status Determination) [Sec 8.5.5]")
    
    # [Sec 8.5.5] 步骤1：计算合同组净余额试算值
    # IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC
    if_csm_post = cohort_state.bop_csm + cohort_state.csm_interest
    nb_csm_post = context.nb_initial_csm + context.nb_interest_csm
    if_lc_post = cohort_state.bop_lc  # 简化：假设无IFIE分摊
    nb_lc_post = context.nb_initial_lc + context.nb_interest_lc
    
    net_trial = if_csm_post + nb_csm_post + if_lc_post + nb_lc_post
    
    logger.log_item(
        "合同组净余额试算值",
        "[Sec 8.5.5] 步骤1：计算合同组净余额试算值",
        "Net_trial = Σ(IF_CSM_post + NB_CSM_post + IF_LC_post + NB_LC_post)",
        {
            "IF_CSM_post": if_csm_post,
            "NB_CSM_post": nb_csm_post,
            "IF_LC_post": if_lc_post,
            "NB_LC_post": nb_lc_post
        },
        net_trial
    )
    
    # [Sec 8.5.5] 步骤2：确定合同组最终状态
    if net_trial >= 0:
        # 合同组为盈利状态
        cohort_csm = net_trial
        cohort_lc = Decimal('0')
        cohort_state.is_profitable = True
        status = "盈利 (Profitable)"
    else:
        # 合同组为亏损状态
        cohort_csm = Decimal('0')
        cohort_lc = net_trial
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
    
    # [Sec 8.5.5] 步骤3：状态回写（Re-apportionment）
    # 若组为盈利，所有 LC 清零；若组为亏损，所有 CSM 清零
    if policies:
        for policy in policies:
            if cohort_state.is_profitable:
                # 合同组为盈利状态：强制清零所有 LC
                policy.initial_lc = Decimal('0')
                # 保持 CSM 不变（已在上面计算）
            else:
                # 合同组为亏损状态：强制清零所有 CSM
                policy.initial_csm = Decimal('0')
                # 保持 LC 不变（已在上面计算）
        
        logger.log_item(
            "状态回写",
            "[Sec 8.5.5] 步骤3：状态回写（Re-apportionment）",
            "组盈利则LC清零，组亏损则CSM清零",
            {
                "保单数量": len(policies),
                "合同组状态": status
            },
            Decimal('0'),
            note="确保合同组内所有保单的 CSM/LC 标记与合同组状态一致"
        )
    
    # 更新期末余额（摊销前）
    context.end_csm_before_amort = cohort_csm
    context.end_lc_before_amort = cohort_lc
    
    # 更新 CohortState
    cohort_state.net_trial = net_trial

