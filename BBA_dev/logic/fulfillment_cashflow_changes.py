"""
履约现金流变化模块 (Fulfillment Cashflow Changes)

对应文档：
- 第4节：经验调整
- 第5节：被CSM/LC吸收的变化

核心功能：
1. 经验调整（文档 Sec 4）：保费现金流经验调整、IACF经验调整
2. 被CSM/LC吸收的变化（文档 Sec 5）：
   - 保费现金流变化
   - IACF变化
   - 赔付现金流变化
   - 维持费用现金流变化
   - 预期现金流变化合计
   - 非金融风险调整变化
   - 被CSM/LC吸收的变化合计

注意：
- 所有现值必须从PV原材料数据读取，不允许使用旧的计算方式
- 使用统一字段逻辑：CSM/LC使用一个字段，>=0走CSM逻辑，<0走LC逻辑
- 计息逻辑不在此模块，应在interest_accretion模块中处理
"""

from decimal import Decimal
from typing import List, Optional, Any
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from BBA_dev.models import CohortState, PolicyState, Assumptions
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data
from BBA_dev.utils.pv_field_desc import describe_field

DECIMAL_ZERO = Decimal('0')

def _get_bop_csm_lc(context, cohort_state: Optional[CohortState] = None) -> Decimal:
    """
    获取统一的CSM/LC字段（期初余额）
    
    逻辑：
    - 合并bop_csm和bop_lc为统一字段：bop_csm_lc = bop_csm + bop_lc
    - 当盈利时：bop_csm > 0, bop_lc = 0，所以 bop_csm_lc = bop_csm（正数，走CSM逻辑）
    - 当亏损时：bop_csm = 0, bop_lc < 0，所以 bop_csm_lc = bop_lc（负数，走LC逻辑）
    - 根据符号判断：>=0走CSM计息计量等逻辑，<0走LC计息计量等逻辑
    - 优先从context获取，如果没有则从cohort_state获取
    
    Args:
        context: 计算上下文
        cohort_state: 合同组状态（可选）
    
    Returns:
        统一的CSM/LC字段值（>=0为CSM，<0为LC）
    """
    # 优先从context获取
    bop_csm = getattr(context, 'bop_csm', None)
    bop_lc = getattr(context, 'bop_lc', None)
    
    # 如果context中没有，从cohort_state获取
    if bop_csm is None and cohort_state:
        bop_csm = cohort_state.bop_csm
    if bop_lc is None and cohort_state:
        bop_lc = cohort_state.bop_lc
    
    # 合并为统一字段：bop_csm_lc = bop_csm + bop_lc
    # 盈利时：bop_csm > 0, bop_lc = 0，所以 bop_csm_lc = bop_csm（正数）
    # 亏损时：bop_csm = 0, bop_lc < 0，所以 bop_csm_lc = bop_lc（负数）
    bop_csm_val = bop_csm if bop_csm is not None else DECIMAL_ZERO
    bop_lc_val = bop_lc if bop_lc is not None else DECIMAL_ZERO
    return bop_csm_val + bop_lc_val
from BBA_dev.logic.coverage_units import (
    calculate_coverage_units_released,
    calculate_coverage_units_remaining
)
from BBA_dev.logic.actual_cashflows import get_actual_cashflows

DECIMAL_ZERO = Decimal('0')


def _pv_amount(pv_data, field_name: str) -> Decimal:
    """从PV数据获取字段值"""
    if pv_data is None:
        return DECIMAL_ZERO
    try:
        return pv_data.get_field(field_name, DECIMAL_ZERO)
    except Exception:
        return DECIMAL_ZERO


def _calculate_expense_allocation_ratio(context):
    """
    经验调整占比：复用费用分摊比例（覆盖单元动态比例法）
    返回 (ratio, meta)
    """
    ratio = Decimal('0')
    meta: dict = {}
    if hasattr(context, 'policies') and context.policies:
        valuation_date = getattr(context, 'eop_date', None) or getattr(context, 'valuation_date', None)
        if valuation_date is None:
            valuation_date = date(getattr(context, 'year', 2022), 12, 31)
        start_of_year = date(valuation_date.year, 1, 1)
        is_initial_year = getattr(context, 'is_initial_year', False)
        cu_released = calculate_coverage_units_released(
            context.policies,
            valuation_date,
            start_of_year,
            logger=None,
            is_initial_year=is_initial_year
        )
        cu_remaining = calculate_coverage_units_remaining(
            context.policies,
            valuation_date,
            logger=None
        )
        denominator = cu_released + cu_remaining
        if denominator > 0:
            ratio = cu_released / denominator
        meta = {
            "CU_released": cu_released,
            "CU_remaining": cu_remaining,
            "Denominator": denominator,
            "Valuation Date": valuation_date,
            "Start Of Year": start_of_year,
            "Is Initial Year": is_initial_year
        }
    else:
        total_months = getattr(context, 'total_months', 0) or 0
        months_passed = getattr(context, 'months_passed', 0) or 0
        if total_months > 0:
            ratio = Decimal(str(months_passed)) / Decimal(str(total_months))
        meta = {
            "Months Passed": months_passed,
            "Total Months": total_months,
            "Mode": "Time-based"
        }
    return ratio, meta


def _calculate_experience_adjustment(context, logger, assumptions: Assumptions, is_new_business: bool):
    """
    计算经验调整（文档第4节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设
        is_new_business: 是否为新增合同
    """
    logger.log_section("Part 2: 经验调整 (Experience Adjustment) [Sec 4]")
    
    # 将is_new_business保存到context，供后续使用
    context.is_new_business = is_new_business
    
    # 获取实际现金流数据（从数据库读取）
    policy_no = getattr(context, 'policy_no', None)
    certi_no = getattr(context, 'certi_no', None)
    under_write_date = getattr(context, 'under_write_date', None)
    
    if policy_no:
        try:
            actual_cashflows = get_actual_cashflows(
                policy_no=policy_no,
                certi_no=certi_no,
                under_write_date=under_write_date
            )
            # 将实际现金流保存到context，供后续使用
            context.actual_cashflows = actual_cashflows
        except Exception as e:
            logger.log_text(f"⚠️  警告: 无法从数据库加载实际现金流数据: {e}，将使用context中的值")
            context.actual_cashflows = None
    else:
        context.actual_cashflows = None
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        acquisition_expense_ratio = assumptions.acquisition_expense_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from BBA_dev.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_IACF
        loss_ratio = RATIO_CLAIM
        indirect_claims_expense_ratio = Decimal('0')
        maintenance_expense_ratio = RATIO_MAINT_EXP
        acquisition_expense_ratio = RATIO_IACF
    
    # 计算当期预期流出 (从初始确认到年底)
    if not hasattr(context, 'months_passed') or context.months_passed is None:
        context.months_passed = 12 - context.under_write_date.month + 1  # 包含当月
        if context.months_passed < 0: 
            context.months_passed = 0
    
    catch_up_flag = bool(getattr(context, 'start_date', None) and getattr(context, 'under_write_date', None) and context.start_date < context.under_write_date)

    logger.log_item(
        "服务期间统计",
        "[Sec 4] 追溯至保单起期的服务月数",
        "Months_Passed / Total_Months",
        {
            "Months Passed": context.months_passed,
            "Total Months": context.total_months
        },
        context.months_passed,
        note=f"包含追溯月份: {'是' if catch_up_flag else '否'}（起算点: {context.start_date}）"
    )

    # 检查是否在保修期内
    warranty_end_date = None
    if hasattr(context, 'policies') and context.policies and len(context.policies) > 0:
        warranty_end_date = getattr(context.policies[0], 'warranty_end_date', None)
    if warranty_end_date is None:
        warranty_end_date = getattr(context, 'warranty_end_date', None)
    if warranty_end_date is None:
        warranty_end_date = getattr(context, 'start_date', None)
    
    # 判断评估日期是否在保修期内
    valuation_date = getattr(context, 'eop_date', None) or getattr(context, 'valuation_date', None)
    if valuation_date is None:
        valuation_date = date(getattr(context, 'year', 2022), 12, 31)
    
    is_in_warranty_period = (warranty_end_date is not None and valuation_date < warranty_end_date)
    
    # 预期赔付（名义金额，不折现）
    if is_in_warranty_period:
        context.expected_claim_nominal = Decimal('0')
        context.expected_maint_nominal = Decimal('0')
    else:
        # 在保修期后，计算预期的赔付和维费
        if warranty_end_date and warranty_end_date > getattr(context, 'start_date', valuation_date):
            end_date = getattr(context, 'end_date', None)
            if end_date is None:
                end_date = getattr(context.policies[0], 'end_date', None) if hasattr(context, 'policies') and context.policies else None
            if end_date is None:
                months_after_warranty = context.months_passed
                risk_period_months = context.total_months
            else:
                warranty_end_month = date(warranty_end_date.year, warranty_end_date.month, 1)
                end_month = date(end_date.year, end_date.month, 1)
                delta_risk = relativedelta(end_month, warranty_end_month)
                risk_period_months = delta_risk.years * 12 + delta_risk.months
                if end_date.day >= warranty_end_date.day:
                    risk_period_months += 1
                risk_period_months = max(1, risk_period_months)
                
                valuation_month = date(valuation_date.year, valuation_date.month, 1)
                if valuation_month > warranty_end_month:
                    delta = relativedelta(valuation_month, warranty_end_month)
                    months_after_warranty = delta.years * 12 + delta.months
                    if valuation_date.day >= warranty_end_date.day:
                        months_after_warranty += 1
                    months_after_warranty = max(0, months_after_warranty)
                else:
                    months_after_warranty = 0
        else:
            months_after_warranty = context.months_passed
            risk_period_months = context.total_months
        
        context.expected_claim_nominal = (context.actual_premium * loss_ratio * (Decimal('1') + indirect_claims_expense_ratio) / Decimal(str(risk_period_months))) * Decimal(str(months_after_warranty))
        context.expected_maint_nominal = (context.actual_premium * maintenance_expense_ratio / Decimal(str(risk_period_months))) * Decimal(str(months_after_warranty))
    
    context.actual_claim_incurred = context.expected_claim_nominal
    context.actual_maint_incurred = context.expected_maint_nominal

    # 获取评估月
    eop_month_str = context.val_month_str
    
    # 获取PV数据（只使用当前评估期的PV数据）
    pv_data = context.pv_source_data.get_data(eop_month_str)
    
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 经验调整占比（与费用分摊比例同源）
    exp_adj_ratio, exp_ratio_meta = _calculate_expense_allocation_ratio(context)
    context.exp_adj_ratio = exp_adj_ratio
    logger.log_item(
        "经验调整占比（费用分摊比例）",
        "保费/IACF经验调整使用与费用摊销相同的覆盖单元动态比例",
        "CU_released / (CU_released + CU_remaining) 或 时间比例（无保单列表时）",
        exp_ratio_meta,
        exp_adj_ratio,
        note="与费用分摊比例保持一致，用于保费/IACF经验调整占比"
    )
    
    # [Sec 4.3] 保费现金流经验调整
    if is_new_business:
        # 新增合同（从当前评估月的PV数据读取）
        new_f_end_prem = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt')
        new_f_init_prem = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rep_Wlk_Pre_Amt')
        new_c_init_prem = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt')
        
        # 从实际现金流模块获取实际保费（名义值，不计息）
        if hasattr(context, 'actual_cashflows') and context.actual_cashflows:
            new_c_actual_prem = context.actual_cashflows.get_actual_premium(context.year)
        elif hasattr(context, 'actual_premium'):
            # 兼容旧代码：如果actual_cashflows未加载，使用context中的值
            new_c_actual_prem = context.actual_premium if context.year == context.under_write_date.year else Decimal('0')
        else:
            new_c_actual_prem = Decimal('0')
        
        prem_var_raw = (new_f_end_prem + new_c_actual_prem) - (new_f_init_prem + new_c_init_prem)
        context.prem_var = prem_var_raw * exp_adj_ratio
        context.adj_prem = context.prem_var
        context.actual_premium_nb = new_c_actual_prem
        context.actual_premium_eff = Decimal('0')
        
        logger.log_item(
            "保费现金流经验调整",
            "[Sec 4.3] 实际保费与预期保费的差异（经验调整）",
            "Adj_Prem^New = [(New.F_end + New.C_actual) - (New.F_init + New.C_init)] × EA_ratio_prem",
            {
                "New.F_end": new_f_end_prem,
                "New.C_actual": new_c_actual_prem,
                "New.F_init": new_f_init_prem,
                "New.C_init": new_c_init_prem,
                "EA_ratio_prem": exp_adj_ratio,
                "Adj_Prem": context.prem_var
            },
            context.prem_var,
            note="从PV原材料数据读取。保费经验调整占比=100%"
        )
    else:
        # 存量合同
        eff_f_end_prem = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt')
        eff_c_actual_prem = Decimal('0')
        eff_f_beg_prem = pv_data.get_field('Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt')
        eff_c_year_prem = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt')
        
        prem_var_raw = (eff_f_end_prem + eff_c_actual_prem) - (eff_f_beg_prem + eff_c_year_prem)
        context.prem_var = prem_var_raw * exp_adj_ratio
        context.adj_prem = context.prem_var
        context.actual_premium_eff = eff_c_actual_prem
        context.actual_premium_nb = Decimal('0')
        
        logger.log_item(
            "保费现金流经验调整",
            "[Sec 4.3] 实际保费与预期保费的差异（经验调整）",
            "Adj_Prem^Eff = [(Eff.F_end + Eff.C_actual) - (Eff.F_beg + Eff.C_year)] × EA_ratio_prem",
            {
                "Eff.F_end": eff_f_end_prem,
                "Eff.C_actual": eff_c_actual_prem,
                "Eff.F_beg": eff_f_beg_prem,
                "Eff.C_year": eff_c_year_prem,
                "EA_ratio_prem": exp_adj_ratio,
                "Adj_Prem": context.prem_var
            },
            context.prem_var,
            note="从PV原材料数据读取。保费经验调整占比=100%"
        )

    # [Sec 4.4] IACF 经验调整
    if is_new_business:
        # 新增合同（从当前评估月的PV数据读取）
        new_f_end_iacf = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt')
        new_f_init_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rep_Wlk_Acq_Amt')
        new_c_init_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt')
        
        # 从实际现金流模块获取实际IACF（名义值，不计息）
        if hasattr(context, 'actual_cashflows') and context.actual_cashflows:
            new_c_actual_iacf = context.actual_cashflows.get_actual_iacf(context.year)
        elif hasattr(context, 'actual_iacf_incurred') and context.actual_iacf_incurred is not None:
            # 兼容旧代码：如果actual_cashflows未加载，使用context中的值
            new_c_actual_iacf = context.actual_iacf_incurred if context.year == context.under_write_date.year else Decimal('0')
        else:
            new_c_actual_iacf = Decimal('0')
        
        iacf_var_raw = (new_f_end_iacf + new_c_actual_iacf) - (new_f_init_iacf + new_c_init_iacf)
        context.iacf_var = iacf_var_raw * exp_adj_ratio
        context.adj_iacf = context.iacf_var
        context.expected_iacf_nominal = new_f_init_iacf + new_c_init_iacf
        context.actual_iacf_incurred = new_c_actual_iacf
        context.actual_iacf_nb = new_c_actual_iacf
        context.actual_iacf_eff = Decimal('0')
        
        logger.log_item(
            "IACF 经验调整",
            "[Sec 4.4] 实际获取费用与预期获取费用的差异（经验调整）",
            "Adj_IACF^New = [(New.F_end^I + New.C_actual^I) - (New.F_init^I + New.C_init^I)] × EA_ratio_iacf",
            {
                "New.F_end^I": new_f_end_iacf,
                "New.C_actual^I": new_c_actual_iacf,
                "New.F_init^I": new_f_init_iacf,
                "New.C_init^I": new_c_init_iacf,
                "EA_ratio_iacf": exp_adj_ratio,
                "Adj_IACF": context.iacf_var
            },
            context.iacf_var,
            note="实际IACF（New.C_actual^I）是名义值，不计息，直接从保单数据获取。预期IACF从PV原材料数据读取。IACF经验调整占比=0%"
        )
    else:
        # 存量合同
        eff_f_end_iacf = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt')
        eff_c_actual_iacf = Decimal('0')
        eff_f_beg_iacf = pv_data.get_field('Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt')
        eff_c_year_iacf = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt')
        
        iacf_var_raw = (eff_f_end_iacf + eff_c_actual_iacf) - (eff_f_beg_iacf + eff_c_year_iacf)
        context.iacf_var = iacf_var_raw * exp_adj_ratio
        context.adj_iacf = context.iacf_var
        context.expected_iacf_nominal = eff_f_beg_iacf + eff_c_year_iacf
        context.actual_iacf_incurred = eff_c_actual_iacf
        context.actual_iacf_eff = eff_c_actual_iacf
        context.actual_iacf_nb = Decimal('0')
        
        logger.log_item(
            "IACF 经验调整",
            "[Sec 4.4] 实际获取费用与预期获取费用的差异（经验调整）",
            "Adj_IACF^Eff = [(Eff.F_end^I + Eff.C_actual^I) - (Eff.F_beg^I + Eff.C_year^I)] × EA_ratio_iacf",
            {
                "Eff.F_end^I": eff_f_end_iacf,
                "Eff.C_actual^I": eff_c_actual_iacf,
                "Eff.F_beg^I": eff_f_beg_iacf,
                "Eff.C_year^I": eff_c_year_iacf,
                "EA_ratio_iacf": exp_adj_ratio,
                "Adj_IACF": context.iacf_var
            },
            context.iacf_var,
            note="从PV原材料数据读取。IACF经验调整占比=0%"
        )

    logger.log_item(
        "经验调整合计",
        "[Sec 4] 保费和IACF经验调整合计",
        "Adj_Total = Adj_Prem + Adj_IACF",
        {
            "Adj_Prem": context.prem_var,
            "Adj_IACF": context.iacf_var
        },
        context.prem_var + context.iacf_var,
        note="所有 'F'/ 'C' 项需保持同一加权初始确认利率"
    )


def _calculate_csm_lc_absorption(context, logger, cohort_state: CohortState, policies: List[PolicyState]):
    """
    计算被CSM/LC吸收的变化（文档第5节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policies: 保单列表
    """
    logger.log_section("Part 4: 被CSM/LC吸收的变化 (CSM/LC Absorption) [Sec 5]")
    
    # 验证context中的现值是否已从PV原材料数据读取
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
    
    # 获取评估月
    eop_month_str = context.val_month_str
    
    # 获取PV数据（只使用当前评估期的PV数据）
    pv_data = context.pv_source_data.get_data(eop_month_str)
    
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 判断是否为新增合同
    if hasattr(context, 'is_new_business'):
        is_new_business = context.is_new_business
    elif hasattr(context, 'under_write_date') and hasattr(context, 'year'):
        is_new_business = (context.year == context.under_write_date.year)
    else:
        is_new_business = False
    
    # [Sec 5.2] 保费现金流变化
    eff_f_end_prem = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt')
    eff_f_beg_prem = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt')
    eff_c_year_prem = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt')
    if is_new_business:
        new_f_end_prem = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt')
        new_f_init_prem = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Pre_Amt')
        new_c_init_prem = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt')
        # 从实际现金流模块获取实际保费（名义值，不计息）
        if hasattr(context, 'actual_cashflows') and context.actual_cashflows:
            actual_prem_nb = context.actual_cashflows.get_actual_premium(context.year)
        else:
            # 兼容旧代码
            actual_prem_nb = getattr(context, 'actual_premium_nb', None)
            if actual_prem_nb is None:
                actual_prem_nb = context.actual_premium if hasattr(context, 'under_write_date') and context.year == context.under_write_date.year else DECIMAL_ZERO
    else:
        new_f_end_prem = DECIMAL_ZERO
        new_f_init_prem = DECIMAL_ZERO
        new_c_init_prem = DECIMAL_ZERO
        actual_prem_nb = DECIMAL_ZERO
    # 有效合同的实际保费（后续年度为0）
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
        note="全部使用Wlk字段并扣除经验调整。实际现金流（Eff_C_actual、New_C_actual）是名义值，不计息"
    )

    # [Sec 5.3] IACF变化
    eff_f_end_iacf = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt')
    eff_f_beg_iacf = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt')
    eff_c_year_iacf = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt')
    if is_new_business:
        new_f_end_iacf = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt')
        new_f_init_iacf = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Acq_Amt')
        new_c_init_iacf = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt')
        # 从实际现金流模块获取实际IACF（名义值，不计息）
        if hasattr(context, 'actual_cashflows') and context.actual_cashflows:
            actual_iacf_nb = context.actual_cashflows.get_actual_iacf(context.year)
        else:
            # 兼容旧代码
            actual_iacf_nb = getattr(context, 'actual_iacf_nb', None)
            if actual_iacf_nb is None:
                actual_iacf_nb = context.actual_iacf_incurred if hasattr(context, 'under_write_date') and context.year == context.under_write_date.year else DECIMAL_ZERO
    else:
        new_f_end_iacf = DECIMAL_ZERO
        new_f_init_iacf = DECIMAL_ZERO
        new_c_init_iacf = DECIMAL_ZERO
        actual_iacf_nb = DECIMAL_ZERO
    # 有效合同的实际IACF（后续年度为0）
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
        note="全部使用Wlk字段并扣除经验调整。实际现金流（Eff_C_actual^I、New_C_actual^I）是名义值，不计息"
    )

    # [Sec 5.4] 赔付现金流变化
    pv_field_eff_f_end_claim = 'Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt'
    pv_field_eff_f_beg_claim = 'Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt'
    eff_f_end_claim = _pv_amount(pv_data, pv_field_eff_f_end_claim)
    eff_f_beg_claim = _pv_amount(pv_data, pv_field_eff_f_beg_claim)
    
    if is_new_business:
        pv_field_new_f_end_claim = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt'
        pv_field_new_f_init_claim = 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Cla_Amt'
        new_f_end_claim = _pv_amount(pv_data, pv_field_new_f_end_claim)
        new_f_init_claim = _pv_amount(pv_data, pv_field_new_f_init_claim)
    else:
        pv_field_new_f_end_claim = None
        pv_field_new_f_init_claim = None
        new_f_end_claim = DECIMAL_ZERO
        new_f_init_claim = DECIMAL_ZERO
    
    delta_claims = (eff_f_end_claim + new_f_end_claim) - (eff_f_beg_claim + new_f_init_claim)
    
    # 构建公式描述，使用PV字段的完整含义
    formula_parts = []
    formula_parts.append(f"【{describe_field(pv_field_eff_f_end_claim)}】")
    if is_new_business:
        formula_parts.append(f"+【{describe_field(pv_field_new_f_end_claim)}】")
    formula_parts.append(f"-【{describe_field(pv_field_eff_f_beg_claim)}】")
    if is_new_business:
        formula_parts.append(f"-【{describe_field(pv_field_new_f_init_claim)}】")
    formula_desc = "".join(formula_parts)
    
    # 构建数值字典，使用PV字段的完整含义作为键
    values_dict = {
        describe_field(pv_field_eff_f_end_claim): eff_f_end_claim,
        describe_field(pv_field_eff_f_beg_claim): eff_f_beg_claim
    }
    if is_new_business:
        values_dict[describe_field(pv_field_new_f_end_claim)] = new_f_end_claim
        values_dict[describe_field(pv_field_new_f_init_claim)] = new_f_init_claim
        values_dict["PV字段"] = f"{pv_field_eff_f_end_claim}, {pv_field_eff_f_beg_claim}, {pv_field_new_f_end_claim}, {pv_field_new_f_init_claim}"
    else:
        values_dict["PV字段"] = f"{pv_field_eff_f_end_claim}, {pv_field_eff_f_beg_claim}"
    
    logger.log_item(
        "赔付与费用_预期赔付变化",
        "[Sec 5.4] 赔付现金流变化（统一Wlk公式）",
        formula_desc,
        values_dict,
        delta_claims,
        note="所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk）"
    )

    # [Sec 5.5] 维持费用现金流变化
    eff_f_end_maint = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    eff_f_beg_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt')
    if is_new_business:
        new_f_end_maint = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
        new_f_init_maint = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Mtn_Amt')
    else:
        new_f_end_maint = DECIMAL_ZERO
        new_f_init_maint = DECIMAL_ZERO
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
    # 注意：流出项（IACF、赔付、费用）的增加代表负债增加（不利变化），对CSM是负面影响，因此用减号
    delta_cf_total = delta_prem - delta_iacf - delta_claims - delta_maint
    context.delta_cf_total = delta_cf_total  # 保存到context，供LC计量模块使用
    logger.log_item(
        "预期现金流变化合计",
        "[Sec 5.6] 保费、IACF、赔付、维持费用的变化合计（对CSM的影响）",
        "Δ_CF_Total = Δ_Prem - Δ_IACF - Δ_Claims - Δ_Maint",
        {
            "Δ_Prem (有利+)": delta_prem,
            "Δ_IACF (不利-)": delta_iacf,
            "Δ_Claims (不利-)": delta_claims,
            "Δ_Maint (不利-)": delta_maint
        },
        delta_cf_total,
        note="保费增加为有利(+)，流出增加为不利(-)"
    )

    # [Sec 5.7] 非金融风险调整变化
    eff_f_end_ra = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
    eff_f_beg_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt')
    if is_new_business:
        new_f_end_ra = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
        new_f_init_ra = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Rad_Amt')
    else:
        new_f_end_ra = DECIMAL_ZERO
        new_f_init_ra = DECIMAL_ZERO
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

    # [Sec 5.8] 被CSM/LC吸收的变化合计
    # 注意：RA增加代表负债增加（不利变化），对CSM是负面影响，因此用减号
    delta_csm_lc = delta_cf_total - delta_ra
    context.exp_adj_csm_impact = delta_csm_lc
    
    logger.log_item(
        "被CSM/LC吸收的变化合计",
        "[Sec 5.8] 当期各类现金流、风险调整对合同服务边际或亏损合同的影响",
        "Δ_CSM/LC = Δ_CF_Total - Δ_RA",
        {
            "Δ_CF_Total": delta_cf_total,
            "Δ_RA (不利-)": delta_ra
        },
        delta_csm_lc
    )
    
    # ==========================================================================================
    # CSM/LC统一字段逻辑：使用一个字段，>=0走CSM逻辑，<0走LC逻辑
    # ==========================================================================================
    # 获取统一的CSM/LC字段（用于计算LC IFIE分摊比例）
    # 修复：正确合并bop_csm和bop_lc，根据符号判断是CSM（>=0）还是LC（<0）
    bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
    
    # 获取统一的CSM/LC字段（用于计算LC IFIE分摊比例）
    # 修复：context.nb_initial_lc 现在直接存储为负数（亏损），不需要再转换
    nb_initial_csm_lc = context.nb_initial_csm or Decimal('0')
    if nb_initial_csm_lc == Decimal('0') and hasattr(context, 'nb_initial_lc'):
        nb_lc_val = context.nb_initial_lc or Decimal('0')
        if nb_lc_val < Decimal('0'):  # LC应该是负数
            nb_initial_csm_lc = nb_lc_val
    
    # [Sec 7.2.2] LC IFIE分摊比例（期初有效合同）
    # 注意：LC IFIE分摊比例用于后续IFIE模块，这里只计算并保存到context
    if_lc_ifie_ratio = Decimal('0')
    if bop_csm_lc < 0:
        # 分母：预期赔付现金流年初现值 + 预期维持费用现金流年初现值 + 预期非金融风险调整年初现值
        # 理解：有效合同-年初预期-预期未来-年初现值（LCU），已包含1月现金流
        # 注意：已删除 Cca_Beg_Lcu 字段，Cfa_Beg_Lcu 已经包含了1月现金流（折现到年初）
        # 年初现值：有效合同-年初预期-预期未来-年初现值（LCU）
        pv_if_init_claims = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt', DECIMAL_ZERO)
        pv_if_init_maint = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO)
        pv_if_init_ra = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt', DECIMAL_ZERO)
        denom_if = pv_if_init_claims + pv_if_init_maint + pv_if_init_ra
        
        if denom_if > 0:
            if_lc_ifie_ratio = abs(bop_csm_lc) / denom_if
    
    # [Sec 7.3.2] LC IFIE分摊比例（当年新增合同）
    nb_lc_ifie_ratio = Decimal('0')
    if nb_initial_csm_lc < 0:
        denom_nb = context.init_fut_claim + context.init_fut_maint + context.init_ra
        if denom_nb > 0:
            nb_lc_ifie_ratio = abs(nb_initial_csm_lc) / denom_nb
    
    # 保存LC IFIE分摊比例到context（供IFIE模块使用）
    context.nb_lc_ratio = nb_lc_ifie_ratio
    context.if_lc_ifie_ratio = if_lc_ifie_ratio
    
    # [Sec 5] 被CSM/LC吸收的变化分摊
    # 使用统一字段逻辑：如果变化被LC吸收（nb_initial_csm_lc < 0），则分摊到LC；否则被CSM吸收
    context.allocated_lc_exp_adj = delta_csm_lc * nb_lc_ifie_ratio
    context.csm_absorbed = delta_csm_lc - context.allocated_lc_exp_adj
    
    logger.log_item(
        "被CSM/LC吸收的变化分摊",
        "[Sec 5] 被CSM/LC吸收的变化分摊（使用统一字段逻辑）",
        "被CSM吸收 = Δ_CSM/LC × (1 - LC_Ratio)\n被LC吸收 = Δ_CSM/LC × LC_Ratio",
        {
            "Δ_CSM/LC": delta_csm_lc,
            "NB_LC_Ratio": nb_lc_ifie_ratio,
            "被CSM吸收": context.csm_absorbed,
            "被LC吸收": context.allocated_lc_exp_adj,
            "NB_初始CSM/LC": nb_initial_csm_lc,
            "说明": "如果NB_初始CSM/LC < 0，则为LC，部分变化被LC吸收；否则全部被CSM吸收"
        },
        delta_csm_lc,
        note="被CSM/LC吸收的变化使用同一个字段（delta_csm_lc），根据LC_Ratio分摊到CSM或LC。注意：计息逻辑不在此模块，应在interest_accretion模块中处理"
    )


def run(
    context,
    logger,
    assumptions: Assumptions = None,
    cohort_state: CohortState = None,
    policies: List[PolicyState] = None,
    is_new_business: bool = None
):
    """
    执行履约现金流变化计算（整合经验调整和被CSM/LC吸收的变化）
    
    对应文档：
    - 第4节：经验调整
    - 第5节：被CSM/LC吸收的变化
    
    核心内容：
    1. 经验调整：保费现金流经验调整、IACF经验调整
    2. 被CSM/LC吸收的变化：
       - 保费现金流变化
       - IACF变化
       - 赔付现金流变化
       - 维持费用现金流变化
       - 预期现金流变化合计
       - 非金融风险调整变化
       - 被CSM/LC吸收的变化合计
    
    注意：
    - 计息逻辑不在此模块，应在interest_accretion模块中处理
    - 合同组状态判定不在此模块，应在csm_allocation模块中处理
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设（从数据库读取）
        cohort_state: 合同组状态（可选，用于计算LC IFIE分摊比例）
        policies: 保单列表（可选，当前未使用）
        is_new_business: 是否为新增合同（可选，如果不提供则自动判断）
    """
    logger.log_section("Part 2-4: 履约现金流变化 (Fulfillment Cashflow Changes) [Sec 4-5]")
    
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
    
    # 判断是否为新增合同
    if is_new_business is None:
        if hasattr(context, 'is_new_business'):
            is_new_business = context.is_new_business
        elif hasattr(context, 'under_write_date') and hasattr(context, 'year'):
            is_new_business = (context.year == context.under_write_date.year)
        else:
            is_new_business = False
    
    # 步骤1：计算经验调整（文档第4节）
    _calculate_experience_adjustment(context, logger, assumptions, is_new_business)
    
    # 步骤2：计算被CSM/LC吸收的变化（文档第5节）
    _calculate_csm_lc_absorption(context, logger, cohort_state, policies)
    
    logger.log_item(
        "履约现金流变化合计",
        "[汇总] 经验调整和被CSM/LC吸收的变化合计",
        "履约现金流变化 = 经验调整 + 被CSM/LC吸收的变化",
        {
            "经验调整（保费）": context.prem_var,
            "经验调整（IACF）": context.iacf_var,
            "经验调整合计": context.prem_var + context.iacf_var,
            "被CSM/LC吸收的变化": context.exp_adj_csm_impact,
            "被CSM吸收": context.csm_absorbed,
            "被LC吸收": context.allocated_lc_exp_adj
        },
        (context.prem_var + context.iacf_var) + context.exp_adj_csm_impact,
        note="整合经验调整和被CSM/LC吸收的变化，使用统一字段逻辑。注意：计息逻辑不在此模块，应在interest_accretion模块中处理"
    )

