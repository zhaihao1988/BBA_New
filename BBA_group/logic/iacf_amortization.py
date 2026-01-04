"""
IACF 摊销模块 (IACF Amortization)

核心功能：
1. 计算当年新增合同总 IACF 期末现值
2. 计算 IACF 摊销比例和摊销金额
3. 计算期末待摊 IACF 余额

Rename Wlk->Lkd: 适配 pv_calculator.py 的字段更名
"""

from decimal import Decimal
from datetime import date
from typing import Optional, Any
from BBA_group.logic.coverage_units import (
    calculate_coverage_units_released,
    calculate_coverage_units_remaining
)

def run(context, logger):
    logger.log_section("Part 6: IACF 摊销 (IACF Amortization)")
    
    # ==========================================================================================
    # 1. 当年新增合同总 IACF 期末现值
    # ==========================================================================================
    
    # 1.1 初始确认预期当年 IACF
    # 公式：-[新增合同-初始确认-预期当期-预期IACF-期末现值(Lkd)]
    # 注意：这里使用Lkd利率，从PV数据获取
    if context.pv_source_data:
        # 获取评估月的PV数据（所有数据都从当前评估期的PV数据读取）
        eop_month_str = context.val_month_str
        pv_data = context.pv_source_data.get_data(eop_month_str)
        
        if pv_data:
            # 1.1 初始确认预期当年 IACF
            # 公式：-[新增合同-初始确认-预期当期-预期IACF-期末现值(Lkd)]
            # 从当前评估月的PV数据读取
            init_expected_cur_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Lkd_Acq_Amt', Decimal('0'))
            # 取负号
            init_expected_cur_iacf = -init_expected_cur_iacf
        else:
            init_expected_cur_iacf = Decimal('0')
            
        # 1.3 期末预期未来 IACF 现值
        # 公式：-[新增合同-初始确认-预期未来-IACF-期末现值(Lkd)]
        # 从当前评估月的PV数据读取
        if pv_data:
            end_expected_fut_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rep_Lkd_Acq_Amt', Decimal('0'))
            # 取负号
            end_expected_fut_iacf = -end_expected_fut_iacf
        else:
            end_expected_fut_iacf = Decimal('0')
        
    else:
        init_expected_cur_iacf = Decimal('0')
        end_expected_fut_iacf = Decimal('0')

    logger.log_item(
        "初始确认预期当年IACF",
        "[Step 1.1] 初始确认时预期的当年IACF流出（期末现值）",
        "-[新增合同-初始确认-预期当期-预期IACF-期末现值(Lkd)]",
        {},
        init_expected_cur_iacf
    )
    
    # 1.2 当年 IACF 计息
    # 方案：不考虑获取费用计息 => 0
    iacf_interest_current = Decimal('0')
    logger.log_item(
        "当年IACF计息",
        "[Step 1.2] 当年新增IACF产生的利息",
        "0 (不考虑时间价值)",
        {},
        iacf_interest_current
    )
    
    logger.log_item(
        "期末预期未来IACF现值",
        "[Step 1.3] 期末时预期的未来IACF流出（期末现值）",
        "-[新增合同-初始确认-预期未来-IACF-期末现值(Lkd)]",
        {},
        end_expected_fut_iacf
    )
    
    # 1.4 当年新增总 IACF 期末现值
    total_nb_iacf_end_pv = init_expected_cur_iacf + iacf_interest_current + end_expected_fut_iacf
    logger.log_item(
        "当年新增总IACF期末现值",
        "[Step 1.4] 当年新增合同相关的IACF总额（期末现值）",
        "Sum(初始确认预期当年IACF, 当年IACF计息, 期末预期未来IACF现值)",
        {
            "初始确认预期当年IACF": init_expected_cur_iacf,
            "当年IACF计息": iacf_interest_current,
            "期末预期未来IACF现值": end_expected_fut_iacf
        },
        total_nb_iacf_end_pv
    )
    
    # ==========================================================================================
    # 2. IACF 摊销
    # ==========================================================================================
    
    # 2.1 IACF 摊销比例
    # 使用覆盖单元动态比例法计算IACF摊销比例
    context.iacf_amort_ratio = Decimal('0')
    if hasattr(context, 'policies') and context.policies:
        # 获取评估日期和年初日期
        valuation_date = getattr(context, 'eop_date', None) or getattr(context, 'valuation_date', None)
        if valuation_date is None:
            valuation_date = date(getattr(context, 'year', 2022), 12, 31)
        
        start_of_year = date(valuation_date.year, 1, 1)
        is_initial_year = getattr(context, 'is_initial_year', False)
        
        # 独立计算覆盖单元
        cu_released_iacf = calculate_coverage_units_released(
            context.policies,
            valuation_date,
            start_of_year,
            logger=None,
            is_initial_year=is_initial_year
        )
        cu_remaining_iacf = calculate_coverage_units_remaining(
            context.policies,
            valuation_date,
            logger=None
        )
        
        denominator_iacf = cu_released_iacf + cu_remaining_iacf
        if denominator_iacf > 0:
            context.iacf_amort_ratio = cu_released_iacf / denominator_iacf
            
        logger.log_item(
            "IACF摊销比例",
            "[Step 2.1] 本期摊销的比例",
            "CU_released / (CU_released + CU_remaining)",
            {
                "CU_released": cu_released_iacf,
                "CU_remaining": cu_remaining_iacf,
                "Denominator": denominator_iacf
            },
            context.iacf_amort_ratio,
            note="独立计算，不直接复用CSM摊销比例"
        )
    else:
        # 兼容模式
        if context.total_months > 0:
            context.iacf_amort_ratio = Decimal(context.months_passed) / Decimal(context.total_months)
        logger.log_item("IACF摊销比例（兼容模式）", "", "Time-based", {}, context.iacf_amort_ratio)

    # 2.2 年初待摊 IACF 余额
    if not hasattr(context, 'bop_iacf') or context.bop_iacf is None:
        context.bop_iacf = Decimal('0')
    logger.log_item(
        "年初待摊IACF余额",
        "[Step 2.2] 期初尚未摊销的获取费用余额",
        "BOP Balance",
        {},
        context.bop_iacf
    )
    
    # 2.3 年初待摊 IACF 计息
    iacf_interest_bop = Decimal('0')
    logger.log_item(
        "年初待摊IACF计息",
        "[Step 2.3] 期初余额产生的利息",
        "0 (不考虑时间价值)",
        {},
        iacf_interest_bop
    )
    
    # 2.4 当年新增 IACF
    # 使用名义值（不折现）
    # 关键修正：只有在初始年度（新业务年度）才有新增IACF，非初始年度应该为0
    # expected_iacf_nominal在非初始年度是从PV数据读取的有效合同IACF，不应该作为新增IACF
    is_new_business = getattr(context, 'is_new_business', False)
    if is_new_business:
        context.nb_iacf_addition = context.expected_iacf_nominal
    else:
        context.nb_iacf_addition = Decimal('0')
    logger.log_item(
        "当年新增IACF",
        "[Step 2.4] 本期新增业务带来的获取费用 (名义值)",
        "Expected IACF Nominal (不考虑时间价值) - 仅初始年度有值",
        {"Expected IACF": context.expected_iacf_nominal, "Is New Business": is_new_business},
        context.nb_iacf_addition
    )
    
    # 2.5 当年新增 IACF 计息
    context.iacf_interest_nb = Decimal('0')
    logger.log_item(
        "当年新增IACF计息",
        "[Step 2.5] 新增IACF产生的利息",
        "0 (不考虑时间价值)",
        {},
        context.iacf_interest_nb
    )
    
    # 2.6 IACF 变化
    context.iacf_change = context.iacf_var
    logger.log_item(
        "IACF变化",
        "[Step 2.6] 实际与预期获取费用的差异",
        "Actual IACF - Expected IACF",
        {"Actual": context.actual_iacf_incurred, "Expected": context.expected_iacf_nominal},
        context.iacf_change
    )
    
    # 2.7 IACF 经验调整
    iacf_exp_adj = Decimal('0')
    logger.log_item(
        "IACF经验调整",
        "[Step 2.7] 其他经验调整项",
        "Manual Input",
        {},
        iacf_exp_adj
    )
    
    # 2.8 摊销的 IACF
    iacf_balance_base = context.bop_iacf + iacf_interest_bop + context.nb_iacf_addition + context.iacf_interest_nb + context.iacf_change
    # 关键修正：根据文档，IACF摊销金额应该是正数（计入费用），但摊销会减少IACF余额
    # 公式：IACF_Amort = (IACF_balance_base * Ratio + ExpAdj)，正数表示摊销金额
    context.iacf_amort_amount = (iacf_balance_base * context.iacf_amort_ratio + iacf_exp_adj)
    
    logger.log_item(
        "摊销的IACF",
        "[Step 2.8] 本期摊销计入费用的金额",
        "(Sum(Balance+Additions+Var) * Ratio + ExpAdj)",
        {"Base Sum": iacf_balance_base, "Ratio": context.iacf_amort_ratio, "ExpAdj": iacf_exp_adj},
        context.iacf_amort_amount
    )
    
    # 2.9 期末待摊 IACF 余额
    # 关键修正：摊销减少IACF余额，所以应该是减去摊销金额
    # 公式：EOP_IACF = BOP_IACF + New_IACF + Change + ExpAdj - Amort
    # 即：eop_iacf_balance = iacf_balance_base + iacf_exp_adj - context.iacf_amort_amount
    # 由于iacf_amort_amount = iacf_balance_base * ratio + iacf_exp_adj
    # 所以：eop_iacf_balance = iacf_balance_base + iacf_exp_adj - (iacf_balance_base * ratio + iacf_exp_adj)
    #     = iacf_balance_base - iacf_balance_base * ratio
    #     = iacf_balance_base * (1 - ratio)
    # 使用通用公式，即使iacf_exp_adj不为0也能正确计算
    context.eop_iacf_balance = iacf_balance_base + iacf_exp_adj - context.iacf_amort_amount
    
    logger.log_item(
        "期末待摊IACF余额",
        "[Step 2.9] 期末剩余的待摊获取费用",
        "Sum(Base + ExpAdj + Amortization)",
        {
            "Base": iacf_balance_base,
            "ExpAdj": iacf_exp_adj,
            "Amortization": context.iacf_amort_amount
        },
        context.eop_iacf_balance
    )