from decimal import Decimal
from datetime import date as date_class
from BBA_dev.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
import pandas as pd
from BBA_dev.data_access.loader import get_rates
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data

def run(context, logger):
    logger.log_section("Part 7: 保险合同收入 (Insurance Revenue)")
    
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
    
    # 7.1 预期赔付与费用释放（从PV原材料数据读取现值）
    # 根据文档要求：使用加权初始确认利率（Wlk），只包含预期当期（Cca），同时包含有效合同和新增合同
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
    
    from BBA_dev.utils.pv_field_desc import describe_field, format_pv_field_in_formula
    
    # 获取当前评估期的PV数据（所有数据都从当前评估期读取）
    eop_month_str = context.val_month_str if hasattr(context, 'val_month_str') else context.eop_date.strftime('%Y%m')
    pv_data = context.pv_source_data.get_data(eop_month_str)
    
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 从PV原材料数据读取预期赔付与费用现值（加权初始确认利率，预期当期）
    # 同时包含有效合同和新增合同
    # 有效合同：年初预期-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
    pv_field_claims_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt'
    pv_field_maint_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt'
    pv_claims_if = pv_data.get_field(pv_field_claims_if) if pv_data else Decimal('0')
    pv_maint_if = pv_data.get_field(pv_field_maint_if) if pv_data else Decimal('0')
    
    # 新增合同：初始确认-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
    # 从当前评估月的PV数据读取
    pv_field_claims_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt'
    pv_field_maint_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt'
    pv_claims_nb = pv_data.get_field(pv_field_claims_nb, Decimal('0')) if pv_data else Decimal('0')
    pv_maint_nb = pv_data.get_field(pv_field_maint_nb, Decimal('0')) if pv_data else Decimal('0')
    
    # 合计：有效合同 + 新增合同
    revenue_claims_expenses_gross = pv_claims_if + pv_maint_if + pv_claims_nb + pv_maint_nb
    
    # 亏损分摊：分摊的LC_预期现金流 + LC调整_预期现金流
    # 分摊的LC_预期现金流 = 预期赔付与费用_含亏损 × LC_Ratio
    revenue_claims_expenses_lc_alloc_base = revenue_claims_expenses_gross * (getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'))
    
    # LC调整_预期现金流：从csm_lc_measurement模块获取
    # 注意：如果csm_lc_measurement模块中还没有计算LC调整，这里先使用占位符
    lc_adjust_cf = getattr(context, 'lc_adjust_cf', Decimal('0')) or Decimal('0')
    revenue_claims_expenses_lc_alloc = revenue_claims_expenses_lc_alloc_base + lc_adjust_cf
    
    context.revenue_claims_expenses_net = revenue_claims_expenses_gross - revenue_claims_expenses_lc_alloc_base
    
    # 构建公式描述
    formula_desc = (
        f"【有效合同-年初预期-预期当年-赔付现金流-期末现值（加权初始确认利率）】\n"
        f"+【新增合同-初始确认-预期当期-预赔付现金流-期末现值（加权初始确认利率）】\n"
        f"+【有效合同-年初预期-预期当年-维持费用现金流-期末现值（加权初始确认利率）】\n"
        f"+【新增合同-初始确认-预期当期-维持费用现金流-期末现值（加权初始确认利率）】\n"
        f"PV字段：{pv_field_claims_if}, {pv_field_maint_if}, {pv_field_claims_nb}, {pv_field_maint_nb}\n"
        f"所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk），只包含预期当期（Cca）"
    )
    
    logger.log_item(
        "保险合同收入_预期赔付与费用_含亏损",
        "当期预期的赔付和维持费用释放（有效合同+新增合同，预期当期）",
        formula_desc,
        {
            "有效合同_预期当期_赔付（Wlk）": pv_claims_if,
            "新增合同_预期当期_赔付（Wlk）": pv_claims_nb,
            "有效合同_预期当期_维费（Wlk）": pv_maint_if,
            "新增合同_预期当期_维费（Wlk）": pv_maint_nb,
            "预期赔付与费用合计（含亏损）": revenue_claims_expenses_gross,
            "PV字段": f"{pv_field_claims_if}, {pv_field_maint_if}, {pv_field_claims_nb}, {pv_field_maint_nb}",
            "评估月": eop_month_str
        },
        revenue_claims_expenses_gross,
        note=f"所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk），只包含预期当期（Cca）。同时包含有效合同和新增合同"
    )
    
    # 记录亏损分摊明细
    logger.log_item(
        "保险合同收入_预期赔付与费用_亏损分摊",
        "分摊到亏损成分的预期赔付与费用",
        "分摊的LC_预期现金流 + LC调整_预期现金流\n其中：\n  分摊的LC_预期现金流 = 预期赔付与费用_含亏损 × LC_Ratio\n  LC调整_预期现金流 = 从csm_lc_measurement模块获取",
        {
            "预期赔付与费用_含亏损": revenue_claims_expenses_gross,
            "LC Ratio": getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'),
            "分摊的LC_预期现金流": revenue_claims_expenses_lc_alloc_base,
            "LC调整_预期现金流": lc_adjust_cf,
            "亏损分摊合计": revenue_claims_expenses_lc_alloc
        },
        revenue_claims_expenses_lc_alloc,
        note=f"亏损分摊 = 分摊的LC_预期现金流({revenue_claims_expenses_lc_alloc_base}) + LC调整_预期现金流({lc_adjust_cf}) = {revenue_claims_expenses_lc_alloc}"
    )
    
    # 7.2 RA 释放（直接使用PV字段中的Rad_Amt）
    # 根据文档要求：使用加权初始确认利率（Wlk），只包含预期当期（Cca），同时包含有效合同和新增合同
    # 有效合同：年初预期-预期当期-非金融风险调整-期末现值（加权初始确认利率）
    pv_field_ra_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt'
    ra_release_if = pv_data.get_field(pv_field_ra_if) if pv_data else Decimal('0')
    
    # 新增合同：初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）
    # 从当前评估月的PV数据读取
    pv_field_ra_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt'
    ra_release_nb = pv_data.get_field(pv_field_ra_nb, Decimal('0')) if pv_data else Decimal('0')
    
    # 合计：有效合同 + 新增合同
    ra_release_gross = ra_release_if + ra_release_nb
    
    # 亏损分摊：分摊的LC_非金融风险调整 + LC调整_非金融风险调整
    # 分摊的LC_非金融风险调整 = RA释放_含亏损 × LC_Ratio
    ra_release_lc_alloc_base = ra_release_gross * (getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'))
    
    # LC调整_非金融风险调整：从csm_lc_measurement模块获取
    lc_adjust_ra = getattr(context, 'lc_adjust_ra', Decimal('0')) or Decimal('0')
    ra_release_lc_alloc = ra_release_lc_alloc_base + lc_adjust_ra
    
    context.ra_release_net = ra_release_gross - ra_release_lc_alloc_base
    context.ra_release_gross = ra_release_gross
    context.ra_release_lc_alloc = ra_release_lc_alloc
    
    # 构建公式描述
    formula_desc = (
        f"【有效合同-年初预期-预期当年-非金融风险调整-期末现值（加权初始确认利率）】\n"
        f"+【新增合同-初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）】\n"
        f"PV字段：{pv_field_ra_if}, {pv_field_ra_nb}\n"
        f"所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）"
    )
    
    logger.log_item(
        "保险合同收入_预期释放的非金融风险调整_含亏损",
        "当期释放的非金融风险调整（有效合同+新增合同，预期当期）",
        formula_desc,
        {
            "有效合同_预期当期_RA（Wlk）": ra_release_if,
            "新增合同_预期当期_RA（Wlk）": ra_release_nb,
            "RA释放（含亏损）": ra_release_gross,
            "PV字段": f"{pv_field_ra_if}, {pv_field_ra_nb}",
            "评估月": eop_month_str
        },
        ra_release_gross,
        note=f"所有现值均从PV原材料数据读取，使用Rad字段。同时包含有效合同和新增合同"
    )
    
    # 记录亏损分摊明细
    logger.log_item(
        "保险合同收入_预期释放的非金融风险调整_亏损分摊",
        "分摊到亏损成分的非金融风险调整",
        "分摊的LC_非金融风险调整 + LC调整_非金融风险调整\n其中：\n  分摊的LC_非金融风险调整 = RA释放_含亏损 × LC_Ratio\n  LC调整_非金融风险调整 = 从csm_lc_measurement模块获取",
        {
            "RA释放_含亏损": ra_release_gross,
            "LC Ratio": getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'),
            "分摊的LC_非金融风险调整": ra_release_lc_alloc_base,
            "LC调整_非金融风险调整": lc_adjust_ra,
            "亏损分摊合计": ra_release_lc_alloc
        },
        ra_release_lc_alloc,
        note=f"亏损分摊 = 分摊的LC_非金融风险调整({ra_release_lc_alloc_base}) + LC调整_非金融风险调整({lc_adjust_ra}) = {ra_release_lc_alloc}"
    )
    
    # 7.3 CSM 摊销（文档 Sec 8.2 & 8.9）
    # 使用覆盖单元动态比例法计算摊销比例
    from BBA_dev.logic.coverage_units import calculate_csm_amortization_ratio
    
    # 获取年初日期（用于计算覆盖单元）
    start_of_year = date_class(context.year, 1, 1)
    
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
    
    # CSM摊销金额（负值，表示CSM减少）
    context.csm_amort_amount = -(context.end_csm_before_amort * csm_amort_ratio)
    # CSM摊销确认的收入（正值）
    context.revenue_csm_amort = abs(context.csm_amort_amount)
    
    logger.log_item(
        "保险合同收入_摊销的CSM",
        "[Sec 8.9] 当期确认的合同服务边际（使用覆盖单元动态比例法）",
        "CSM_Amort_Revenue = Abs(-(CSM_beg + CSM_new + CSM_Interest + Δ_CSM) × CSM_Amort_Ratio)",
        {
            "CSM Balance (摊销前)": context.end_csm_before_amort,
            "摊销比例": csm_amort_ratio,
            "CSM摊销金额(负)": context.csm_amort_amount
        },
        context.revenue_csm_amort,
        note="摊销减少CSM余额，同时增加保险合同收入"
    )
    
    # 注意：end_csm_final 已经在 CSM/LC计量模块中正确计算完成（包含了被CSM吸收的变化）
    # Revenue模块不应该重新计算这个值，只使用它来确认收入
    # 原代码: context.end_csm_final = context.end_csm_before_amort + context.csm_amort_amount （已删除）
    
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
    # 经验调整包括保费经验调整和IACF经验调整
    # 注意：如果经验调整为正（实际优于预期），应增加收入
    prem_exp_adj = getattr(context, 'prem_var', Decimal('0')) or Decimal('0')
    iacf_exp_adj = getattr(context, 'iacf_var', Decimal('0')) or Decimal('0')
    context.revenue_exp_adj = prem_exp_adj + iacf_exp_adj
    
    logger.log_item(
        "保险合同收入_经验调整",
        "与当期服务相关的经验调整（保费+IACF）",
        "保费经验调整 + IACF经验调整",
        {
            "保费经验调整": prem_exp_adj,
            "IACF经验调整": iacf_exp_adj,
            "经验调整合计": prem_exp_adj + iacf_exp_adj,
            "保险合同收入_经验调整": context.revenue_exp_adj
        },
        context.revenue_exp_adj,
        note="经验调整包括保费经验调整和IACF经验调整"
    )
    
    # 7.6 合计
    # 根据文档：Sum(含亏损各项 - 亏损分摊各项 + CSM摊销 + IACF摊销 + 经验调整)
    # 注意：亏损分摊应从收入中扣除
    context.total_revenue = (
        revenue_claims_expenses_gross - revenue_claims_expenses_lc_alloc +  # 赔付与费用（扣除亏损分摊）
        ra_release_gross - ra_release_lc_alloc +  # RA释放（扣除亏损分摊）
        context.revenue_csm_amort +  # CSM摊销（正值）
        context.revenue_iacf_amort +  # IACF摊销（正值）
        context.revenue_exp_adj  # 经验调整
    )
    
    logger.log_item(
        "保险合同收入_合计",
        "当期确认的总保险合同收入",
        "Sum(保险合同收入_预期赔付与费用_含亏损 - 保险合同收入_预期赔付与费用_亏损分摊, 保险合同收入_预期释放的非金融风险调整_含亏损 - 保险合同收入_预期释放的非金融风险调整_亏损分摊, 保险合同收入_摊销的CSM, 保险合同收入_摊销的IACF, 保险合同收入_经验调整)\n其中：\n  保险合同收入_预期赔付与费用_含亏损 = 预期赔付与费用合计（含亏损）\n  保险合同收入_预期赔付与费用_亏损分摊 = 亏损分摊（分摊的LC_预期现金流 + LC调整_预期现金流）\n  保险合同收入_预期释放的非金融风险调整_含亏损 = RA释放（含亏损）\n  保险合同收入_预期释放的非金融风险调整_亏损分摊 = RA释放（亏损分摊）（分摊的LC_非金融风险调整 + LC调整_非金融风险调整）\n  保险合同收入_摊销的CSM = CSM摊销确认的收入\n  保险合同收入_摊销的IACF = IACF摊销\n  保险合同收入_经验调整 = 保费经验调整 + IACF经验调整",
        {
            "保险合同收入_预期赔付与费用_含亏损": revenue_claims_expenses_gross,
            "减：保险合同收入_预期赔付与费用_亏损分摊": -revenue_claims_expenses_lc_alloc,
            "保险合同收入_预期释放的非金融风险调整_含亏损": ra_release_gross,
            "减：保险合同收入_预期释放的非金融风险调整_亏损分摊": -ra_release_lc_alloc,
            "保险合同收入_摊销的CSM": context.revenue_csm_amort,
            "保险合同收入_摊销的IACF": context.revenue_iacf_amort,
            "保险合同收入_经验调整": context.revenue_exp_adj
        },
        context.total_revenue,
        note=f"合计 = {revenue_claims_expenses_gross} (赔付含亏损) - {revenue_claims_expenses_lc_alloc} (赔付亏损分摊) + {ra_release_gross} (RA含亏损) - {ra_release_lc_alloc} (RA亏损分摊) + {context.revenue_csm_amort} (CSM摊销) + {context.revenue_iacf_amort} (IACF摊销) + {context.revenue_exp_adj} (经验调整) = {context.total_revenue}"
    )

