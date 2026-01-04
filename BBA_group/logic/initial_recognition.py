"""
初始确认逻辑 (Initial Recognition)

对应文档：第1-3节

核心功能：
1. 使用即期利率（Spot Rate）计算现值（文档 Sec 2.0）
2. 计算初始 CSM/LC
3. 绕过组级加权，直接使用单保单即期利率更新锁定利率（文档 Sec 1.5 调整）
"""

from decimal import Decimal
from BBA_group.logic.rates_manager import calculate_spot_rate
from BBA_group.models import Assumptions
from BBA_group.models.pv_source_data import PVSourceDataCollection
from BBA_group.utils.pv_source_loader import ensure_pv_source_data


def run(context, logger, assumptions: Assumptions = None, cohort_state=None):
    """
    执行初始确认
    
    对应文档：第1-3节
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设
        cohort_state: 合同组状态（用于设置锁定利率）
    """
    logger.log_section("Part 1: 初始确认 (Initial Recognition) - New Business [Sec 1-3]")

    if context.pv_source_data is None:
        ensure_pv_source_data(context)
    
    if context.pv_source_data is None:
        policy_no = getattr(context.policy_data, 'policy_no', None) or getattr(context, 'policy_no', 'UNKNOWN')
        raise ValueError(f"❌ 错误: PV原材料数据不可用！保单号: {policy_no}")
    
    logger.log_item(
        "PV原材料数据验证",
        "验证PV原材料数据已加载",
        "ensure_pv_source_data()",
        {},
        "✅ 成功",
        note="所有现值计算将严格使用PV原材料数据"
    )

    # 获取签单保费
    context.actual_premium = Decimal(context.policy_data['sum_premium_no_tax'] or 0)
    
    if assumptions:
        loss_ratio = assumptions.loss_ratio
    else:
        from BBA_group.config import RATIO_CLAIM
        loss_ratio = RATIO_CLAIM
    
    # [Sec 2.0] 新单初始确认：使用即期利率
    spot_rate = calculate_spot_rate(context.rates_df)
    logger.log_item(
        "即期利率（Spot Rate）",
        "[Sec 2.0] 新单初始确认时使用的即期利率",
        "利率曲线的第一个值",
        {},
        spot_rate,
        note="新单初始确认时使用即期利率"
    )
    
    uw_month_str = context.under_write_date.strftime('%Y%m')
    pv_data = context.pv_source_data.get_data(uw_month_str)
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {uw_month_str} 的PV原材料数据！")
    
    is_reversal_policy = pv_data.metadata.get('is_reversal_policy', False)
    context.is_reversal_policy = is_reversal_policy
    
    if is_reversal_policy:
        logger.log_text("⚠️  **批减单标记**: 检测到批减单。本次口径：PV/计量全程按原始符号不取反；仅在CSM/LC判定时反转符号。")
    
    from BBA_group.utils.pv_field_desc import describe_field
    
    # 1.1 保费现值
    pv_field_prem = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt'
    pv_premium = pv_data.get_field(pv_field_prem)
    # 保存初始确认时的预期保费现值（用于104报表）
    context.init_pv_premium = pv_premium
    logger.log_item(
        "当年新增合同_初始确认_预期保费现值",
        "[Sec 2.1] 初始确认时，预期未来收到的保费折现值",
        f"{describe_field(pv_field_prem)}",
        {f"{describe_field(pv_field_prem)}": pv_premium},
        pv_premium,
        note=f"从PV原材料数据读取：{pv_field_prem}，使用锁定利率。此值已保存到init_pv_premium，供104报表使用。"
    )
    
    # 1.2 IACF 现值
    pv_field_iacf = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt'
    val_iacf = pv_data.get_field(pv_field_iacf)
    
    # 保存初始确认时的预期获取费用现值（用于104报表）
    context.init_pv_iacf = val_iacf
    # 设置预期获取费用（使用PV数据中的预期获取费用现值，而不是精算假设计算的值）
    # 这样104报表中的预期获取费用就能与初始确认时使用的值一致
    context.actual_iacf_incurred = val_iacf
    logger.log_item(
        "当年新增合同_初始确认_IACF现值",
        "[Sec 2.1] 初始确认时，预期支付的获取费用折现值",
        f"{describe_field(pv_field_iacf)}",
        {f"{describe_field(pv_field_iacf)}": val_iacf},
        val_iacf,
        note=f"从PV原材料数据读取：{pv_field_iacf}，使用锁定利率。此值已保存到init_pv_iacf和actual_iacf_incurred，供104报表使用。"
    )

    # 1.3 赔付现值
    pv_field_claims = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt'
    context.init_fut_claim = pv_data.get_field(pv_field_claims)
    logger.log_item(
        "当年新增合同_初始确认_预期赔付现值",
        "[Sec 2.2] 初始确认时，预期赔付支出的折现值",
        f"{describe_field(pv_field_claims)}",
        {f"{describe_field(pv_field_claims)}": context.init_fut_claim},
        context.init_fut_claim,
        note=f"从PV原材料数据读取：{pv_field_claims}，使用锁定利率"
    )

    # 1.4 维费现值
    pv_field_maint = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt'
    context.init_fut_maint = pv_data.get_field(pv_field_maint)
    logger.log_item(
        "当年新增合同_初始确认_预期维费现值",
        "[Sec 2.3] 初始确认时，预期维持费用的折现值",
        f"{describe_field(pv_field_maint)}",
        {f"{describe_field(pv_field_maint)}": context.init_fut_maint},
        context.init_fut_maint,
        note=f"从PV原材料数据读取：{pv_field_maint}，使用锁定利率"
    )

    # 1.5 RA
    pv_field_ra = 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt'
    context.init_ra = pv_data.get_field(pv_field_ra)
    logger.log_item(
        "当年新增合同_初始确认_非金融风险调整(RA)",
        "[Sec 3.2] 初始确认时，对非金融风险的调整额",
        f"{describe_field(pv_field_ra)}",
        {f"{describe_field(pv_field_ra)}": context.init_ra},
        context.init_ra,
        note=f"从PV原材料数据读取：{pv_field_ra}，使用锁定利率"
    )

    # 1.6 初始 CSM/LC 计算
    pv_inflow = pv_premium
    pv_outflow = val_iacf + context.init_fut_claim + context.init_fut_maint
    net_inflow = pv_inflow - pv_outflow
    margin = net_inflow - context.init_ra
    
    context.nb_initial_csm = Decimal('0')
    context.nb_initial_lc = Decimal('0')
    
    is_reversal = getattr(context, 'is_reversal_policy', False)
    csm_status = ""
    # 正常保单：>=0 为CSM，<0 为LC；批减单符号相反
    if (not is_reversal and margin >= 0) or (is_reversal and margin <= 0):
        context.nb_initial_csm = margin
        context.nb_initial_lc = Decimal('0')
        csm_status = "Profitable (CSM)"
    else:
        context.nb_initial_csm = Decimal('0')
        context.nb_initial_lc = margin
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
        note=f"判定结果: {csm_status}. Initial CSM = {context.nb_initial_csm:,.2f}, Initial LC = {context.nb_initial_lc:,.2f}"
    )
    
    # [Sec 1.5] 更新锁定利率 (简化为直接赋值，单保单逻辑)
    if cohort_state:
        # 在单保单模式下，锁定利率即为当期即期利率，无需加权
        cohort_state.weighted_locked_rate = spot_rate
        logger.log_item(
            "锁定利率更新",
            "[Sec 1.5] 锁定利率更新（单保单模式）",
            "Weighted Locked Rate = Spot Rate",
            {},
            spot_rate,
            note="单保单模式下，直接使用即期利率作为锁定利率，不进行加权计算。"
        )