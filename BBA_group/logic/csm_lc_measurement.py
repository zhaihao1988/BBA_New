"""
CSM/LC计量模块 (CSM/LC Measurement)

对应文档：
- 第6节：CSM计息
- 第7节：LC分摊IFIE
- 第8.5.5节：合同组CSM/LC判断
- 第8.2节：CSM计量（摊销）
- LC计量（LC变化计算）

核心功能：
1. CSM计息：使用加权初始确认利率（Wlk）进行CSM计息
2. LC分摊IFIE：计算LC的IFIE分摊（IF和NB）
3. 合同组CSM/LC判断：确定合同组最终状态（盈利或亏损）
4. CSM计量：CSM摊销计算
5. LC计量：LC变化计算

注意：
- 使用统一字段逻辑：CSM/LC使用一个字段，>=0走CSM逻辑，<0走LC逻辑
- 所有现值必须从PV原材料数据读取
"""

from decimal import Decimal
from typing import List, Optional, Any, Tuple
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from BBA_group.models import CohortState, PolicyState, Assumptions
from BBA_group.utils.pv_source_loader import ensure_pv_source_data
from BBA_group.utils.math_tools import get_accretion_rate_factor
from BBA_group.assumptions import get_discount_factors
from BBA_group.logic.coverage_units import calculate_csm_amortization_ratio

DECIMAL_ZERO = Decimal('0')


def _format_for_log(value: Any) -> str:
    """统一格式化输出"""
    if isinstance(value, Decimal):
        if value == 0:
            return "0.00"
        precision = 6 if (value > -Decimal('10') and value < Decimal('10')) else 2
        return f"{value:,.{precision}f}"
    return str(value)


def _log_lc_measurement_cf_details(
    logger,
    bop_lc_cf,
    nb_initial_lc_total,
    nb_initial_lc_cf,
    pv_data,
    if_lc_ifie_cf,
    nb_lc_ifie_cf,
    lc_ifie_cf,
    pv_if_cur_claims,
    pv_if_cur_maint,
    pv_nb_cur_claims,
    pv_nb_cur_maint,
    lc_allocation_ratio_total,
    allocated_lc_cf,
    lc_balance_to_adjust_total,
    bop_lc_total,
    nb_initial_lc_total_for_sum,
    lc_ifie_total,
    allocated_lc_total,
    delta_csm_lc,
    delta_cf_total,
    allocated_lc_exp_adj_total,
    allocated_lc_exp_adj_cf,
    lc_balance_to_adjust_cf,
    csm_amort_ratio,
    lc_adjust_cf,
    end_lc_cf,
):
    """记录LC计量_预期现金流的详细计算过程"""

    def fmt(v):
        return _format_for_log(v)

    details = []
    details.append("**详细计算过程**:\n")

    # 1. 年初LC余额_预期现金流
    details.append("#### 1. 年初LC余额_预期现金流")
    details.append("- **来源**: 直接取数（简化处理，假设年初LC余额全部为预期现金流）")
    details.append(f"- **数值**: {fmt(bop_lc_cf)}\n")

    # 2. 当年新增LC_预期现金流
    details.append("#### 2. 当年新增LC_预期现金流")
    details.append("- **公式**: `当年新增LC_预期现金流 = 当年新增LC_合计 × (NB_预期赔付现金流 + NB_预期维持费用现金流) / (NB_预期赔付现金流 + NB_预期维持费用现金流 + NB_预期非金融风险调整)`")
    details.append("- **计算步骤**:")
    details.append(f"  - 当年新增LC_合计 = {fmt(nb_initial_lc_total)} (来源：NB_新增LC)")

    if pv_data is not None:
        pv_nb_init_claims = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt', DECIMAL_ZERO)
        pv_nb_init_maint = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt', DECIMAL_ZERO)
        pv_nb_init_ra = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt', DECIMAL_ZERO)
        denom_nb_init = pv_nb_init_claims + pv_nb_init_maint + pv_nb_init_ra
        numerator = pv_nb_init_claims + pv_nb_init_maint

        details.append(f"  - NB_预期赔付现金流（初始确认现值） = {fmt(pv_nb_init_claims)} (来源：Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt)")
        details.append(f"  - NB_预期维持费用现金流（初始确认现值） = {fmt(pv_nb_init_maint)} (来源：Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt)")
        details.append(f"  - NB_预期非金融风险调整（初始确认现值） = {fmt(pv_nb_init_ra)} (来源：Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt)")
        details.append(f"  - 分子 = {fmt(pv_nb_init_claims)} + {fmt(pv_nb_init_maint)} = {fmt(numerator)}")
        details.append(f"  - 分母 = {fmt(pv_nb_init_claims)} + {fmt(pv_nb_init_maint)} + {fmt(pv_nb_init_ra)} = {fmt(denom_nb_init)}")
        if denom_nb_init > 0:
            ratio = numerator / denom_nb_init
            details.append(f"  - 比例 = {fmt(numerator)} / {fmt(denom_nb_init)} = {fmt(ratio)}")
            details.append(f"  - 当年新增LC_预期现金流 = {fmt(nb_initial_lc_total)} × {fmt(ratio)} = {fmt(nb_initial_lc_cf)}")
        else:
            details.append("  - 分母为0，当年新增LC_预期现金流 = 0.00")
    else:
        details.append("  - PV数据为空，当年新增LC_预期现金流 = 0.00")
    details.append(f"- **结果**: `{fmt(nb_initial_lc_cf)}`\n")

    # 3. LC分摊IFIE_预期现金流
    details.append("#### 3. LC分摊IFIE_预期现金流")
    details.append("- **公式**: `LC分摊IFIE_预期现金流 = IF_LC分摊IFIE_赔付与费用 + NB_LC分摊IFIE_赔付与费用`")
    details.append("- **计算步骤**:")
    details.append(f"  - IF_LC分摊IFIE_赔付与费用 = {fmt(if_lc_ifie_cf)} (来源：context.if_lc_ifie_cf)")
    details.append(f"  - NB_LC分摊IFIE_赔付与费用 = {fmt(nb_lc_ifie_cf)} (来源：context.nb_lc_ifie_cf)")
    details.append(f"  - LC分摊IFIE_预期现金流 = {fmt(if_lc_ifie_cf)} + {fmt(nb_lc_ifie_cf)} = {fmt(lc_ifie_cf)}")
    details.append(f"- **结果**: `{fmt(lc_ifie_cf)}`\n")

    # 4. 分摊的LC_预期现金流
    details.append("#### 4. 分摊的LC_预期现金流")
    details.append("- **公式**: `分摊的LC_预期现金流 = (IF_预期当期赔付 + IF_预期当期维费 + NB_预期当期赔付 + NB_预期当期维费) × LC分摊比例_合计`")
    details.append("- **计算步骤**:")
    details.append(f"  - IF_预期当期赔付现金流（期末现值Wlk） = {fmt(pv_if_cur_claims)} (来源：Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt)")
    details.append(f"  - IF_预期当期维持费用现金流（期末现值Wlk） = {fmt(pv_if_cur_maint)} (来源：Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt)")
    details.append(f"  - NB_预期当期赔付现金流（期末现值Wlk） = {fmt(pv_nb_cur_claims)} (来源：Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt)")
    details.append(f"  - NB_预期当期维持费用现金流（期末现值Wlk） = {fmt(pv_nb_cur_maint)} (来源：Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt)")
    cur_cf_total = pv_if_cur_claims + pv_if_cur_maint + pv_nb_cur_claims + pv_nb_cur_maint
    details.append(f"  - 预期当期现金流合计 = {fmt(cur_cf_total)}")
    details.append(f"  - LC分摊比例_合计 = {fmt(lc_allocation_ratio_total)} (来源：LC计量_合计部分)")
    details.append(f"  - 分摊的LC_预期现金流 = {fmt(cur_cf_total)} × {fmt(lc_allocation_ratio_total)} = {fmt(allocated_lc_cf)}")
    details.append(f"- **结果**: `{fmt(allocated_lc_cf)}`")
    details.append("- **说明**: 正数表示减少LC亏损（LC余额绝对值减少），因为当现金流释放时，亏损应该被摊销\n")

    # 5. 被LC吸收的变化_预期现金流
    details.append("#### 5. 被LC吸收的变化_预期现金流")
    details.append("- **公式**: `IF(待调整LC余额_合计=0, -SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC), 被LC吸收的变化_合计×IFERROR(预期现金流变化合计/被CSM/LC吸收的变化合计,0))`")
    details.append("- **判断条件**:")
    details.append(f"  - 待调整LC余额_合计 = {fmt(lc_balance_to_adjust_total)} (来源：LC计量_合计部分)")
    if lc_balance_to_adjust_total == 0:
        details.append("  - 条件判断：待调整LC余额_合计 = 0，走分支1")
        details.append("- **计算步骤（分支1）**:")
        sum_before_adj = bop_lc_total + nb_initial_lc_total_for_sum + lc_ifie_total + allocated_lc_total
        details.append(f"  - SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC) = {fmt(sum_before_adj)}")
        details.append(f"  - 被LC吸收的变化_预期现金流 = -{fmt(sum_before_adj)} = {fmt(allocated_lc_exp_adj_cf)}")
    else:
        details.append("  - 条件判断：待调整LC余额_合计 ≠ 0，走分支2")
        details.append("- **计算步骤（分支2）**:")
        details.append(f"  - 被LC吸收的变化_合计 = {fmt(allocated_lc_exp_adj_total)} (来源：LC计量_合计部分)")
        details.append(f"  - 预期现金流变化合计 = {fmt(delta_cf_total)} (来源：context.delta_cf_total)")
        details.append(f"  - 被CSM/LC吸收的变化合计 = {fmt(delta_csm_lc)} (来源：context.exp_adj_csm_impact)")
        if delta_csm_lc != 0:
            ratio_cf = delta_cf_total / delta_csm_lc
            details.append(f"  - 比例 = {fmt(ratio_cf)}")
            details.append(f"  - 被LC吸收的变化_预期现金流 = {fmt(allocated_lc_exp_adj_total)} × {fmt(ratio_cf)} = {fmt(allocated_lc_exp_adj_cf)}")
        else:
            details.append("  - 被CSM/LC吸收的变化合计为0，被LC吸收的变化_预期现金流 = 0.00")
    details.append(f"- **结果**: `{fmt(allocated_lc_exp_adj_cf)}`\n")

    # 6. 待调整LC余额_预期现金流
    details.append("#### 6. 待调整LC余额_预期现金流")
    details.append("- **公式**: `待调整LC余额_预期现金流 = 年初LC余额_预期现金流 + 当年新增LC_预期现金流 + LC分摊IFIE_预期现金流 + 分摊的LC_预期现金流 + 被LC吸收的变化_预期现金流`")
    details.append(f"- **计算**: {fmt(bop_lc_cf)} + {fmt(nb_initial_lc_cf)} + {fmt(lc_ifie_cf)} + {fmt(allocated_lc_cf)} + {fmt(allocated_lc_exp_adj_cf)} = {fmt(lc_balance_to_adjust_cf)}")
    details.append(f"- **结果**: `{fmt(lc_balance_to_adjust_cf)}`\n")

    # 7. LC调整_预期现金流
    details.append("#### 7. LC调整_预期现金流")
    details.append("- **公式**: `LC调整_预期现金流 = IF(CSM摊销比例=100%, -待调整LC余额_预期现金流, 0)`")
    if csm_amort_ratio >= Decimal('1'):
        details.append(f"- **判断**: CSM摊销比例 = {fmt(csm_amort_ratio)} >= 100%，所以 LC调整_预期现金流 = -{fmt(lc_balance_to_adjust_cf)} = {fmt(lc_adjust_cf)}")
    else:
        details.append(f"- **判断**: CSM摊销比例 = {fmt(csm_amort_ratio)} < 100%，所以 LC调整_预期现金流 = 0.00")
    details.append(f"- **结果**: `{fmt(lc_adjust_cf)}`\n")

    # 8. 期末LC余额_预期现金流
    details.append("#### 8. 期末LC余额_预期现金流")
    details.append("- **公式**: `期末LC余额_预期现金流 = 待调整LC余额_预期现金流 + LC调整_预期现金流`")
    details.append(f"- **计算**: {fmt(lc_balance_to_adjust_cf)} + {fmt(lc_adjust_cf)} = {fmt(end_lc_cf)}")
    details.append(f"- **结果**: `{fmt(end_lc_cf)}`\n")

    logger.log_text("\n".join(details))


def _log_lc_measurement_ra_details(
    logger,
    bop_lc_ra,
    nb_initial_lc_total,
    nb_initial_lc_cf,
    nb_initial_lc_ra,
    if_lc_ifie_ra,
    nb_lc_ifie_ra,
    lc_ifie_ra,
    pv_if_cur_ra,
    pv_nb_cur_ra,
    lc_allocation_ratio_total,
    allocated_lc_ra,
    allocated_lc_exp_adj_total,
    allocated_lc_exp_adj_cf,
    allocated_lc_exp_adj_ra,
    lc_balance_to_adjust_ra,
    csm_amort_ratio,
    lc_adjust_ra,
    end_lc_ra,
):
    """记录LC计量_非金融风险调整的详细计算过程"""

    def fmt(v):
        return _format_for_log(v)

    details = []
    details.append("**详细计算过程**:\n")

    # 1. 年初LC余额_非金融风险调整
    details.append("#### 1. 年初LC余额_非金融风险调整")
    details.append("- **来源**: 直接取数（简化处理，假设为0）")
    details.append(f"- **数值**: {fmt(bop_lc_ra)}\n")

    # 2. 当年新增LC_非金融风险调整
    details.append("#### 2. 当年新增LC_非金融风险调整")
    details.append("- **公式**: `当年新增LC_非金融风险调整 = 当年新增LC_合计 - 当年新增LC_预期现金流`")
    details.append("- **计算步骤**:")
    details.append(f"  - 当年新增LC_合计 = {fmt(nb_initial_lc_total)} (来源：NB_新增LC)")
    details.append(f"  - 当年新增LC_预期现金流 = {fmt(nb_initial_lc_cf)} (来源：LC计量_预期现金流部分)")
    details.append(f"  - 当年新增LC_非金融风险调整 = {fmt(nb_initial_lc_total)} - ({fmt(nb_initial_lc_cf)}) = {fmt(nb_initial_lc_ra)}")
    details.append(f"- **结果**: `{fmt(nb_initial_lc_ra)}`")
    details.append("- **说明**: 倒挤法，确保当年新增LC_合计 = 预期现金流 + 非金融风险调整\n")

    # 3. LC分摊IFIE_非金融风险调整
    details.append("#### 3. LC分摊IFIE_非金融风险调整")
    details.append("- **公式**: `LC分摊IFIE_非金融风险调整 = IF_LC分摊IFIE_非金融风险调整 + NB_LC分摊IFIE_非金融风险调整`")
    details.append("- **计算步骤**:")
    details.append(f"  - IF_LC分摊IFIE_非金融风险调整 = {fmt(if_lc_ifie_ra)} (来源：context.if_lc_ifie_ra)")
    details.append(f"  - NB_LC分摊IFIE_非金融风险调整 = {fmt(nb_lc_ifie_ra)} (来源：context.nb_lc_ifie_ra)")
    details.append(f"  - LC分摊IFIE_非金融风险调整 = {fmt(if_lc_ifie_ra)} + {fmt(nb_lc_ifie_ra)} = {fmt(lc_ifie_ra)}")
    details.append(f"- **结果**: `{fmt(lc_ifie_ra)}`\n")

    # 4. 分摊的LC_非金融风险调整
    details.append("#### 4. 分摊的LC_非金融风险调整")
    details.append("- **公式**: `分摊的LC_非金融风险调整 = (IF_预期当期非金融风险调整 + NB_预期当期非金融风险调整) × LC分摊比例_合计`")
    details.append("- **计算步骤**:")
    details.append(f"  - IF_预期当期非金融风险调整（期末现值Wlk） = {fmt(pv_if_cur_ra)} (来源：Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt)")
    details.append(f"  - NB_预期当期非金融风险调整（期末现值Wlk） = {fmt(pv_nb_cur_ra)} (来源：Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt)")
    pv_cur_ra_total = pv_if_cur_ra + pv_nb_cur_ra
    details.append(f"  - 预期当期非金融风险调整合计 = {fmt(pv_if_cur_ra)} + {fmt(pv_nb_cur_ra)} = {fmt(pv_cur_ra_total)}")
    details.append(f"  - LC分摊比例_合计 = {fmt(lc_allocation_ratio_total)} (来源：LC计量_合计部分)")
    details.append(f"  - 分摊的LC_非金融风险调整 = {fmt(pv_cur_ra_total)} × {fmt(lc_allocation_ratio_total)} = {fmt(allocated_lc_ra)}")
    details.append(f"- **结果**: `{fmt(allocated_lc_ra)}`")
    details.append("- **说明**: 正数表示减少LC亏损（LC余额绝对值减少），因为当非金融风险调整释放时，亏损应被摊销\n")

    # 5. 被LC吸收的变化_非金融风险调整
    details.append("#### 5. 被LC吸收的变化_非金融风险调整")
    details.append("- **公式**: `被LC吸收的变化_非金融风险调整 = 被LC吸收的变化_合计 - 被LC吸收的变化_预期现金流`")
    details.append("- **计算步骤**:")
    details.append(f"  - 被LC吸收的变化_合计 = {fmt(allocated_lc_exp_adj_total)} (来源：LC计量_合计部分)")
    details.append(f"  - 被LC吸收的变化_预期现金流 = {fmt(allocated_lc_exp_adj_cf)} (来源：LC计量_预期现金流部分)")
    details.append(f"  - 被LC吸收的变化_非金融风险调整 = {fmt(allocated_lc_exp_adj_total)} - {fmt(allocated_lc_exp_adj_cf)} = {fmt(allocated_lc_exp_adj_ra)}")
    details.append(f"- **结果**: `{fmt(allocated_lc_exp_adj_ra)}`")
    details.append("- **说明**: 倒挤法，确保合计 = 预期现金流 + 非金融风险调整\n")

    # 6. 待调整LC余额_非金融风险调整
    details.append("#### 6. 待调整LC余额_非金融风险调整")
    details.append("- **公式**: `待调整LC余额_非金融风险调整 = 年初LC余额_非金融风险调整 + 当年新增LC_非金融风险调整 + LC分摊IFIE_非金融风险调整 + 分摊的LC_非金融风险调整 + 被LC吸收的变化_非金融风险调整`")
    details.append(f"- **计算**: {fmt(bop_lc_ra)} + {fmt(nb_initial_lc_ra)} + {fmt(lc_ifie_ra)} + {fmt(allocated_lc_ra)} + {fmt(allocated_lc_exp_adj_ra)} = {fmt(lc_balance_to_adjust_ra)}")
    details.append(f"- **结果**: `{fmt(lc_balance_to_adjust_ra)}`\n")

    # 7. LC调整_非金融风险调整
    details.append("#### 7. LC调整_非金融风险调整")
    details.append("- **公式**: `LC调整_非金融风险调整 = IF(CSM摊销比例=100%, -待调整LC余额_非金融风险调整, 0)`")
    if csm_amort_ratio >= Decimal('1'):
        details.append(f"- **判断**: CSM摊销比例 = {fmt(csm_amort_ratio)} >= 100%，所以 LC调整_非金融风险调整 = -{fmt(lc_balance_to_adjust_ra)} = {fmt(lc_adjust_ra)}")
    else:
        details.append(f"- **判断**: CSM摊销比例 = {fmt(csm_amort_ratio)} < 100%，所以 LC调整_非金融风险调整 = 0.00")
    details.append(f"- **结果**: `{fmt(lc_adjust_ra)}`\n")

    # 8. 期末LC余额_非金融风险调整
    details.append("#### 8. 期末LC余额_非金融风险调整")
    details.append("- **公式**: `期末LC余额_非金融风险调整 = 待调整LC余额_非金融风险调整 + LC调整_非金融风险调整`")
    details.append(f"- **计算**: {fmt(lc_balance_to_adjust_ra)} + {fmt(lc_adjust_ra)} = {fmt(end_lc_ra)}")
    details.append(f"- **结果**: `{fmt(end_lc_ra)}`\n")

    logger.log_text("\n".join(details))


def months_from_uw_to_target(uw_date: date, target_month_str: str) -> int:
    """
    计算从签单日期到目标月份的月数差
    
    Args:
        uw_date: 签单日期
        target_month_str: 目标月份（YYYYMM格式）
    
    Returns:
        从签单日期到目标月份的月数差（从1开始计数）
    """
    if not uw_date or not target_month_str:
        return 0
    
    try:
        target_date = datetime.strptime(target_month_str, '%Y%m').date()
        if target_date.month == 12:
            target_date = date(target_date.year, 12, 31)
        else:
            target_date = (target_date + relativedelta(months=1) - relativedelta(days=1))
        
        delta = relativedelta(target_date, uw_date)
        months = delta.years * 12 + delta.months
        if target_date > uw_date and months == 0:
            months = 1
        return max(months, 0)
    except Exception:
        return 0


def get_wlk_curve_from_pv_data(context, uw_month_str: str):
    """从PV原材料数据获取签单年月的Wlk利率曲线"""
    if not context.pv_source_data:
        return None
    
    pv_data = context.pv_source_data.get_data(uw_month_str)
    if pv_data and pv_data.metadata:
        rate_locked_month = pv_data.metadata.get('rate_locked_month')
        if rate_locked_month:
            try:
                return get_discount_factors("locked", rate_locked_month)
            except Exception:
                pass
    
    try:
        return get_discount_factors("locked", uw_month_str)
    except Exception:
        return None


def calculate_interest_with_stop_date(
    principal: Decimal,
    rates_df,
    start_term: int,
    end_term: int,
    stop_date: Optional[date] = None,
    val_month_str: Optional[str] = None,
    uw_date: Optional[date] = None
) -> Tuple[Decimal, Decimal]:
    """使用锁定利率曲线计算利息，支持止期判断"""
    if rates_df is None or rates_df.empty:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    actual_end_term = end_term
    if stop_date and val_month_str and uw_date:
        try:
            val_date = datetime.strptime(val_month_str, '%Y%m').date()
            # 止期处理：如果止期在评估月当月或之前，使用止期当月；如果止期在评估月之后，正常计息
            # 例如：7月止期，7月正常计息，8月及之后使用7月的累计利息
            if stop_date.year == val_date.year:
                if stop_date.month < val_date.month:
                    # 止期在评估月之前，使用止期当月
                    stop_month_str = stop_date.strftime('%Y%m')
                    stop_term = months_from_uw_to_target(uw_date, stop_month_str)
                    if stop_term > 0 and stop_term < actual_end_term:
                        actual_end_term = stop_term
                # 如果止期在评估月当月或之后，正常计息（不调整actual_end_term）
        except Exception:
            pass
    
    factor = get_accretion_rate_factor(rates_df, start_term - 1, actual_end_term)
    if principal is None or principal == DECIMAL_ZERO or factor == 0:
        return DECIMAL_ZERO, factor
    return principal * factor, factor

def calculate_nb_csm_interest(
    principal: Decimal,
    rates_df,
    uw_date: date,
    val_month_str: str,
    stop_date: Optional[date] = None
) -> Tuple[Decimal, Decimal]:
    """
    新增合同CSM计息
    
    逻辑：
    - 签单月：CSM × (1 + wlk[1]/2)
    - 第二个月：CSM × (1 + wlk[1]/2) × (1 + wlk[2])
    - 第三个月：CSM × (1 + wlk[1]/2) × (1 + wlk[2]) × (1 + wlk[3])
    - 以此类推
    
    Args:
        principal: CSM本金
        rates_df: Wlk利率曲线
        uw_date: 签单日期
        val_month_str: 评估月份（YYYYMM格式）
        stop_date: 合同止期（可选）
    
    Returns:
        (利息金额, 计息因子)
    """
    if rates_df is None or rates_df.empty or principal is None or principal == DECIMAL_ZERO:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 计算从签单月到评估月的月数差
    months_diff = months_from_uw_to_target(uw_date, val_month_str)
    if months_diff <= 0:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 处理止期：止期当月正常计息，止期之后使用止期当月的累计利息
    # 例如：7月止期，7月正常计息，8月及之后使用7月的累计利息
    actual_months_diff = months_diff
    if stop_date:
        try:
            val_date = datetime.strptime(val_month_str, '%Y%m').date()
            if stop_date.year == val_date.year:
                if stop_date.month < val_date.month:
                    # 止期在评估月之前，使用止期当月（止期当月正常计息）
                    stop_month_str = stop_date.strftime('%Y%m')
                    actual_months_diff = months_from_uw_to_target(uw_date, stop_month_str)
                # 如果止期在评估月当月或之后，正常计息
        except Exception:
            pass
    
    if actual_months_diff <= 0:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 构建利率映射
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    # 计算计息因子
    # 第一期：使用 wlk[1]/2（因为初始确认在月中）
    # 第二期及以后：使用 wlk[2], wlk[3], ...
    factor = Decimal('1.0')
    
    # 第一期：wlk[1]/2
    r1 = rates_map.get(1, Decimal('0'))
    factor *= (Decimal('1.0') + r1 / Decimal('2'))
    
    # 第二期到第actual_months_diff期：累乘整月利率
    for term in range(2, actual_months_diff + 1):
        r = rates_map.get(term, rates_map.get(max_term, Decimal('0')) if max_term > 0 else Decimal('0'))
        factor *= (Decimal('1.0') + r)
    
    # 利息 = 本金 × (因子 - 1)
    interest = principal * (factor - Decimal('1'))
    
    return interest, factor - Decimal('1')

def calculate_if_csm_interest(
    principal: Decimal,
    rates_df,
    uw_date: date,
    bop_month_str: str,
    val_month_str: str,
    stop_date: Optional[date] = None
) -> Tuple[Decimal, Decimal]:
    """
    期初有效合同CSM计息
    
    逻辑：
    - 从年初开始，每个月使用 (该月-签单月的月份差+1) 这一期的wlk利率
    - 例如：签单月202205，评估月202301
    - 1月：使用 wlk[(1月-签单月的月份差+1)] = wlk[8+1] = wlk[9]
    - 2月：累乘 wlk[9] × wlk[10]
    - 3月：累乘 wlk[9] × wlk[10] × wlk[11]
    
    Args:
        principal: CSM本金
        rates_df: Wlk利率曲线
        uw_date: 签单日期
        bop_month_str: 年初月份（YYYYMM格式）
        val_month_str: 评估月份（YYYYMM格式）
        stop_date: 合同止期（可选）
    
    Returns:
        (利息金额, 计息因子)
    """
    if rates_df is None or rates_df.empty or principal is None or principal == DECIMAL_ZERO:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 计算年初月份差和评估月月份差
    bop_months_diff = months_from_uw_to_target(uw_date, bop_month_str)
    val_months_diff = months_from_uw_to_target(uw_date, val_month_str)
    
    if val_months_diff <= bop_months_diff:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 处理止期：止期当月正常计息，止期之后使用止期当月的累计利息
    # 例如：7月止期，7月正常计息，8月及之后使用7月的累计利息
    actual_val_months_diff = val_months_diff
    if stop_date:
        try:
            val_date = datetime.strptime(val_month_str, '%Y%m').date()
            if stop_date.year == val_date.year:
                if stop_date.month < val_date.month:
                    # 止期在评估月之前，使用止期当月（止期当月正常计息）
                    stop_month_str = stop_date.strftime('%Y%m')
                    actual_val_months_diff = months_from_uw_to_target(uw_date, stop_month_str)
                # 如果止期在评估月当月或之后，正常计息
        except Exception:
            pass
    
    if actual_val_months_diff <= bop_months_diff:
        return DECIMAL_ZERO, DECIMAL_ZERO
    
    # 构建利率映射
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    # 计算计息因子
    # 从年初开始，每个月使用 (该月-签单月的月份差+1) 这一期的利率
    # 例如：签单月202205，年初202301（1月），评估月202303（3月）
    # 1月：使用 wlk[(1月-签单月的月份差+1)] = wlk[bop_months_diff+1]
    # 2月：累乘 wlk[bop_months_diff+1] × wlk[bop_months_diff+2]
    # 3月：累乘 wlk[bop_months_diff+1] × wlk[bop_months_diff+2] × wlk[val_months_diff+1]
    factor = Decimal('1.0')
    
    # 从年初月份到评估月份，累乘对应期数的利率
    # 年初月份对应的期数 = bop_months_diff + 1
    # 评估月份对应的期数 = actual_val_months_diff + 1
    for term in range(bop_months_diff + 1, actual_val_months_diff + 1):
        r = rates_map.get(term, rates_map.get(max_term, Decimal('0')) if max_term > 0 else Decimal('0'))
        factor *= (Decimal('1.0') + r)
    
    # 利息 = 本金 × (因子 - 1)
    interest = principal * (factor - Decimal('1'))
    
    return interest, factor - Decimal('1')


def _calculate_csm_interest(context, logger, cohort_state: CohortState, policy_state: PolicyState):
    """
    计算CSM计息（文档第6节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policy_state: 保单状态
    """
    logger.log_section("Part 3: CSM计息 (Interest Accretion) [Sec 6]")
    
    if context.pv_source_data is None:
        ensure_pv_source_data(context)
    
    if context.pv_source_data is None:
        policy_no = getattr(context.policy_data, 'policy_no', None) or getattr(context, 'policy_no', 'UNKNOWN')
        raise ValueError(
            f"❌ 错误: PV原材料数据不可用！\n"
            f"   保单号: {policy_no}\n"
            f"   请先运行 pv_calculator.py 生成PV原材料数据文件"
        )
    
    if not hasattr(context, 'eop_date') or context.eop_date is None:
        context.eop_date = datetime(context.year, 12, 31).date()
    
    uw_date = getattr(context, 'under_write_date', None)
    if not uw_date:
        raise ValueError("❌ 错误: context.under_write_date 未设置")
    uw_month_str = uw_date.strftime('%Y%m')
    
    val_month_str = getattr(context, 'val_month_str', None)
    if not val_month_str:
        val_month_str = context.eop_date.strftime('%Y%m')
    
    # 从PV原材料数据获取签单年月的Wlk利率曲线
    wlk_curve = get_wlk_curve_from_pv_data(context, uw_month_str)
    if wlk_curve is None or wlk_curve.empty:
        logger.log_item(
            "锁定利率曲线缺失",
            "[Sec 6.1] 无法从PV原材料数据获取签单年月的Wlk利率曲线",
            f"UW Month: {uw_month_str}",
            {},
            DECIMAL_ZERO,
            note="请确保PV原材料数据包含签单月份的利率曲线信息"
        )
        return
    
    stop_date = None
    if policy_state and hasattr(policy_state, 'end_date'):
        stop_date = policy_state.end_date
    elif hasattr(context, 'end_date'):
        stop_date = context.end_date
    
    # 获取统一的CSM/LC字段
    # 修复：正确合并bop_csm和bop_lc，如果bop_csm > 0则为CSM，如果bop_lc < 0则为LC
    bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
    
    # 修复：CSM计息应该直接使用 nb_initial_csm，不要从 nb_initial_lc 获取值
    # 对于亏损保单，nb_initial_csm = 0，nb_initial_lc > 0
    # 如果从 nb_initial_lc 获取值，会导致亏损保单错误地按CSM计息
    nb_initial_csm = context.nb_initial_csm or DECIMAL_ZERO
    
    # 分离CSM和LC
    bop_csm = bop_csm_lc if bop_csm_lc >= 0 else DECIMAL_ZERO
    # nb_initial_csm 已经直接获取，不需要再判断正负（因为初始确认时已经正确设置）
    
    # 期初有效合同CSM计息
    # 从年初开始，每个月使用 (该月-签单月的月份差+1) 这一期的wlk利率累乘
    bop_month_str = date(context.year, 1, 1).strftime('%Y%m')
    
    if_interest_csm, if_factor = calculate_if_csm_interest(
        bop_csm,
        wlk_curve,
        uw_date,
        bop_month_str,
        val_month_str,
        stop_date=stop_date
    )
    
    # 新增合同CSM计息
    # 第一期利率用一半（wlk[1]/2），然后累乘后续利率
    nb_interest_csm, nb_factor = calculate_nb_csm_interest(
        nb_initial_csm,
        wlk_curve,
        uw_date,
        val_month_str,
        stop_date=stop_date
    )
    
    # 保存到context
    context.if_interest_csm = if_interest_csm
    context.nb_interest_csm = nb_interest_csm
    
    # 计算计息后余额（文档要求）
    if_csm_post_interest = bop_csm + if_interest_csm
    nb_csm_post_interest = nb_initial_csm + nb_interest_csm
    
    # 更新cohort_state
    if cohort_state:
        cohort_state.csm_interest = if_interest_csm + nb_interest_csm
    
    logger.log_item(
        "CSM计息明细",
        "[Sec 6] CSM计息明细（文档对照）",
        "IF_计息后CSM = IF_年初CSM余额 + IF_CSM计息\nNB_计息后CSM = NB_新增CSM + NB_CSM计息",
        {
            "IF_年初CSM余额": bop_csm,
            "当年新增合同CSM": nb_initial_csm,
            "期初有效合同CSM计息": if_interest_csm,
            "新增合同CSM计息": nb_interest_csm,
            "IF_计息后CSM": if_csm_post_interest,
            "NB_计息后CSM": nb_csm_post_interest
        },
        if_interest_csm + nb_interest_csm,
        note="CSM计息结果，用于后续净余额试算"
    )


def _pv_amount(pv_data, field_name):
    """Helper to safely get PV amount, returning 0 if pv_data is None"""
    if pv_data is None:
        return Decimal('0')
    return pv_data.get_field(field_name)

def _get_bop_csm_lc(context, cohort_state: Optional[CohortState] = None) -> Decimal:
    """
    获取统一的CSM/LC字段（期初余额，供“建筑模型”判定使用）

    这里实现的是 Excel 中“统一CSM/LC字段”的思想：

    - 我们在底层**始终分别存储**：
      - bop_csm: 年初 CSM 余额（IF 视角）
      - bop_lc : 年初 LC 余额（IF 视角）
    - 在做合同组状态判定 / LC IFIE 分摊时，需要一个“统一净额字段”：
      - 盈利组：bop_csm > 0, bop_lc = 0 ⇒ 统一字段 = bop_csm（正数 → CSM 逻辑）
      - 亏损组：bop_csm = 0, bop_lc < 0 ⇒ 统一字段 = bop_lc（负数 → LC 逻辑）
    - 判定规则：
      - 统一字段 >= 0 → 走 CSM 计息 / 判定逻辑
      - 统一字段 < 0  → 走 LC 判定 / IFIE 分摊逻辑

    注意：
    - 这里只是**组合视图**，不会破坏 / 覆盖原有的 bop_csm / bop_lc 字段；
    - 优先从 context 读取（年度内滚存后的值），若缺失则回退到 cohort_state（组状态对象）。
    
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

def _calculate_lc_ifie_allocation(context, logger, cohort_state: CohortState):
    """
    计算LC分摊IFIE（文档第7节）
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
    """
    logger.log_section("Part 7: LC分摊IFIE (LC IFIE Allocation) [Sec 7]")
    
    # 获取评估月
    eop_month_str = context.val_month_str
    # 所有数据都从当前评估期的PV数据读取
    
    # 获取PV数据
    pv_data = context.pv_source_data.get_data(eop_month_str)
    
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 获取统一的CSM/LC字段
    # 修复：正确合并bop_csm和bop_lc，如果bop_csm > 0则为CSM，如果bop_lc < 0则为LC
    bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
    
    # 获取统一的CSM/LC字段（用于计算LC IFIE分摊比例）
    # 修复：context.nb_initial_lc 现在直接存储为负数（亏损），不需要再转换
    is_reversal = getattr(context, 'is_reversal_policy', False)
    nb_initial_csm_lc = context.nb_initial_csm or DECIMAL_ZERO
    if nb_initial_csm_lc == DECIMAL_ZERO and hasattr(context, 'nb_initial_lc'):
        nb_lc_val = context.nb_initial_lc or DECIMAL_ZERO
        is_nb_lc = (nb_lc_val < DECIMAL_ZERO) if (not is_reversal) else (nb_lc_val > DECIMAL_ZERO)
        if is_nb_lc:
            nb_initial_csm_lc = nb_lc_val
    
    # ==========================================================================================
    # IF（期初有效合同）LC IFIE分摊
    # ==========================================================================================
    # 正常保单：LC < 0；批减单：LC > 0（符号逻辑相反）
    is_if_lc = (bop_csm_lc < 0) if (not is_reversal) else (bop_csm_lc > 0)
    if_bop_lc = bop_csm_lc if is_if_lc else DECIMAL_ZERO
    
    logger.log_item(
        "IF_年初LC",
        "[LC IFIE分摊] 期初有效合同年初LC（直接取数）",
        "IF_年初LC = IF_年初CSM/LC（如果<0，则为LC）",
        {
            "IF_年初CSM/LC": bop_csm_lc,
            "IF_年初LC": if_bop_lc
        },
        if_bop_lc,
        note="使用统一字段逻辑：正常保单IF_年初CSM/LC < 0为LC；批减单IF_年初CSM/LC > 0为LC（符号逻辑相反）"
    )
    
    # IF_LC IFIE分摊比例
    # 分母：IF_预期赔付现金流_年初现值 + IF_预期维持费用现金流_年初现值 + IF_预期非金融风险调整_年初现值
    if_lc_ifie_ratio = getattr(context, 'if_lc_ifie_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    pv_if_init_claims = DECIMAL_ZERO
    pv_if_init_maint = DECIMAL_ZERO
    pv_if_init_ra = DECIMAL_ZERO
    denom_if = DECIMAL_ZERO
    
    if is_if_lc and if_lc_ifie_ratio == DECIMAL_ZERO:
        # 如果还未计算，则计算
        # 注意：已删除 Cca_Beg_Lcu 字段，Cfa_Beg_Lcu 已经包含了1月现金流（折现到年初）
        # 年初现值：有效合同-年初预期-预期未来-年初现值（LCU）
        pv_if_init_claims = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt', DECIMAL_ZERO)
        pv_if_init_maint = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO)
        pv_if_init_ra = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt', DECIMAL_ZERO)
        denom_if = pv_if_init_claims + pv_if_init_maint + pv_if_init_ra
        
        denom_if_abs = denom_if.copy_abs()
        if denom_if_abs > 0:
            if_lc_ifie_ratio = if_bop_lc.copy_abs() / denom_if_abs
        context.if_lc_ifie_ratio = if_lc_ifie_ratio
    elif is_if_lc:
        # 如果已有值，也需要获取分母用于日志显示
        pv_if_init_claims = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt', DECIMAL_ZERO)
        pv_if_init_maint = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO)
        pv_if_init_ra = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt', DECIMAL_ZERO)
        denom_if = pv_if_init_claims + pv_if_init_maint + pv_if_init_ra
    
    logger.log_item(
        "IF_LC IFIE分摊比例",
        "[LC IFIE分摊] 期初有效合同LC IFIE分摊比例",
        "IF_LC IFIE分摊比例 = IF_年初LC / (IF_预期赔付现金流_年初现值 + IF_预期维持费用现金流_年初现值 + IF_预期非金融风险调整_年初现值)",
        {
            "IF_年初LC": if_bop_lc,
            "IF_预期赔付现金流_年初现值（LCU）": pv_if_init_claims if is_if_lc else DECIMAL_ZERO,
            "IF_预期维持费用现金流_年初现值（LCU）": pv_if_init_maint if is_if_lc else DECIMAL_ZERO,
            "IF_预期非金融风险调整_年初现值（LCU）": pv_if_init_ra if is_if_lc else DECIMAL_ZERO,
            "分母合计(|denom|)": denom_if.copy_abs() if is_if_lc else DECIMAL_ZERO,
            "IF_LC IFIE分摊比例": if_lc_ifie_ratio
        },
        if_lc_ifie_ratio,
        note="如果存在LC（正常保单：IF_年初LC<0；批减单：IF_年初LC>0），则计算分摊比例；否则为0。年初现值指：有效合同-年初预期-预期未来-年初现值（LCU），已包含1月现金流折现到年初"
    )
    
    # ==========================================================================================
    # IF（期初有效合同）待分摊IFIE计算（详细逻辑）
    # ==========================================================================================
    # 1. IF_待分摊IFIE_计息_赔付与费用
    # 公式：[Bop_Cfa_Rep_Wlk] + [Bop_Cca_Rep_Wlk] - [Bop_Cfa_Beg_Wlk]
    pv_if_bop_cfa_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt')
    pv_if_bop_cfa_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt')
    pv_if_bop_cca_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt')
    pv_if_bop_cca_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt')
    pv_if_bop_cfa_beg_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt')
    pv_if_bop_cfa_beg_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt')
    
    if_ifie_accretion_claims = (
        pv_if_bop_cfa_rep_wlk_claims +
        pv_if_bop_cfa_rep_wlk_maint +
        pv_if_bop_cca_rep_wlk_claims +
        pv_if_bop_cca_rep_wlk_maint -
        pv_if_bop_cfa_beg_wlk_claims -
        pv_if_bop_cfa_beg_wlk_maint
    )
    
    logger.log_item(
        "IF_待分摊IFIE_计息_赔付与费用",
        "[LC IFIE分摊] 期初有效合同待分摊IFIE_计息_赔付与费用",
        "IF_待分摊IFIE_计息_赔付与费用 = 【有效合同-年初预期-预期未来-预期赔付现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期未来-预期维持费用现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-预期赔付现金流-期末现值（加权初始确认利率）】+【有效合同-年初预期-预期当年-预期维持费用现金流-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期赔付现金流-年初现值（上年）加权初始确认利率】-【有效合同-年初预期-预期未来-预期维持费用现金流-年初现值（上年）加权初始确认利率】",
        {
            "年初-预期未来-赔付（Rep_Wlk）": pv_if_bop_cfa_rep_wlk_claims,
            "年初-预期未来-维费（Rep_Wlk）": pv_if_bop_cfa_rep_wlk_maint,
            "年初-预期当年-赔付（Rep_Wlk）": pv_if_bop_cca_rep_wlk_claims,
            "年初-预期当年-维费（Rep_Wlk）": pv_if_bop_cca_rep_wlk_maint,
            "年初-预期未来-赔付（Beg_Wlk）": pv_if_bop_cfa_beg_wlk_claims,
            "年初-预期未来-维费（Beg_Wlk）": pv_if_bop_cfa_beg_wlk_maint,
            "IF_待分摊IFIE_计息_赔付与费用": if_ifie_accretion_claims
        },
        if_ifie_accretion_claims,
        note="所有现值均从PV原材料数据读取，使用Wlk字段（加权初始确认利率）。公式：[Bop_Cfa_Rep_Wlk] + [Bop_Cca_Rep_Wlk] - [Bop_Cfa_Beg_Wlk]"
    )
    
    # 2. IF_待分摊IFIE_计息_非金融风险调整
    # 公式：[Bop_Cfa_Rep_Wlk] - [Bop_Cfa_Beg_Wlk] + [Bop_Cca_Rep_Wlk]
    pv_if_bop_cfa_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt')
    pv_if_bop_cfa_beg_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt')
    pv_if_bop_cca_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt')
    
    if_ifie_accretion_ra = (
        pv_if_bop_cfa_rep_wlk_ra -
        pv_if_bop_cfa_beg_wlk_ra +
        pv_if_bop_cca_rep_wlk_ra
    )
    
    logger.log_item(
        "IF_待分摊IFIE_计息_非金融风险调整",
        "[LC IFIE分摊] 期初有效合同待分摊IFIE_计息_非金融风险调整",
        "IF_待分摊IFIE_计息_非金融风险调整 = 【有效合同-年初预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期非金融风险调整-年初现值（上年）加权初始确认利率】+【有效合同-年初预期-预期当年-预期非金融风险调整-期末现值（加权初始确认利率）】",
        {
            "年初-预期未来-RA（Rep_Wlk）": pv_if_bop_cfa_rep_wlk_ra,
            "年初-预期当年-RA（Rep_Wlk）": pv_if_bop_cca_rep_wlk_ra,
            "年初-预期未来-RA（Beg_Wlk）": pv_if_bop_cfa_beg_wlk_ra,
            "IF_待分摊IFIE_计息_非金融风险调整": if_ifie_accretion_ra
        },
        if_ifie_accretion_ra,
        note="所有现值均从PV原材料数据读取，使用Wlk字段（加权初始确认利率）和Rad字段。公式：[Bop_Cfa_Rep_Wlk] - [Bop_Cfa_Beg_Wlk] + [Bop_Cca_Rep_Wlk]"
    )
    
    # 3. IF_待分摊IFIE_利率变化的影响_赔付与费用
    # 公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])
    # 注意：文档中还要加上 [Eop_Cfa_Rep_Cur_Mtn] 等，以及年初部分的 Lcu 和 Wlk 差额
    pv_if_eop_cfa_rep_cur_claims = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt')
    pv_if_eop_cfa_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt')
    pv_if_eop_cfa_rep_cur_maint = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt')
    pv_if_eop_cfa_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    pv_if_bop_cfa_beg_lcu_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt')
    pv_if_bop_cfa_beg_wlk_claims = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt')
    pv_if_bop_cfa_beg_lcu_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt')
    pv_if_bop_cfa_beg_wlk_maint = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt')
    
    term_end_diff = (
        pv_if_eop_cfa_rep_cur_claims -
        pv_if_eop_cfa_rep_wlk_claims +
        pv_if_eop_cfa_rep_cur_maint -
        pv_if_eop_cfa_rep_wlk_maint
    )
    term_beg_diff = (
        pv_if_bop_cfa_beg_lcu_claims -
        pv_if_bop_cfa_beg_wlk_claims +
        pv_if_bop_cfa_beg_lcu_maint -
        pv_if_bop_cfa_beg_wlk_maint
    )
    if_ifie_rate_change_claims = term_end_diff - term_beg_diff
    
    logger.log_item(
        "IF_待分摊IFIE_利率变化的影响_赔付与费用",
        "[LC IFIE分摊] 期初有效合同待分摊IFIE_利率变化的影响_赔付与费用",
        "IF_待分摊IFIE_利率变化的影响_赔付与费用 = 【有效合同-期末预期-预期未来-预期赔付现金流-期末现值（期末利率）】-【有效合同-期末预期-预期未来-预期赔付现金流-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期赔付现金流-年初现值（上年）期末利率】-【有效合同-年初预期-预期未来-预期赔付现金流-年初现值（上年）加权初始确认利率】+【有效合同-期末预期-预期未来-预期维持费用现金流-期末现值（期末利率）】-【有效合同-期末预期-预期未来-预期维持费用现金流-期末现值（加权初始确认利率）】-【有效合同-年初预期-预期未来-预期维持费用现金流-年初现值（上年）期末利率】-【有效合同-年初预期-预期未来-预期维持费用现金流-年初现值（上年）加权初始确认利率】",
        {
            "期末-预期未来-赔付（Cur）": pv_if_eop_cfa_rep_cur_claims,
            "期末-预期未来-赔付（Wlk）": pv_if_eop_cfa_rep_wlk_claims,
            "年初-预期未来-赔付（Lcu）": pv_if_bop_cfa_beg_lcu_claims,
            "年初-预期未来-赔付（Wlk）": pv_if_bop_cfa_beg_wlk_claims,
            "期末-预期未来-维费（Cur）": pv_if_eop_cfa_rep_cur_maint,
            "期末-预期未来-维费（Wlk）": pv_if_eop_cfa_rep_wlk_maint,
            "年初-预期未来-维费（Lcu）": pv_if_bop_cfa_beg_lcu_maint,
            "年初-预期未来-维费（Wlk）": pv_if_bop_cfa_beg_wlk_maint,
            "期末利率差异": term_end_diff,
            "年初利率差异": term_beg_diff,
            "IF_待分摊IFIE_利率变化的影响_赔付与费用": if_ifie_rate_change_claims
        },
        if_ifie_rate_change_claims,
        note="所有现值均从PV原材料数据读取，使用Cur字段（期末利率）、Wlk字段（加权初始确认利率）和Lcu字段（年初现值-上年期末利率）。公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])"
    )
    
    # 4. IF_待分摊IFIE_利率变化的影响_非金融风险调整
    # 公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])
    pv_if_eop_cfa_rep_cur_ra = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt')
    pv_if_eop_cfa_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt')
    pv_if_bop_cfa_beg_lcu_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt')
    pv_if_bop_cfa_beg_wlk_ra = _pv_amount(pv_data, 'Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt')
    
    term_end_diff_ra = (
        pv_if_eop_cfa_rep_cur_ra -
        pv_if_eop_cfa_rep_wlk_ra
    )
    term_beg_diff_ra = (
        pv_if_bop_cfa_beg_lcu_ra -
        pv_if_bop_cfa_beg_wlk_ra
    )
    if_ifie_rate_change_ra = term_end_diff_ra - term_beg_diff_ra
    
    logger.log_item(
        "IF_待分摊IFIE_利率变化的影响_非金融风险调整",
        "[LC IFIE分摊] 期初有效合同待分摊IFIE_利率变化的影响_非金融风险调整",
        "IF_待分摊IFIE_利率变化的影响_非金融风险调整 = 【有效合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】-【有效合同-期末预期-预期未来-非金融风险调整-期末现值（加权初始确认利率）】-（【有效合同-年初预期-预期未来-非金融风险调整-年初现值（上年）期末利率】-【有效合同-年初预期-预期未来-非金融风险调整-年初现值（上年）加权初始确认利率】）",
        {
            "期末-预期未来-RA（Cur）": pv_if_eop_cfa_rep_cur_ra,
            "期末-预期未来-RA（Wlk）": pv_if_eop_cfa_rep_wlk_ra,
            "年初-预期未来-RA（Lcu）": pv_if_bop_cfa_beg_lcu_ra,
            "年初-预期未来-RA（Wlk）": pv_if_bop_cfa_beg_wlk_ra,
            "期末利率差异": term_end_diff_ra,
            "年初利率差异": term_beg_diff_ra,
            "IF_待分摊IFIE_利率变化的影响_非金融风险调整": if_ifie_rate_change_ra
        },
        if_ifie_rate_change_ra,
        note="所有现值均从PV原材料数据读取，使用Cur字段（期末利率）、Wlk字段（加权初始确认利率）和Lcu字段（年初现值-上年期末利率）。公式：([Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]) - ([Bop_Cfa_Beg_Lcu] - [Bop_Cfa_Beg_Wlk])"
    )
    
    # 计算分摊结果
    if_lc_ifie_claims_before_sign = (if_ifie_accretion_claims + if_ifie_rate_change_claims) * if_lc_ifie_ratio
    if_lc_ifie_ra_before_sign = (if_ifie_accretion_ra + if_ifie_rate_change_ra) * if_lc_ifie_ratio
    if_lc_ifie_total_before_sign = if_lc_ifie_claims_before_sign + if_lc_ifie_ra_before_sign
    
    # LC IFIE分摊应与LC本金同方向（正常保单为负，批减单为正）
    if is_if_lc:
        lc_sign = Decimal('-1') if if_bop_lc < 0 else Decimal('1')
        if_lc_ifie_claims = if_lc_ifie_claims_before_sign.copy_abs() * lc_sign
        if_lc_ifie_ra = if_lc_ifie_ra_before_sign.copy_abs() * lc_sign
        if_lc_ifie_total = if_lc_ifie_total_before_sign.copy_abs() * lc_sign
    else:
        if_lc_ifie_claims = if_lc_ifie_claims_before_sign
        if_lc_ifie_ra = if_lc_ifie_ra_before_sign
        if_lc_ifie_total = if_lc_ifie_total_before_sign
    
    logger.log_item(
        "IF_LC分摊IFIE_赔付与费用",
        "[LC IFIE分摊] 期初有效合同LC分摊IFIE_赔付与费用",
        "IF_LC分摊IFIE_赔付与费用 = (IF_待分摊IFIE_计息_赔付与费用 + IF_待分摊IFIE_利率变化的影响_赔付与费用) × IF_LC IFIE分摊比例",
        {
            "IF_待分摊IFIE_计息_赔付与费用": if_ifie_accretion_claims,
            "IF_待分摊IFIE_利率变化的影响_赔付与费用": if_ifie_rate_change_claims,
            "IF_LC IFIE分摊比例": if_lc_ifie_ratio,
            "IF_LC分摊IFIE_赔付与费用（符号处理前）": if_lc_ifie_claims_before_sign,
            "IF_LC分摊IFIE_赔付与费用": if_lc_ifie_claims
        },
        if_lc_ifie_claims,
        note=f"计算过程：({if_ifie_accretion_claims} + {if_ifie_rate_change_claims}) × {if_lc_ifie_ratio} = {if_lc_ifie_claims_before_sign}，符号处理：{'与LC同方向' if is_if_lc else '保持原值'}"
    )
    
    logger.log_item(
        "IF_LC分摊IFIE_非金融风险调整",
        "[LC IFIE分摊] 期初有效合同LC分摊IFIE_非金融风险调整",
        "IF_LC分摊IFIE_非金融风险调整 = (IF_待分摊IFIE_计息_非金融风险调整 + IF_待分摊IFIE_利率变化的影响_非金融风险调整) × IF_LC IFIE分摊比例",
        {
            "IF_待分摊IFIE_计息_非金融风险调整": if_ifie_accretion_ra,
            "IF_待分摊IFIE_利率变化的影响_非金融风险调整": if_ifie_rate_change_ra,
            "IF_LC IFIE分摊比例": if_lc_ifie_ratio,
            "IF_LC分摊IFIE_非金融风险调整（符号处理前）": if_lc_ifie_ra_before_sign,
            "IF_LC分摊IFIE_非金融风险调整": if_lc_ifie_ra
        },
        if_lc_ifie_ra,
        note=f"计算过程：({if_ifie_accretion_ra} + {if_ifie_rate_change_ra}) × {if_lc_ifie_ratio} = {if_lc_ifie_ra_before_sign}，符号处理：{'与LC同方向' if is_if_lc else '保持原值'}"
    )
    
    logger.log_item(
        "IF_LC分摊IFIE",
        "[LC IFIE分摊] 期初有效合同LC分摊IFIE合计",
        "IF_LC分摊IFIE = IF_LC分摊IFIE_赔付与费用 + IF_LC分摊IFIE_非金融风险调整",
        {
            "IF_LC分摊IFIE_赔付与费用": if_lc_ifie_claims,
            "IF_LC分摊IFIE_非金融风险调整": if_lc_ifie_ra,
            "IF_LC分摊IFIE": if_lc_ifie_total
        },
        if_lc_ifie_total,
        note=f"计算过程：{if_lc_ifie_claims} + {if_lc_ifie_ra} = {if_lc_ifie_total}"
    )
    
    if_lc_after_ifie = if_bop_lc + if_lc_ifie_total
    
    logger.log_item(
        "IF_分摊后IFIE后LC",
        "[LC IFIE分摊] 期初有效合同分摊后IFIE后LC",
        "IF_分摊后IFIE后LC = IF_年初LC + IF_LC分摊IFIE",
        {
            "IF_年初LC": if_bop_lc,
            "IF_LC分摊IFIE": if_lc_ifie_total,
            "IF_分摊后IFIE后LC": if_lc_after_ifie
        },
        if_lc_after_ifie,
        note=f"计算过程：{if_bop_lc} + {if_lc_ifie_total} = {if_lc_after_ifie}"
    )
    
    context.if_lc_after_ifie = if_lc_after_ifie
    context.if_lc_ifie_total = if_lc_ifie_total
    context.if_lc_ifie_cf = if_lc_ifie_claims
    context.if_lc_ifie_ra = if_lc_ifie_ra
    
    # ==========================================================================================
    # NB（新增合同）LC IFIE分摊（详细逻辑）
    # ==========================================================================================
    # 使用统一字段逻辑：
    # - 正常保单：nb_initial_csm_lc < 0 为LC
    # - 批减单：nb_initial_csm_lc > 0 为LC（符号逻辑相反）
    is_nb_lc = (nb_initial_csm_lc < 0) if (not is_reversal) else (nb_initial_csm_lc > 0)
    nb_initial_lc = nb_initial_csm_lc if is_nb_lc else DECIMAL_ZERO
    
    logger.log_item(
        "NB_新增LC",
        "[LC IFIE分摊] 新增合同新增LC",
        "NB_新增LC = Sum(当年各月新增合同CSM/LC中<0的值)",
        {
            "NB_初始CSM/LC": nb_initial_csm_lc,
            "NB_新增LC": nb_initial_lc
        },
        nb_initial_lc,
        note="使用统一字段逻辑：正常保单NB_初始CSM/LC < 0为LC；批减单NB_初始CSM/LC > 0为LC（符号逻辑相反）"
    )
    
    # NB_LC IFIE分摊比例
    nb_lc_ifie_ratio = getattr(context, 'nb_lc_ratio', DECIMAL_ZERO) or DECIMAL_ZERO
    init_fut_claim = getattr(context, 'init_fut_claim', DECIMAL_ZERO) or DECIMAL_ZERO
    init_fut_maint = getattr(context, 'init_fut_maint', DECIMAL_ZERO) or DECIMAL_ZERO
    init_ra = getattr(context, 'init_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    denom_nb = init_fut_claim + init_fut_maint + init_ra
    
    is_nb_lc_for_ratio = (nb_initial_lc < 0) if (not is_reversal) else (nb_initial_lc > 0)
    if is_nb_lc_for_ratio and nb_lc_ifie_ratio == DECIMAL_ZERO:
        denom_nb_abs = denom_nb.copy_abs()
        if denom_nb_abs > 0:
            nb_lc_ifie_ratio = nb_initial_lc.copy_abs() / denom_nb_abs
        context.nb_lc_ratio = nb_lc_ifie_ratio
    
    logger.log_item(
        "NB_LC IFIE分摊比例",
        "[LC IFIE分摊] 新增合同LC IFIE分摊比例",
        "NB_LC IFIE分摊比例 = |NB_年初LC| / (汇总当年各新增年月_预期赔付现金流_初始确认现值 + 汇总当年各新增年月_预期维持费用现金流_初始确认现值 + 汇总当年各新增年月_预期非金融风险调整_初始确认现值)",
        {
            "NB_年初LC": nb_initial_lc,
            "分子（|NB_年初LC|）": (nb_initial_lc.copy_abs() if is_nb_lc_for_ratio else DECIMAL_ZERO),
            "汇总当年各新增年月_预期赔付现金流_初始确认现值": init_fut_claim,
            "汇总当年各新增年月_预期维持费用现金流_初始确认现值": init_fut_maint,
            "汇总当年各新增年月_预期非金融风险调整_初始确认现值": init_ra,
            "分母合计(|denom|)": denom_nb.copy_abs(),
            "NB_LC IFIE分摊比例": nb_lc_ifie_ratio
        },
        nb_lc_ifie_ratio,
        note=f"如果存在NB_LC（正常保单: NB_年初LC<0；批减单: NB_年初LC>0），则计算分摊比例；否则为0。比例{'已在其他模块计算' if nb_lc_ifie_ratio > 0 and getattr(context, 'nb_lc_ratio', None) else '在此处计算'}。计算过程：|{nb_initial_lc}| / |({init_fut_claim} + {init_fut_maint} + {init_ra})| = |{nb_initial_lc}| / {denom_nb.copy_abs()} = {nb_lc_ifie_ratio}" if is_nb_lc_for_ratio and denom_nb.copy_abs() > 0 else "NB_LC不存在或分母为0，比例为0"
    )
    
    # 1. NB_待分摊IFIE_计息_赔付与费用
    # 公式：使用期末时点的数据（Eop），而不是初始确认时点的数据（Ini）
    # 【新增合同-期末预期-预期未来-预期赔付现金流-期末现值（加权初始确认利率）】+
    # 【新增合同-期末预期-预期未来-预期维持费用现金流-期末现值（加权初始确认利率）】+
    # 【新增合同-期末预期-预期当期-预期赔付现金流-期末现值（加权初始确认利率）】+
    # 【新增合同-期末预期-预期当期-预期维持费用现金流-期末现值（加权初始确认利率）】-
    # 【新增合同-初始确认-预期未来-预期赔付现金流-初始确认现值（当月初始利率）】-
    # 【新增合同-初始确认-预期未来-预期维持费用现金流-初始确认现值（当月初始利率）】
    # 注意：已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月），初始确认现值只使用预期未来部分
    if pv_data is None:
        nb_ifie_accretion_claims = DECIMAL_ZERO
        pv_nb_eop_fut_claims_wlk = pv_nb_eop_fut_maint_wlk = pv_nb_eop_cur_claims_wlk = pv_nb_eop_cur_maint_wlk = DECIMAL_ZERO
        pv_nb_ini_fut_claims_lkd = pv_nb_ini_fut_maint_lkd = DECIMAL_ZERO
    else:
        # 期末现值（加权初始确认利率）：预期未来 + 预期当期
        pv_nb_eop_fut_claims_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt')
        pv_nb_eop_fut_maint_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
        pv_nb_eop_cur_claims_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Wlk_Cla_Amt')
        pv_nb_eop_cur_maint_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Wlk_Mtn_Amt')
        
        # 初始确认现值（当月初始利率）：预期未来（Cfa字段包含所有现金流）
        # 从当前评估月的PV数据读取
        pv_nb_ini_fut_claims_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        pv_nb_ini_fut_maint_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        
        nb_ifie_accretion_claims = ((pv_nb_eop_fut_claims_wlk + pv_nb_eop_fut_maint_wlk +
                                    pv_nb_eop_cur_claims_wlk + pv_nb_eop_cur_maint_wlk) -
                                   (pv_nb_ini_fut_claims_lkd + pv_nb_ini_fut_maint_lkd))
    
    logger.log_item(
        "NB_待分摊IFIE_计息_赔付与费用",
        "[LC IFIE分摊] 新增合同待分摊IFIE_计息_赔付与费用",
        "NB_待分摊IFIE_计息_赔付与费用 = 【新增合同-初始确认-预期未来-预期赔付现金流-期末现值（加权初始确认利率）】+【新增合同-初始确认-预期未来-预期维持费用现金流-期末现值（加权初始确认利率）】-【新增合同-初始确认-预期未来-预期赔付现金流-初始确认现值（当月初始利率）】-【新增合同-初始确认-预期未来-预期维持费用现金流-初始确认现值（当月初始利率）】+【新增合同-初始确认-预期当期-预赔付现金流-期末现值（加权初始确认利率）】+【新增合同-初始确认-预期当期-预期维持费用现金流-期末现值（加权初始确认利率）】",
        {
            "期末-预期未来-赔付（Wlk）": pv_nb_eop_fut_claims_wlk,
            "期末-预期未来-维费（Wlk）": pv_nb_eop_fut_maint_wlk,
            "期末-预期当期-赔付（Wlk）": pv_nb_eop_cur_claims_wlk,
            "期末-预期当期-维费（Wlk）": pv_nb_eop_cur_maint_wlk,
            "期末现值合计（Wlk）": (pv_nb_eop_fut_claims_wlk + pv_nb_eop_fut_maint_wlk + pv_nb_eop_cur_claims_wlk + pv_nb_eop_cur_maint_wlk),
            "初始-预期未来-赔付（Lkd）": pv_nb_ini_fut_claims_lkd,
            "初始-预期未来-维费（Lkd）": pv_nb_ini_fut_maint_lkd,
            "初始现值合计（Lkd）": (pv_nb_ini_fut_claims_lkd + pv_nb_ini_fut_maint_lkd),
            "NB_待分摊IFIE_计息_赔付与费用": nb_ifie_accretion_claims
        },
        nb_ifie_accretion_claims,
        note=f"所有现值均从PV原材料数据读取，使用Wlk字段（加权初始确认利率）和Lkd字段（当月初始利率）。计算过程：({pv_nb_eop_fut_claims_wlk} + {pv_nb_eop_fut_maint_wlk} + {pv_nb_eop_cur_claims_wlk} + {pv_nb_eop_cur_maint_wlk}) - ({pv_nb_ini_fut_claims_lkd} + {pv_nb_ini_fut_maint_lkd}) = {nb_ifie_accretion_claims}"
    )
    
    # 2. NB_待分摊IFIE_计息_非金融风险调整
    # 公式：使用期末时点的数据（Eop），而不是初始确认时点的数据（Ini）
    # 【新增合同-期末预期-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】-
    # 【新增合同-初始确认-预期未来-预期非金融风险调整-初始确认现值（当月初始利率）】+
    # 【新增合同-期末预期-预期当期-预期非金融风险调整-期末现值（加权初始确认利率）】
    # 注意：已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月），初始确认现值只使用预期未来部分
    if pv_data is None:
        nb_ifie_accretion_ra = DECIMAL_ZERO
        pv_nb_eop_fut_ra_wlk = pv_nb_eop_cur_ra_wlk = pv_nb_ini_fut_ra_lkd = DECIMAL_ZERO
    else:
        # 期末现值（加权初始确认利率）：预期未来 + 预期当期
        pv_nb_eop_fut_ra_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
        pv_nb_eop_cur_ra_wlk = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cca_Rep_Wlk_Rad_Amt')
        
        # 初始确认现值（当月初始利率）：预期未来（Cfa字段包含所有现金流）
        # 从当前评估月的PV数据读取
        pv_nb_ini_fut_ra_lkd = _pv_amount(pv_data, 'Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        
        nb_ifie_accretion_ra = (pv_nb_eop_fut_ra_wlk - pv_nb_ini_fut_ra_lkd + pv_nb_eop_cur_ra_wlk)
    
    logger.log_item(
        "NB_待分摊IFIE_计息_非金融风险调整",
        "[LC IFIE分摊] 新增合同待分摊IFIE_计息_非金融风险调整",
        "NB_待分摊IFIE_计息_非金融风险调整 = 【新增合同-初始确认-预期未来-预期非金融风险调整-期末现值（加权初始确认利率）】-【新增合同-初始确认-预期未来-预期非金融风险调整-初始确认现值（当月初始利率）】+【新增合同-初始确认-预期当期-预期非金融风险调整-期末现值（加权初始确认利率）】\n注意：已删除Cca字段，Cfa字段现在包含所有现金流（包括签单月），初始确认现值只使用预期未来部分",
        {
            "期末-预期未来-RA（Wlk）": pv_nb_eop_fut_ra_wlk,
            "期末-预期当期-RA（Wlk）": pv_nb_eop_cur_ra_wlk,
            "初始-预期未来-RA（Lkd）": pv_nb_ini_fut_ra_lkd,
            "NB_待分摊IFIE_计息_非金融风险调整": nb_ifie_accretion_ra
        },
        nb_ifie_accretion_ra,
        note="所有现值均从PV原材料数据读取，使用Wlk字段（加权初始确认利率）和Lkd字段（当月初始利率）"
    )
    
    # 3. NB_待分摊IFIE_利率变化的影响_赔付与费用
    # 公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]
    pv_nb_eop_cfa_rep_cur_claims = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt')
    pv_nb_eop_cfa_rep_wlk_claims = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Cla_Amt')
    pv_nb_eop_cfa_rep_cur_maint = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt')
    pv_nb_eop_cfa_rep_wlk_maint = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Mtn_Amt')
    
    nb_ifie_rate_change_claims = (
        pv_nb_eop_cfa_rep_cur_claims -
        pv_nb_eop_cfa_rep_wlk_claims +
        pv_nb_eop_cfa_rep_cur_maint -
        pv_nb_eop_cfa_rep_wlk_maint
    )
    
    logger.log_item(
        "NB_待分摊IFIE_利率变化的影响_赔付与费用",
        "[LC IFIE分摊] 新增合同待分摊IFIE_利率变化的影响_赔付与费用",
        "NB_待分摊IFIE_利率变化的影响_赔付与费用 = 【新增合同-期末预期-预期未来-预期赔付现金流-期末现值（期末利率）】-【新增合同-期末预期-预期未来-预期赔付现金流-期末现值（加权初始确认利率）】+【新增合同-期末预期-预期未来-预期维持费用现金流-期末现值（期末利率）】-【新增合同-期末预期-预期未来-预期维持费用现金流-期末现值（加权初始确认利率）】",
        {
            "期末-预期未来-赔付（Cur）": pv_nb_eop_cfa_rep_cur_claims,
            "期末-预期未来-赔付（Wlk）": pv_nb_eop_cfa_rep_wlk_claims,
            "期末-预期未来-维费（Cur）": pv_nb_eop_cfa_rep_cur_maint,
            "期末-预期未来-维费（Wlk）": pv_nb_eop_cfa_rep_wlk_maint,
            "NB_待分摊IFIE_利率变化的影响_赔付与费用": nb_ifie_rate_change_claims
        },
        nb_ifie_rate_change_claims,
        note="所有现值均从PV原材料数据读取，使用Cur字段（期末利率）和Wlk字段（加权初始确认利率）"
    )
    
    # 4. NB_待分摊IFIE_利率变化的影响_非金融风险调整
    # 公式：[Eop_Cfa_Rep_Cur] - [Eop_Cfa_Rep_Wlk]
    pv_nb_eop_cfa_rep_cur_ra = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Cur_Rad_Amt')
    pv_nb_eop_cfa_rep_wlk_ra = _pv_amount(pv_data, 'Pvfl_Nb_Eop_Cfa_Rep_Wlk_Rad_Amt')
    
    nb_ifie_rate_change_ra = (
        pv_nb_eop_cfa_rep_cur_ra -
        pv_nb_eop_cfa_rep_wlk_ra
    )
    
    logger.log_item(
        "NB_待分摊IFIE_利率变化的影响_非金融风险调整",
        "[LC IFIE分摊] 新增合同待分摊IFIE_利率变化的影响_非金融风险调整",
        "NB_待分摊IFIE_利率变化的影响_非金融风险调整 = 【新增合同-期末预期-预期未来-非金融风险调整-期末现值（期末利率）】-【新增合同-期末预期-预期未来-非金融风险调整-期末现值（加权初始确认利率）】",
        {
            "期末-预期未来-RA（Cur）": pv_nb_eop_cfa_rep_cur_ra,
            "期末-预期未来-RA（Wlk）": pv_nb_eop_cfa_rep_wlk_ra,
            "NB_待分摊IFIE_利率变化的影响_非金融风险调整": nb_ifie_rate_change_ra
        },
        nb_ifie_rate_change_ra,
        note="所有现值均从PV原材料数据读取，使用Cur字段（期末利率）和Wlk字段（加权初始确认利率）"
    )
    
    # 计算分摊结果
    nb_lc_ifie_claims_before_sign = (nb_ifie_accretion_claims + nb_ifie_rate_change_claims) * nb_lc_ifie_ratio
    nb_lc_ifie_ra_before_sign = (nb_ifie_accretion_ra + nb_ifie_rate_change_ra) * nb_lc_ifie_ratio
    nb_lc_ifie_total_before_sign = nb_lc_ifie_claims_before_sign + nb_lc_ifie_ra_before_sign
    
    # LC IFIE分摊应与LC本金同方向（正常保单为负，批减单为正）
    is_nb_lc_sign = (nb_initial_lc < 0) if (not is_reversal) else (nb_initial_lc > 0)
    if is_nb_lc_sign:
        lc_sign = Decimal('-1') if nb_initial_lc < 0 else Decimal('1')
        nb_lc_ifie_claims = nb_lc_ifie_claims_before_sign.copy_abs() * lc_sign
        nb_lc_ifie_ra = nb_lc_ifie_ra_before_sign.copy_abs() * lc_sign
        nb_lc_ifie_total = nb_lc_ifie_total_before_sign.copy_abs() * lc_sign
    else:
        nb_lc_ifie_claims = nb_lc_ifie_claims_before_sign
        nb_lc_ifie_ra = nb_lc_ifie_ra_before_sign
        nb_lc_ifie_total = nb_lc_ifie_total_before_sign
    
    logger.log_item(
        "NB_LC分摊IFIE_赔付与费用",
        "[LC IFIE分摊] 新增合同LC分摊IFIE_赔付与费用",
        "NB_LC分摊IFIE_赔付与费用 = (NB_待分摊IFIE_计息_赔付与费用 + NB_待分摊IFIE_利率变化的影响_赔付与费用) × NB_LC IFIE分摊比例",
        {
            "NB_待分摊IFIE_计息_赔付与费用": nb_ifie_accretion_claims,
            "NB_待分摊IFIE_利率变化的影响_赔付与费用": nb_ifie_rate_change_claims,
            "NB_LC IFIE分摊比例": nb_lc_ifie_ratio,
            "NB_LC分摊IFIE_赔付与费用（符号处理前）": nb_lc_ifie_claims_before_sign,
            "NB_LC分摊IFIE_赔付与费用": nb_lc_ifie_claims
        },
        nb_lc_ifie_claims,
        note=f"计算过程：({nb_ifie_accretion_claims} + {nb_ifie_rate_change_claims}) × {nb_lc_ifie_ratio} = {nb_lc_ifie_claims_before_sign}，符号处理：{'与LC同方向' if is_nb_lc_sign else '保持原值'}"
    )
    
    logger.log_item(
        "NB_LC分摊IFIE_非金融风险调整",
        "[LC IFIE分摊] 新增合同LC分摊IFIE_非金融风险调整",
        "NB_LC分摊IFIE_非金融风险调整 = (NB_待分摊IFIE_计息_非金融风险调整 + NB_待分摊IFIE_利率变化的影响_非金融风险调整) × NB_LC IFIE分摊比例",
        {
            "NB_待分摊IFIE_计息_非金融风险调整": nb_ifie_accretion_ra,
            "NB_待分摊IFIE_利率变化的影响_非金融风险调整": nb_ifie_rate_change_ra,
            "NB_LC IFIE分摊比例": nb_lc_ifie_ratio,
            "NB_LC分摊IFIE_非金融风险调整（符号处理前）": nb_lc_ifie_ra_before_sign,
            "NB_LC分摊IFIE_非金融风险调整": nb_lc_ifie_ra
        },
        nb_lc_ifie_ra,
        note=f"计算过程：({nb_ifie_accretion_ra} + {nb_ifie_rate_change_ra}) × {nb_lc_ifie_ratio} = {nb_lc_ifie_ra_before_sign}，符号处理：{'与LC同方向' if is_nb_lc_sign else '保持原值'}"
    )
    
    logger.log_item(
        "NB_LC分摊IFIE",
        "[LC IFIE分摊] 新增合同LC分摊IFIE合计",
        "NB_LC分摊IFIE = NB_LC分摊IFIE_赔付与费用 + NB_LC分摊IFIE_非金融风险调整",
        {
            "NB_LC分摊IFIE_赔付与费用": nb_lc_ifie_claims,
            "NB_LC分摊IFIE_非金融风险调整": nb_lc_ifie_ra,
            "NB_LC分摊IFIE": nb_lc_ifie_total
        },
        nb_lc_ifie_total,
        note=f"计算过程：{nb_lc_ifie_claims} + {nb_lc_ifie_ra} = {nb_lc_ifie_total}"
    )
    
    nb_lc_after_ifie = nb_initial_lc + nb_lc_ifie_total
    
    logger.log_item(
        "NB_分摊后IFIE后LC",
        "[LC IFIE分摊] 新增合同分摊后IFIE后LC",
        "NB_分摊后IFIE后LC = NB_年初LC + NB_LC分摊IFIE",
        {
            "NB_年初LC": nb_initial_lc,
            "NB_LC分摊IFIE": nb_lc_ifie_total,
            "NB_分摊后IFIE后LC": nb_lc_after_ifie
        },
        nb_lc_after_ifie,
        note=f"计算过程：{nb_initial_lc} + {nb_lc_ifie_total} = {nb_lc_after_ifie}"
    )
    
    context.nb_lc_after_ifie = nb_lc_after_ifie
    context.nb_lc_ifie_total = nb_lc_ifie_total
    context.nb_lc_ifie_cf = nb_lc_ifie_claims
    context.nb_lc_ifie_ra = nb_lc_ifie_ra
    
    # 保存待分摊IFIE项（用于计算LC分摊比例_合计）
    context.if_ifie_accretion_claims = if_ifie_accretion_claims
    context.if_ifie_accretion_ra = if_ifie_accretion_ra
    context.if_ifie_rate_change_claims = if_ifie_rate_change_claims
    context.if_ifie_rate_change_ra = if_ifie_rate_change_ra
    context.nb_ifie_accretion_claims = nb_ifie_accretion_claims
    context.nb_ifie_accretion_ra = nb_ifie_accretion_ra
    context.nb_ifie_rate_change_claims = nb_ifie_rate_change_claims
    context.nb_ifie_rate_change_ra = nb_ifie_rate_change_ra
    
    logger.log_item(
        "LC分摊IFIE明细",
        "[Sec 7] LC分摊IFIE明细（文档对照）",
        "LC分摊IFIE = IF_LC分摊IFIE + NB_LC分摊IFIE",
        {
            # IF 部分
            "IF_年初LC": if_bop_lc,
            "IF_LC IFIE分摊比例": if_lc_ifie_ratio,
            "IF_待分摊IFIE_计息_赔付与费用": if_ifie_accretion_claims,
            "IF_待分摊IFIE_计息_非金融风险调整": if_ifie_accretion_ra,
            "IF_待分摊IFIE_利率变化的影响_赔付与费用": if_ifie_rate_change_claims,
            "IF_待分摊IFIE_利率变化的影响_非金融风险调整": if_ifie_rate_change_ra,
            "IF_LC分摊IFIE_赔付与费用": if_lc_ifie_claims,
            "IF_LC分摊IFIE_非金融风险调整": if_lc_ifie_ra,
            "IF_LC分摊IFIE": if_lc_ifie_total,
            "IF_分摊后IFIE后LC": if_lc_after_ifie,
            
            # NB 部分
            "NB_新增LC": (nb_initial_lc.copy_abs() if is_nb_lc_sign else DECIMAL_ZERO),
            "NB_LC IFIE分摊比例": nb_lc_ifie_ratio,
            "NB_待分摊IFIE_计息_赔付与费用": nb_ifie_accretion_claims,
            "NB_待分摊IFIE_计息_非金融风险调整": nb_ifie_accretion_ra,
            "NB_待分摊IFIE_利率变化的影响_赔付与费用": nb_ifie_rate_change_claims,
            "NB_待分摊IFIE_利率变化的影响_非金融风险调整": nb_ifie_rate_change_ra,
            "NB_LC分摊IFIE_赔付与费用": nb_lc_ifie_claims,
            "NB_LC分摊IFIE_非金融风险调整": nb_lc_ifie_ra,
            "NB_LC分摊IFIE": nb_lc_ifie_total,
            "NB_分摊后IFIE后LC": nb_lc_after_ifie
        },
        if_lc_ifie_total + nb_lc_ifie_total,
        note="详细展示IF和NB的LC分摊IFIE逻辑"
    )


def _determine_cohort_status(
    cohort_state: CohortState,
    context: Any,
    logger: Any,
    policies: Optional[List[PolicyState]] = None
):
    """
    合同组状态判定（文档第8.5.5节，对应“建筑模型”里的 Net_trial + 合同组CSM/LC）

    Excel 公式口径简化为：
        IF_计息后CSM = IF_年初CSM + IF_CSM计息
        NB_计息后CSM = NB_新增CSM + NB_CSM计息
        IF_分摊后IFIE后LC = IF_年初LC + IF_LC分摊IFIE
        NB_分摊后IFIE后LC = NB_年初LC + NB_LC分摊IFIE

        Net_trial = IF_计息后CSM + NB_计息后CSM
                    + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC

        合同组CSM = IF(Net_trial >= 0, Net_trial, 0)
        合同组LC  = IF(Net_trial <  0, Net_trial, 0)

    本函数做的事情：
    1. 按上述口径计算 IF_计息后 / NB_计息后 CSM，以及 IF/NB 分摊后 LC；
    2. 得到 Net_trial 并据此判断合同组最终状态（盈利组/亏损组）；
    3. 将合同组 CSM/LC 写回：
       - context.end_csm_before_amort / context.end_lc_before_amort
       - cohort_state.net_trial / cohort_state.is_profitable
    4. 根据最终状态，对保单逐单做“Re-apportionment”（盈利组：清零 LC；亏损组：清零 CSM）
    """
    logger.log_section("Part 8.5.5: 合同组状态判定 (Cohort Status Determination) [Sec 8.5.5]")
    
    # 获取统一的CSM/LC字段
    # 修复：正确合并bop_csm和bop_lc，如果bop_csm > 0则为CSM，如果bop_lc < 0则为LC
    bop_csm_lc = _get_bop_csm_lc(context, cohort_state)
    # 分离IF的CSM和LC
    if_bop_csm = bop_csm_lc if bop_csm_lc >= 0 else DECIMAL_ZERO
    if_bop_lc = bop_csm_lc if bop_csm_lc < 0 else DECIMAL_ZERO
    # IF_计息后CSM = IF_年初CSM + IF_CSM计息（只计算CSM部分）
    # 修复：使用 context.if_interest_csm（只包含IF的计息），而不是 cohort_state.csm_interest（IF+NB合计）
    if_interest_csm = getattr(context, 'if_interest_csm', None) or DECIMAL_ZERO
    if_csm_post = if_bop_csm + if_interest_csm
    
    # 分离NB的CSM和LC
    nb_initial_csm = context.nb_initial_csm or DECIMAL_ZERO
    # 修复：nb_initial_lc 现在直接存储为负数（亏损），不需要再转换
    nb_initial_lc = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    # NB_计息后CSM = NB_新增CSM + NB_CSM计息（只计算CSM部分，LC不计息）
    nb_csm_post = nb_initial_csm + (context.nb_interest_csm or DECIMAL_ZERO)
    # NB_LC部分（不计息，但会加上IFIE分摊）
    nb_lc_base = nb_initial_lc
    
    # 获取LC的IFIE分摊额（变化额，不包含期初余额）
    if_lc_ifie_total = getattr(context, 'if_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_total = getattr(context, 'nb_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 计算净余额试算值（严格对齐文档图片）
    # Net_trial = IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC
    # 注意：文档公式中不包含"被CSM/LC吸收的变化"
    # 修复：if_lc_after_ifie 已经是(年初LC + IFIE分摊)后的余额，不应再次加 if_bop_lc
    # IF_分摊后IFIE后LC = IF_年初LC + IF_LC分摊IFIE
    if_lc_post = if_bop_lc + if_lc_ifie_total
    # 修复：nb_lc_after_ifie 已经是(新增LC + IFIE分摊)后的余额，不应再次加 nb_lc_base
    # NB_分摊后IFIE后LC = NB_新增LC + NB_LC分摊IFIE（LC不计息）
    nb_lc_post = nb_lc_base + nb_lc_ifie_total
    
    net_trial = if_csm_post + nb_csm_post + if_lc_post + nb_lc_post
    
    logger.log_item(
        "合同组净余额试算值",
        "[Sec 8.5.5] 步骤1：计算合同组净余额试算值（文档对照）",
        "Net_trial = IF_计息后CSM + NB_计息后CSM + IF_分摊后IFIE后LC + NB_分摊后IFIE后LC",
        {
            "IF_计息后CSM": if_csm_post,
            "NB_计息后CSM": nb_csm_post,
            "IF_分摊后IFIE后LC": if_lc_post,
            "NB_分摊后IFIE后LC": nb_lc_post,
            "Net_trial": net_trial
        },
        net_trial,
        note="严格按照文档公式：判定状态时不包含当期履约现金流变化（被CSM/LC吸收的变化）"
    )
    
    # 确定合同组最终状态
    is_reversal = getattr(context, 'is_reversal_policy', False)
    # 正常保单：net_trial >= 0 为盈利(CSM)，<0 为亏损(LC)
    # 批减单：符号逻辑相反（net_trial <= 0 为CSM，>0 为LC），且取值保持原符号（CSM为负，LC为正）
    if (not is_reversal and net_trial >= 0) or (is_reversal and net_trial <= 0):
        cohort_csm = net_trial
        cohort_lc = DECIMAL_ZERO
        if cohort_state:
            cohort_state.is_profitable = True
        status = "盈利 (Profitable)"
    else:
        cohort_csm = DECIMAL_ZERO
        cohort_lc = net_trial
        if cohort_state:
            cohort_state.is_profitable = False
        status = "亏损 (Onerous)"
    
    logger.log_item(
        "合同组最终状态",
        "[Sec 8.5.5] 步骤2：确定合同组最终状态",
        "IF(Net_trial ≥ 0, 盈利, 亏损)",
        {
            "Net_trial": net_trial,
            "合同组 CSM": cohort_csm,
            "合同组 LC": cohort_lc
        },
        net_trial,
        note=f"判定结果: {status}"
    )
    
    # 状态回写
    if policies and cohort_state:
        for policy in policies:
            if cohort_state.is_profitable:
                policy.initial_lc = DECIMAL_ZERO
            else:
                policy.initial_csm = DECIMAL_ZERO
        
        logger.log_item(
            "状态回写",
            "[Sec 8.5.5] 步骤3：状态回写（Re-apportionment）",
            "组盈利则LC清零，组亏损则CSM清零",
            {
                "保单数量": len(policies),
                "合同组状态": status
            },
            DECIMAL_ZERO
        )
    
    # 更新期末余额（摊销前，组级判定口径）
    # 正常保单：统一字段 CSM/LC >= 0 视为 CSM；< 0 视为 LC
    # 批减单：符号逻辑相反（<= 0 视为 CSM；> 0 视为 LC），且取值保持原符号（CSM为负，LC为正）
    cohort_csm_lc = cohort_csm + cohort_lc
    is_csm_bucket = (cohort_csm_lc >= 0) if (not is_reversal) else (cohort_csm_lc <= 0)
    if is_csm_bucket:
        context.end_csm_before_amort = cohort_csm_lc
        context.end_lc_before_amort = DECIMAL_ZERO
    else:
        context.end_csm_before_amort = DECIMAL_ZERO
        context.end_lc_before_amort = cohort_csm_lc
    # 将合同组CSM/LC（判定口径）显式写回到cohort_state和context，便于其他模块和报表直接引用
    if cohort_state:
        cohort_state.net_trial = net_trial
        cohort_state.eop_csm = cohort_csm
        cohort_state.eop_lc = cohort_lc
    # 在context中保留同样的组级视图字段（不影响原有end_csm_before_amort/end_lc_before_amort的使用）
    context.cohort_csm = cohort_csm
    context.cohort_lc = cohort_lc


def _calculate_csm_measurement(context, logger):
    """
    计算CSM计量（文档第8.2节：CSM摊销，对应“CSM vs LC 动态对冲机制”中的 CSM 部分）

    口径映射（与 Excel / 业务公式一致）：

    1. 前一阶段（合同组判定 + LC计量）已经得到：
       - 合同组CSM(判定期) = context.end_csm_before_amort
       - 合同组LC(判定期) = context.end_lc_before_amort
       - 被CSM/LC吸收的变化合计 = delta_csm_lc = context.exp_adj_csm_impact
       - 被LC吸收的变化_合计   = allocated_lc_exp_adj_total = context.lc_change

    2. 这里首先做“CSM vs LC 的动态对冲拆分”：
       - 被CSM吸收的变化 = 被CSM/LC吸收的变化合计 - 被LC吸收的变化_合计
         即：csm_absorbed_total = delta_csm_lc - allocated_lc_exp_adj_total
       - 再拆分为：
         - 被CSM吸收的现金流变化 = 预期现金流变化合计 - 被LC吸收的变化_预期现金流
         - 被CSM吸收的RA变化   = 被CSM吸收的变化 - 被CSM吸收的现金流变化

    3. 然后进入 CSM 摊销阶段：
       - 摊销前CSM = 合同组CSM(判定期) + 被CSM吸收的变化
       - 摊销金额  = -(摊销前CSM × CSM摊销比例)
       - 期末CSM   = 摊销前CSM + 摊销金额

    最终结果：
       - context.csm_amort_amount  : 摊销的CSM
       - context.end_csm_final     : 期末CSM余额（供 revenue / LRC closing 使用）
       - context.csm_amort_ratio   : 当期CSM摊销比例（供日志和其他模块参考）
    """
    logger.log_section("Part 8.2: CSM计量 (CSM Measurement) [Sec 8.2]")
    
    # 获取必要的基础数据
    cohort_csm = getattr(context, 'end_csm_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO # 这里的end_csm_before_amort来自合同组判定，仅包含期初+新增+计息+IFIE
    cohort_lc = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    
    delta_csm_lc = getattr(context, 'exp_adj_csm_impact', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_cf_total = getattr(context, 'delta_cf_total', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_ra = delta_csm_lc - delta_cf_total
    
    # 获取LC计量结果（因为现在CSM计量在LC计量之后，所以可以获取）
    allocated_lc_exp_adj_total = getattr(context, 'lc_change', DECIMAL_ZERO) or DECIMAL_ZERO # 被LC吸收的变化_合计
    allocated_lc_exp_adj_cf = getattr(context, 'allocated_lc_exp_adj_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    allocated_lc_exp_adj_ra = getattr(context, 'allocated_lc_exp_adj_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 计算被CSM吸收的变化
    # 文档逻辑：如果合同组是CSM状态，或者虽然是LC状态但变化足够大能转回CSM，则：
    # 被CSM吸收的变化 = 总变化 - 被LC吸收的变化
    # 这里的公式推导：Total = CSM_Absorbed + LC_Absorbed => CSM_Absorbed = Total - LC_Absorbed
    
    # 验证文档中的复杂IF公式：
    # IF(OR(AND(合同组CSM>0,SUM(...)>=0),AND(合同组CSM=0,SUM(...)>=0)), SUM(被CSM/LC吸收的变化合计, 年初LC...分摊LC), -SUM(年初CSM...CSM计息))
    # 其实 SUM(被CSM/LC吸收的变化合计, 年初LC...分摊LC) 就是 剩余能给CSM的部分（即总变化 + LC转回的部分）
    # 而 -SUM(年初CSM...CSM计息) 就是 把CSM扣光
    
    # 既然我们已经有了准确的 allocated_lc_exp_adj_total (被LC吸收的变化)，我们可以直接用减法：
    # 注意：allocated_lc_exp_adj_total 在LC计量模块计算时，如果 LC 增加是负数，减少（转回）是正数？
    # 检查 LC 计量逻辑：
    # allocated_lc_exp_adj_total = -(bop_lc_total + ...) 如果不够扣
    # allocated_lc_exp_adj_total = delta_csm_lc + bop_csm... 如果转为盈利
    
    # 统一逻辑：总变化 (delta_csm_lc) = CSM吸收部分 + LC吸收部分
    # 所以：CSM吸收部分 = delta_csm_lc - LC吸收部分
    csm_absorbed_total = delta_csm_lc - allocated_lc_exp_adj_total
    
    # 被CSM吸收的现金流变化
    csm_absorbed_cf = delta_cf_total - allocated_lc_exp_adj_cf
    
    # 被CSM吸收的非金融风险调整变化
    # 注意：delta_ra 在 fulfillment_cashflow_changes 中是 (End - Beg)，代表RA增加（不利）
    # 在 csm_absorbed 公式中，不利变化会导致 CSM 减少。
    # 文档公式：被CSM吸收的非金融风险调整变化 = 非金融风险调整变化 - 被LC吸收的变化_非金融风险调整
    # 这里直接相减即可，符号会自动处理。
    # 但要注意 delta_ra 的符号定义。在 fulfillment 模块：delta_csm_lc = delta_cf - delta_ra
    # 所以“非金融风险调整变化”对 CSM 的影响是 -delta_ra
    # 文档中写的是“非金融风险调整变化”，可能指绝对值变化量？
    # 让我们看文档公式：被CSM吸收的非金融风险调整变化 = 非金融风险调整变化 - 被LC吸收的变化_非金融风险调整
    # 这里的“变化”应该是指“对盈余的影响额”。
    # 在 fulfillment 模块，我们定义 delta_ra 为 (End - Beg)，即增加量。
    # 对 CSM 的影响是负的。
    # 如果我们保持 delta_csm_lc = delta_cf - delta_ra，那么这里的“变化”就是指“影响额”。
    # 修正：fulfillment 模块计算的 delta_csm_lc 已经是“影响额”。
    # 但 delta_cf_total 是 (Prem - Claims - Exp)，也是影响额。
    # delta_ra 是 (End - Beg)，是RA增加量。
    # 所以“非金融风险调整变化”这一项，如果要作为加项，应该是 -delta_ra。
    # 让我们假设 context.delta_ra 存储的是 RA 的增加量。
    # 那么 对CSM的影响 = -delta_ra。
    # 被LC吸收的RA影响 = allocated_lc_exp_adj_ra (在LC计量中计算，应该是负数如果RA增加且被LC吸收)
    # 所以 csm_absorbed_ra = (-delta_ra) - allocated_lc_exp_adj_ra
    # 但为了与文档字面一致，如果文档说“非金融风险调整变化”，可能指的就是那个增加量。
    # 让我们回看 fulfillment 模块，context.delta_ra 存的是增加量。
    # 而 delta_csm_lc 存的是影响额 (cf - ra)。
    # 如果我们用 csm_absorbed_total (影响额) - csm_absorbed_cf (影响额)，剩下的就是 csm_absorbed_ra (影响额)。
    csm_absorbed_ra = csm_absorbed_total - csm_absorbed_cf
    
    # 更新 Context
    context.csm_absorbed = csm_absorbed_total
    
    logger.log_item(
        "被CSM吸收的变化",
        "[Sec 8.2] 被CSM吸收的变化（基于LC计量结果推导）",
        "被CSM吸收的变化 = 被CSM/LC吸收的变化合计 - 被LC吸收的变化\n被CSM吸收的现金流 = 预期现金流变化(影响额) - 被LC吸收的现金流\n被CSM吸收的RA = RA变化(影响额) - 被LC吸收的RA",
        {
            "被CSM/LC吸收的变化合计": delta_csm_lc,
            "被LC吸收的变化": allocated_lc_exp_adj_total,
            "被CSM吸收的变化": csm_absorbed_total,
            "其中：被CSM吸收的现金流变化": csm_absorbed_cf,
            "其中：被CSM吸收的RA变化": csm_absorbed_ra
        },
        csm_absorbed_total,
        note="通过总变化减去LC吸收部分得到CSM吸收部分"
    )
    
    # 计算CSM摊销比例（使用覆盖单元动态比例法）
    start_of_year = date(context.year, 1, 1)
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
        # 兼容旧代码
        csm_amort_ratio = Decimal('0')
    
    # 计算摊销前CSM余额（含吸收的变化）
    # 这里的 cohort_csm 是从 Contract Status Determination 来的，只含 期初+新增+计息+IFIE
    # 所以要加上 被CSM吸收的变化
    csm_before_amort_adjusted = cohort_csm + csm_absorbed_total
    
    # 计算CSM摊销金额
    if csm_before_amort_adjusted <= 0:
        context.csm_amort_amount = DECIMAL_ZERO
        csm_final = csm_before_amort_adjusted
    else:
        context.csm_amort_amount = -(csm_before_amort_adjusted * csm_amort_ratio)
        csm_final = csm_before_amort_adjusted + context.csm_amort_amount
    
    context.end_csm_final = csm_final
    context.csm_amort_ratio = csm_amort_ratio # 保存供后续使用
    
    logger.log_item(
        "CSM摊销与期末余额",
        "[Sec 8.2] CSM摊销与期末余额计算",
        "摊销前CSM = 合同组CSM(判定期) + 被CSM吸收的变化\nCSM摊销 = -摊销前CSM * 摊销比例\n期末CSM = 摊销前CSM + CSM摊销",
        {
            "合同组CSM(判定期)": cohort_csm,
            "被CSM吸收的变化": csm_absorbed_total,
            "摊销前CSM": csm_before_amort_adjusted,
            "摊销比例": csm_amort_ratio,
            "CSM摊销": context.csm_amort_amount,
            "期末CSM": csm_final
        },
        csm_final
    )


def _calculate_lc_measurement(context, logger):
    """
    计算LC计量（完整的LC计量逻辑）
    
    包括：
    1. 预期现金流部分
    2. 非金融风险调整部分
    3. 合计部分
    
    Args:
        context: 计算上下文
        logger: 日志记录器
    """
    logger.log_section("Part LC: LC计量 (LC Measurement)")
    
    # 获取评估月
    eop_month_str = context.val_month_str
    # 所有数据都从当前评估期的PV数据读取

    # 批减单标记：符号逻辑相反（CSM<=0，LC>0）
    is_reversal = getattr(context, 'is_reversal_policy', False)
    
    # 获取PV数据
    pv_data = context.pv_source_data.get_data(eop_month_str)
    
    if pv_data is None:
        raise ValueError(f"❌ 错误: 找不到评估月 {eop_month_str} 的PV原材料数据！")
    
    # 获取CSM摊销比例（用于LC调整判断）
    # 注意：CSM摊销比例应该在revenue模块中计算，但LC计量在revenue之前运行
    # 这里先尝试从context获取，如果没有则使用IACF摊销比例作为参考
    csm_amort_ratio = getattr(context, 'csm_amort_ratio', None)
    if csm_amort_ratio is None:
        # 尝试从csm_amort_amount和end_csm_before_amort计算
        csm_amort_amount = getattr(context, 'csm_amort_amount', None)
        end_csm_before_amort = getattr(context, 'end_csm_before_amort', None)
        if csm_amort_amount is not None and end_csm_before_amort is not None and end_csm_before_amort != 0:
            csm_amort_ratio = (csm_amort_amount if csm_amort_amount > 0 else -csm_amort_amount) / end_csm_before_amort
        else:
            # 如果没有，使用IACF摊销比例作为参考
            csm_amort_ratio = getattr(context, 'iacf_amort_ratio', Decimal('0')) or Decimal('0')
    csm_amort_ratio = Decimal(str(csm_amort_ratio)) if csm_amort_ratio is not None else Decimal('0')
    
    # 获取基础数据
    bop_lc = getattr(context, 'bop_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_lc_total = getattr(context, 'nb_initial_lc', DECIMAL_ZERO) or DECIMAL_ZERO
    if_lc_ifie_total = getattr(context, 'if_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_total = getattr(context, 'nb_lc_ifie_total', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 获取被CSM/LC吸收的变化合计
    delta_csm_lc = getattr(context, 'exp_adj_csm_impact', DECIMAL_ZERO) or DECIMAL_ZERO
    delta_cf_total = getattr(context, 'delta_cf_total', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # ==========================================================================================
    # 先计算合计部分（因为被LC吸收的变化_预期现金流需要用到合计部分的结果）
    # ==========================================================================================
    logger.log_section("LC计量_合计部分（先计算）")
    
    # 年初LC余额_合计：IF_年初LC
    bop_lc_total = bop_lc
    
    # 当年新增LC_合计：NB_新增LC
    # nb_initial_lc_total 已在上面获取
    
    # LC分摊IFIE_合计：IF_LC分摊IFIE + NB_LC分摊IFIE
    lc_ifie_total = if_lc_ifie_total + nb_lc_ifie_total
    
    # ==========================================================================================
    # 计算 LC分摊比例_合计（用于计算"分摊的LC"）
    # ==========================================================================================
    # 分子：合同组LC（从context获取，已在合同组状态判定中计算，包含IFIE分摊）
    cohort_lc_for_ratio = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    
    # 分母：包含IF和NB的预期现金流，以及所有IFIE相关项
    if pv_data is None:
        lc_allocation_ratio_total = DECIMAL_ZERO
    else:
        # 1. IF的预期现金流（取上年12月期末值，即年初现值LCU）
        pv_if_beg_claims = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt', DECIMAL_ZERO)
        pv_if_beg_maint = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt', DECIMAL_ZERO)
        pv_if_beg_ra = pv_data.get_field('Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt', DECIMAL_ZERO)
        
        # 2. NB的预期现金流（初始确认现值）
        pv_nb_init_claims = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt', DECIMAL_ZERO)
        pv_nb_init_maint = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt', DECIMAL_ZERO)
        pv_nb_init_ra = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt', DECIMAL_ZERO)
        
        # 3. IFIE相关项（从context获取，已在_calculate_lc_ifie_allocation中计算）
        if_ifie_accretion_claims = getattr(context, 'if_ifie_accretion_claims', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_ifie_accretion_claims = getattr(context, 'nb_ifie_accretion_claims', DECIMAL_ZERO) or DECIMAL_ZERO
        if_ifie_accretion_ra = getattr(context, 'if_ifie_accretion_ra', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_ifie_accretion_ra = getattr(context, 'nb_ifie_accretion_ra', DECIMAL_ZERO) or DECIMAL_ZERO
        if_ifie_rate_change_claims = getattr(context, 'if_ifie_rate_change_claims', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_ifie_rate_change_claims = getattr(context, 'nb_ifie_rate_change_claims', DECIMAL_ZERO) or DECIMAL_ZERO
        if_ifie_rate_change_ra = getattr(context, 'if_ifie_rate_change_ra', DECIMAL_ZERO) or DECIMAL_ZERO
        nb_ifie_rate_change_ra = getattr(context, 'nb_ifie_rate_change_ra', DECIMAL_ZERO) or DECIMAL_ZERO
        
        # 计算分母合计
        denominator_total = (
            pv_if_beg_claims + pv_nb_init_claims +  # IF和NB的预期赔付现金流
            pv_if_beg_maint + pv_nb_init_maint +    # IF和NB的预期维持费用现金流
            pv_if_beg_ra + pv_nb_init_ra +          # IF和NB的预期非金融风险调整
            if_ifie_accretion_claims + nb_ifie_accretion_claims +  # IFIE计息_赔付与费用
            if_ifie_accretion_ra + nb_ifie_accretion_ra +          # IFIE计息_非金融风险调整
            if_ifie_rate_change_claims + nb_ifie_rate_change_claims +  # IFIE利率变化的影响_赔付与费用
            if_ifie_rate_change_ra + nb_ifie_rate_change_ra           # IFIE利率变化的影响_非金融风险调整
        )
        
        # 计算比例
        # 正常保单：合同组LC < 0 才计算；批减单：合同组LC > 0 才计算（符号逻辑相反）
        is_lc_for_ratio = (cohort_lc_for_ratio < 0) if (not is_reversal) else (cohort_lc_for_ratio > 0)
        if is_lc_for_ratio and denominator_total > 0:
            lc_allocation_ratio_total = cohort_lc_for_ratio.copy_abs() / denominator_total
        else:
            lc_allocation_ratio_total = Decimal('0')
        
        # 记录日志
        logger.log_item(
            "LC分摊比例_合计",
            "[LC计量] LC分摊比例_合计（用于计算分摊的LC）",
            "LC分摊比例_合计 = IF(合同组LC<0, 合同组LC / (SUM(IF和NB的预期现金流 + 所有IFIE相关项)), 0)",
            {
                "合同组LC（分子）": cohort_lc_for_ratio,
                "IF_预期赔付现金流（年初现值LCU）": pv_if_beg_claims,
                "IF_预期维持费用现金流（年初现值LCU）": pv_if_beg_maint,
                "IF_预期非金融风险调整（年初现值LCU）": pv_if_beg_ra,
                "NB_预期赔付现金流（初始确认现值）": pv_nb_init_claims,
                "NB_预期维持费用现金流（初始确认现值）": pv_nb_init_maint,
                "NB_预期非金融风险调整（初始确认现值）": pv_nb_init_ra,
                "IF_待分摊IFIE_计息_赔付与费用": if_ifie_accretion_claims,
                "NB_待分摊IFIE_计息_赔付与费用": nb_ifie_accretion_claims,
                "IF_待分摊IFIE_计息_非金融风险调整": if_ifie_accretion_ra,
                "NB_待分摊IFIE_计息_非金融风险调整": nb_ifie_accretion_ra,
                "IF_待分摊IFIE_利率变化的影响_赔付与费用": if_ifie_rate_change_claims,
                "NB_待分摊IFIE_利率变化的影响_赔付与费用": nb_ifie_rate_change_claims,
                "IF_待分摊IFIE_利率变化的影响_非金融风险调整": if_ifie_rate_change_ra,
                "NB_待分摊IFIE_利率变化的影响_非金融风险调整": nb_ifie_rate_change_ra,
                "分母合计": denominator_total,
                "LC分摊比例_合计": lc_allocation_ratio_total
            },
            lc_allocation_ratio_total,
            note="用于计算'分摊的LC'，替代原来的nb_lc_ratio"
        )
    
    # 分摊的LC_合计：（有效合同+新增合同的所有预期当期现金流）× LC分摊比例_合计
    # 注意：正数表示减少LC亏损（LC余额绝对值减少），因为当现金流释放时，亏损应该被摊销
    if pv_data is None:
        allocated_lc_total = DECIMAL_ZERO
    else:
        pv_if_cur_claims = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_if_cur_maint = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        pv_if_cur_ra = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        # 新增合同-初始确认-预期当期-现金流-期末现值（加权初始确认利率）
        # 从当前评估月的PV数据读取
        pv_nb_cur_claims = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_nb_cur_maint = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        pv_nb_cur_ra = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        allocated_lc_total = (pv_if_cur_claims + pv_if_cur_maint + pv_if_cur_ra + 
                              pv_nb_cur_claims + pv_nb_cur_maint + pv_nb_cur_ra) * lc_allocation_ratio_total
    
    # 被LC吸收的变化_合计：复杂的IF条件判断
    # IF(OR(AND(合同组LC<0,SUM(合同组LC, 分摊的LC，被CSM/LC吸收的变化合计)<0),AND(合同组LC=0,SUM(合同组CSM, 被CSM/LC吸收的变化合计)<0)),
    #     SUM(被CSM/LC吸收的变化合计, 年初CSM余额，当年新增CSM，CSM计息),
    #     -SUM(年初LC余额_合计，当年新增LC_合计，LC分摊IFIE_合计，分摊的LC_合计))
    cohort_lc = getattr(context, 'end_lc_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    cohort_csm = getattr(context, 'end_csm_before_amort', DECIMAL_ZERO) or DECIMAL_ZERO
    bop_csm = getattr(context, 'bop_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_initial_csm = getattr(context, 'nb_initial_csm', DECIMAL_ZERO) or DECIMAL_ZERO
    csm_interest = (getattr(context, 'if_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO) + (getattr(context, 'nb_interest_csm', DECIMAL_ZERO) or DECIMAL_ZERO)
    
    sum_lc_test = cohort_lc + allocated_lc_total + delta_csm_lc
    sum_csm_test = cohort_csm + delta_csm_lc
    
    # 正常保单：LC<0；批减单：LC>0（符号逻辑相反）
    is_lc_bucket = (cohort_lc < 0) if (not is_reversal) else (cohort_lc > 0)
    lc_stays_lc = (sum_lc_test < 0) if (not is_reversal) else (sum_lc_test > 0)
    csm_turns_lc = (sum_csm_test < 0) if (not is_reversal) else (sum_csm_test > 0)

    if (is_lc_bucket and lc_stays_lc) or ((not is_lc_bucket) and csm_turns_lc):
        allocated_lc_exp_adj_total = delta_csm_lc + bop_csm + nb_initial_csm + csm_interest
    else:
        allocated_lc_exp_adj_total = -(bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total)
    
    # 待调整LC余额_合计（用于判断被LC吸收的变化_预期现金流）
    lc_balance_to_adjust_total = bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total + allocated_lc_exp_adj_total
    
    # ==========================================================================================
    # 预期现金流部分
    # ==========================================================================================
    logger.log_section("LC计量_预期现金流部分")
    
    # 年初LC余额_预期现金流：直接取数（简化处理，假设年初LC余额全部为预期现金流）
    bop_lc_cf = bop_lc
    
    # 当年新增LC_预期现金流：按比例分配
    # 分母：新增合同-初始确认-预期未来-（赔付+维费+RA）-初始确认现值（当月初始利率）
    # 从当前评估月的PV数据读取
    if pv_data is None:
        nb_initial_lc_cf = DECIMAL_ZERO
    else:
        # 获取新增合同初始确认现值（当月初始利率）
        pv_nb_init_claims = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt', DECIMAL_ZERO)
        pv_nb_init_maint = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt', DECIMAL_ZERO)
        pv_nb_init_ra = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt', DECIMAL_ZERO)
        
        denom_nb_init = pv_nb_init_claims + pv_nb_init_maint + pv_nb_init_ra
        if denom_nb_init > 0:
            nb_initial_lc_cf = nb_initial_lc_total * (pv_nb_init_claims + pv_nb_init_maint) / denom_nb_init
        else:
            nb_initial_lc_cf = DECIMAL_ZERO
    
    # LC分摊IFIE_预期现金流：IF_LC分摊IFIE_赔付与费用 + NB_LC分摊IFIE_赔付与费用
    if_lc_ifie_cf = getattr(context, 'if_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_cf = getattr(context, 'nb_lc_ifie_cf', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
    
    # 分摊的LC_预期现金流：（有效合同+新增合同的预期当期赔付和维费）× LC分摊比例
    # 注意：正数表示减少LC亏损（LC余额绝对值减少），因为当现金流释放时，亏损应该被摊销
    if pv_data is None:
        allocated_lc_cf = DECIMAL_ZERO
    else:
        # 有效合同-年初预期-预期当年-赔付/维费现金流-期末现值（加权初始确认利率）
        pv_if_cur_claims = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_if_cur_maint = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        
        # 新增合同-初始确认-预期当期-赔付/维费现金流-期末现值（加权初始确认利率）
        # 从当前评估月的PV数据读取
        pv_nb_cur_claims = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Cla_Amt', DECIMAL_ZERO)
        pv_nb_cur_maint = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Mtn_Amt', DECIMAL_ZERO)
        
        allocated_lc_cf = (pv_if_cur_claims + pv_if_cur_maint + pv_nb_cur_claims + pv_nb_cur_maint) * lc_allocation_ratio_total
    
    # 被LC吸收的变化_预期现金流
    # IF(待调整LC余额_合计=0, -SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC), 被LC吸收的变化_合计*IFERROR(预期现金流变化合计/被CSM/LC吸收的变化合计,0))
    if lc_balance_to_adjust_total == 0:
        # 如果待调整LC余额_合计=0，则等于负的SUM(年初LC余额，当年新增LC，LC分摊IFIE，分摊的LC)
        allocated_lc_exp_adj_cf = -(bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total)
    else:
        # 否则按比例分配
        if delta_csm_lc != 0:
            ratio_cf = delta_cf_total / delta_csm_lc if delta_csm_lc != 0 else DECIMAL_ZERO
            allocated_lc_exp_adj_cf = allocated_lc_exp_adj_total * ratio_cf
        else:
            allocated_lc_exp_adj_cf = DECIMAL_ZERO
    
    # 待调整LC余额_预期现金流
    lc_balance_to_adjust_cf = bop_lc_cf + nb_initial_lc_cf + lc_ifie_cf + allocated_lc_cf + allocated_lc_exp_adj_cf
    
    # LC调整_预期现金流：如果CSM摊销比例=100%，则等于负的待调整LC余额_预期现金流；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_cf = -lc_balance_to_adjust_cf
    else:
        lc_adjust_cf = DECIMAL_ZERO
    
    # 期末LC余额_预期现金流
    end_lc_cf = lc_balance_to_adjust_cf + lc_adjust_cf
    
    # 保存到context（供revenue模块和其他模块使用）
    context.lc_adjust_cf = lc_adjust_cf
    context.allocated_lc_cf = allocated_lc_cf  # 保存分摊的LC_预期现金流，供revenue模块使用
    context.allocated_lc_exp_adj_cf = allocated_lc_exp_adj_cf  # 保存被LC吸收的变化_预期现金流，用于亏损合同损益拆分
    context.end_lc_cf = end_lc_cf  # 保存期末LC余额_预期现金流，用于未到期责任负债拆分
    context.nb_initial_lc_cf = nb_initial_lc_cf  # 保存当年新增LC_预期现金流，用于亏损合同损益拆分
    
    logger.log_item(
        "LC计量_预期现金流",
        "[LC计量] 预期现金流部分的LC计量",
        "待调整LC余额_预期现金流 = SUM(年初LC余额_预期现金流, 当年新增LC_预期现金流, LC分摊IFIE_预期现金流, 分摊的LC_预期现金流, 被LC吸收的变化_预期现金流)\nLC调整_预期现金流 = IF(CSM摊销比例=100%, -待调整LC余额_预期现金流, 0)\n期末LC余额_预期现金流 = 待调整LC余额_预期现金流 + LC调整_预期现金流",
        {
            "年初LC余额_预期现金流": bop_lc_cf,
            "当年新增LC_预期现金流": nb_initial_lc_cf,
            "LC分摊IFIE_预期现金流": lc_ifie_cf,
            "分摊的LC_预期现金流": allocated_lc_cf,
            "被LC吸收的变化_预期现金流": allocated_lc_exp_adj_cf,
            "待调整LC余额_预期现金流": lc_balance_to_adjust_cf,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_预期现金流": lc_adjust_cf,
            "期末LC余额_预期现金流": end_lc_cf
        },
        end_lc_cf,
        note="LC调整_预期现金流供revenue模块使用"
    )
    
    # ==========================================================================================
    # 非金融风险调整部分
    # ==========================================================================================
    logger.log_section("LC计量_非金融风险调整部分")
    
    # 年初LC余额_非金融风险调整：直接取数（简化处理，假设为0）
    bop_lc_ra = DECIMAL_ZERO
    
    # 当年新增LC_非金融风险调整：当年新增LC_合计 - 当年新增LC_预期现金流
    nb_initial_lc_ra = nb_initial_lc_total - nb_initial_lc_cf
    
    # LC分摊IFIE_非金融风险调整：IF_LC分摊IFIE_非金融风险调整 + NB_LC分摊IFIE_非金融风险调整
    if_lc_ifie_ra = getattr(context, 'if_lc_ifie_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    nb_lc_ifie_ra = getattr(context, 'nb_lc_ifie_ra', DECIMAL_ZERO) or DECIMAL_ZERO
    lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
    
    # 分摊的LC_非金融风险调整：（有效合同+新增合同的预期当期非金融风险调整）× LC分摊比例
    # 注意：正数表示减少LC亏损（LC余额绝对值减少），因为当非金融风险调整释放时，亏损应该被摊销
    if pv_data is None:
        pv_if_cur_ra = DECIMAL_ZERO
        pv_nb_cur_ra = DECIMAL_ZERO
        allocated_lc_ra = DECIMAL_ZERO
    else:
        # 有效合同-年初预期-预期当年-非金融风险调整-期末现值（加权初始确认利率）
        pv_if_cur_ra = pv_data.get_field('Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        # 新增合同-初始确认-预期当期-非金融风险调整-期末现值（加权初始确认利率）
        # 从当前评估月的PV数据读取
        pv_nb_cur_ra = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rep_Wlk_Rad_Amt', DECIMAL_ZERO)
        
        allocated_lc_ra = (pv_if_cur_ra + pv_nb_cur_ra) * lc_allocation_ratio_total
    
    # 被LC吸收的变化_非金融风险调整：被LC吸收的变化_合计 - 被LC吸收的变化_预期现金流
    # 注意：这里使用合计部分计算出的allocated_lc_exp_adj_total
    allocated_lc_exp_adj_ra = allocated_lc_exp_adj_total - allocated_lc_exp_adj_cf
    
    # 待调整LC余额_非金融风险调整
    lc_balance_to_adjust_ra = bop_lc_ra + nb_initial_lc_ra + lc_ifie_ra + allocated_lc_ra + allocated_lc_exp_adj_ra
    
    # LC调整_非金融风险调整：如果CSM摊销比例=100%，则等于负的待调整LC余额_非金融风险调整；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_ra = -lc_balance_to_adjust_ra
    else:
        lc_adjust_ra = DECIMAL_ZERO
    
    # 期末LC余额_非金融风险调整
    end_lc_ra = lc_balance_to_adjust_ra + lc_adjust_ra
    
    # 保存到context（供revenue模块和其他模块使用）
    context.lc_adjust_ra = lc_adjust_ra
    context.allocated_lc_ra = allocated_lc_ra  # 保存分摊的LC_非金融风险调整，供revenue模块使用
    context.allocated_lc_exp_adj_ra = allocated_lc_exp_adj_ra  # 保存被LC吸收的变化_非金融风险调整，用于亏损合同损益拆分
    context.end_lc_ra = end_lc_ra  # 保存期末LC余额_非金融风险调整，用于未到期责任负债拆分
    context.nb_initial_lc_ra = nb_initial_lc_ra  # 保存当年新增LC_非金融风险调整，用于亏损合同损益拆分
    
    # 记录详细计算过程（非金融风险调整）
    _log_lc_measurement_ra_details(
        logger,
        bop_lc_ra,
        nb_initial_lc_total,
        nb_initial_lc_cf,
        nb_initial_lc_ra,
        if_lc_ifie_ra,
        nb_lc_ifie_ra,
        lc_ifie_ra,
        pv_if_cur_ra,
        pv_nb_cur_ra,
        lc_allocation_ratio_total,
        allocated_lc_ra,
        allocated_lc_exp_adj_total,
        allocated_lc_exp_adj_cf,
        allocated_lc_exp_adj_ra,
        lc_balance_to_adjust_ra,
        csm_amort_ratio,
        lc_adjust_ra,
        end_lc_ra,
    )
    
    logger.log_item(
        "LC计量_非金融风险调整",
        "[LC计量] 非金融风险调整部分的LC计量",
        "待调整LC余额_非金融风险调整 = SUM(年初LC余额_非金融风险调整, 当年新增LC_非金融风险调整, LC分摊IFIE_非金融风险调整, 分摊的LC_非金融风险调整, 被LC吸收的变化_非金融风险调整)\nLC调整_非金融风险调整 = IF(CSM摊销比例=100%, -待调整LC余额_非金融风险调整, 0)\n期末LC余额_非金融风险调整 = 待调整LC余额_非金融风险调整 + LC调整_非金融风险调整",
        {
            "年初LC余额_非金融风险调整": bop_lc_ra,
            "当年新增LC_非金融风险调整": nb_initial_lc_ra,
            "LC分摊IFIE_非金融风险调整": lc_ifie_ra,
            "分摊的LC_非金融风险调整": allocated_lc_ra,
            "被LC吸收的变化_非金融风险调整": allocated_lc_exp_adj_ra,
            "待调整LC余额_非金融风险调整": lc_balance_to_adjust_ra,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_非金融风险调整": lc_adjust_ra,
            "期末LC余额_非金融风险调整": end_lc_ra
        },
        end_lc_ra,
        note="LC调整_非金融风险调整供revenue模块使用"
    )
    
    # ==========================================================================================
    # 合计部分（最终汇总和记录日志）
    # ==========================================================================================
    logger.log_section("LC计量_合计部分（最终汇总）")
    
    # 注意：合计部分的主要计算已在上面完成，这里只是汇总和记录日志
    # 待调整LC余额_合计已在上面计算
    
    # LC调整_合计：如果CSM摊销比例=100%，则等于负的待调整LC余额_合计；否则为0
    if csm_amort_ratio >= Decimal('1'):
        lc_adjust_total = -lc_balance_to_adjust_total
    else:
        lc_adjust_total = DECIMAL_ZERO
    
    # 期末LC余额_合计
    end_lc_total = lc_balance_to_adjust_total + lc_adjust_total
    
    # 保存到context
    context.lc_change = allocated_lc_exp_adj_total
    context.end_lc_final = end_lc_total
    context.allocated_lc_total = allocated_lc_total  # 保存LC摊销（分摊的LC_合计）供汇总使用
    
    logger.log_item(
        "LC计量_合计",
        "[LC计量] 合计部分的LC计量",
        "待调整LC余额_合计 = SUM(年初LC余额_合计, 当年新增LC_合计, LC分摊IFIE_合计, 分摊的LC_合计, 被LC吸收的变化_合计)\nLC调整_合计 = IF(CSM摊销比例=100%, -待调整LC余额_合计, 0)\n期末LC余额_合计 = 待调整LC余额_合计 + LC调整_合计",
        {
            "年初LC余额_合计": bop_lc_total,
            "当年新增LC_合计": nb_initial_lc_total,
            "LC分摊IFIE_合计": lc_ifie_total,
            "分摊的LC_合计": allocated_lc_total,
            "被LC吸收的变化_合计": allocated_lc_exp_adj_total,
            "待调整LC余额_合计": lc_balance_to_adjust_total,
            "CSM摊销比例": csm_amort_ratio,
            "LC调整_合计": lc_adjust_total,
            "期末LC余额_合计": end_lc_total
        },
        end_lc_total,
        note="完整的LC计量逻辑，包括预期现金流、非金融风险调整和合计三部分"
    )


def run(
    context,
    logger,
    cohort_state: CohortState = None,
    policy_state: PolicyState = None,
    policies: List[PolicyState] = None,
    assumptions: Assumptions = None
):
    """
    执行CSM/LC计量
    
    对应文档：
    - 第6节：CSM计息
    - 第7节：LC分摊IFIE
    - 第8.5.5节：合同组CSM/LC判断
    - 第8.2节：CSM计量
    - LC计量
    
    Args:
        context: 计算上下文
        logger: 日志记录器
        cohort_state: 合同组状态
        policy_state: 保单状态（用于CSM计息）
        policies: 保单列表（用于合同组状态判定和CSM摊销）
        assumptions: 精算假设（可选）
    """
    logger.log_section("Part 3-8.5.5: CSM/LC计量 (CSM/LC Measurement)")
    
    # 步骤1：CSM计息
    _calculate_csm_interest(context, logger, cohort_state, policy_state)
    
    # 步骤2：LC分摊IFIE（需要在IFIE模块之后调用，这里简化处理）
    # 注意：完整的LC IFIE分摊应在IFIE模块中完成，这里只做基础计算
    _calculate_lc_ifie_allocation(context, logger, cohort_state)
    
    # 步骤3：合同组CSM/LC判断
    if cohort_state:
        _determine_cohort_status(cohort_state, context, logger, policies)
    
    # 步骤4：LC计量（先计算，供CSM计量使用）
    _calculate_lc_measurement(context, logger)
    
    # 步骤5：CSM计量（后计算，依赖LC计量结果）
    _calculate_csm_measurement(context, logger)
    
    logger.log_item(
        "CSM/LC计量合计",
        "[汇总] CSM/LC计量合计",
        "CSM/LC计量包括：CSM计息、LC分摊IFIE、合同组判断、CSM摊销、LC摊销（分摊的LC）、LC变化",
        {
            "CSM计息": (context.if_interest_csm or DECIMAL_ZERO) + (context.nb_interest_csm or DECIMAL_ZERO),
            "LC分摊IFIE": (context.if_lc_ifie_total or DECIMAL_ZERO) + (context.nb_lc_ifie_total or DECIMAL_ZERO),
            "CSM摊销": context.csm_amort_amount or DECIMAL_ZERO,
            "LC摊销（分摊的LC）": getattr(context, 'allocated_lc_total', DECIMAL_ZERO) or DECIMAL_ZERO,
            "LC变化": context.lc_change or DECIMAL_ZERO,
            "期末CSM": context.end_csm_final or DECIMAL_ZERO,
            "期末LC": context.end_lc_final or DECIMAL_ZERO
        },
        (context.if_interest_csm or DECIMAL_ZERO) + (context.nb_interest_csm or DECIMAL_ZERO),
        note="使用统一字段逻辑：>=0走CSM逻辑，<0走LC逻辑。注意：LC不计息，但通过分摊的LC进行摊销"
    )

