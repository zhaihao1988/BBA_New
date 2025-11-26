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
    # 根据文档要求：使用加权初始确认利率（Wlk），只包含预期当期（Cca），区分有效合同和新增合同
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
    
    # 判断是否为新业务
    is_new_business = getattr(context, 'is_new_business', None)
    if is_new_business is None:
        is_new_business = (context.year == getattr(context, 'under_write_date', None).year if hasattr(context, 'under_write_date') else False)
    
    # 从PV原材料数据读取预期赔付与费用现值（加权初始确认利率，预期当期）
    if is_new_business:
        # 新增合同：初始确认-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
        pv_field_claims_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt'
        pv_field_maint_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt'
        pv_claims_nb = pv_data_eop.get_field(pv_field_claims_nb)
        pv_maint_nb = pv_data_eop.get_field(pv_field_maint_nb)
        revenue_claims_expenses_gross = pv_claims_nb + pv_maint_nb
        contract_type_desc = "新增合同"
        pv_field_claims_desc = pv_field_claims_nb
        pv_field_maint_desc = pv_field_maint_nb
    else:
        # 有效合同：年初预期-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
        # 需要获取年初月份的PV数据
        bop_month_str = date_class(context.year, 1, 1).strftime('%Y%m')
        pv_data_bop = context.pv_source_data.get_data(bop_month_str)
        if pv_data_bop is None:
            raise ValueError(f"❌ 错误: 找不到年初月份 {bop_month_str} 的PV原材料数据！")
        pv_field_claims_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt'
        pv_field_maint_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt'
        pv_claims_if = pv_data_bop.get_field(pv_field_claims_if)
        pv_maint_if = pv_data_bop.get_field(pv_field_maint_if)
        revenue_claims_expenses_gross = pv_claims_if + pv_maint_if
        contract_type_desc = "有效合同"
        pv_field_claims_desc = pv_field_claims_if
        pv_field_maint_desc = pv_field_maint_if
    
    # 亏损分摊：分摊的LC_预期现金流
    # 根据文档：分摊的LC_预期现金流+LC调整_预期现金流
    # 简化实现：使用LC_Ratio分摊
    revenue_claims_expenses_lc_alloc = revenue_claims_expenses_gross * context.nb_lc_ratio
    context.revenue_claims_expenses_net = revenue_claims_expenses_gross - revenue_claims_expenses_lc_alloc
    
    # 构建公式描述
    if is_new_business:
        formula_desc = (
            f"【新增合同-初始确认-预期当期-赔付现金流-期末现值（加权初始确认利率）】\n"
            f"+【新增合同-初始确认-预期当期-维持费用现金流-期末现值（加权初始确认利率）】\n"
            f"PV字段：{pv_field_claims_desc}, {pv_field_maint_desc}\n"
            f"所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk），只包含预期当期（Cca）"
        )
    else:
        formula_desc = (
            f"【有效合同-年初预期-预期当期-赔付现金流-期末现值（加权初始确认利率）】\n"
            f"+【有效合同-年初预期-预期当期-维持费用现金流-期末现值（加权初始确认利率）】\n"
            f"PV字段：{pv_field_claims_desc}, {pv_field_maint_desc}\n"
            f"所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk），只包含预期当期（Cca）"
        )
    
    logger.log_item(
        "保险合同收入_预期赔付与费用_含亏损",
        f"当期预期的赔付和维持费用释放（{contract_type_desc}，预期当期）",
        formula_desc,
        {
            f"{contract_type_desc}_预期当期_赔付（Wlk）": pv_claims_nb if is_new_business else pv_claims_if,
            f"{contract_type_desc}_预期当期_维费（Wlk）": pv_maint_nb if is_new_business else pv_maint_if,
            "预期赔付与费用合计（含亏损）": revenue_claims_expenses_gross,
            "LC Ratio": context.nb_lc_ratio,
            "亏损分摊": revenue_claims_expenses_lc_alloc,
            "预期赔付与费用（扣除亏损分摊）": context.revenue_claims_expenses_net,
            "PV字段": f"{pv_field_claims_desc}, {pv_field_maint_desc}",
            "评估月（期末）": eop_month_str
        },
        context.revenue_claims_expenses_net,
        note=f"所有现值均从PV原材料数据读取，使用加权初始确认利率（Wlk），只包含预期当期（Cca）。{contract_type_desc}的预期赔付与费用 = {revenue_claims_expenses_gross}，扣除亏损分摊后 = {context.revenue_claims_expenses_net}"
    )
    
    # 记录亏损分摊明细
    logger.log_item(
        "保险合同收入_预期赔付与费用_亏损分摊",
        "分摊到亏损成分的预期赔付与费用",
        "分摊的LC_预期现金流 = 预期赔付与费用_含亏损 × LC_Ratio",
        {
            "预期赔付与费用_含亏损": revenue_claims_expenses_gross,
            "LC Ratio": context.nb_lc_ratio,
            "分摊的LC_预期现金流": revenue_claims_expenses_lc_alloc
        },
        revenue_claims_expenses_lc_alloc,
        note=f"亏损分摊 = {revenue_claims_expenses_gross} × {context.nb_lc_ratio} = {revenue_claims_expenses_lc_alloc}"
    )
    
    # 7.2 RA 释放（直接使用PV字段中的Rad_Amt）
    # 根据文档要求：使用加权初始确认利率（Wlk），只包含预期当期（Cca），区分有效合同和新增合同
    eop_month_str = context.eop_date.strftime('%Y%m')
    pv_data_eop = context.pv_source_data.get_data(eop_month_str)
    if pv_data_eop is None:
        # 尝试使用上一个可用的评估月数据（按月份倒序查找）
        available_months = sorted(context.pv_source_data.data_by_month.keys(), reverse=True)
        if available_months:
            # 找到小于等于当前评估月的最大月份
            fallback_month = None
            for month in available_months:
                if month <= eop_month_str:
                    fallback_month = month
                    break
            if fallback_month:
                pv_data_eop = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用 {fallback_month} 的数据作为替代")
            else:
                # 如果找不到合适的替代月份，使用最新的可用数据
                fallback_month = available_months[0]
                pv_data_eop = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用最新的可用数据 {fallback_month} 作为替代")
        else:
            raise ValueError(
                f"❌ 错误: 找不到期末评估月 {eop_month_str} 的PV原材料数据，且没有可用的替代数据！\n"
                f"   评估日期: {context.eop_date}\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
    
    # 从PV原材料数据读取期末现值（基于当前利率）- 用于其他计算
    from BBA_dev.utils.pv_field_desc import describe_field, format_pv_field_in_formula
    if is_new_business:
        pv_field_claims = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt'
        pv_field_maint = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt'
    else:
        pv_field_claims = 'Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt'
        pv_field_maint = 'Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt'
    context.pv_eop_claims_current = pv_data_eop.get_field(pv_field_claims)
    context.pv_eop_maint_current = pv_data_eop.get_field(pv_field_maint)
    
    # RA释放：直接使用PV字段中的Rad_Amt（加权初始确认利率，预期当期）
    # 根据文档：区分有效合同和新增合同
    if is_new_business:
        # 新增合同：初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）
        pv_field_ra_nb = 'Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt'
        ra_release_gross = pv_data_eop.get_field(pv_field_ra_nb)
        contract_type_desc = "新增合同"
    else:
        # 有效合同：年初预期-预期当期-非金融风险调整-期末现值（加权初始确认利率）
        # 需要获取年初月份的PV数据
        bop_month_str = date_class(context.year, 1, 1).strftime('%Y%m')
        pv_data_bop = context.pv_source_data.get_data(bop_month_str)
        if pv_data_bop is None:
            raise ValueError(f"❌ 错误: 找不到年初月份 {bop_month_str} 的PV原材料数据！")
        pv_field_ra_if = 'Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt'
        ra_release_gross = pv_data_bop.get_field(pv_field_ra_if)
        contract_type_desc = "有效合同"
    
    # 扣除 LC 分摊
    ra_release_lc_alloc = ra_release_gross * context.nb_lc_ratio
    context.ra_release_net = ra_release_gross - ra_release_lc_alloc
    
    # 构建公式描述
    if is_new_business:
        formula_desc = (
            f"【新增合同-初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）】\n"
            f"PV字段：{pv_field_ra_nb}\n"
            f"所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）"
        )
        pv_field_ra_desc = pv_field_ra_nb
    else:
        formula_desc = (
            f"【有效合同-年初预期-预期当期-非金融风险调整-期末现值（加权初始确认利率）】\n"
            f"PV字段：{pv_field_ra_if}\n"
            f"所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）"
        )
        pv_field_ra_desc = pv_field_ra_if
    
    logger.log_item(
        "保险合同收入_RA释放",
        f"当期释放的非金融风险调整（{contract_type_desc}，预期当期）",
        formula_desc,
        {
            f"{contract_type_desc}_预期当期_RA（Wlk）": ra_release_gross,
            "LC Ratio": context.nb_lc_ratio,
            "RA释放（含亏损）": ra_release_gross,
            "RA释放（扣除亏损分摊）": context.ra_release_net,
            "PV字段": pv_field_ra_desc,
            "评估月（期末）": eop_month_str
        },
        context.ra_release_net,
        note=f"所有现值均从PV原材料数据读取，使用Rad字段。{contract_type_desc}的RA释放 = {ra_release_gross}，扣除LC分摊后 = {context.ra_release_net}"
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
    # 根据文档：Sum(含亏损各项 + 亏损分摊各项 + CSM摊销 + IACF摊销 + 经验调整 - 投资成分)
    # 注意：含亏损和亏损分摊是分开的，需要分别加总
    context.total_revenue = (
        revenue_claims_expenses_gross +  # 含亏损
        revenue_claims_expenses_lc_alloc +  # 亏损分摊
        getattr(context, 'ra_release_gross', context.ra_release_net) +  # RA含亏损
        getattr(context, 'ra_release_lc_alloc', Decimal('0')) +  # RA亏损分摊
        context.csm_amort_amount +
        context.revenue_iacf_amort +
        context.revenue_exp_adj - 
        revenue_inv_comp
    )
    
    logger.log_item(
        "保险合同收入_合计",
        "当期确认的总保险合同收入",
        "Sum(保险合同收入_预期赔付与费用_含亏损, 保险合同收入_预期赔付与费用_亏损分摊, 保险合同收入_预期释放的非金融风险调整_含亏损, 保险合同收入_预期释放的非金融风险调整_亏损分摊, 保险合同收入_摊销的CSM, 保险合同收入_摊销的IACF, 保险合同收入_经验调整, 保险合同收入_分解的投资成分)\n其中：\n  保险合同收入_预期赔付与费用_含亏损 = 预期赔付与费用合计（含亏损）\n  保险合同收入_预期赔付与费用_亏损分摊 = 亏损分摊\n  保险合同收入_预期释放的非金融风险调整_含亏损 = RA释放（含亏损）\n  保险合同收入_预期释放的非金融风险调整_亏损分摊 = RA释放（亏损分摊）\n  保险合同收入_摊销的CSM = CSM摊销\n  保险合同收入_摊销的IACF = IACF摊销\n  保险合同收入_经验调整 = 经验调整\n  保险合同收入_分解的投资成分 = 投资成分（通常为0）",
        {
            "保险合同收入_预期赔付与费用_含亏损": revenue_claims_expenses_gross,
            "保险合同收入_预期赔付与费用_亏损分摊": revenue_claims_expenses_lc_alloc,
            "保险合同收入_预期释放的非金融风险调整_含亏损": getattr(context, 'ra_release_gross', context.ra_release_net),
            "保险合同收入_预期释放的非金融风险调整_亏损分摊": getattr(context, 'ra_release_lc_alloc', Decimal('0')),
            "保险合同收入_摊销的CSM": context.csm_amort_amount,
            "保险合同收入_摊销的IACF": context.revenue_iacf_amort,
            "保险合同收入_经验调整": context.revenue_exp_adj,
            "保险合同收入_分解的投资成分": revenue_inv_comp
        },
        context.total_revenue,
        note=f"合计 = {revenue_claims_expenses_gross}（含亏损）+ {revenue_claims_expenses_lc_alloc}（亏损分摊）+ {getattr(context, 'ra_release_gross', context.ra_release_net)}（RA含亏损）+ {getattr(context, 'ra_release_lc_alloc', Decimal('0'))}（RA亏损分摊）+ {context.csm_amort_amount}（CSM摊销）+ {context.revenue_iacf_amort}（IACF摊销）+ {context.revenue_exp_adj}（经验调整）- {revenue_inv_comp}（投资成分） = {context.total_revenue}"
    )

