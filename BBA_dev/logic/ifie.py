"""
IFIE（利率变化对预期现金流的影响）

对应文档：
- 第13节：IFIE（计入损益部分）
- 第14节：IFIE_OCI（计入其他综合收益部分）

核心功能：
1. IFIE_P&C：仅包含计息影响，使用加权初始确认利率（锁定利率）
2. IFIE_OCI：仅包含利率变化影响
3. 严格区分 OCI=1（拆分）模式
"""

from decimal import Decimal
from typing import Optional
from datetime import date
from BBA_dev.config import USE_OCI_OPTION
from BBA_dev.models import Assumptions, CohortState
from BBA_dev.logic.rates_manager import get_locked_rate_for_discounting
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

def run(context, logger, assumptions: Assumptions = None, cohort_state: CohortState = None):
    """
    执行IFIE计算
    
    对应文档：第13-14节
    
    关键修正：
    - IFIE_P&C：仅包含计息影响，使用加权初始确认利率（锁定利率）
    - IFIE_OCI：仅包含利率变化影响
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        assumptions: 精算假设（从数据库读取）
        cohort_state: 合同组状态（包含加权锁定利率）
    """
    logger.log_section("Part 8: IFIE（利率变化对预期现金流的影响）[Sec 13-14]")
    
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
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        ra_ratio = assumptions.ra_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from BBA_dev.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
        loss_ratio = RATIO_CLAIM
        indirect_claims_expense_ratio = Decimal('0')
        maintenance_expense_ratio = RATIO_MAINT_EXP
        ra_ratio = RATIO_RA
    
    # [Sec 13.1] 获取加权初始确认利率（锁定利率）
    if cohort_state:
        locked_rate = cohort_state.weighted_locked_rate
    else:
        # 兼容旧代码：使用即期利率
        from BBA_dev.logic.rates_manager import calculate_spot_rate
        locked_rate = calculate_spot_rate(context.rates_df)
    
    logger.log_item(
        "加权初始确认利率（锁定利率）",
        "[Sec 13.1] 用于IFIE_P&C计算的锁定利率",
        "CohortState.weighted_locked_rate",
        {"Locked Rate": locked_rate},
        locked_rate,
        note="IFIE_P&C仅包含计息影响，使用加权初始确认利率（锁定利率）"
    )
    
    # 判断是否为新业务
    # 优先使用 context.is_new_business（由 experience_adj 设置）
    # 如果没有设置，则根据评估年度和签单年度判断
    if hasattr(context, 'is_new_business') and context.is_new_business is not None:
        is_new_business = bool(context.is_new_business)
    else:
        # 回退判断：签单年 = 评估年 → 新业务，签单年 < 评估年 → 有效合同
        is_new_business = (context.year == getattr(context, 'under_write_date', None).year if hasattr(context, 'under_write_date') else False)
        # 记录警告，说明使用了回退判断
        logger.log_text(f"⚠️  警告: context.is_new_business 未设置，使用回退判断: year={context.year}, under_write_date.year={getattr(context, 'under_write_date', None).year if hasattr(context, 'under_write_date') else None}, is_new_business={is_new_business}")
    
    # 获取期末评估月数据
    eop_month_str = context.eop_date.strftime('%Y%m')
    pv_data = context.pv_source_data.get_data(eop_month_str)
    if pv_data is None:
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
                pv_data = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用 {fallback_month} 的数据作为替代")
            else:
                # 如果找不到合适的替代月份，使用最新的可用数据
                fallback_month = available_months[0]
                pv_data = context.pv_source_data.get_data(fallback_month)
                logger.log_text(f"⚠️  警告: 评估月 {eop_month_str} 的PV原材料数据不存在，使用最新的可用数据 {fallback_month} 作为替代")
        else:
            raise ValueError(
                f"❌ 错误: 找不到期末评估月 {eop_month_str} 的PV原材料数据，且没有可用的替代数据！\n"
                f"   评估日期: {context.eop_date}\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
    
    # [Sec 13.2] 年初有效合同_预期现金流 IFIE_P&C
    # 当OCI选择权=1（拆分）时，只包含计息部分（逗号前的公式）
    # 所有数据都从当前评估期的PV数据读取
    # 初始化变量，避免未定义错误
    ifie_if_cf = Decimal('0')
    
    # 当OCI选择权=1（拆分）时，公式为：
    # 【有效合同-年初预期-预期未来-预期现金流-期末现值（加权初始确认利率）】+
    # 【有效合同-年初预期-预期当年-保费现金流-期末现值（加权初始确认利率）】+
    # 【有效合同-年初预期-预期当年-IACF-期末现值（加权初始确认利率）】+
    # 【有效合同-年初预期-预期当年-赔付现金流-期末现值（加权初始确认利率）】+
    # 【有效合同-年初预期-预期当年-维持费用现金流-期末现值（加权初始确认利率）】-
    # 【有效合同-年初预期-预期未来-预期现金流-年初现值（上年）加权初始确认利率】
    
    # 期末现值（当年年末数据，加权初始确认利率）：预期未来 + 预期当期（保费+IACF+赔付+维费）
    pv_eop_fut_claims = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt')
    pv_eop_fut_maint = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    pv_eop_cur_prem = pv_data.get_field('Pvfl_If_Eop_Cca_Rep_Wlk_Pre_Amt')
    pv_eop_cur_iacf = pv_data.get_field('Pvfl_If_Eop_Cca_Rep_Wlk_Acq_Amt')
    pv_eop_cur_claims = pv_data.get_field('Pvfl_If_Eop_Cca_Rep_Wlk_Cla_Amt')
    pv_eop_cur_maint = pv_data.get_field('Pvfl_If_Eop_Cca_Rep_Wlk_Mtn_Amt')
    
    pv_end_total = (pv_eop_fut_claims + pv_eop_fut_maint +
                   pv_eop_cur_prem + pv_eop_cur_iacf + pv_eop_cur_claims + pv_eop_cur_maint)
    
    # 期初现值（当年年初数据，上年加权初始确认利率）：预期未来（使用Wlk字段）
    pv_bop_fut_claims_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt', Decimal('0'))
    pv_bop_fut_maint_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt', Decimal('0'))
    
    pv_beg_fut_wlk = pv_bop_fut_claims_wlk + pv_bop_fut_maint_wlk
    
    # IFIE_P&C = 期末现值（Wlk） - 期初现值（Wlk）
    ifie_if_cf = pv_end_total - pv_beg_fut_wlk
    
    logger.log_item(
        "年初有效合同_预期现金流 IFIE_P&C",
        "[Sec 13.2] 年初有效合同预期现金流 IFIE（OCI选择权=1时只包含计息部分）",
        f"IFIE_P&C_IF^CF = 【有效合同-年初预期-预期未来-预期现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-保费现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-IACF-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-赔付现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-维持费用现金流-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期现金流-年初现值（上年）加权初始确认利率】\n注意：当OCI选择权=1时，只使用逗号前的公式（计息部分），利率变化部分在IFIE_OCI中计算",
        {
            "期末-预期未来-赔付（Wlk）": pv_eop_fut_claims,
            "期末-预期未来-维费（Wlk）": pv_eop_fut_maint,
            "期末-预期当年-保费（Wlk）": pv_eop_cur_prem,
            "期末-预期当年-IACF（Wlk）": pv_eop_cur_iacf,
            "期末-预期当年-赔付（Wlk）": pv_eop_cur_claims,
            "期末-预期当年-维费（Wlk）": pv_eop_cur_maint,
            "期末现值合计（Wlk）": pv_end_total,
            "年初-预期未来-赔付（Wlk）": pv_bop_fut_claims_wlk,
            "年初-预期未来-维费（Wlk）": pv_bop_fut_maint_wlk,
            "年初现值合计（Wlk）": pv_beg_fut_wlk,
            "IFIE_P&C_IF^CF": ifie_if_cf,
            "OCI选择权": "1（拆分）" if USE_OCI_OPTION else "0（不拆分）",
            "评估月": eop_month_str
        },
        ifie_if_cf,
        note=f"所有现值均从PV原材料数据读取。当OCI选择权=1时，只包含计息部分（逗号前的公式），利率变化部分在IFIE_OCI中计算。计算过程：{pv_end_total} - {pv_beg_fut_wlk} = {ifie_if_cf}"
    )
    
    # [Sec 13.3] 当年新增合同_预期现金流 IFIE_P&C
    # 当OCI选择权=1（拆分）时，只包含计息部分（逗号前的公式）
    # 重要：此部分仅针对新增合同（NB），有效合同（IF）的IFIE已在IFIE_IF^CF中计算
    
    # 根据是否为新业务选择不同的PV字段
    if is_new_business:
        contract_type_desc = "新增合同"
        # 当OCI选择权=1（拆分）时，公式为：
        # 【新增合同-初始确认-预期未来-预期现金流-期末现值（加权初始确认利率）】+
        # 【新增合同-初始确认-预期当期-保费现金流-期末现值（加权初始确认利率）】+
        # 【新增合同-初始确认-预期当期-IACF-期末现值（加权初始确认利率）】+
        # 【新增合同-初始确认-预期当期-赔付现金流-期末现值（加权初始确认利率）】+
        # 【新增合同-初始确认-预期当期-维持费用现金流-期末现值（加权初始确认利率）】-
        # 【新增合同-初始确认-预期未来-预期现金流-初始确认现值（当月初始利率）】
        
        # 期末现值（加权初始确认利率）：预期未来 + 预期当期
        pv_eop_fut_prem = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt')
        pv_eop_fut_iacf = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Acq_Amt')
        pv_eop_fut_claims = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt')
        pv_eop_fut_maint = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
        pv_eop_cur_prem = pv_data.get_field('Pvfl_Nb_Eop_Cca_Rep_Wlk_Pre_Amt')
        pv_eop_cur_iacf = pv_data.get_field('Pvfl_Nb_Eop_Cca_Rep_Wlk_Acq_Amt')
        pv_eop_cur_claims = pv_data.get_field('Pvfl_Nb_Eop_Cca_Rep_Wlk_Cla_Amt')
        pv_eop_cur_maint = pv_data.get_field('Pvfl_Nb_Eop_Cca_Rep_Wlk_Mtn_Amt')
        
        # 修正：保费为现金流入（负债减少），在计算负债现值时应为负项；其他为现金流出（负债增加），为正项
        # Part 1: 期末时点 (基于加权初始确认利率)
        # IFIE = (-Prem + IACF + Claims + Mtn)_End - (-Prem + IACF + Claims + Mtn)_Init
        pv_end_total = (
            -pv_eop_fut_prem + pv_eop_fut_iacf + pv_eop_fut_claims + pv_eop_fut_maint +
            -pv_eop_cur_prem + pv_eop_cur_iacf + pv_eop_cur_claims + pv_eop_cur_maint
        )
        
        # 初始现值（当月初始利率）：预期未来 + 预期当期（从当前评估月的PV数据读取）
        # 预期未来：从PV原材料数据读取（使用Lkd字段，当月初始利率）
        pv_init_fut_prem = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt')
        pv_init_fut_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt')
        # remove duplicate line
        pv_init_fut_claims = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        pv_init_fut_maint = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        
        # Part 2: 初始确认扣除项 (基于当月初始利率)
        # 注意：这里计算的是 Init 部分的 Liability Proxy，即 (-Prem + Others)
        # 最终公式为 End - Init，即 End - (-Prem + Others) = End + Prem - Others
        pv_init_fut_total = -pv_init_fut_prem + pv_init_fut_iacf + pv_init_fut_claims + pv_init_fut_maint
        
        # 注意：已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月）
        # 所以只需要使用Cfa字段即可
        pv_init_total = pv_init_fut_total
        
        # IFIE_P&C = 期末现值（Wlk） - 初始现值（Lkd，包含预期未来+预期当期）
        ifie_nb_cf = pv_end_total - pv_init_total
    else:
        # 有效合同：IFIE_NB^CF = 0（有效合同的IFIE已在IFIE_IF^CF中计算）
        ifie_nb_cf = Decimal('0')
        contract_type_desc = "新增合同"  # 虽然不会记录日志，但保持变量定义
        pv_end_total = Decimal('0')
        pv_init_fut_total = Decimal('0')
        pv_init_total = Decimal('0')
        pv_eop_fut_prem = pv_eop_fut_iacf = pv_eop_fut_claims = pv_eop_fut_maint = Decimal('0')
        pv_eop_cur_prem = pv_eop_cur_iacf = pv_eop_cur_claims = pv_eop_cur_maint = Decimal('0')
        pv_init_fut_prem = pv_init_fut_iacf = pv_init_fut_claims = pv_init_fut_maint = Decimal('0')
        init_source_desc = "有效合同的IFIE已在IFIE_IF^CF中计算，此处IFIE_NB^CF = 0"
    
    # 仅记录新增合同的IFIE_NB^CF日志（有效合同的IFIE已在IFIE_IF^CF中记录）
    if is_new_business:
        logger.log_item(
            "新增合同_预期现金流 IFIE_P&C",
            "[Sec 13.3] 新增合同预期现金流 IFIE（OCI选择权=1时只包含计息部分）",
            f"IFIE_P&C_NB^CF = ( -【新增合同-初始确认-预期未来/当期-保费现金流-期末现值（加权初始确认利率）】 + 【新增合同-初始确认-预期未来/当期-IACF-期末现值（加权初始确认利率）】 + 【新增合同-初始确认-预期未来/当期-赔付现金流-期末现值（加权初始确认利率）】 + 【新增合同-初始确认-预期未来/当期-维持费用现金流-期末现值（加权初始确认利率）】 ) - ( -【新增合同-初始确认-预期未来-保费现金流-初始确认现值（当月初始利率）】 + 【新增合同-初始确认-预期未来-IACF-初始确认现值（当月初始利率）】 + 【新增合同-初始确认-预期未来-赔付现金流-初始确认现值（当月初始利率）】 + 【新增合同-初始确认-预期未来-维持费用现金流-初始确认现值（当月初始利率）】 )\n注意：当OCI选择权=1时，只使用逗号前的公式（计息部分），利率变化部分在IFIE_OCI中计算。已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月），初始确认现值只使用预期未来部分",
            {
                "期末-预期未来-保费（Wlk）": pv_eop_fut_prem,
                "期末-预期未来-IACF（Wlk）": pv_eop_fut_iacf,
                "期末-预期未来-赔付（Wlk）": pv_eop_fut_claims,
                "期末-预期未来-维费（Wlk）": pv_eop_fut_maint,
                "期末-预期当期-保费（Wlk）": pv_eop_cur_prem,
                "期末-预期当期-IACF（Wlk）": pv_eop_cur_iacf,
                "期末-预期当期-赔付（Wlk）": pv_eop_cur_claims,
                "期末-预期当期-维费（Wlk）": pv_eop_cur_maint,
                "期末现值合计（Wlk）": pv_end_total,
                "初始-预期未来-保费（Lkd）": pv_init_fut_prem,
                "初始-预期未来-IACF（Lkd）": pv_init_fut_iacf,
                "初始-预期未来-赔付（Lkd）": pv_init_fut_claims,
                "初始-预期未来-维费（Lkd）": pv_init_fut_maint,
                "初始现值合计（Lkd，预期未来，Cfa字段包含所有现金流）": pv_init_total,
                "IFIE_P&C_NB^CF": ifie_nb_cf,
                "OCI选择权": "1（拆分）" if USE_OCI_OPTION else "0（不拆分）",
                "评估月": eop_month_str
            },
            ifie_nb_cf,
            note=f"所有现值均从PV原材料数据读取。当OCI选择权=1时，只包含计息部分（逗号前的公式），利率变化部分在IFIE_OCI中计算。计算过程：{pv_end_total} - {pv_init_total} = {ifie_nb_cf}"
        )
    else:
        # 有效合同：IFIE_NB^CF = 0，不记录日志（有效合同的IFIE已在IFIE_IF^CF中记录）
        logger.log_text(f"ℹ️  信息: 有效合同的IFIE已在'年初有效合同_预期现金流 IFIE_P&C'中计算，此处IFIE_NB^CF = 0")
    
    # [Sec 13.4] IFIE_预期现金流
    ifie_cf = ifie_if_cf + ifie_nb_cf
    
    # [Sec 13.5-13.6] 非金融风险调整 IFIE_P&C
    # 公式：期末RA现值（预期未来+预期当期，锁定利率）- 初始RA现值（预期未来+预期当期，当月初始利率）
    # 注意：必须使用Rad字段，不能从(Cla+Mtn)×RA_Ratio计算
    
    # [Sec 13.5] 年初有效合同_非金融风险调整 IFIE_P&C
    # 当OCI选择权=1（拆分）时，只包含计息部分（逗号前的公式）
    if pv_data is None:
        # 如果当年年初数据不存在（如首年），则年初有效合同RA IFIE为0
        ifie_if_ra = Decimal('0')
        logger.log_text(f"ℹ️  信息: 找不到当前评估月 {eop_month_str} 的PV原材料数据，年初有效合同_非金融风险调整 IFIE_P&C = 0")
    else:
        # 当OCI选择权=1（拆分）时，公式为：
        # 【有效合同-年初预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】+
        # 【有效合同-年初预期-预期当年-预期非金融风险调整-期末现值（加权初始确认利率）】-
        # 【有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年）加权初始确认利率】
        
        # 期末RA现值（当年年末数据，加权初始确认利率）：预期未来 + 预期当期
        ra_eop_fut = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
        ra_eop_cur = pv_data.get_field('Pvfl_If_Eop_Cca_Rep_Wlk_Rad_Amt')
        ra_end_total = ra_eop_fut + ra_eop_cur
        
        # 期初RA现值（当年年初数据，上年加权初始确认利率）：预期未来（使用Wlk字段）
        ra_bop_fut_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt', Decimal('0'))
        
        # IFIE_P&C = 期末RA现值（Wlk） - 期初RA现值（Wlk，仅预期未来）
        ifie_if_ra = ra_end_total - ra_bop_fut_wlk
        
        logger.log_item(
            "年初有效合同_非金融风险调整 IFIE_P&C",
            "[Sec 13.5] 年初有效合同非金融风险调整 IFIE（OCI选择权=1时只包含计息部分）",
            f"IFIE_P&C_IF^RA = 【有效合同-年初预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-预期非金融风险调整-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年）加权初始确认利率】\n注意：当OCI选择权=1时，只使用逗号前的公式（计息部分），利率变化部分在IFIE_OCI中计算",
            {
                "期末-预期未来-RA（Wlk）": ra_eop_fut,
                "期末-预期当年-RA（Wlk）": ra_eop_cur,
                "期末RA现值合计（Wlk）": ra_end_total,
                "年初-预期未来-RA（Wlk）": ra_bop_fut_wlk,
                "IFIE_P&C_IF^RA": ifie_if_ra,
                "OCI选择权": "1（拆分）" if USE_OCI_OPTION else "0（不拆分）",
                "评估月": eop_month_str
            },
            ifie_if_ra,
            note=f"所有现值均从PV原材料数据读取，使用Rad字段。当OCI选择权=1时，只包含计息部分（逗号前的公式），利率变化部分在IFIE_OCI中计算。计算过程：{ra_end_total} - {ra_bop_fut_wlk} = {ifie_if_ra}"
        )
    
    # [Sec 13.6] 当年新增合同_非金融风险调整 IFIE_P&C
    # 当OCI选择权=1（拆分）时，只包含计息部分（逗号前的公式）
    # 重要：此部分仅针对新增合同（NB），有效合同（IF）的RA IFIE已在IFIE_IF^RA中计算
    if is_new_business:
        contract_type_desc_ra = "新增合同"  # 重新设置合同类型描述
        # 当OCI选择权=1（拆分）时，公式为：
        # 【新增合同-初始确认-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】+
        # 【新增合同-初始确认-预期当期-预期非金融风险调整-期末现值（加权初始确认利率）】-
        # 【新增合同-初始确认-预期未来-预期非金融风险调整-初始确认现值（当月初始利率）】
        
        # 期末RA现值（加权初始确认利率）：预期未来 + 预期当期
        ra_eop_fut = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
        ra_eop_cur = pv_data.get_field('Pvfl_Nb_Eop_Cca_Rep_Wlk_Rad_Amt')
        ra_end_total = ra_eop_fut + ra_eop_cur
        
        # 初始RA现值（当月初始利率）：预期未来 + 预期当期（使用Lkd字段）
        # 从当前评估月的PV数据读取
        ra_init_fut = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        # 注意：已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月）
        
        # IFIE_P&C = 期末RA现值（Wlk） - 初始RA现值（Lkd，Cfa字段包含所有现金流）
        ifie_nb_ra = ra_end_total - ra_init_fut
    else:
        # 有效合同：IFIE_NB^RA = 0（有效合同的RA IFIE已在IFIE_IF^RA中计算）
        ifie_nb_ra = Decimal('0')
        contract_type_desc_ra = "新增合同"  # 虽然不会记录日志，但保持变量定义
        ra_end_total = Decimal('0')
        ra_init_fut = Decimal('0')
        ra_eop_fut = ra_eop_cur = Decimal('0')
        init_source_desc = "有效合同的RA IFIE已在IFIE_IF^RA中计算，此处IFIE_NB^RA = 0"
    
    ifie_ra = ifie_if_ra + ifie_nb_ra
    
    # 仅记录新增合同的IFIE_NB^RA日志（有效合同的RA IFIE已在IFIE_IF^RA中记录）
    if is_new_business:
        logger.log_item(
            "新增合同_非金融风险调整 IFIE_P&C",
            "[Sec 13.6] 新增合同非金融风险调整 IFIE（OCI选择权=1时只包含计息部分）",
            f"IFIE_P&C_NB^RA = 【新增合同-初始确认-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】+【新增合同-初始确认-预期当期-预期非金融风险调整-期末现值（加权初始确认利率）】-【新增合同-初始确认-预期未来-预期非金融风险调整-初始确认现值（当月初始利率）】\n注意：当OCI选择权=1时，只使用逗号前的公式（计息部分），利率变化部分在IFIE_OCI中计算。已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月）",
            {
                "期末-预期未来-RA（Wlk）": ra_eop_fut,
                "期末-预期当期-RA（Wlk）": ra_eop_cur,
                "期末RA现值合计（Wlk）": ra_end_total,
                "初始-预期未来-RA（Lkd）": ra_init_fut,
                "初始RA现值合计（Lkd，Cfa字段包含所有现金流）": ra_init_fut,
                "IFIE_P&C_NB^RA": ifie_nb_ra,
                "OCI选择权": "1（拆分）" if USE_OCI_OPTION else "0（不拆分）",
                "评估月": eop_month_str
            },
            ifie_nb_ra,
            note=f"所有现值均从PV原材料数据读取，使用Rad字段。当OCI选择权=1时，只包含计息部分（逗号前的公式），利率变化部分在IFIE_OCI中计算。已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月）。计算过程：{ra_end_total} - {ra_init_fut} = {ifie_nb_ra}"
        )
    else:
        # 有效合同：IFIE_NB^RA = 0，不记录日志（有效合同的RA IFIE已在IFIE_IF^RA中记录）
        logger.log_text(f"ℹ️  信息: 有效合同的RA IFIE已在'年初有效合同_非金融风险调整 IFIE_P&C'中计算，此处IFIE_NB^RA = 0")
    
    # [Sec 13.8] IFIE_CSM
    # IFIE_CSM = -CSM计息（来自Part 5：CSM计息）
    # 根据合同类型选择对应的CSM计息
    if is_new_business:
        contract_type_desc_csm = "新增合同"  # 重新设置合同类型描述
        csm_interest = context.nb_interest_csm  # 新增合同使用NB_Interest_CSM
        csm_interest_source = "NB_Interest_CSM (来自Part 5 - CSM计息) - 当年新增CSM计息"
    else:
        contract_type_desc_csm = "有效合同"  # 重新设置合同类型描述
        csm_interest = getattr(context, 'if_interest_csm', Decimal('0')) or Decimal('0')  # 有效合同使用IF_Interest_CSM
        csm_interest_source = "IF_Interest_CSM (来自Part 5 - CSM计息) - 期初有效合同CSM计息"
    
    ifie_csm = -csm_interest  # CSM计息的负值
    
    # [Sec 13.9] IFIE_P&C 合计
    ifie_pl_total = ifie_cf + ifie_ra + ifie_csm
    
    logger.log_item(
        "IFIE_P&C_预期现金流",
        "[Sec 13.4] IFIE_P&C 预期现金流合计",
        "IFIE_CF = IFIE_P&C_IF^CF + IFIE_P&C_NB^CF",
        {
            "年初有效合同_预期现金流": ifie_if_cf,
            "当年新增合同_预期现金流": ifie_nb_cf,
            "IFIE_预期现金流": ifie_cf
        },
        ifie_cf,
        note="包含有效合同和新增合同的IFIE_P&C预期现金流部分"
    )

    logger.log_item(
        "IFIE_P&C_非金融风险调整",
        "[Sec 13.7] IFIE_P&C 非金融风险调整合计",
        "IFIE_RA = IFIE_P&C_IF^RA + IFIE_P&C_NB^RA",
        {
            "年初有效合同_非金融风险调整": ifie_if_ra,
            "当年新增合同_非金融风险调整": ifie_nb_ra,
            "IFIE_非金融风险调整": ifie_ra
        },
        ifie_ra,
        note="包含有效合同和新增合同的IFIE_P&C非金融风险调整部分"
    )

    logger.log_item(
        "IFIE_CSM",
        "[Sec 13.8] CSM IFIE（仅包含计息影响）",
        f"IFIE_CSM = -{'NB' if is_new_business else 'IF'}_Interest_CSM",
        {
            f"{contract_type_desc_csm}_CSM计息": csm_interest,
            "IFIE_CSM": ifie_csm
        },
        ifie_csm,
        note="IFIE_CSM是CSM计息的负值"
    )

    logger.log_item(
        "IFIE",
        "[Sec 13.9] IFIE计入损益部分合计（仅包含计息影响）",
        "IFIE = IFIE_预期现金流 + IFIE_非金融风险调整 + IFIE_CSM",
        {
            "IFIE_预期现金流": ifie_cf,
            "IFIE_非金融风险调整": ifie_ra,
            "IFIE_CSM": ifie_csm
        },
        ifie_pl_total,
        note="所有计算均使用加权初始确认利率（锁定利率），仅包含计息影响。"
    )
    
    # [Sec 14] IFIE_OCI（计入其他综合收益）
    # 仅包含利率变化影响，不包含计息影响
    
    if USE_OCI_OPTION:
        # [Sec 14.2] 年初有效合同_预期现金流 IFIE_OCI
        # 公式：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - (Eff.F_{beg_prev_curr}^{CF} - Eff.F_{beg_prev}^{CF})
        # 注意：由于Pvfl_If_Bop_Cfa_Beg_Wlk_*字段不存在，年初的"上年加权初始确认利率"部分无法计算，假设为0
        # 因此公式简化为：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - (Eff.F_{beg_prev_curr}^{CF} - 0)
        # 进一步简化为：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - Eff.F_{beg_prev_curr}^{CF}
        # 但根据文档逻辑，应该是：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - 0 = Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}
        
        # [Sec 14.2] 年初有效合同_预期现金流 IFIE_OCI
        # 公式：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - (Eff.F_{beg_prev_curr}^{CF} - Eff.F_{beg_prev}^{CF})
        # 所有数据都从当前评估期的PV数据读取
        # 期末现值（期末利率和锁定利率）：有效合同-期末预期-预期未来
        pv_if_end_claims_current = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt')
        pv_if_end_maint_current = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt')
        pv_if_end_claims_locked = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt')
        pv_if_end_maint_locked = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
        
        # 年初现值（上年期末利率）：有效合同-年初预期-预期未来-年初现值（Lcu）
        pv_if_beg_claims_prev_curr = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt')
        pv_if_beg_maint_prev_curr = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt')
        
        # 年初现值（上年加权初始确认利率）：有效合同-年初预期-预期未来-年初现值（Wlk）
        pv_if_beg_claims_prev_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt')
        pv_if_beg_maint_prev_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt')
        
        # 验证必需字段是否存在
        if not pv_data.has_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt'):
            raise ValueError(f"❌ 错误: PV原材料数据中缺少必需字段: Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt（年初现值-上年加权初始确认利率）")
        if not pv_data.has_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt'):
            raise ValueError(f"❌ 错误: PV原材料数据中缺少必需字段: Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt（年初现值-上年加权初始确认利率）")
        
        # 公式：IFIE_{OCI_IF}^{CF} = (Eff.F_{end_curr}^{CF} - Eff.F_{end}^{CF}) - (Eff.F_{beg_prev_curr}^{CF} - Eff.F_{beg_prev}^{CF})
        # 期末利率差异
        end_rate_diff = (pv_if_end_claims_current + pv_if_end_maint_current) - (pv_if_end_claims_locked + pv_if_end_maint_locked)
        # 年初利率差异
        beg_rate_diff = (pv_if_beg_claims_prev_curr + pv_if_beg_maint_prev_curr) - (pv_if_beg_claims_prev_wlk + pv_if_beg_maint_prev_wlk)
        # 完整公式
        ifie_oci_if_cf = end_rate_diff - beg_rate_diff
        
        logger.log_item(
            "年初有效合同_预期现金流 IFIE_OCI",
            "[Sec 14.2] 年初有效合同预期现金流 IFIE（仅包含利率变化影响）",
            f"IFIE_OCI_IF^CF = (Eff.F_{{end_curr}}^{{CF}} - Eff.F_{{end}}^{{CF}}) - (Eff.F_{{beg_prev_curr}}^{{CF}} - Eff.F_{{beg_prev}}^{{CF}})\n其中：\n  Eff.F_{{end_curr}}^{{CF}}：有效合同-期末预期-预期未来-预期现金流-期末现值（期末利率）\n  Eff.F_{{end}}^{{CF}}：有效合同-期末预期-预期未来-预期现金流-期末现值（加权初始确认利率）\n  Eff.F_{{beg_prev_curr}}^{{CF}}：有效合同-年初预期-预期未来-预期现金流-年初现值（上年期末利率，使用Lcu字段）\n  Eff.F_{{beg_prev}}^{{CF}}：有效合同-年初预期-预期未来-预期现金流-年初现值（上年加权初始确认利率，使用Wlk字段）",
            {
                "期末-期末利率-赔付": pv_if_end_claims_current,
                "期末-期末利率-维费": pv_if_end_maint_current,
                "期末-锁定利率-赔付": pv_if_end_claims_locked,
                "期末-锁定利率-维费": pv_if_end_maint_locked,
                "年初-上年期末利率-赔付（Lcu）": pv_if_beg_claims_prev_curr,
                "年初-上年期末利率-维费（Lcu）": pv_if_beg_maint_prev_curr,
                "年初-上年加权初始确认利率-赔付（Wlk）": pv_if_beg_claims_prev_wlk,
                "年初-上年加权初始确认利率-维费（Wlk）": pv_if_beg_maint_prev_wlk,
                "期末利率差异": end_rate_diff,
                "年初利率差异": beg_rate_diff,
                "PV字段（期末-期末利率）": "Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt, Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt",
                "PV字段（期末-锁定利率）": "Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt, Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt",
                "PV字段（年初-Lcu）": "Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt, Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt",
                "PV字段（年初-Wlk）": "Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt, Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt",
                "评估月": eop_month_str
            },
            ifie_oci_if_cf,
            note=f"所有现值均从PV原材料数据读取。仅包含利率变化影响，不包含计息影响。完整公式：({pv_if_end_claims_current} + {pv_if_end_maint_current}) - ({pv_if_end_claims_locked} + {pv_if_end_maint_locked}) - [({pv_if_beg_claims_prev_curr} + {pv_if_beg_maint_prev_curr}) - ({pv_if_beg_claims_prev_wlk} + {pv_if_beg_maint_prev_wlk})] = {end_rate_diff} - {beg_rate_diff} = {ifie_oci_if_cf}"
        )
        
        # [Sec 14.3] 当年新增合同_预期现金流 IFIE_OCI
        # 判断是否为新业务，以确定使用哪个PV字段
        # 优先使用 context.is_new_business（由 experience_adj 设置）
        # 如果没有设置，则根据评估年度和签单年度判断
        if hasattr(context, 'is_new_business') and context.is_new_business is not None:
            is_new_business_oci = bool(context.is_new_business)
        else:
            # 回退判断：签单年 = 评估年 → 新业务，签单年 < 评估年 → 有效合同
            is_new_business_oci = (context.year == getattr(context, 'under_write_date', None).year if hasattr(context, 'under_write_date') else False)
            # 记录警告，说明使用了回退判断
            logger.log_text(f"⚠️  警告: context.is_new_business 未设置（IFIE_OCI部分），使用回退判断: year={context.year}, under_write_date.year={getattr(context, 'under_write_date', None).year if hasattr(context, 'under_write_date') else None}, is_new_business={is_new_business_oci}")
        
        # 重要：此部分仅针对新增合同（NB），有效合同（IF）的IFIE_OCI已在IFIE_OCI_IF^CF中计算
        if is_new_business_oci:
            # 获取期末现值（期末利率和锁定利率）- 从PV原材料数据读取（新增合同字段）
            pv_field_end_claims_current = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt'
            pv_field_end_maint_current = 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt'
            pv_field_end_claims_locked = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt'
            pv_field_end_maint_locked = 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt'
            
            pv_end_claims_current = pv_data.get_field(pv_field_end_claims_current)
            pv_end_maint_current = pv_data.get_field(pv_field_end_maint_current)
            pv_end_claims_locked = pv_data.get_field(pv_field_end_claims_locked)
            pv_end_maint_locked = pv_data.get_field(pv_field_end_maint_locked)
            
            # [Sec 14.3] 当年新增合同_预期现金流 IFIE_OCI
            # 公式：IFIE_{OCI_NB}^{CF} = New.F_{end_curr}^{CF} - New.F_{end}^{CF}
            ifie_oci_nb_cf = (pv_end_claims_current + pv_end_maint_current) - (pv_end_claims_locked + pv_end_maint_locked)
            
            # 记录IFIE_OCI_CF的详细计算
            logger.log_item(
                "新增合同_预期现金流 IFIE_OCI",
                "[Sec 14.3] 新增合同预期现金流 IFIE（仅包含利率变化影响）",
                f"IFIE_OCI_NB^CF = ({describe_field(pv_field_end_claims_current)} + {describe_field(pv_field_end_maint_current)}) - ({describe_field(pv_field_end_claims_locked)} + {describe_field(pv_field_end_maint_locked)})\n其中：\n  期末现值（期末利率）：{describe_field(pv_field_end_claims_current)} + {describe_field(pv_field_end_maint_current)}（来自PV原材料数据）\n  期末现值（锁定利率）：{describe_field(pv_field_end_claims_locked)} + {describe_field(pv_field_end_maint_locked)}（来自PV原材料数据）",
                {
                    f"{describe_field(pv_field_end_claims_current)}": pv_end_claims_current,
                    f"{describe_field(pv_field_end_maint_current)}": pv_end_maint_current,
                    f"{describe_field(pv_field_end_claims_locked)}": pv_end_claims_locked,
                    f"{describe_field(pv_field_end_maint_locked)}": pv_end_maint_locked,
                    "PV字段（期末-期末利率）": f"{pv_field_end_claims_current}, {pv_field_end_maint_current}",
                    "PV字段（期末-锁定利率）": f"{pv_field_end_claims_locked}, {pv_field_end_maint_locked}",
                    "评估月": eop_month_str
                },
                ifie_oci_nb_cf,
                note=f"所有现值均从PV原材料数据读取。仅包含利率变化影响，不包含计息影响。计算过程：({pv_end_claims_current} + {pv_end_maint_current}) - ({pv_end_claims_locked} + {pv_end_maint_locked}) = {ifie_oci_nb_cf}"
            )
        else:
            # 有效合同：IFIE_OCI_NB^CF = 0（有效合同的IFIE_OCI已在IFIE_OCI_IF^CF中计算）
            ifie_oci_nb_cf = Decimal('0')
            logger.log_text(f"ℹ️  信息: 有效合同的IFIE_OCI已在'年初有效合同_预期现金流 IFIE_OCI'中计算，此处IFIE_OCI_NB^CF = 0")
        
        # [Sec 14.4] IFIE_OCI_预期现金流合计
        ifie_oci_cf = ifie_oci_if_cf + ifie_oci_nb_cf
        
        # [Sec 14.5] 年初有效合同_非金融风险调整 IFIE_OCI
        # 公式：IFIE_{OCI_IF}^{RA} = (Eff.F_{end_curr}^{RA} - Eff.F_{end}^{RA}) - (Eff.F_{beg_prev_curr}^{RA} - Eff.F_{beg_prev}^{RA})
        if pv_data is None:
            # 如果当年年初数据不存在（如首年），则年初有效合同RA IFIE_OCI为0
            ifie_oci_if_ra = Decimal('0')
            logger.log_text(f"ℹ️  信息: 找不到当前评估月 {eop_month_str} 的PV原材料数据，年初有效合同_非金融风险调整 IFIE_OCI = 0")
        else:
            # 期末RA现值（期末利率和锁定利率）：有效合同-期末预期-预期未来-使用Rad字段
            ra_if_end_current = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt')
            ra_if_end_locked = pv_data.get_field('Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
            
            # 年初RA现值（上年期末利率）：有效合同-年初预期-预期未来-年初现值（Lcu）-使用Rad字段
            ra_if_beg_prev_curr = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt')
            
            # 年初RA现值（上年加权初始确认利率）：有效合同-年初预期-预期未来-年初现值（Wlk）-使用Rad字段
            ra_if_beg_prev_wlk = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt')
            
            # 验证必需字段是否存在
            if not pv_data.has_field('Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt'):
                raise ValueError(f"❌ 错误: PV原材料数据中缺少必需字段: Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt（年初现值-上年加权初始确认利率）")
            
            # 公式：IFIE_{OCI_IF}^{RA} = (Eff.F_{end_curr}^{RA} - Eff.F_{end}^{RA}) - (Eff.F_{beg_prev_curr}^{RA} - Eff.F_{beg_prev}^{RA})
            # 期末利率差异
            end_ra_rate_diff = ra_if_end_current - ra_if_end_locked
            # 年初利率差异
            beg_ra_rate_diff = ra_if_beg_prev_curr - ra_if_beg_prev_wlk
            # 完整公式
            ifie_oci_if_ra = end_ra_rate_diff - beg_ra_rate_diff
            
            logger.log_item(
                "年初有效合同_非金融风险调整 IFIE_OCI",
                "[Sec 14.5] 年初有效合同非金融风险调整 IFIE（仅包含利率变化影响）",
                f"IFIE_OCI_IF^RA = (Eff.F_{{end_curr}}^{{RA}} - Eff.F_{{end}}^{{RA}}) - (Eff.F_{{beg_prev_curr}}^{{RA}} - Eff.F_{{beg_prev}}^{{RA}})\n其中：\n  Eff.F_{{end_curr}}^{{RA}}：有效合同-期末预期-预期未来-预期非金融风险调整-期末现值（期末利率）- 使用Rad字段\n  Eff.F_{{end}}^{{RA}}：有效合同-期末预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）- 使用Rad字段\n  Eff.F_{{beg_prev_curr}}^{{RA}}：有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年期末利率，使用Lcu字段）\n  Eff.F_{{beg_prev}}^{{RA}}：有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年加权初始确认利率，使用Wlk字段）",
                {
                    "期末-期末利率-RA": ra_if_end_current,
                    "期末-锁定利率-RA": ra_if_end_locked,
                    "年初-上年期末利率-RA（Lcu）": ra_if_beg_prev_curr,
                    "年初-上年加权初始确认利率-RA（Wlk）": ra_if_beg_prev_wlk,
                    "期末利率差异": end_ra_rate_diff,
                    "年初利率差异": beg_ra_rate_diff,
                    "PV字段（期末-期末利率）": "Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt",
                    "PV字段（期末-锁定利率）": "Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt",
                    "PV字段（年初-Lcu）": "Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt",
                    "PV字段（年初-Wlk）": "Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt",
                    "评估月": eop_month_str
                },
                ifie_oci_if_ra,
                note=f"所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）。仅包含利率变化影响，不包含计息影响。完整公式：{ra_if_end_current} - {ra_if_end_locked} - ({ra_if_beg_prev_curr} - {ra_if_beg_prev_wlk}) = {end_ra_rate_diff} - {beg_ra_rate_diff} = {ifie_oci_if_ra}"
            )
        
        # [Sec 14.6] 当年新增合同_非金融风险调整 IFIE_OCI
        # 公式：IFIE_{OCI_NB}^{RA} = New.F_{end_curr}^{RA} - New.F_{end}^{RA}
        # 注意：必须使用Rad字段，不能使用(Cla+Mtn)×RA_Ratio计算
        # 重要：此部分仅针对新增合同（NB），有效合同（IF）的RA IFIE_OCI已在IFIE_OCI_IF^RA中计算
        if is_new_business_oci:
            ra_nb_end_current = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt')
            ra_nb_end_locked = pv_data.get_field('Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
            
            ifie_oci_nb_ra = ra_nb_end_current - ra_nb_end_locked
            
            # 记录IFIE_OCI_RA的详细计算
            logger.log_item(
                "新增合同_非金融风险调整 IFIE_OCI",
                "[Sec 14.6] 新增合同非金融风险调整 IFIE（仅包含利率变化影响）",
                f"IFIE_OCI_NB^RA = (New.F_{{end_curr}}^{{RA}} - New.F_{{end}}^{{RA}})\n其中：\n  New.F_{{end_curr}}^{{RA}}：新增合同-期末预期-预期未来-预期非金融风险调整-期末现值（期末利率）- 使用Rad字段\n  New.F_{{end}}^{{RA}}：新增合同-期末预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）- 使用Rad字段\n所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）",
                {
                    "期末-期末利率-RA": ra_nb_end_current,
                    "期末-锁定利率-RA": ra_nb_end_locked,
                    "PV字段（期末-期末利率）": "Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt",
                    "PV字段（期末-锁定利率）": "Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt",
                    "评估月": eop_month_str
                },
                ifie_oci_nb_ra,
                note=f"所有现值均从PV原材料数据读取，使用Rad字段（不能从(Cla+Mtn)×RA_Ratio计算）。仅包含利率变化影响，不包含计息影响。计算过程：{ra_nb_end_current} - {ra_nb_end_locked} = {ifie_oci_nb_ra}"
            )
        else:
            # 有效合同：IFIE_OCI_NB^RA = 0（有效合同的RA IFIE_OCI已在IFIE_OCI_IF^RA中计算）
            ifie_oci_nb_ra = Decimal('0')
            logger.log_text(f"ℹ️  信息: 有效合同的RA IFIE_OCI已在'年初有效合同_非金融风险调整 IFIE_OCI'中计算，此处IFIE_OCI_NB^RA = 0")
        
        # [Sec 14.7] IFIE_OCI_非金融风险调整合计
        ifie_oci_ra = ifie_oci_if_ra + ifie_oci_nb_ra
        
        # [Sec 14.8] IFIE_OCI合计
        ifie_oci_total = ifie_oci_cf + ifie_oci_ra
        
        # 确定合同类型描述（用于合计部分的日志）
        contract_type_desc_oci = "新增合同" if is_new_business_oci else "有效合同"
        
        logger.log_item(
            "IFIE_OCI合计",
            "[Sec 14.8] IFIE计入其他综合收益部分（仅包含利率变化影响）",
            f"IFIE_OCI_Total = IFIE_OCI_CF + IFIE_OCI_RA\n其中：\n  IFIE_OCI_CF：来自\"年初有效合同_预期现金流 IFIE_OCI\"和\"{'新增合同' if is_new_business_oci else '（无新增合同）'}_预期现金流 IFIE_OCI\"的计算结果\n  IFIE_OCI_RA：来自\"年初有效合同_非金融风险调整 IFIE_OCI\"和\"{'新增合同' if is_new_business_oci else '（无新增合同）'}_非金融风险调整 IFIE_OCI\"的计算结果",
            {
                "IFIE_OCI_CF (来自年初有效合同_预期现金流 IFIE_OCI)": ifie_oci_if_cf,
                f"IFIE_OCI_CF (来自{'新增合同' if is_new_business_oci else '（无新增合同）'}_预期现金流 IFIE_OCI)": ifie_oci_nb_cf,
                "IFIE_OCI_CF合计": ifie_oci_cf,
                "IFIE_OCI_RA (来自年初有效合同_非金融风险调整 IFIE_OCI)": ifie_oci_if_ra,
                f"IFIE_OCI_RA (来自{'新增合同' if is_new_business_oci else '（无新增合同）'}_非金融风险调整 IFIE_OCI)": ifie_oci_nb_ra,
                "IFIE_OCI_RA合计": ifie_oci_ra
            },
            ifie_oci_total,
            note="仅包含利率变化影响，不包含计息影响（计息影响计入 IFIE_P&C）。所有现值均从PV原材料数据读取。"
        )
    else:
        # OCI=0：不拆分，所有IFIE计入损益
        ifie_oci_total = Decimal('0')
        logger.log_item(
            "IFIE_OCI",
            "[Sec 14] OCI选择权=0，不拆分",
            "0 (所有IFIE计入损益)",
            {},
            ifie_oci_total
        )
    
    # 更新上下文
    context.ifie_pl = ifie_pl_total
    context.ifie_oci = ifie_oci_total
    
    # [Sec 13.10-13.13] IFIE_P&C亏损分摊
    # 根据文档（OCI=1拆分模式）：
    # IFIE_P&C_预期现金流_亏损 = IFIE_P&C_预期现金流 / sum(IFIE_P&C_预期现金流 + IFIE_OCI_预期现金流) × LC分摊IFIE_预期现金流
    # IFIE_P&C_非金融风险调整_亏损 = IFIE_P&C_非金融风险调整 / sum(IFIE_P&C_非金融风险调整 + IFIE_OCI_非金融风险调整) × LC分摊IFIE_非金融风险调整
    # 其中：LC分摊IFIE_预期现金流 = (IFIE_P&C_CF + IFIE_OCI_CF) × LC_Ratio
    #      LC分摊IFIE_非金融风险调整 = (IFIE_P&C_RA + IFIE_OCI_RA) × LC_Ratio
    
    if USE_OCI_OPTION:
        # OCI=1（拆分）模式：使用比例公式
        # 计算LC分摊IFIE（来自第7章：csm_lc_measurement.py）
        # LC分摊IFIE_预期现金流 = IF_LC分摊IFIE_CF + NB_LC分摊IFIE_CF
        if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', Decimal('0')) or Decimal('0')
        nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', Decimal('0')) or Decimal('0')
        lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
        # LC分摊IFIE_非金融风险调整 = IF_LC分摊IFIE_RA + NB_LC分摊IFIE_RA
        if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', Decimal('0')) or Decimal('0')
        nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', Decimal('0')) or Decimal('0')
        lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
        
        # [Sec 13.10] IFIE_P&C_预期现金流_亏损
        # IFIE_P&C_CF_LC = IFIE_P&C_CF / (IFIE_P&C_CF + IFIE_OCI_CF) × LC_IFIE_CF
        ifie_cf_total = ifie_cf + ifie_oci_cf
        if ifie_cf_total != 0:
            ifie_pl_cf_lc = ifie_cf / ifie_cf_total * lc_ifie_cf
        else:
            ifie_pl_cf_lc = Decimal('0')
        
        # [Sec 13.12] IFIE_P&C_非金融风险调整_亏损
        # IFIE_P&C_RA_LC = IFIE_P&C_RA / (IFIE_P&C_RA + IFIE_OCI_RA) × LC_IFIE_RA
        ifie_ra_total = ifie_ra + ifie_oci_ra
        if ifie_ra_total != 0:
            ifie_pl_ra_lc = ifie_ra / ifie_ra_total * lc_ifie_ra
        else:
            ifie_pl_ra_lc = Decimal('0')
        
        # IFIE_P&C_LC合计
        context.ifie_pl_lc = ifie_pl_cf_lc + ifie_pl_ra_lc
        context.ifie_pl_non_lc = ifie_pl_total - context.ifie_pl_lc
        
        # 保存CF和RA的亏损分摊，用于后续计算
        context.ifie_pl_cf_lc = ifie_pl_cf_lc
        context.ifie_pl_ra_lc = ifie_pl_ra_lc
        context.ifie_pl_cf_non_lc = ifie_cf - ifie_pl_cf_lc
        context.ifie_pl_ra_non_lc = ifie_ra - ifie_pl_ra_lc
    elif hasattr(context, 'nb_lc_ratio') and context.nb_lc_ratio:
        # OCI=0（不拆分）模式：IFIE_P&C_LC = IFIE_P&C_Total × LC_Ratio
        context.ifie_pl_lc = ifie_pl_total * context.nb_lc_ratio
        context.ifie_pl_non_lc = ifie_pl_total - context.ifie_pl_lc
        # 按比例拆分CF和RA
        if ifie_pl_total != 0:
            ifie_pl_cf_ratio = ifie_cf / ifie_pl_total
            ifie_pl_ra_ratio = ifie_ra / ifie_pl_total
        else:
            ifie_pl_cf_ratio = Decimal('0')
            ifie_pl_ra_ratio = Decimal('0')
        context.ifie_pl_cf_lc = context.ifie_pl_lc * ifie_pl_cf_ratio
        context.ifie_pl_ra_lc = context.ifie_pl_lc * ifie_pl_ra_ratio
        context.ifie_pl_cf_non_lc = ifie_cf - context.ifie_pl_cf_lc
        context.ifie_pl_ra_non_lc = ifie_ra - context.ifie_pl_ra_lc
    else:
        context.ifie_pl_lc = Decimal('0')
        context.ifie_pl_non_lc = ifie_pl_total
        context.ifie_pl_cf_lc = Decimal('0')
        context.ifie_pl_ra_lc = Decimal('0')
        context.ifie_pl_cf_non_lc = ifie_cf
        context.ifie_pl_ra_non_lc = ifie_ra
    
    # [Sec 14.9-14.12] IFIE_OCI亏损分摊
    # 根据文档：IFIE_{OCI_CF_LC} = LC_{IFIE_CF} - IFIE_{CF_LC}
    # 其中：LC_{IFIE_CF} = IFIE_CF中分摊到LC的总数（包括P&L和OCI）= LC分摊IFIE_预期现金流
    #      IFIE_{CF_LC} = IFIE_P&C_CF中分摊到LC的部分（已在上面计算并保存到context.ifie_pl_cf_lc）
    if USE_OCI_OPTION:
        # 计算IFIE_CF和IFIE_RA中分摊到LC的总数（包括P&L和OCI）
        # LC_{IFIE_CF} = IF_LC分摊IFIE_CF + NB_LC分摊IFIE_CF（来自第7章：csm_lc_measurement.py）
        # LC_{IFIE_RA} = IF_LC分摊IFIE_RA + NB_LC分摊IFIE_RA（来自第7章：csm_lc_measurement.py）
        if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', Decimal('0')) or Decimal('0')
        nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', Decimal('0')) or Decimal('0')
        lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
        if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', Decimal('0')) or Decimal('0')
        nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', Decimal('0')) or Decimal('0')
        lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
        
        # 获取IFIE_P&C_CF和IFIE_P&C_RA中分摊到LC的部分（已在上面计算并保存到context）
        ifie_cf_lc = getattr(context, 'ifie_pl_cf_lc', Decimal('0')) or Decimal('0')
        ifie_ra_lc = getattr(context, 'ifie_pl_ra_lc', Decimal('0')) or Decimal('0')
        
        # [Sec 14.9] IFIE_OCI_预期现金流_亏损
        # IFIE_{OCI_CF_LC} = LC_{IFIE_CF} - IFIE_{CF_LC}
        # 根据文档：IFIE_OCI_预期现金流_亏损 = LC分摊IFIE_预期现金流 - IFIE_P&C_预期现金流_亏损
        context.ifie_oci_cf_lc = lc_ifie_cf - ifie_cf_lc
        
        # [Sec 14.10] IFIE_OCI_预期现金流_非亏损
        # IFIE_{OCI_CF_nonLC} = IFIE_{OCI_CF} - IFIE_{OCI_CF_LC}
        context.ifie_oci_cf_non_lc = ifie_oci_cf - context.ifie_oci_cf_lc
        
        # [Sec 14.11] IFIE_OCI_非金融风险调整_亏损
        # IFIE_{OCI_RA_LC} = LC_{IFIE_RA} - IFIE_{RA_LC}
        # 根据文档：IFIE_OCI_非金融风险调整_亏损 = LC分摊IFIE_非金融风险调整 - IFIE_P&C_非金融风险调整_亏损
        context.ifie_oci_ra_lc = lc_ifie_ra - ifie_ra_lc
        
        # [Sec 14.12] IFIE_OCI_非金融风险调整_非亏损
        # IFIE_{OCI_RA_nonLC} = IFIE_{OCI_RA} - IFIE_{OCI_RA_LC}
        context.ifie_oci_ra_non_lc = ifie_oci_ra - context.ifie_oci_ra_lc
        
        # 合计
        context.ifie_oci_lc = context.ifie_oci_cf_lc + context.ifie_oci_ra_lc
        context.ifie_oci_non_lc = context.ifie_oci_cf_non_lc + context.ifie_oci_ra_non_lc
    else:
        # OCI=0：不拆分，所有IFIE计入损益，IFIE_OCI_亏损为0
        context.ifie_oci_cf_lc = Decimal('0')
        context.ifie_oci_cf_non_lc = Decimal('0')
        context.ifie_oci_ra_lc = Decimal('0')
        context.ifie_oci_ra_non_lc = Decimal('0')
        context.ifie_oci_lc = Decimal('0')
        context.ifie_oci_non_lc = Decimal('0')
    
    # 获取LC Ratio的来源说明
    lc_ratio_source = "来自Part 5（被CSM/LC吸收的变化）- LC分摊比例"
    if hasattr(context, 'nb_lc_ratio') and context.nb_lc_ratio:
        lc_ratio_value = context.nb_lc_ratio
    else:
        lc_ratio_value = Decimal('0')
        lc_ratio_source = "0（无亏损成分）"
    
    # [Sec 13.10-13.13] IFIE_P&C亏损分摊详细记录
    if USE_OCI_OPTION:
        # 计算LC分摊IFIE（用于日志，来自第7章：csm_lc_measurement.py）
        if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', Decimal('0')) or Decimal('0')
        nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', Decimal('0')) or Decimal('0')
        lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
        if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', Decimal('0')) or Decimal('0')
        nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', Decimal('0')) or Decimal('0')
        lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
        
        logger.log_item(
            "IFIE_预期现金流_亏损",
            "[Sec 13.10] IFIE_预期现金流_亏损",
            f"IFIE_P&C_CF_LC = IFIE_预期现金流 / (IFIE_预期现金流 + IFIE_OCI_预期现金流) × LC_IFIE_CF\n其中：\n  LC_IFIE_CF：来自第7章（csm_lc_measurement.py）= IF_LC分摊IFIE_CF + NB_LC分摊IFIE_CF",
            {
                "IFIE_预期现金流": ifie_cf,
                "IFIE_OCI_预期现金流": ifie_oci_cf,
                "IFIE_CF合计": ifie_cf + ifie_oci_cf,
                "IF_LC分摊IFIE_CF (来自csm_lc_measurement.py)": if_lc_ifie_cf,
                "NB_LC分摊IFIE_CF (来自csm_lc_measurement.py)": nb_lc_ifie_cf,
                "LC_IFIE_CF (合计)": lc_ifie_cf,
                "IFIE_预期现金流_亏损": context.ifie_pl_cf_lc
            },
            context.ifie_pl_cf_lc,
            note=f"计算过程：IFIE_P&C_CF_LC = {ifie_cf} / ({ifie_cf} + {ifie_oci_cf}) × {lc_ifie_cf} = {context.ifie_pl_cf_lc}。LC_IFIE_CF来自第7章（csm_lc_measurement.py）的计算结果"
        )
        
        logger.log_item(
            "IFIE_预期现金流_非亏损",
            "[Sec 13.11] IFIE_预期现金流_非亏损",
            f"IFIE_P&C_CF_nonLC = IFIE_预期现金流 - IFIE_预期现金流_亏损",
            {
                "IFIE_预期现金流": ifie_cf,
                "IFIE_预期现金流_亏损": context.ifie_pl_cf_lc,
                "IFIE_预期现金流_非亏损": context.ifie_pl_cf_non_lc
            },
            context.ifie_pl_cf_non_lc,
            note=f"计算过程：IFIE_P&C_CF_nonLC = {ifie_cf} - {context.ifie_pl_cf_lc} = {context.ifie_pl_cf_non_lc}"
        )
        
        logger.log_item(
            "IFIE_非金融风险调整_亏损",
            "[Sec 13.12] IFIE_非金融风险调整_亏损",
            f"IFIE_P&C_RA_LC = IFIE_非金融风险调整 / (IFIE_非金融风险调整 + IFIE_OCI_非金融风险调整) × LC_IFIE_RA\n其中：\n  LC_IFIE_RA：来自第7章（csm_lc_measurement.py）= IF_LC分摊IFIE_RA + NB_LC分摊IFIE_RA",
            {
                "IFIE_非金融风险调整": ifie_ra,
                "IFIE_OCI_非金融风险调整": ifie_oci_ra,
                "IFIE_RA合计": ifie_ra + ifie_oci_ra,
                "IF_LC分摊IFIE_RA (来自csm_lc_measurement.py)": if_lc_ifie_ra,
                "NB_LC分摊IFIE_RA (来自csm_lc_measurement.py)": nb_lc_ifie_ra,
                "LC_IFIE_RA (合计)": lc_ifie_ra,
                "IFIE_非金融风险调整_亏损": context.ifie_pl_ra_lc
            },
            context.ifie_pl_ra_lc,
            note=f"计算过程：IFIE_P&C_RA_LC = {ifie_ra} / ({ifie_ra} + {ifie_oci_ra}) × {lc_ifie_ra} = {context.ifie_pl_ra_lc}。LC_IFIE_RA来自第7章（csm_lc_measurement.py）的计算结果"
        )
        
        logger.log_item(
            "IFIE_非金融风险调整_非亏损",
            "[Sec 13.13] IFIE_非金融风险调整_非亏损",
            f"IFIE_P&C_RA_nonLC = IFIE_非金融风险调整 - IFIE_非金融风险调整_亏损",
            {
                "IFIE_非金融风险调整": ifie_ra,
                "IFIE_非金融风险调整_亏损": context.ifie_pl_ra_lc,
                "IFIE_非金融风险调整_非亏损": context.ifie_pl_ra_non_lc
            },
            context.ifie_pl_ra_non_lc,
            note=f"计算过程：IFIE_P&C_RA_nonLC = {ifie_ra} - {context.ifie_pl_ra_lc} = {context.ifie_pl_ra_non_lc}"
        )
        
        logger.log_item(
            "IFIE_P&C_亏损分摊合计",
            "[Sec 13.10-13.13] IFIE_P&C 分摊到亏损成分和非亏损成分合计",
            f"IFIE_P&C_LC = IFIE_P&C_CF_LC + IFIE_P&C_RA_LC\nIFIE_P&C_Non-LC = IFIE_P&C_CF_nonLC + IFIE_P&C_RA_nonLC",
            {
                "IFIE_P&C_CF_LC": context.ifie_pl_cf_lc,
                "IFIE_P&C_RA_LC": context.ifie_pl_ra_lc,
                "IFIE_P&C_LC合计": context.ifie_pl_lc,
                "IFIE_P&C_CF_nonLC": context.ifie_pl_cf_non_lc,
                "IFIE_P&C_RA_nonLC": context.ifie_pl_ra_non_lc,
                "IFIE_P&C_Non-LC合计": context.ifie_pl_non_lc
            },
            context.ifie_pl_non_lc,
            note=f"计算过程：IFIE_P&C_LC = {context.ifie_pl_cf_lc} + {context.ifie_pl_ra_lc} = {context.ifie_pl_lc}, IFIE_P&C_Non-LC = {context.ifie_pl_cf_non_lc} + {context.ifie_pl_ra_non_lc} = {context.ifie_pl_non_lc}"
        )
    else:
        logger.log_item(
            "IFIE_P&C_亏损分摊",
            "[Sec 13.10-13.13] IFIE_P&C 分摊到亏损成分和非亏损成分",
            f"IFIE_P&C_LC = IFIE_P&C_Total × LC_Ratio（OCI选择权=0或不拆分模式）\nIFIE_P&C_Non-LC = IFIE_P&C_Total - IFIE_P&C_LC\n其中：\n  IFIE_P&C_Total：来自\"IFIE_P&C合计\"的计算结果\n  LC_Ratio：{lc_ratio_source}",
            {
                "IFIE_P&C_Total (来自IFIE_P&C合计)": ifie_pl_total,
                f"LC_Ratio ({lc_ratio_source})": lc_ratio_value,
                "IFIE_P&C_LC": context.ifie_pl_lc,
                "IFIE_P&C_Non-LC": context.ifie_pl_non_lc
            },
            context.ifie_pl_non_lc,
            note=f"计算过程：IFIE_P&C_LC = {ifie_pl_total} × {lc_ratio_value} = {context.ifie_pl_lc}, IFIE_P&C_Non-LC = {ifie_pl_total} - {context.ifie_pl_lc} = {context.ifie_pl_non_lc}"
        )
    
    # [Sec 14.9-14.12] IFIE_OCI亏损分摊详细记录
    if USE_OCI_OPTION:
        # 计算LC_{IFIE_CF}和LC_{IFIE_RA}（用于日志，来自第7章：csm_lc_measurement.py）
        if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', Decimal('0')) or Decimal('0')
        nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', Decimal('0')) or Decimal('0')
        lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
        if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', Decimal('0')) or Decimal('0')
        nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', Decimal('0')) or Decimal('0')
        lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
        
        # 获取IFIE_P&C_CF和IFIE_P&C_RA中分摊到LC的部分（已在上面计算并保存到context）
        ifie_cf_lc = getattr(context, 'ifie_pl_cf_lc', Decimal('0')) or Decimal('0')
        ifie_ra_lc = getattr(context, 'ifie_pl_ra_lc', Decimal('0')) or Decimal('0')
        
        logger.log_item(
            "IFIE_OCI_预期现金流_亏损",
            "[Sec 14.9] IFIE_OCI_预期现金流_亏损",
            f"IFIE_{{OCI_CF_LC}} = LC_{{IFIE_CF}} - IFIE_{{CF_LC}}\n其中：\n  LC_{{IFIE_CF}}：IFIE_CF中分摊到LC的总数（包括P&L和OCI）= IF_LC分摊IFIE_CF + NB_LC分摊IFIE_CF（来自第7章：csm_lc_measurement.py）\n  IFIE_{{CF_LC}}：IFIE_P&C_CF中分摊到LC的部分（来自第13.10节）",
            {
                "IFIE_P&C_CF": ifie_cf,
                "IFIE_OCI_CF": ifie_oci_cf,
                "IFIE_CF合计": ifie_cf + ifie_oci_cf,
                "IF_LC分摊IFIE_CF (来自csm_lc_measurement.py)": if_lc_ifie_cf,
                "NB_LC分摊IFIE_CF (来自csm_lc_measurement.py)": nb_lc_ifie_cf,
                "LC_{IFIE_CF} (合计)": lc_ifie_cf,
                "IFIE_{CF_LC} (来自IFIE_P&C_CF_LC)": ifie_cf_lc,
                "IFIE_OCI_CF_LC": context.ifie_oci_cf_lc
            },
            context.ifie_oci_cf_lc,
            note=f"计算过程：LC_{{IFIE_CF}} = {if_lc_ifie_cf} + {nb_lc_ifie_cf} = {lc_ifie_cf}（来自第7章：csm_lc_measurement.py）, IFIE_{{CF_LC}} = {ifie_cf_lc}, IFIE_OCI_CF_LC = {lc_ifie_cf} - {ifie_cf_lc} = {context.ifie_oci_cf_lc}"
        )
        
        logger.log_item(
            "IFIE_OCI_预期现金流_非亏损",
            "[Sec 14.10] IFIE_OCI_预期现金流_非亏损",
            f"IFIE_{{OCI_CF_nonLC}} = IFIE_{{OCI_CF}} - IFIE_{{OCI_CF_LC}}",
            {
                "IFIE_OCI_CF": ifie_oci_cf,
                "IFIE_OCI_CF_LC": context.ifie_oci_cf_lc,
                "IFIE_OCI_CF_nonLC": context.ifie_oci_cf_non_lc
            },
            context.ifie_oci_cf_non_lc,
            note=f"计算过程：IFIE_OCI_CF_nonLC = {ifie_oci_cf} - {context.ifie_oci_cf_lc} = {context.ifie_oci_cf_non_lc}"
        )
        
        logger.log_item(
            "IFIE_OCI_非金融风险调整_亏损",
            "[Sec 14.11] IFIE_OCI_非金融风险调整_亏损",
            f"IFIE_{{OCI_RA_LC}} = LC_{{IFIE_RA}} - IFIE_{{RA_LC}}\n其中：\n  LC_{{IFIE_RA}}：IFIE_RA中分摊到LC的总数（包括P&L和OCI）= IF_LC分摊IFIE_RA + NB_LC分摊IFIE_RA（来自第7章：csm_lc_measurement.py）\n  IFIE_{{RA_LC}}：IFIE_P&C_RA中分摊到LC的部分（来自第13.12节）",
            {
                "IFIE_P&C_RA": ifie_ra,
                "IFIE_OCI_RA": ifie_oci_ra,
                "IFIE_RA合计": ifie_ra + ifie_oci_ra,
                "IF_LC分摊IFIE_RA (来自csm_lc_measurement.py)": if_lc_ifie_ra,
                "NB_LC分摊IFIE_RA (来自csm_lc_measurement.py)": nb_lc_ifie_ra,
                "LC_{IFIE_RA} (合计)": lc_ifie_ra,
                "IFIE_{RA_LC} (来自IFIE_P&C_RA_LC)": ifie_ra_lc,
                "IFIE_OCI_RA_LC": context.ifie_oci_ra_lc
            },
            context.ifie_oci_ra_lc,
            note=f"计算过程：LC_{{IFIE_RA}} = {if_lc_ifie_ra} + {nb_lc_ifie_ra} = {lc_ifie_ra}（来自第7章：csm_lc_measurement.py）, IFIE_{{RA_LC}} = {ifie_ra_lc}, IFIE_OCI_RA_LC = {lc_ifie_ra} - {ifie_ra_lc} = {context.ifie_oci_ra_lc}"
        )
        
        logger.log_item(
            "IFIE_OCI_非金融风险调整_非亏损",
            "[Sec 14.12] IFIE_OCI_非金融风险调整_非亏损",
            f"IFIE_{{OCI_RA_nonLC}} = IFIE_{{OCI_RA}} - IFIE_{{OCI_RA_LC}}",
            {
                "IFIE_OCI_RA": ifie_oci_ra,
                "IFIE_OCI_RA_LC": context.ifie_oci_ra_lc,
                "IFIE_OCI_RA_nonLC": context.ifie_oci_ra_non_lc
            },
            context.ifie_oci_ra_non_lc,
            note=f"计算过程：IFIE_OCI_RA_nonLC = {ifie_oci_ra} - {context.ifie_oci_ra_lc} = {context.ifie_oci_ra_non_lc}"
        )
        
        logger.log_item(
            "IFIE_OCI_亏损分摊合计",
            "[Sec 14.9-14.12] IFIE_OCI 分摊到亏损成分和非亏损成分合计",
            f"IFIE_OCI_LC = IFIE_OCI_CF_LC + IFIE_OCI_RA_LC\nIFIE_OCI_Non-LC = IFIE_OCI_CF_nonLC + IFIE_OCI_RA_nonLC",
            {
                "IFIE_OCI_CF_LC": context.ifie_oci_cf_lc,
                "IFIE_OCI_RA_LC": context.ifie_oci_ra_lc,
                "IFIE_OCI_LC合计": context.ifie_oci_lc,
                "IFIE_OCI_CF_nonLC": context.ifie_oci_cf_non_lc,
                "IFIE_OCI_RA_nonLC": context.ifie_oci_ra_non_lc,
                "IFIE_OCI_Non-LC合计": context.ifie_oci_non_lc
            },
            context.ifie_oci_non_lc,
            note=f"计算过程：IFIE_OCI_LC = {context.ifie_oci_cf_lc} + {context.ifie_oci_ra_lc} = {context.ifie_oci_lc}, IFIE_OCI_Non-LC = {context.ifie_oci_cf_non_lc} + {context.ifie_oci_ra_non_lc} = {context.ifie_oci_non_lc}"
        )
    else:
        logger.log_item(
            "IFIE_OCI_亏损分摊",
            "[Sec 14.9-14.12] IFIE_OCI 分摊到亏损成分和非亏损成分",
            f"IFIE_OCI_LC = 0（OCI选择权=0，不拆分）\nIFIE_OCI_Non-LC = 0（所有IFIE计入损益）",
            {
                "IFIE_OCI_Total (来自IFIE_OCI合计)": ifie_oci_total,
                "IFIE_OCI_LC": context.ifie_oci_lc,
                "IFIE_OCI_Non-LC": context.ifie_oci_non_lc
            },
            context.ifie_oci_non_lc,
            note="OCI选择权=0，不拆分，所有IFIE计入损益，IFIE_OCI_亏损为0"
        )
