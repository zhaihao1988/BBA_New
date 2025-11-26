from decimal import Decimal
from datetime import date
from typing import Optional, Any
from BBA_dev.logic.coverage_units import (
    calculate_coverage_units_released,
    calculate_coverage_units_remaining
)

def run(context, logger):
    logger.log_section("Part 6: IACF 摊销 (IACF Amortization)")
    
    # 6.1 期初待摊 IACF 余额
    # 如果 context.bop_iacf 已经设置（从上年末滚存），则使用已有值；否则设置为0（新增合同）
    if not hasattr(context, 'bop_iacf') or context.bop_iacf is None:
        context.bop_iacf = Decimal('0')  # 新增合同或首次计算
    logger.log_item(
        "年初待摊IACF余额",
        "期初尚未摊销的获取费用余额（从上年末滚存）",
        "BOP Balance (Rolled from Previous Year End)",
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
    
    # 6.7 摊销比例（使用覆盖单元动态比例法，与CSM摊销比例算法一致，但独立计算）
    # 重要：IACF摊销比例独立计算，不直接复用CSM的摊销比例值，以便未来可独立调整
    context.iacf_amort_ratio = Decimal('0')
    
    # 使用覆盖单元动态比例法计算IACF摊销比例
    if hasattr(context, 'policies') and context.policies:
        # 获取评估日期和年初日期
        valuation_date = getattr(context, 'eop_date', None) or getattr(context, 'valuation_date', None)
        if valuation_date is None:
            # 如果没有评估日期，使用年份的最后一天
            valuation_date = date(getattr(context, 'year', 2022), 12, 31)
        
        start_of_year = date(valuation_date.year, 1, 1)
        is_initial_year = getattr(context, 'is_initial_year', False)
        
        # 独立计算覆盖单元（不复用CSM的计算结果）
        cu_released_iacf = calculate_coverage_units_released(
            context.policies,
            valuation_date,
            start_of_year,
            logger=None,  # IACF摊销比例计算时不输出详细日志，避免重复
            is_initial_year=is_initial_year
        )
        
        cu_remaining_iacf = calculate_coverage_units_remaining(
            context.policies,
            valuation_date,
            logger=None  # IACF摊销比例计算时不输出详细日志，避免重复
        )
        
        # 计算IACF摊销比例：Ratio = CU_released / (CU_released + CU_remaining)
        denominator_iacf = cu_released_iacf + cu_remaining_iacf
        if denominator_iacf > 0:
            context.iacf_amort_ratio = cu_released_iacf / denominator_iacf
        else:
            context.iacf_amort_ratio = Decimal('0')
        
        logger.log_item(
            "IACF摊销比例",
            "本期摊销的比例 (使用覆盖单元动态比例法，与CSM摊销比例算法一致，但独立计算)",
            "CU_released / (CU_released + CU_remaining)",
            {
                "CU_released": cu_released_iacf,
                "CU_remaining": cu_remaining_iacf,
                "Denominator": denominator_iacf
            },
            context.iacf_amort_ratio,
            note="独立计算IACF摊销比例，不直接复用CSM的摊销比例值，以便未来可独立调整精算方案"
        )
    else:
        # 兼容模式：如果没有policies，使用时间比例法（不推荐）
        if context.total_months > 0:
            context.iacf_amort_ratio = Decimal(context.months_passed) / Decimal(context.total_months)
        
        logger.log_item(
            "IACF摊销比例（兼容模式）",
            "本期摊销的比例 (未提供保单列表，使用时间比例法，不推荐)",
            "Passed Months / Total Months",
            {"Passed": context.months_passed, "Total": context.total_months},
            context.iacf_amort_ratio,
            note="⚠️ 警告：应使用覆盖单元动态比例法"
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



