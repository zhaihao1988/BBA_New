from decimal import Decimal

def run(context, logger):
    logger.log_section("Part 6: IACF 摊销 (IACF Amortization)")
    
    # 6.1 期初待摊 IACF 余额
    context.bop_iacf = Decimal('0') # 新增合同
    logger.log_item(
        "年初待摊IACF余额",
        "期初尚未摊销的获取费用余额",
        "BOP Balance",
        {"BOP": context.bop_iacf},
        context.bop_iacf
    )
    
    # 6.2 期初待摊 IACF 计息 (0)
    iacf_interest_bop = Decimal('0')
    logger.log_item(
        "年初待摊IACF计息",
        "期初余额产生的利息 (不考虑时间价值)",
        "0 (Logic: No Time Value)",
        {},
        iacf_interest_bop
    )
    
    # 6.3 当年新增 IACF
    context.nb_iacf_addition = context.expected_iacf_nominal
    logger.log_item(
        "当年新增IACF",
        "本期新增业务带来的获取费用 (名义值)",
        "Expected IACF Nominal",
        {"Expected IACF": context.expected_iacf_nominal},
        context.nb_iacf_addition
    )
    
    # 6.4 当年新增 IACF 计息 (0)
    context.iacf_interest_nb = Decimal('0')
    logger.log_item(
        "当年新增IACF计息",
        "新增IACF产生的利息 (不考虑时间价值)",
        "0 (Logic: No Time Value)",
        {},
        context.iacf_interest_nb
    )
    
    # 6.5 IACF 变化
    context.iacf_change = context.iacf_var
    logger.log_item(
        "IACF变化",
        "实际与预期获取费用的差异",
        "Actual IACF - Expected IACF",
        {"Actual": context.actual_iacf_incurred, "Expected": context.expected_iacf_nominal},
        context.iacf_change
    )
    
    # 6.6 IACF 经验调整
    iacf_exp_adj = Decimal('0')
    logger.log_item(
        "IACF经验调整",
        "其他经验调整项",
        "Manual Input",
        {},
        iacf_exp_adj
    )
    
    # 6.7 摊销比例
    context.iacf_amort_ratio = Decimal('0')
    if context.total_months > 0:
        context.iacf_amort_ratio = Decimal(context.months_passed) / Decimal(context.total_months)
        
    logger.log_item(
        "IACF摊销比例",
        "本期摊销的比例 (基于时间)",
        "Passed Months / Total Months",
        {"Passed": context.months_passed, "Total": context.total_months},
        context.iacf_amort_ratio
    )
    
    # 6.8 摊销的 IACF
    iacf_balance_base = context.bop_iacf + iacf_interest_bop + context.nb_iacf_addition + context.iacf_interest_nb + context.iacf_change
    context.iacf_amort_amount = - (iacf_balance_base * context.iacf_amort_ratio + iacf_exp_adj)
    
    logger.log_item(
        "摊销的IACF",
        "本期摊销计入费用的金额 (负值代表减少余额)",
        "- (Sum(Balance+Additions+Var) * Ratio + ExpAdj)",
        {"Base Sum": iacf_balance_base, "Ratio": context.iacf_amort_ratio, "ExpAdj": iacf_exp_adj},
        context.iacf_amort_amount
    )
    
    # 6.9 期末待摊 IACF 余额
    context.eop_iacf_balance = iacf_balance_base + iacf_exp_adj + context.iacf_amort_amount
    
    logger.log_item(
        "期末待摊IACF余额",
        "期末剩余的待摊获取费用",
        "Sum(BOP + Interest + NB + NB Interest + Var + ExpAdj + Amortization)",
        {
            "Base": iacf_balance_base,
            "ExpAdj": iacf_exp_adj,
            "Amortization": context.iacf_amort_amount
        },
        context.eop_iacf_balance
    )



