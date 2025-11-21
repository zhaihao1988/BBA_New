"""
被CSM/LC吸收的变化与合同组状态判定

对应文档：
- 第5节：被CSM/LC吸收的变化
- 第8.5.5节：合同组状态判定（关键步骤）

核心功能：
1. 计算被CSM/LC吸收的变化（文档 Sec 5）
2. 实现合同组状态判定（文档 Sec 8.5.5）
3. 执行状态回写（Re-apportionment）
"""

from decimal import Decimal
from typing import List, Optional, Any
from bba_model.models import CohortState, PolicyState


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
    
    # [Sec 5.2] 保费现金流变化
    # 注意：需扣除对应的经验调整项（见第4.3节）
    delta_prem = context.prem_var - getattr(context, 'adj_prem', Decimal('0'))
    
    # [Sec 5.3] IACF变化
    # 注意：需扣除对应的经验调整项（见第4.4节）
    delta_iacf = context.iacf_var - getattr(context, 'adj_iacf', Decimal('0'))
    
    # [Sec 5.4] 赔付现金流变化
    delta_claims = -context.claim_var  # 赔付增加导致负债增加，变化为负
    
    # [Sec 5.5] 维持费用现金流变化
    delta_maint = -context.maint_var  # 费用增加导致负债增加，变化为负
    
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
        note="所有现值均使用加权初始确认利率折现"
    )
    
    # [Sec 5.7] 非金融风险调整变化
    # 简化：假设RA变化为0
    delta_ra = Decimal('0')
    
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

