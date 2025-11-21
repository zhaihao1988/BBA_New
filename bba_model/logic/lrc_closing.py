from decimal import Decimal
from bba_model.config import RATIO_RA

def run_closing(context, logger):
    logger.log_section("Part 9: 期末未到期责任负债 (LRC Closing Balance)")
    
    # 9.1 预期保费 (0)
    lrc_bel_premium = Decimal('0')
    logger.log_item("预期保费现金流现值", "期末预期未来收到的保费现值", "- PV_EOP_Premiums", {"Future Premiums": 0}, lrc_bel_premium)
    
    # 9.2 预期IACF (0)
    lrc_bel_iacf = Decimal('0')
    logger.log_item("预期IACF现值", "期末预期未来支付的获取费用现值", "PV_EOP_IACF", {"Future IACF": 0}, lrc_bel_iacf)
    
    # 9.3 预期赔付与费用
    # PV EOP (Current Rates) 已经在 Part 7 计算并存入 context
    lrc_bel_claims_expenses = context.pv_eop_claims_current + context.pv_eop_maint_current
    logger.log_item(
        "预期赔付与费用现金流现值",
        "期末预期未来赔付和维持费用的现值 (基于期末利率)",
        "PV_EOP_Claims + PV_EOP_Maint",
        {"PV EOP Claims": context.pv_eop_claims_current, "PV EOP Maint": context.pv_eop_maint_current},
        lrc_bel_claims_expenses
    )
    
    # 9.4 Total BEL
    lrc_bel_total = lrc_bel_premium + lrc_bel_iacf + lrc_bel_claims_expenses
    logger.log_item("预期现金流现值 (BEL)", "履约现金流的现值估计", "Sum(Premium, IACF, Claims & Expenses)", {}, lrc_bel_total)
    
    # 9.5 RA
    lrc_ra = lrc_bel_total * RATIO_RA
    logger.log_item("预期非金融风险调整 (RA)", "期末非金融风险调整余额", "BEL * RA Ratio", {"BEL": lrc_bel_total}, lrc_ra)
    
    # 9.6 CSM
    lrc_csm = context.end_csm_final
    if lrc_csm is None:
        csm_before = getattr(context, 'end_csm_before_amort', None) or Decimal('0')
        csm_amort = getattr(context, 'csm_amort_amount', None) or Decimal('0')
        lrc_csm = csm_before - csm_amort
    logger.log_item("CSM (合同服务边际)", "期末合同服务边际余额", "End CSM Balance", {}, lrc_csm)
    
    # 9.7 Total LRC
    lrc_total = lrc_bel_total + lrc_ra + lrc_csm
    logger.log_item(
        "期末未到期责任负债余额 (Total LRC)",
        "期末未到期责任负债总额",
        "BEL + RA + CSM",
        {"BEL": lrc_bel_total, "RA": lrc_ra, "CSM": lrc_csm},
        lrc_total
    )

def run_summary(context, logger):
    logger.log_section("Part 5: 汇总 (Summary)")
    
    csm_interest_total = getattr(context, 'total_csm_interest', None)
    if csm_interest_total is None:
        csm_interest_total = (context.nb_interest_csm or Decimal('0')) + (getattr(context, 'if_interest_csm', Decimal('0')) or Decimal('0'))
    lc_interest_total = (context.nb_interest_lc or Decimal('0')) + (getattr(context, 'if_interest_lc', Decimal('0')) or Decimal('0'))
    
    print(f"CSM 变动表:")
    print(f"  期初余额:          0.00")
    print(f"  + 本年新增:        {context.nb_initial_csm:,.2f}")
    print(f"  + 计息:            {csm_interest_total:,.2f}")
    print(f"  + 经验调整(CSM):    {context.csm_absorbed:,.2f}")
    print(f"  - 摊销:            {context.csm_amort_amount:,.2f}")
    print(f"  = 期末CSM余额:      {context.end_csm_final:,.2f}")
    
    print(f"\nLC (亏损成分) 变动表:")
    print(f"  期初余额:          0.00")
    print(f"  + 本年新增:        {context.nb_initial_lc:,.2f}")
    print(f"  + 计息:            {lc_interest_total:,.2f}")
    print(f"  + 经验调整(LC):     {context.lc_change:,.2f}")
    print(f"  = 摊销前LC余额:     {context.end_lc_before_amort:,.2f}")
    
    print(f"\nIACF (待摊获取费用) 变动表:")
    print(f"  期初余额:          {context.bop_iacf:,.2f}")
    print(f"  + 本年新增:        {context.nb_iacf_addition:,.2f}")
    print(f"  + 计息:            {context.iacf_interest_nb:,.2f}")
    print(f"  + 变化(Variance):  {context.iacf_change:,.2f}")
    print(f"  + 摊销:            {context.iacf_amort_amount:,.2f}")
    print(f"  = 期末余额:         {context.eop_iacf_balance:,.2f}")


