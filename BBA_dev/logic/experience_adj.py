"""
经验调整逻辑 (Experience Adjustment)

对应文档：第4节 当期经验调整

核心功能：
1. 保费现金流经验调整（文档 Sec 4.3）
2. IACF 经验调整（文档 Sec 4.4）
3. 需区分期初有效合同 (Eff) 与当年新增合同 (New)

注意：所有现值相关计算必须使用PV原材料数据，不允许使用旧的计算方式。
"""

from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from BBA_dev.models import Assumptions
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data
from BBA_dev.logic.coverage_units import (
    calculate_coverage_units_released,
    calculate_coverage_units_remaining
)


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


def run(context, logger, assumptions: Assumptions = None, is_new_business: bool = True):
    """
    执行经验调整
    
    对应文档：第4节
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设（从数据库读取）
        is_new_business: 是否为新增合同（True=新增合同，False=存量合同）
    """
    logger.log_section("Part 2: 经验调整 (Experience Adjustment) [Sec 4]")
    
    # 将is_new_business保存到context，供后续使用
    context.is_new_business = is_new_business
    
    # 强制要求PV原材料数据必须存在（经验调整可能需要使用现值）
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
    # 获取保修结束日期（从policy_state或context中获取）
    warranty_end_date = None
    if hasattr(context, 'policies') and context.policies and len(context.policies) > 0:
        warranty_end_date = getattr(context.policies[0], 'warranty_end_date', None)
    if warranty_end_date is None:
        # 如果没有从policies获取到，尝试从context获取
        warranty_end_date = getattr(context, 'warranty_end_date', None)
    if warranty_end_date is None:
        # 如果还是没有，默认使用start_date（即没有保修期）
        warranty_end_date = getattr(context, 'start_date', None)
    
    # 判断评估日期是否在保修期内
    valuation_date = getattr(context, 'eop_date', None) or getattr(context, 'valuation_date', None)
    if valuation_date is None:
        # 如果没有评估日期，使用年份的最后一天
        from datetime import date
        valuation_date = date(getattr(context, 'year', 2022), 12, 31)
    
    is_in_warranty_period = (warranty_end_date is not None and valuation_date < warranty_end_date)
    
    # 预期赔付（名义金额，不折现）
    # 在保修期内，预期赔付和维费应该是0
    if is_in_warranty_period:
        context.expected_claim_nominal = Decimal('0')
        context.expected_maint_nominal = Decimal('0')
    else:
        # 在保修期后，计算预期的赔付和维费
        # 关键：使用风险期内的月数，而不是整个合同期的月数
        # 风险期 = 保修结束日期到保单止期
        if warranty_end_date and warranty_end_date > getattr(context, 'start_date', valuation_date):
            # 计算风险期内的总月数（从保修结束日期到保单止期）
            from datetime import date
            end_date = getattr(context, 'end_date', None)
            if end_date is None:
                end_date = getattr(context.policies[0], 'end_date', None) if hasattr(context, 'policies') and context.policies else None
            if end_date is None:
                # 如果没有止期，使用原来的逻辑
                months_after_warranty = context.months_passed
                risk_period_months = context.total_months
            else:
                # 计算风险期内的总月数
                warranty_end_month = date(warranty_end_date.year, warranty_end_date.month, 1)
                end_month = date(end_date.year, end_date.month, 1)
                delta_risk = relativedelta(end_month, warranty_end_month)
                risk_period_months = delta_risk.years * 12 + delta_risk.months
                if end_date.day >= warranty_end_date.day:
                    risk_period_months += 1
                risk_period_months = max(1, risk_period_months)  # 至少1个月
                
                # 计算保修期后的服务月数（从保修结束日期到评估日期）
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
            # 没有保修期或保修期已过，使用原来的逻辑
            months_after_warranty = context.months_passed
            risk_period_months = context.total_months
        
        # 使用风险期内的月数计算预期赔付和维费
        context.expected_claim_nominal = (context.actual_premium * loss_ratio * (Decimal('1') + indirect_claims_expense_ratio) / Decimal(str(risk_period_months))) * Decimal(str(months_after_warranty))
        context.expected_maint_nominal = (context.actual_premium * maintenance_expense_ratio / Decimal(str(risk_period_months))) * Decimal(str(months_after_warranty))
    
    context.actual_claim_incurred = context.expected_claim_nominal  # 暂定实际=预期
    context.actual_maint_incurred = context.expected_maint_nominal  # 暂定实际=预期

    # 获取评估月和年初月份
    eop_month_str = context.val_month_str
    bop_month_str = (context.eop_date.replace(day=1) - relativedelta(months=11)).strftime('%Y%m') if hasattr(context, 'eop_date') else None
    if bop_month_str is None:
        # 如果没有eop_date，尝试从val_month_str推算
        from datetime import datetime
        val_date = datetime.strptime(eop_month_str, '%Y%m')
        bop_date = val_date.replace(month=1, day=1)
        bop_month_str = bop_date.strftime('%Y%m')
    
    # 获取PV数据
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    pv_data_bop = context.pv_source_data.get_data(bop_month_str) if bop_month_str else None
    
    if pv_data_eop is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    from BBA_dev.utils.pv_field_desc import describe_field

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
    # 注意：实施时需按合同类型二选一（Eff 或 New）
    if is_new_business:
        # 新增合同：Adj_Prem^New = (New.F_end + New.C_actual) - (New.F_init + New.C_init)
        # 对于一次性缴费的保单，保费在初始确认时已全部收取
        # New.F_end = 期末预期未来保费现值（期末现值-加权初始确认利率）
        # New.C_actual = 0（后续年度无实际保费现金流）
        # New.F_init = 初始确认时的预期未来保费现值（期末现值-加权初始确认利率）
        # New.C_init = 初始确认时的预期当期保费现值（期末现值-加权初始确认利率）
        uw_month_str = context.under_write_date.strftime('%Y%m')
        pv_data_init = context.pv_source_data.get_data(uw_month_str)
        if pv_data_init is None:
            raise ValueError(f"❌ 错误: 找不到初始确认月 {uw_month_str} 的PV原材料数据！")
        
        # 从PV原材料数据读取：新增合同-期末预期-预期未来-期末现值-加权初始确认利率-保费现金流
        pv_field_new_end_prem = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt'
        new_f_end_prem = pv_data_eop.get_field(pv_field_new_end_prem)
        
        # 从PV原材料数据读取：新增合同-初始确认-预期未来-期末现值-加权初始确认利率-保费现金流
        pv_field_new_init_prem = 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Pre_Amt'
        new_f_init_prem = pv_data_init.get_field(pv_field_new_init_prem)
        
        # 从PV原材料数据读取：新增合同-初始确认-预期当期-期末现值-加权初始确认利率-保费现金流
        pv_field_new_init_current_prem = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Pre_Amt'
        new_c_init_prem = pv_data_init.get_field(pv_field_new_init_current_prem)
        
        # 判断是否为签单年度：签单年度时，实际保费 = 签单保费；签单年度之后，实际保费 = 0
        if context.year == context.under_write_date.year:
            new_c_actual_prem = context.actual_premium  # 签单年度：实际保费 = 签单保费（实际值）
        else:
            new_c_actual_prem = Decimal('0')  # 签单年度之后：无实际保费现金流
        
        # [Sec 4.3] 保费现金流经验调整 = [(New.F_end + New.C_actual) - (New.F_init + New.C_init)] × EA_ratio_prem
        ea_ratio_prem = exp_adj_ratio
        prem_var_raw = (new_f_end_prem + new_c_actual_prem) - (new_f_init_prem + new_c_init_prem)
        context.prem_var = prem_var_raw * ea_ratio_prem
        context.adj_prem = context.prem_var  # 保存经验调整值，供后续使用
        context.actual_premium_nb = new_c_actual_prem
        context.actual_premium_eff = Decimal('0')
        
        logger.log_item(
            "保费现金流经验调整",
            "[Sec 4.3] 实际保费与预期保费的差异（经验调整）",
            f"Adj_Prem^New = [(New.F_end + New.C_actual) - (New.F_init + New.C_init)] × EA_ratio_prem\n其中：\n  New.F_end = {describe_field(pv_field_new_end_prem)}\n  New.C_actual = 签单年度时=签单保费，签单年度之后=0\n  New.F_init = {describe_field(pv_field_new_init_prem)}\n  New.C_init = {describe_field(pv_field_new_init_current_prem)}\n  EA_ratio_prem = 100%（保费经验调整占比）",
            {
                "PV字段（New.F_end）": pv_field_new_end_prem,
                "PV字段（New.F_init）": pv_field_new_init_prem,
                "PV字段（New.C_init）": pv_field_new_init_current_prem,
                f"{describe_field(pv_field_new_end_prem)}": new_f_end_prem,
                "New.C_actual": new_c_actual_prem,
                f"{describe_field(pv_field_new_init_prem)}": new_f_init_prem,
                f"{describe_field(pv_field_new_init_current_prem)}": new_c_init_prem,
                "评估月（期末）": eop_month_str,
                "评估月（初始）": uw_month_str,
                "数据来源": "PV原材料数据（pv_calculator.py）"
            },
            context.prem_var,
            note=f"从PV原材料数据读取。签单年度时New.C_actual=签单保费（实际值），签单年度之后New.C_actual=0。保费经验调整占比=100%"
        )
    else:
        # 存量合同：Adj_Prem^Eff = (Eff.F_end + Eff.C_actual) - (Eff.F_beg + Eff.C_year)
        # 对于一次性缴费的保单，从第二年开始：
        # Eff.F_end = 0（有效合同-期末预期-预期未来-保费，一次性缴费无未来保费）
        # Eff.C_actual = 0（后续年度无实际保费现金流）
        # Eff.F_beg = 0（有效合同-年初预期-预期未来-保费，一次性缴费无未来保费）
        # Eff.C_year = 0（有效合同-年初预期-预期当年-保费，一次性缴费无当年保费）
        if pv_data_bop is None:
            raise ValueError(f"❌ 错误: 找不到年初月份 {bop_month_str} 的PV原材料数据！")
        
        # 从PV原材料数据读取：有效合同-期末预期-预期未来-期末现值-加权初始确认利率-保费现金流
        pv_field_eff_end_prem = 'Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt'
        eff_f_end_prem = pv_data_eop.get_field(pv_field_eff_end_prem)
        eff_c_actual_prem = Decimal('0')  # 后续年度无实际保费现金流
        
        # 从PV原材料数据读取：有效合同-年初预期-预期未来-期末现值-加权初始确认利率-保费现金流
        pv_field_eff_beg_prem = 'Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt'
        eff_f_beg_prem = pv_data_bop.get_field(pv_field_eff_beg_prem)
        # 从PV原材料数据读取：有效合同-年初预期-预期当期-期末现值-加权初始确认利率-保费现金流
        pv_field_eff_year_prem = 'Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt'
        eff_c_year_prem = pv_data_bop.get_field(pv_field_eff_year_prem)
        
        # [Sec 4.3] 保费现金流经验调整 = [(Eff.F_end + Eff.C_actual) - (Eff.F_beg + Eff.C_year)] × EA_ratio_prem
        ea_ratio_prem = exp_adj_ratio
        prem_var_raw = (eff_f_end_prem + eff_c_actual_prem) - (eff_f_beg_prem + eff_c_year_prem)
        context.prem_var = prem_var_raw * ea_ratio_prem
        context.adj_prem = context.prem_var  # 保存经验调整值，供后续使用
        context.actual_premium_eff = eff_c_actual_prem
        context.actual_premium_nb = Decimal('0')
        
        logger.log_item(
            "保费现金流经验调整",
            "[Sec 4.3] 实际保费与预期保费的差异（经验调整）",
            f"Adj_Prem^Eff = [(Eff.F_end + Eff.C_actual) - (Eff.F_beg + Eff.C_year)] × EA_ratio_prem\n其中：\n  Eff.F_end = {describe_field(pv_field_eff_end_prem)}\n  Eff.C_actual = 0（后续年度无实际保费现金流）\n  Eff.F_beg = {describe_field(pv_field_eff_beg_prem)}\n  Eff.C_year = {describe_field(pv_field_eff_year_prem)}\n  EA_ratio_prem = 100%（保费经验调整占比）",
            {
                "PV字段（Eff.F_end）": pv_field_eff_end_prem,
                "PV字段（Eff.F_beg）": pv_field_eff_beg_prem,
                "PV字段（Eff.C_year）": pv_field_eff_year_prem,
                f"{describe_field(pv_field_eff_end_prem)}": eff_f_end_prem,
                "Eff.C_actual": eff_c_actual_prem,
                f"{describe_field(pv_field_eff_beg_prem)}": eff_f_beg_prem,
                f"{describe_field(pv_field_eff_year_prem)}": eff_c_year_prem,
                "评估月（期末）": eop_month_str,
                "评估月（年初）": bop_month_str,
                "数据来源": "PV原材料数据（pv_calculator.py）"
            },
            context.prem_var,
            note=f"从PV原材料数据读取。对于一次性缴费的保单，后续年度无保费现金流，因此Eff.C_actual=0，且所有预期未来和预期当期保费均为0，所以经验调整=0。保费经验调整占比=100%"
        )

    # [Sec 4.4] IACF 经验调整
    # 注意：实施时需按合同类型二选一（Eff 或 New）
    if is_new_business:
        # 新增合同：Adj_IACF^New = (New.F_end^I + New.C_actual^I) - (New.F_init^I + New.C_init^I)
        # 对于一次性缴费的保单，IACF在初始确认时已全部支付
        # New.F_end^I = 期末预期未来IACF现值（期末现值-加权初始确认利率）
        # New.C_actual^I = 0（后续年度无实际IACF现金流）
        # New.F_init^I = 初始确认时的预期未来IACF现值（期末现值-加权初始确认利率）
        # New.C_init^I = 初始确认时的预期当期IACF现值（期末现值-加权初始确认利率）
        uw_month_str = context.under_write_date.strftime('%Y%m')
        pv_data_init = context.pv_source_data.get_data(uw_month_str)
        if pv_data_init is None:
            raise ValueError(f"❌ 错误: 找不到初始确认月 {uw_month_str} 的PV原材料数据！")
        
        # 从PV原材料数据读取：新增合同-期末预期-预期未来-期末现值-加权初始确认利率-保险获取现金流
        pv_field_new_end_iacf = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt'
        new_f_end_iacf = pv_data_eop.get_field(pv_field_new_end_iacf)
        
        # 从PV原材料数据读取：新增合同-初始确认-预期未来-期末现值-加权初始确认利率-保险获取现金流
        pv_field_new_init_iacf = 'Pvfl_Nb_Ini_Cfa_Rep_Wlk_Acq_Amt'
        new_f_init_iacf = pv_data_init.get_field(pv_field_new_init_iacf)
        
        # 从PV原材料数据读取：新增合同-初始确认-预期当期-期末现值-加权初始确认利率-保险获取现金流
        pv_field_new_init_current_iacf = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Acq_Amt'
        new_c_init_iacf = pv_data_init.get_field(pv_field_new_init_current_iacf)
        
        # 判断是否为签单年度：签单年度时，实际获取费用 = 从PV数据读取的实际值（Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt）
        # 签单年度之后，实际获取费用 = 0
        if context.year == context.under_write_date.year:
            # 签单年度：从PV原材料数据读取实际获取费用（初始确认现值-当月初始利率）
            # 注意：签单时点发生的IACF，现值=名义值（不折现）
            pv_field_actual_iacf = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt'
            new_c_actual_iacf = pv_data_init.get_field(pv_field_actual_iacf)  # 实际获取费用（从数据库读取的实际值）
        else:
            new_c_actual_iacf = Decimal('0')  # 签单年度之后：无实际IACF现金流
        
        # [Sec 4.4] IACF经验调整 = [(New.F_end^I + New.C_actual^I) - (New.F_init^I + New.C_init^I)] × EA_ratio_iacf
        ea_ratio_iacf = exp_adj_ratio
        iacf_var_raw = (new_f_end_iacf + new_c_actual_iacf) - (new_f_init_iacf + new_c_init_iacf)
        context.iacf_var = iacf_var_raw * ea_ratio_iacf
        context.adj_iacf = context.iacf_var  # 保存经验调整值，供后续使用
        context.expected_iacf_nominal = new_f_init_iacf + new_c_init_iacf  # 用于后续IACF摊销计算
        context.actual_iacf_incurred = new_c_actual_iacf  # 实际IACF（签单年度=实际值，签单年度之后=0）
        context.actual_iacf_nb = new_c_actual_iacf
        context.actual_iacf_eff = Decimal('0')
        
        # 获取实际获取费用的PV字段描述（如果是在签单年度）
        if context.year == context.under_write_date.year:
            pv_field_actual_iacf = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt'
            actual_iacf_desc = describe_field(pv_field_actual_iacf)
        else:
            pv_field_actual_iacf = None
            actual_iacf_desc = "0（签单年度之后）"
        
        logger.log_item(
            "IACF 经验调整",
            "[Sec 4.4] 实际获取费用与预期获取费用的差异（经验调整）",
            f"Adj_IACF^New = [(New.F_end^I + New.C_actual^I) - (New.F_init^I + New.C_init^I)] × EA_ratio_iacf\n其中：\n  New.F_end^I = {describe_field(pv_field_new_end_iacf)}\n  New.C_actual^I = 签单年度时=实际获取费用（从PV数据读取），签单年度之后=0\n  New.F_init^I = {describe_field(pv_field_new_init_iacf)}\n  New.C_init^I = {describe_field(pv_field_new_init_current_iacf)}\n  EA_ratio_iacf = 0%（IACF经验调整占比）",
            {
                "PV字段（New.F_end^I）": pv_field_new_end_iacf,
                "PV字段（New.F_init^I）": pv_field_new_init_iacf,
                "PV字段（New.C_init^I）": pv_field_new_init_current_iacf,
                **({"PV字段（New.C_actual^I）": pv_field_actual_iacf} if pv_field_actual_iacf else {}),
                f"{describe_field(pv_field_new_end_iacf)}": new_f_end_iacf,
                "New.C_actual^I": new_c_actual_iacf,
                f"{describe_field(pv_field_new_init_iacf)}": new_f_init_iacf,
                f"{describe_field(pv_field_new_init_current_iacf)}": new_c_init_iacf,
                "评估月（期末）": eop_month_str,
                "评估月（初始）": uw_month_str,
                "数据来源": "PV原材料数据（pv_calculator.py）"
            },
            context.iacf_var,
            note=f"从PV原材料数据读取。签单年度时New.C_actual^I=实际获取费用（从数据库读取的实际值，存储在Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt），签单年度之后New.C_actual^I=0。IACF经验调整占比=0%"
        )
    else:
        # 存量合同：Adj_IACF^Eff = (Eff.F_end^I + Eff.C_actual^I) - (Eff.F_beg^I + Eff.C_year^I)
        # 对于一次性缴费的保单，从第二年开始：
        # Eff.F_end^I = 0（有效合同-期末预期-预期未来-IACF，一次性缴费无未来IACF）
        # Eff.C_actual^I = 0（后续年度无实际IACF现金流）
        # Eff.F_beg^I = 0（有效合同-年初预期-预期未来-IACF，一次性缴费无未来IACF）
        # Eff.C_year^I = 0（有效合同-年初预期-预期当年-IACF，一次性缴费无当年IACF）
        if pv_data_bop is None:
            raise ValueError(f"❌ 错误: 找不到年初月份 {bop_month_str} 的PV原材料数据！")
        
        # 从PV原材料数据读取：有效合同-期末预期-预期未来-期末现值-加权初始确认利率-保险获取现金流
        pv_field_eff_end_iacf = 'Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt'
        eff_f_end_iacf = pv_data_eop.get_field(pv_field_eff_end_iacf)
        eff_c_actual_iacf = Decimal('0')  # 后续年度无实际IACF现金流
        
        # 从PV原材料数据读取：有效合同-年初预期-预期未来-期末现值-加权初始确认利率-保险获取现金流
        pv_field_eff_beg_iacf = 'Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt'
        eff_f_beg_iacf = pv_data_bop.get_field(pv_field_eff_beg_iacf)
        # 从PV原材料数据读取：有效合同-年初预期-预期当期-期末现值-加权初始确认利率-保险获取现金流
        pv_field_eff_year_iacf = 'Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt'
        eff_c_year_iacf = pv_data_bop.get_field(pv_field_eff_year_iacf)
        
        # [Sec 4.4] IACF经验调整 = [(Eff.F_end^I + Eff.C_actual^I) - (Eff.F_beg^I + Eff.C_year^I)] × EA_ratio_iacf
        ea_ratio_iacf = exp_adj_ratio
        iacf_var_raw = (eff_f_end_iacf + eff_c_actual_iacf) - (eff_f_beg_iacf + eff_c_year_iacf)
        context.iacf_var = iacf_var_raw * ea_ratio_iacf
        context.adj_iacf = context.iacf_var  # 保存经验调整值，供后续使用
        context.expected_iacf_nominal = eff_f_beg_iacf + eff_c_year_iacf  # 用于后续IACF摊销计算
        context.actual_iacf_incurred = eff_c_actual_iacf  # 实际IACF（后续年度为0）
        context.actual_iacf_eff = eff_c_actual_iacf
        context.actual_iacf_nb = Decimal('0')
        
        logger.log_item(
            "IACF 经验调整",
            "[Sec 4.4] 实际获取费用与预期获取费用的差异（经验调整）",
            f"Adj_IACF^Eff = [(Eff.F_end^I + Eff.C_actual^I) - (Eff.F_beg^I + Eff.C_year^I)] × EA_ratio_iacf\n其中：\n  Eff.F_end^I = {describe_field(pv_field_eff_end_iacf)}\n  Eff.C_actual^I = 0（后续年度无实际IACF现金流）\n  Eff.F_beg^I = {describe_field(pv_field_eff_beg_iacf)}\n  Eff.C_year^I = {describe_field(pv_field_eff_year_iacf)}\n  EA_ratio_iacf = 0%（IACF经验调整占比）",
            {
                "PV字段（Eff.F_end^I）": pv_field_eff_end_iacf,
                "PV字段（Eff.F_beg^I）": pv_field_eff_beg_iacf,
                "PV字段（Eff.C_year^I）": pv_field_eff_year_iacf,
                f"{describe_field(pv_field_eff_end_iacf)}": eff_f_end_iacf,
                "Eff.C_actual^I": eff_c_actual_iacf,
                f"{describe_field(pv_field_eff_beg_iacf)}": eff_f_beg_iacf,
                f"{describe_field(pv_field_eff_year_iacf)}": eff_c_year_iacf,
                "评估月（期末）": eop_month_str,
                "评估月（年初）": bop_month_str,
                "数据来源": "PV原材料数据（pv_calculator.py）"
            },
            context.iacf_var,
            note=f"从PV原材料数据读取。对于一次性缴费的保单，后续年度无IACF现金流，因此Eff.C_actual^I=0，且所有预期未来和预期当期IACF均为0，所以经验调整=0。IACF经验调整占比=0%"
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

