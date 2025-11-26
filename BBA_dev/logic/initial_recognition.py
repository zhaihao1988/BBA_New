"""
初始确认逻辑 (Initial Recognition)

对应文档：第1-3节

核心功能：
1. 使用即期利率（Spot Rate）计算现值（文档 Sec 2.0）
2. 先计算单单 PV，然后聚合到 CohortState
3. 调用 rates_manager 更新锁定利率（文档 Sec 1.5）
"""

from decimal import Decimal
from BBA_dev.logic.rates_manager import calculate_spot_rate, update_weighted_locked_rate
from BBA_dev.models import Assumptions
from BBA_dev.models.pv_source_data import PVSourceDataCollection
from BBA_dev.utils.pv_source_loader import ensure_pv_source_data


def run(context, logger, assumptions: Assumptions = None, cohort_state=None):
    """
    执行初始确认
    
    对应文档：第1-3节
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设（从数据库读取，包含动态假设）
        cohort_state: 合同组状态（可选，用于更新加权锁定利率）
    """
    logger.log_section("Part 1: 初始确认 (Initial Recognition) - New Business [Sec 1-3]")

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
    
    logger.log_item(
        "PV原材料数据验证",
        "验证PV原材料数据已加载",
        "ensure_pv_source_data()",
        {},
        "✅ 成功",
        note="所有现值计算将严格使用PV原材料数据，确保数据完整性和准确性"
    )

    # 获取签单保费
    context.actual_premium = Decimal(context.policy_data['sum_premium_no_tax'] or 0)
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        ra_ratio = assumptions.ra_ratio
        acquisition_expense_ratio = assumptions.acquisition_expense_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from BBA_dev.config import RATIO_IACF, RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
        loss_ratio = RATIO_CLAIM
        indirect_claims_expense_ratio = Decimal('0')
        maintenance_expense_ratio = RATIO_MAINT_EXP
        ra_ratio = RATIO_RA
        acquisition_expense_ratio = RATIO_IACF
    
    # [Sec 2.0] 新单初始确认：使用即期利率（Spot Rate）计算现值
    spot_rate = calculate_spot_rate(context.rates_df)
    logger.log_item(
        "即期利率（Spot Rate）",
        "[Sec 2.0] 新单初始确认时使用的即期利率",
        "利率曲线的第一个值",
        {},
        spot_rate,
        note="新单初始确认时使用即期利率计算现值，计算完成后权重并入加权锁定利率"
    )
    
    # 获取评估月并加载PV原材料数据
    uw_month_str = context.under_write_date.strftime('%Y%m')
    pv_data = context.pv_source_data.get_data(uw_month_str)
    if pv_data is None:
        raise ValueError(
            f"❌ 错误: 找不到评估月 {uw_month_str} 的PV原材料数据！\n"
            f"   签单日期: {context.under_write_date}\n"
            f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
        )
    
    from BBA_dev.utils.pv_field_desc import describe_field, format_pv_field_in_formula
    
    # 1.1 保费现值（文档 Sec 2.1）
    # 强制从PV原材料数据读取：预期当期 + 预期未来
    pv_field_prem_current = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Pre_Amt'
    pv_field_prem_future = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt'
    pv_prem_current = pv_data.get_field(pv_field_prem_current)
    pv_prem_future = pv_data.get_field(pv_field_prem_future)
    pv_premium = pv_prem_current + pv_prem_future
    logger.log_item(
        "当年新增合同_初始确认_预期保费现值",
        "[Sec 2.1] 初始确认时，预期未来收到的保费折现值（从PV原材料数据读取）",
        f"{describe_field(pv_field_prem_current)} + {describe_field(pv_field_prem_future)}",
        {
            "PV字段（预期当期）": pv_field_prem_current,
            "PV字段（预期未来）": pv_field_prem_future,
            f"{describe_field(pv_field_prem_current)}": pv_prem_current,
            f"{describe_field(pv_field_prem_future)}": pv_prem_future,
            "评估月": uw_month_str,
            "数据来源": "PV原材料数据（pv_calculator.py）"
        },
        pv_premium,
        note=f"从PV原材料数据读取：{pv_field_prem_current} + {pv_field_prem_future}，使用当月初始利率"
    )
    
    # 1.2 IACF 现值（文档 Sec 2.1）
    # 强制从PV原材料数据读取：预期当期 + 预期未来
    pv_field_iacf_current = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt'
    pv_field_iacf_future = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt'
    pv_iacf_current = pv_data.get_field(pv_field_iacf_current)
    pv_iacf_future = pv_data.get_field(pv_field_iacf_future)
    val_iacf = pv_iacf_current + pv_iacf_future
    logger.log_item(
        "当年新增合同_初始确认_IACF现值",
        "[Sec 2.1] 初始确认时，预期支付的获取费用折现值（从PV原材料数据读取）",
        f"{describe_field(pv_field_iacf_current)} + {describe_field(pv_field_iacf_future)}",
        {
            "PV字段（预期当期）": pv_field_iacf_current,
            "PV字段（预期未来）": pv_field_iacf_future,
            f"{describe_field(pv_field_iacf_current)}": pv_iacf_current,
            f"{describe_field(pv_field_iacf_future)}": pv_iacf_future,
            "评估月": uw_month_str,
            "数据来源": "PV原材料数据（pv_calculator.py）"
        },
        val_iacf,
        note=f"从PV原材料数据读取：{pv_field_iacf_current} + {pv_field_iacf_future}，使用当月初始利率"
    )

    # 1.3 赔付现值（文档 Sec 2.2）
    # 强制从PV原材料数据读取：预期当期 + 预期未来赔付现值（初始确认现值-当月初始利率）
    pv_field_claims_current = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Cla_Amt'  # 预期当期
    pv_field_claims_future = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt'  # 预期未来
    pv_claims_current = pv_data.get_field(pv_field_claims_current)
    pv_claims_future = pv_data.get_field(pv_field_claims_future)
    context.init_fut_claim = pv_claims_current + pv_claims_future
    logger.log_item(
        "当年新增合同_初始确认_预期赔付现值",
        "[Sec 2.2] 初始确认时，预期赔付支出的折现值（从PV原材料数据读取）",
        f"{describe_field(pv_field_claims_current)} + {describe_field(pv_field_claims_future)}",
        {
            "PV字段（预期当期）": pv_field_claims_current,
            "PV字段（预期未来）": pv_field_claims_future,
            f"{describe_field(pv_field_claims_current)}": pv_claims_current,
            f"{describe_field(pv_field_claims_future)}": pv_claims_future,
            "评估月": uw_month_str,
            "数据来源": "PV原材料数据（pv_calculator.py）"
        },
        context.init_fut_claim,
        note=f"从PV原材料数据读取：{pv_field_claims_current} + {pv_field_claims_future}，使用当月初始利率。需要加上预期当期，否则当年的现金流现值会被遗漏"
    )

    # 1.4 维费现值（文档 Sec 2.3）
    # 强制从PV原材料数据读取：预期当期 + 预期未来维持费用现值（初始确认现值-当月初始利率）
    pv_field_maint_current = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Mtn_Amt'  # 预期当期
    pv_field_maint_future = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt'  # 预期未来
    pv_maint_current = pv_data.get_field(pv_field_maint_current)
    pv_maint_future = pv_data.get_field(pv_field_maint_future)
    context.init_fut_maint = pv_maint_current + pv_maint_future
    logger.log_item(
        "当年新增合同_初始确认_预期维费现值",
        "[Sec 2.3] 初始确认时，预期维持费用的折现值（从PV原材料数据读取）",
        f"{describe_field(pv_field_maint_current)} + {describe_field(pv_field_maint_future)}",
        {
            "PV字段（预期当期）": pv_field_maint_current,
            "PV字段（预期未来）": pv_field_maint_future,
            f"{describe_field(pv_field_maint_current)}": pv_maint_current,
            f"{describe_field(pv_field_maint_future)}": pv_maint_future,
            "评估月": uw_month_str,
            "数据来源": "PV原材料数据（pv_calculator.py）"
        },
        context.init_fut_maint,
        note=f"从PV原材料数据读取：{pv_field_maint_current} + {pv_field_maint_future}，使用当月初始利率。需要加上预期当期，否则当年的现金流现值会被遗漏"
    )

    # 1.5 RA（文档 Sec 3.2）
    # 强制从PV原材料数据读取：预期当期 + 预期未来非金融风险调整（初始确认现值-当月初始利率）
    pv_field_ra_current = 'Pvfl_Nb_Ini_Cca_Rec_Lkd_Rad_Amt'  # 预期当期
    pv_field_ra_future = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt'  # 预期未来
    pv_ra_current = pv_data.get_field(pv_field_ra_current)
    pv_ra_future = pv_data.get_field(pv_field_ra_future)
    context.init_ra = pv_ra_current + pv_ra_future
    logger.log_item(
        "当年新增合同_初始确认_非金融风险调整(RA)",
        "[Sec 3.2] 初始确认时，对非金融风险的调整额（从PV原材料数据读取）",
        f"{describe_field(pv_field_ra_current)} + {describe_field(pv_field_ra_future)}",
        {
            "PV字段（预期当期）": pv_field_ra_current,
            "PV字段（预期未来）": pv_field_ra_future,
            f"{describe_field(pv_field_ra_current)}": pv_ra_current,
            f"{describe_field(pv_field_ra_future)}": pv_ra_future,
            "评估月": uw_month_str,
            "数据来源": "PV原材料数据（pv_calculator.py）"
        },
        context.init_ra,
        note=f"从PV原材料数据读取：{pv_field_ra_current} + {pv_field_ra_future}，使用当月初始利率。需要加上预期当期，否则当年的现金流现值会被遗漏。RA计算公式：(PV_Claims + PV_Maint) * RA_ratio，已在pv_calculator.py中计算完成"
    )

    # 1.6 初始 CSM/LC 计算（文档 Sec 3.3）
    # 注意：此为初始确认时的逐单判定，后续需进行合同组聚合判定（见第8.5节）
    pv_inflow = pv_premium
    pv_outflow = val_iacf + context.init_fut_claim + context.init_fut_maint
    net_inflow = pv_inflow - pv_outflow
    margin = net_inflow - context.init_ra
    
    context.nb_initial_csm = Decimal('0')
    context.nb_initial_lc = Decimal('0')
    
    csm_status = ""
    if margin >= 0:
        context.nb_initial_csm = margin
        csm_status = "Profitable (CSM)"
    else:
        context.nb_initial_lc = -margin
        csm_status = "Onerous (Loss Component) - 立即确认亏损"

    logger.log_item(
        "当年新增合同_初始确认_CSM/LC",
        "[Sec 3.3] 初始确认时的合同服务边际或亏损（逐单判定）",
        "Net_Inflow = PV_Prem - (PV_Claims + PV_Maint + PV_IACF); Margin = Net_Inflow - RA",
        {
            "PV_Prem": pv_inflow,
            "PV_IACF": val_iacf,
            "PV_Claims": context.init_fut_claim,
            "PV_Maint": context.init_fut_maint,
            "Net_Inflow": net_inflow,
            "RA": context.init_ra,
            "Margin": margin
        },
        margin,
        note=f"判定结果: {csm_status}. Initial CSM = {context.nb_initial_csm:,.2f}, Initial LC = {context.nb_initial_lc:,.2f}。注意：初始确认时逐单计算 CSM/LC，但最终状态需在合同组层面聚合判定（见第8.5节）"
    )
    
    # [Sec 1.5] 更新加权初始确认利率
    if cohort_state:
        update_weighted_locked_rate(
            cohort_state,
            spot_rate,
            context.actual_premium,
            logger
        )

