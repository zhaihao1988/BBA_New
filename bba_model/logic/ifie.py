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
from bba_model.config import USE_OCI_OPTION
from bba_model.utils.math_tools import calculate_future_pv_with_rates
from bba_model.models import Assumptions, CohortState
from bba_model.logic.rates_manager import get_locked_rate_for_discounting


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
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        ra_ratio = assumptions.ra_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from bba_model.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_RA
        loss_ratio = RATIO_CLAIM
        indirect_claims_expense_ratio = Decimal('0')
        maintenance_expense_ratio = RATIO_MAINT_EXP
        ra_ratio = RATIO_RA
    
    # [Sec 13.1] 获取加权初始确认利率（锁定利率）
    if cohort_state:
        locked_rate = cohort_state.weighted_locked_rate
    else:
        # 兼容旧代码：使用即期利率
        from bba_model.logic.rates_manager import calculate_spot_rate
        locked_rate = calculate_spot_rate(context.rates_df)
    
    logger.log_item(
        "加权初始确认利率（锁定利率）",
        "[Sec 13.1] 用于IFIE_P&C计算的锁定利率",
        "CohortState.weighted_locked_rate",
        {"Locked Rate": locked_rate},
        locked_rate,
        note="IFIE_P&C仅包含计息影响，使用加权初始确认利率（锁定利率）"
    )
    
    # [Sec 13.2] 年初有效合同_预期现金流 IFIE_P&C
    # 仅包含计息影响部分（使用加权初始确认利率）
    # 简化实现：假设为新增合同，无期初余额
    ifie_if_cf = Decimal('0')
    
    # [Sec 13.3] 当年新增合同_预期现金流 IFIE_P&C
    # 公式：期末现值（预期未来+预期当期，锁定利率）- 初始现值（预期未来+预期当期，当月初始利率）
    # 注意：必须减去"预期当期"的初始现值，否则结果会包含本金
    
    # 期末现值（使用锁定利率）
    pv_end_claims_locked = calculate_future_pv_with_rates(
        context.actual_premium,
        loss_ratio * (Decimal('1') + indirect_claims_expense_ratio),
        context.total_months,
        context.months_passed,
        context.rates_df,
        rate_offset=0  # 使用锁定利率（简化：假设锁定利率对应rate_offset=0）
    )
    pv_end_maint_locked = calculate_future_pv_with_rates(
        context.actual_premium,
        maintenance_expense_ratio,
        context.total_months,
        context.months_passed,
        context.rates_df,
        rate_offset=0
    )
    
    # 初始现值（使用当月初始利率，即即期利率）
    pv_init_claims_spot = context.init_fut_claim
    pv_init_maint_spot = context.init_fut_maint
    
    # IFIE_P&C = 期末现值（锁定利率）- 初始现值（即期利率）
    ifie_nb_cf = (pv_end_claims_locked + pv_end_maint_locked) - (pv_init_claims_spot + pv_init_maint_spot)
    
    logger.log_item(
        "当年新增合同_预期现金流 IFIE_P&C",
        "[Sec 13.3] 当年新增合同预期现金流 IFIE（仅包含计息影响）",
        "IFIE_NB^CF = (New.F_end^CF + New.C_init_end^CF) - (New.F_init_month^CF + New.C_init_month^CF)",
        {
            "PV_end_Claims (Locked)": pv_end_claims_locked,
            "PV_end_Maint (Locked)": pv_end_maint_locked,
            "PV_init_Claims (Spot)": pv_init_claims_spot,
            "PV_init_Maint (Spot)": pv_init_maint_spot
        },
        ifie_nb_cf,
        note="必须减去'预期当期'的初始现值，否则结果会包含本金。仅包含计息影响部分（使用锁定利率），不包含利率变化影响"
    )
    
    # [Sec 13.4] IFIE_预期现金流
    ifie_cf = ifie_if_cf + ifie_nb_cf
    
    # [Sec 13.5-13.6] 非金融风险调整 IFIE_P&C（类似逻辑）
    ifie_if_ra = Decimal('0')
    ifie_nb_ra = (pv_end_claims_locked + pv_end_maint_locked) * ra_ratio - context.init_ra
    
    ifie_ra = ifie_if_ra + ifie_nb_ra
    
    # [Sec 13.8] IFIE_CSM
    ifie_csm = -context.nb_interest_csm  # CSM计息的负值
    
    # [Sec 13.9] IFIE_P&C 合计
    ifie_pl_total = ifie_cf + ifie_ra + ifie_csm
    
    logger.log_item(
        "IFIE_P&C合计",
        "[Sec 13.9] IFIE计入损益部分（仅包含计息影响）",
        "IFIE_Total = IFIE_CF + IFIE_RA + IFIE_CSM",
        {
            "IFIE_CF": ifie_cf,
            "IFIE_RA": ifie_ra,
            "IFIE_CSM": ifie_csm
        },
        ifie_pl_total,
        note="所有计算均使用加权初始确认利率（锁定利率），仅包含计息影响"
    )
    
    # [Sec 14] IFIE_OCI（计入其他综合收益）
    # 仅包含利率变化影响，不包含计息影响
    
    if USE_OCI_OPTION:
        # [Sec 14.2-14.3] 年初有效合同和新增合同的利率变化影响
        # 期末现值（期末利率）- 期末现值（锁定利率）
        pv_end_claims_current = context.pv_eop_claims_current if hasattr(context, 'pv_eop_claims_current') else pv_end_claims_locked
        pv_end_maint_current = context.pv_eop_maint_current if hasattr(context, 'pv_eop_maint_current') else pv_end_maint_locked
        
        # 利率变化影响 = 期末现值（期末利率）- 期末现值（锁定利率）
        ifie_oci_if_cf = Decimal('0')  # 简化：假设无期初余额
        ifie_oci_nb_cf = (pv_end_claims_current + pv_end_maint_current) - (pv_end_claims_locked + pv_end_maint_locked)
        
        ifie_oci_cf = ifie_oci_if_cf + ifie_oci_nb_cf
        
        # [Sec 14.5-14.6] 非金融风险调整的利率变化影响
        ifie_oci_if_ra = Decimal('0')
        ra_end_current = (pv_end_claims_current + pv_end_maint_current) * ra_ratio
        ra_end_locked = (pv_end_claims_locked + pv_end_maint_locked) * ra_ratio
        ifie_oci_nb_ra = ra_end_current - ra_end_locked
        
        ifie_oci_ra = ifie_oci_if_ra + ifie_oci_nb_ra
        
        # [Sec 14.8] IFIE_OCI合计
        ifie_oci_total = ifie_oci_cf + ifie_oci_ra
        
        logger.log_item(
            "IFIE_OCI合计",
            "[Sec 14.8] IFIE计入其他综合收益部分（仅包含利率变化影响）",
            "IFIE_OCI_Total = IFIE_OCI_CF + IFIE_OCI_RA",
            {
                "IFIE_OCI_CF": ifie_oci_cf,
                "IFIE_OCI_RA": ifie_oci_ra
            },
            ifie_oci_total,
            note="仅包含利率变化影响，不包含计息影响（计息影响计入 IFIE_P&C）"
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
    
    # [Sec 13.10-13.13] 亏损分摊
    # 简化实现：假设按比例分摊
    if hasattr(context, 'nb_lc_ratio') and context.nb_lc_ratio:
        context.ifie_pl_lc = ifie_pl_total * context.nb_lc_ratio
        context.ifie_pl_non_lc = ifie_pl_total - context.ifie_pl_lc
        
        context.ifie_oci_lc = ifie_oci_total * context.nb_lc_ratio
        context.ifie_oci_non_lc = ifie_oci_total - context.ifie_oci_lc
    else:
        context.ifie_pl_lc = Decimal('0')
        context.ifie_pl_non_lc = ifie_pl_total
        context.ifie_oci_lc = Decimal('0')
        context.ifie_oci_non_lc = ifie_oci_total
    
    logger.log_item(
        "IFIE_P&C_亏损分摊",
        "[Sec 13.10-13.13] IFIE_P&C 分摊到亏损成分和非亏损成分",
        "按比例分摊",
        {
            "IFIE_P&C_Total": ifie_pl_total,
            "IFIE_P&C_LC": context.ifie_pl_lc,
            "IFIE_P&C_Non-LC": context.ifie_pl_non_lc
        },
        context.ifie_pl_non_lc
    )
    
    logger.log_item(
        "IFIE_OCI_亏损分摊",
        "[Sec 14.9-14.12] IFIE_OCI 分摊到亏损成分和非亏损成分",
        "按比例分摊",
        {
            "IFIE_OCI_Total": ifie_oci_total,
            "IFIE_OCI_LC": context.ifie_oci_lc,
            "IFIE_OCI_Non-LC": context.ifie_oci_non_lc
        },
        context.ifie_oci_non_lc
    )
