"""
初始确认逻辑 (Initial Recognition)

对应文档：第1-3节

核心功能：
1. 使用即期利率（Spot Rate）计算现值（文档 Sec 2.0）
2. 先计算单单 PV，然后聚合到 CohortState
3. 调用 rates_manager 更新锁定利率（文档 Sec 1.5）
"""

from decimal import Decimal
from bba_model.utils.math_tools import calculate_future_pv_with_rates
from bba_model.logic.rates_manager import calculate_spot_rate, update_weighted_locked_rate
from bba_model.models import Assumptions


def run(context, logger, assumptions: Assumptions = None, cohort_state=None):
    """
    执行初始确认
    
    对应文档：第1-3节
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设（从数据库读取，包含动态假设）
        cohort_state: 合同组状态（可选，用于更新加权锁定利率）
    """
    logger.log_section("Part 1: 初始确认 (Initial Recognition) - New Business [Sec 1-3]")

    # 获取签单保费
    context.actual_premium = Decimal(context.policy_data['sum_premium_no_tax'] or 0)
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        ra_ratio = assumptions.ra_ratio
        acquisition_expense_ratio = assumptions.acquisition_expense_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from bba_model.config import RATIO_IACF, RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
        loss_ratio = RATIO_CLAIM
        indirect_claims_expense_ratio = Decimal('0')
        maintenance_expense_ratio = RATIO_MAINT_EXP
        ra_ratio = RATIO_RA
        acquisition_expense_ratio = RATIO_IACF
    
    # [Sec 2.0] 新单初始确认：使用即期利率（Spot Rate）计算现值
    spot_rate = calculate_spot_rate(context.rates_df)
    logger.log_item(
        "即期利率（Spot Rate）",
        "[Sec 2.0] 新单初始确认时使用的即期利率",
        "利率曲线的第一个值",
        {},
        spot_rate,
        note="新单初始确认时使用即期利率计算现值，计算完成后权重并入加权锁定利率"
    )
    
    # 1.1 保费现值（文档 Sec 2.1）
    # 保费发生在 T=0，现值 = Written Premium
    pv_premium = context.actual_premium
    logger.log_item(
        "当年新增合同_初始确认_预期保费现值",
        "[Sec 2.1] 初始确认时，预期未来收到的保费折现值",
        "Written Premium (发生在 T=0)",
        {"Written Premium": context.actual_premium},
        pv_premium
    )
    
    # 1.2 IACF 现值（文档 Sec 2.1）
    # 获取费用发生在 T=0，现值 = Actual Acquisition Cost
    val_iacf = context.actual_premium * acquisition_expense_ratio
    logger.log_item(
        "当年新增合同_初始确认_IACF现值",
        "[Sec 2.1] 初始确认时，预期支付的获取费用折现值",
        "Written Premium * Acquisition Expense Ratio",
        {"Premium": context.actual_premium, "Acquisition Expense Ratio": acquisition_expense_ratio},
        val_iacf
    )

    # 1.3 赔付现值（文档 Sec 2.2）
    # 使用即期利率（Spot Rate）对应的月化远期利率进行折现
    # 注意：calculate_future_pv_with_rates 使用 rates_df，即期利率对应 rate_offset=0
    context.init_fut_claim = calculate_future_pv_with_rates(
        context.actual_premium, 
        loss_ratio * (Decimal('1') + indirect_claims_expense_ratio),  # 赔付率 × (1 + ULAE比率)
        context.total_months, 
        0,  # passed_months = 0（初始确认时点）
        context.rates_df,
        rate_offset=0  # 使用即期利率（Spot Rate）
    )
    logger.log_item(
        "当年新增合同_初始确认_预期赔付现值",
        "[Sec 2.2] 初始确认时，预期未来赔付支出的折现值（使用即期利率）",
        "SUM(Monthly Claim * Discount Factor with Spot Rate)",
        {
            "Total Premium": context.actual_premium, 
            "Loss Ratio": loss_ratio,
            "ULAE Ratio": indirect_claims_expense_ratio,
            "Total Months": context.total_months
        },
        context.init_fut_claim,
        note="使用即期利率（Spot Rate）进行折现"
    )

    # 1.4 维费现值（文档 Sec 2.3）
    context.init_fut_maint = calculate_future_pv_with_rates(
        context.actual_premium, 
        maintenance_expense_ratio, 
        context.total_months, 
        0,  # passed_months = 0
        context.rates_df,
        rate_offset=0  # 使用即期利率（Spot Rate）
    )
    logger.log_item(
        "当年新增合同_初始确认_预期维费现值",
        "[Sec 2.3] 初始确认时，预期未来维持费用的折现值（使用即期利率）",
        "SUM(Monthly Maint * Discount Factor with Spot Rate)",
        {"Total Premium": context.actual_premium, "Maint Ratio": maintenance_expense_ratio},
        context.init_fut_maint,
        note="使用即期利率（Spot Rate）进行折现"
    )

    # 1.5 RA（文档 Sec 3.2）
    context.init_ra = (context.init_fut_claim + context.init_fut_maint) * ra_ratio
    logger.log_item(
        "当年新增合同_初始确认_非金融风险调整(RA)",
        "[Sec 3.2] 初始确认时，对非金融风险的调整额",
        "(Claim PV + Maint PV) * RA Ratio",
        {"Claim PV": context.init_fut_claim, "Maint PV": context.init_fut_maint, "RA Ratio": ra_ratio},
        context.init_ra
    )

    # 1.6 初始 CSM/LC 计算（文档 Sec 3.3）
    # 注意：此为初始确认时的逐单判定，后续需进行合同组聚合判定（见第8.5节）
    pv_inflow = pv_premium
    pv_outflow = val_iacf + context.init_fut_claim + context.init_fut_maint
    net_inflow = pv_inflow - pv_outflow
    margin = net_inflow - context.init_ra
    
    context.nb_initial_csm = Decimal('0')
    context.nb_initial_lc = Decimal('0')
    
    csm_status = ""
    if margin >= 0:
        context.nb_initial_csm = margin
        csm_status = "Profitable (CSM)"
    else:
        context.nb_initial_lc = -margin
        csm_status = "Onerous (Loss Component) - 立即确认亏损"

    logger.log_item(
        "当年新增合同_初始确认_CSM/LC",
        "[Sec 3.3] 初始确认时的合同服务边际或亏损（逐单判定）",
        "Net_Inflow = PV_Prem - (PV_Claims + PV_Maint + PV_IACF); Margin = Net_Inflow - RA",
        {
            "PV_Prem": pv_inflow,
            "PV_IACF": val_iacf,
            "PV_Claims": context.init_fut_claim,
            "PV_Maint": context.init_fut_maint,
            "Net_Inflow": net_inflow,
            "RA": context.init_ra,
            "Margin": margin
        },
        margin,
        note=f"判定结果: {csm_status}. Initial CSM = {context.nb_initial_csm:,.2f}, Initial LC = {context.nb_initial_lc:,.2f}。注意：初始确认时逐单计算 CSM/LC，但最终状态需在合同组层面聚合判定（见第8.5节）"
    )
    
    # [Sec 1.5] 更新加权初始确认利率
    if cohort_state:
        update_weighted_locked_rate(
            cohort_state,
            spot_rate,
            context.actual_premium,
            logger
        )

