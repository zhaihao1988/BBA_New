from decimal import Decimal
from bba_model.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
from bba_model.utils.math_tools import calculate_future_pv_with_rates
import pandas as pd
from bba_model.data_access.loader import get_rates

def run(context, logger):
    logger.log_section("Part 7: 保险合同收入 (Insurance Revenue)")
    
    # 7.1 预期赔付与费用释放
    revenue_expected_claims = context.expected_claim_nominal
    revenue_expected_maint = context.expected_maint_nominal
    
    revenue_claims_expenses_gross = revenue_expected_claims + revenue_expected_maint
    revenue_claims_expenses_lc_alloc = revenue_claims_expenses_gross * context.nb_lc_ratio
    context.revenue_claims_expenses_net = revenue_claims_expenses_gross - revenue_claims_expenses_lc_alloc
    
    logger.log_item(
        "保险合同收入_预期赔付与费用",
        "当期预期的赔付和维持费用释放 (扣除亏损分摊)",
        "(Expected Claims + Expected Maint) * (1 - LC Ratio)",
        {
            "Expected Claims": revenue_expected_claims,
            "Expected Maint": revenue_expected_maint,
            "LC Ratio": context.nb_lc_ratio
        },
        context.revenue_claims_expenses_net,
        note=f"Gross: {revenue_claims_expenses_gross:,.2f}, Allocated to LC: {revenue_claims_expenses_lc_alloc:,.2f}"
    )
    
    # 7.2 RA 释放 (倒挤法)
    # Step A: 获取期末利率曲线 (用于计算 End_RA)
    eop_month_str = context.eop_date.strftime('%Y%m')
    context.rates_df_eop = get_rates(eop_month_str)
    if context.rates_df_eop.empty: context.rates_df_eop = context.rates_df # Fallback

    # Step B: 计算 End_BEL (基于 Current Rates)
    # PV EOP (Current Rates)
    context.pv_eop_claims_current = calculate_future_pv_with_rates(
        context.actual_premium, RATIO_CLAIM, context.total_months, context.months_passed, context.rates_df_eop, rate_offset=0
    )
    context.pv_eop_maint_current = calculate_future_pv_with_rates(
        context.actual_premium, RATIO_MAINT_EXP, context.total_months, context.months_passed, context.rates_df_eop, rate_offset=0
    )
    end_bel_current = context.pv_eop_claims_current + context.pv_eop_maint_current
    
    # Step C: 计算 End_RA
    end_ra = end_bel_current * RATIO_RA
    
    # Step D: 计算 RA Interest (需与IFIE一致)
    ra_interest = context.init_ra * context.accretion_factor
    
    # Step E: 倒挤 Release
    ra_release_gross = (Decimal('0') + context.init_ra + ra_interest) - end_ra
    
    # 扣除 LC 分摊
    ra_release_lc_alloc = ra_release_gross * context.nb_lc_ratio
    context.ra_release_net = ra_release_gross - ra_release_lc_alloc
    
    logger.log_item(
        "保险合同收入_RA释放",
        "当期释放的非金融风险调整 (倒挤法: Start + New + Int - End)",
        "(Init_RA + RA_Interest - End_RA) * (1 - LC Ratio)",
        {
            "Init RA": context.init_ra, 
            "RA Interest": ra_interest,
            "End RA (calc from End BEL)": end_ra,
            "LC Ratio": context.nb_lc_ratio
        },
        context.ra_release_net,
        note=f"End BEL(Current): {end_bel_current:,.2f}"
    )
    
    # 7.3 CSM 摊销（文档 Sec 8.2 & 8.9）
    # 使用覆盖单元动态比例法计算摊销比例
    from bba_model.logic.coverage_units import calculate_csm_amortization_ratio
    from datetime import date
    
    # 获取年初日期（用于计算覆盖单元）
    start_of_year = date(context.year, 1, 1)
    
    # 获取保单列表（用于计算覆盖单元）
    # 注意：如果 context 中没有 policies，则使用简化方法
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
        # 兼容旧代码：使用时间比例法
        current_period_months = context.months_passed
        remaining_months = context.total_months - context.months_passed
        if remaining_months < 0:
            remaining_months = 0
        
        denom_units = Decimal(current_period_months + remaining_months)
        if denom_units > 0:
            csm_amort_ratio = Decimal(current_period_months) / denom_units
        else:
            csm_amort_ratio = Decimal('1')  # 全部摊销
        
        logger.log_item(
            "CSM摊销比例（兼容模式）",
            "[Sec 8.2] 未提供保单列表，使用时间比例法（不推荐）",
            "Current Months / (Current + Remaining Months)",
            {
                "Current Months": current_period_months,
                "Remaining Months": remaining_months
            },
            csm_amort_ratio,
            note="⚠️ 警告：应使用覆盖单元动态比例法"
        )
    
    context.csm_amort_amount = -(context.end_csm_before_amort * csm_amort_ratio)
    
    logger.log_item(
        "保险合同收入_CSM摊销",
        "[Sec 8.9] 当期确认的合同服务边际（使用覆盖单元动态比例法）",
        "CSM_Amort = -(CSM_beg + CSM_new + CSM_Interest + Δ_CSM) × CSM_Amort_Ratio",
        {
            "CSM Balance (摊销前)": context.end_csm_before_amort,
            "摊销比例": csm_amort_ratio
        },
        context.csm_amort_amount,
        note="负号表示摊销减少 CSM 余额；释放的覆盖单元已包含自保单起期至当前评估日的累计服务（含追溯月份）"
    )
    
    # 更新期末 CSM（csm_amort_amount 为负值，直接相加即可完成扣减）
    context.end_csm_final = context.end_csm_before_amort + context.csm_amort_amount
    
    # 7.4 IACF 摊销 (Revenue Impact)
    context.revenue_iacf_amort = abs(context.iacf_amort_amount)
    
    logger.log_item(
        "保险合同收入_IACF摊销",
        "当期回收的获取费用",
        "Abs(IACF Amortization Expense)",
        {"IACF Amort Expense": context.iacf_amort_amount},
        context.revenue_iacf_amort
    )
    
    # 7.5 经验调整 (Revenue Part)
    context.revenue_exp_adj = context.prem_var
    
    logger.log_item(
        "保险合同收入_经验调整",
        "与当期服务相关的保费经验调整",
        "Premium Variance (Current Service)",
        {"Prem Var": context.prem_var},
        context.revenue_exp_adj
    )
    
    # 7.6 投资成分
    revenue_inv_comp = Decimal('0')
    
    # 7.7 合计
    context.total_revenue = (
        context.revenue_claims_expenses_net +
        context.ra_release_net +
        context.csm_amort_amount +
        context.revenue_iacf_amort +
        context.revenue_exp_adj - 
        revenue_inv_comp
    )
    
    logger.log_item(
        "保险合同收入_合计",
        "当期确认的总保险合同收入",
        "Sum(Exp Claims Net + RA Net + CSM Amort + IACF Amort + Exp Adj - Inv Comp)",
        {
            "Exp Claims Net": context.revenue_claims_expenses_net,
            "RA Net": context.ra_release_net,
            "CSM Amort": context.csm_amort_amount,
            "IACF Amort": context.revenue_iacf_amort
        },
        context.total_revenue
    )

