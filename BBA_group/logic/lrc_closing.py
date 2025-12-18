from decimal import Decimal
from BBA_group.utils.pv_source_loader import ensure_pv_source_data

DECIMAL_ZERO = Decimal('0')

def run_closing(context, logger):
    """
    计算期末未到期责任负债
    
    对应文档：第9节
    
    包含内容：
    1. 预期保费现金流现值
    2. 预期IACF现值
    3. 预期赔付与费用现金流现值
    4. 预期现金流现值
    5. 预期非金融风险调整
    6. CSM
    7. 期末未到期责任负债余额
    """
    logger.log_section("Part 9: 期末未到期责任负债 (LRC Closing Balance)")
    
    # 强制要求PV原材料数据必须存在
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
    
    # 获取期末评估月数据
    eop_month_str = context.eop_date.strftime('%Y%m')
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    if pv_data_eop is None:
        # 尝试使用上一个可用的评估月数据（按月份倒序查找）
        available_months = sorted(context.pv_source_data.data_by_month.keys(), reverse=True)
        if available_months:
            fallback_month = None
            for month in available_months:
                if month <= eop_month_str:
                    fallback_month = month
                    break
            if fallback_month:
                pv_data_eop = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用 {fallback_month} 的数据作为替代")
            else:
                fallback_month = available_months[0]
                pv_data_eop = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用最新的可用数据 {fallback_month} 作为替代")
        else:
            raise ValueError(
                f"❌ 错误: 找不到期末评估月 {eop_month_str} 的PV原材料数据，且没有可用的替代数据！\n"
                f"   评估日期: {context.eop_date}\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
    
    # 9.1 预期保费现金流现值
    # -(【有效合同-期末预期-预期未来-保费现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-保费现金流-期末现值（期末利率）】)
    pv_if_fut_prem = pv_data_eop.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Pre_Amt', DECIMAL_ZERO)
    pv_nb_fut_prem = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Pre_Amt', DECIMAL_ZERO)
    lrc_bel_premium = -(pv_if_fut_prem + pv_nb_fut_prem)
    
    logger.log_item(
        "预期保费现金流现值",
        "期末预期未来收到的保费现值（有效合同+新增合同，期末利率）",
        "-(【有效合同-期末预期-预期未来-保费现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-保费现金流-期末现值（期末利率）】)",
        {
            "有效合同-预期未来-保费（期末利率）": pv_if_fut_prem,
            "新增合同-预期未来-保费（期末利率）": pv_nb_fut_prem,
            "合计": pv_if_fut_prem + pv_nb_fut_prem,
            "预期保费现金流现值（负号）": lrc_bel_premium
        },
        lrc_bel_premium,
        note="所有现值均从PV原材料数据读取，使用期末利率（Cur字段），包含有效合同和新增合同"
    )
    
    # 9.2 预期IACF现值
    # 【有效合同-期末预期-预期未来-IACF-期末现值（期末利率）】+【新增合同-期末预期-预期未来-IACF-期末现值（期末利率）】
    pv_if_fut_iacf = pv_data_eop.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Acq_Amt', DECIMAL_ZERO)
    pv_nb_fut_iacf = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Acq_Amt', DECIMAL_ZERO)
    lrc_bel_iacf = (pv_if_fut_iacf + pv_nb_fut_iacf)
    
    logger.log_item(
        "预期IACF现值",
        "期末预期未来支付的获取费用现值（有效合同+新增合同，期末利率）",
        "【有效合同-期末预期-预期未来-IACF-期末现值（期末利率）】+【新增合同-期末预期-预期未来-IACF-期末现值（期末利率）】",
        {
            "有效合同-预期未来-IACF（期末利率）": pv_if_fut_iacf,
            "新增合同-预期未来-IACF（期末利率）": pv_nb_fut_iacf,
            "合计": pv_if_fut_iacf + pv_nb_fut_iacf,
            "预期IACF现值": lrc_bel_iacf
        },
        lrc_bel_iacf,
        note="IACF是现金流出，增加负债，为正数。所有现值均从PV原材料数据读取，使用期末利率（Cur字段），包含有效合同和新增合同"
    )
    
    # 9.3 预期赔付与费用现金流现值
    # 【有效合同-期末预期-预期未来-赔付现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-赔付现金流-期末现值（期末利率）】+【有效合同-期末预期-预期未来-维持费用现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-维持费用现金流-期末现值（期末利率）】
    pv_if_fut_claims = pv_data_eop.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt', DECIMAL_ZERO)
    pv_nb_fut_claims = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt', DECIMAL_ZERO)
    pv_if_fut_maint = pv_data_eop.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt', DECIMAL_ZERO)
    pv_nb_fut_maint = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt', DECIMAL_ZERO)
    lrc_bel_claims_expenses = (pv_if_fut_claims + pv_nb_fut_claims + pv_if_fut_maint + pv_nb_fut_maint)
    
    logger.log_item(
        "预期赔付与费用现金流现值",
        "期末预期未来赔付和维持费用的现值（有效合同+新增合同，期末利率）",
        "【有效合同-期末预期-预期未来-赔付现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-赔付现金流-期末现值（期末利率）】+【有效合同-期末预期-预期未来-维持费用现金流-期末现值（期末利率）】+【新增合同-期末预期-预期未来-维持费用现金流-期末现值（期末利率）】",
        {
            "有效合同-预期未来-赔付（期末利率）": pv_if_fut_claims,
            "新增合同-预期未来-赔付（期末利率）": pv_nb_fut_claims,
            "有效合同-预期未来-维费（期末利率）": pv_if_fut_maint,
            "新增合同-预期未来-维费（期末利率）": pv_nb_fut_maint,
            "合计": pv_if_fut_claims + pv_nb_fut_claims + pv_if_fut_maint + pv_nb_fut_maint,
            "预期赔付与费用现金流现值": lrc_bel_claims_expenses
        },
        lrc_bel_claims_expenses,
        note="赔付和费用是现金流出，增加负债，为正数。所有现值均从PV原材料数据读取，使用期末利率（Cur字段），包含有效合同和新增合同"
    )
    
    # 9.4 预期现金流现值
    # Sum(预期保费现金流现值, 预期IACF现值, 预期赔付与费用现金流现值)
    lrc_bel_total = lrc_bel_premium + lrc_bel_iacf + lrc_bel_claims_expenses
    
    logger.log_item(
        "预期现金流现值",
        "履约现金流的现值估计（有效合同+新增合同，期末利率）",
        "Sum(预期保费现金流现值, 预期IACF现值, 预期赔付与费用现金流现值)",
        {
            "预期保费现金流现值": lrc_bel_premium,
            "预期IACF现值": lrc_bel_iacf,
            "预期赔付与费用现金流现值": lrc_bel_claims_expenses,
            "预期现金流现值合计": lrc_bel_total
        },
        lrc_bel_total,
        note="所有现值均从PV原材料数据读取，使用期末利率（Cur字段）"
    )
    # 存储到context供后续提取
    context.lrc_bel_total = lrc_bel_total
    
    # 9.5 预期非金融风险调整
    # 【有效合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】+【新增合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】
    # 注意：必须使用Rad字段，不能从(Cla+Mtn)×RA_Ratio计算
    pv_if_fut_ra = pv_data_eop.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt', DECIMAL_ZERO)
    pv_nb_fut_ra = pv_data_eop.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt', DECIMAL_ZERO)
    lrc_ra = (pv_if_fut_ra + pv_nb_fut_ra)
    
    logger.log_item(
        "预期非金融风险调整",
        "期末非金融风险调整余额（有效合同+新增合同，期末利率）",
        "【有效合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】+【新增合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】",
        {
            "有效合同-预期未来-RA（期末利率）": pv_if_fut_ra,
            "新增合同-预期未来-RA（期末利率）": pv_nb_fut_ra,
            "合计": pv_if_fut_ra + pv_nb_fut_ra,
            "预期非金融风险调整": lrc_ra
        },
        lrc_ra,
        note="RA是负债的一部分，增加负债，为正数。所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算），使用期末利率（Cur字段），包含有效合同和新增合同"
    )
    # 存储到context供后续提取
    context.lrc_ra = lrc_ra
    
    # 9.6 CSM
    # 期末CSM余额
    lrc_csm = context.end_csm_final
    if lrc_csm is None:
        csm_before = getattr(context, 'end_csm_before_amort', None) or DECIMAL_ZERO
        csm_amort = getattr(context, 'csm_amort_amount', None) or DECIMAL_ZERO
        lrc_csm = csm_before + csm_amort  # CSM摊销是负数，所以是加法
    if lrc_csm is None:
        lrc_csm = DECIMAL_ZERO
    
    logger.log_item(
        "CSM",
        "期末合同服务边际余额",
        "期末CSM余额（来自CSM计量模块）",
        {
            "期末CSM余额": lrc_csm
        },
        lrc_csm,
        note="CSM余额来自CSM计量模块的计算结果"
    )
    
    # 9.7 期末未到期责任负债余额
    # Sum(预期现金流现值, 预期非金融风险调整，CSM)
    lrc_total = lrc_bel_total + lrc_ra + lrc_csm
    
    logger.log_item(
        "期末未到期责任负债余额",
        "期末未到期责任负债总额",
        "Sum(预期现金流现值, 预期非金融风险调整，CSM)",
        {
            "预期现金流现值": lrc_bel_total,
            "预期非金融风险调整": lrc_ra,
            "CSM": lrc_csm,
            "期末未到期责任负债余额": lrc_total
        },
        lrc_total,
        note="所有现值均从PV原材料数据读取，使用期末利率（Cur字段）"
    )
    # 存储到context供后续提取
    context.lrc_total = lrc_total

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


