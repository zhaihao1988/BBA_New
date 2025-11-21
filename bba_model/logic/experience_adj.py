"""
经验调整逻辑 (Experience Adjustment)

对应文档：第4节 当期经验调整

核心功能：
1. 保费现金流经验调整（文档 Sec 4.3）
2. IACF 经验调整（文档 Sec 4.4）
3. 需区分期初有效合同 (Eff) 与当年新增合同 (New)
"""

from decimal import Decimal
from bba_model.models import Assumptions


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
    
    # 使用动态假设（从数据库读取）或默认值
    if assumptions:
        loss_ratio = assumptions.loss_ratio
        indirect_claims_expense_ratio = assumptions.indirect_claims_expense_ratio
        maintenance_expense_ratio = assumptions.maintenance_expense_ratio
        acquisition_expense_ratio = assumptions.acquisition_expense_ratio
    else:
        # 兼容旧代码：使用配置中的默认值
        from bba_model.config import RATIO_CLAIM, RATIO_MAINT_EXP, RATIO_IACF
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

    # 预期赔付（名义金额，不折现）
    context.expected_claim_nominal = (context.actual_premium * loss_ratio * (Decimal('1') + indirect_claims_expense_ratio) / context.total_months) * context.months_passed
    context.actual_claim_incurred = context.expected_claim_nominal  # 暂定实际=预期
    
    # 预期维持费用（名义金额，不折现）
    context.expected_maint_nominal = (context.actual_premium * maintenance_expense_ratio / context.total_months) * context.months_passed
    context.actual_maint_incurred = context.expected_maint_nominal  # 暂定实际=预期

    # [Sec 4.3] 保费现金流经验调整
    # 注意：实施时需按合同类型二选一（Eff 或 New）
    # 简化实现：假设为新增合同
    context.prem_var = Decimal('0')  # 保费在初始确认时已收，无变化
    logger.log_item(
        "保费现金流经验调整",
        "[Sec 4.3] 实际保费与预期保费的差异（经验调整）",
        "Adj_Prem = (New.F_end + New.C_actual) - (New.F_init + New.C_init)",
        {
            "New.F_end": Decimal('0'),
            "New.C_actual": context.actual_premium,
            "New.F_init": Decimal('0'),
            "New.C_init": context.actual_premium
        }, 
        context.prem_var,
        note="保费在初始确认时已收，无经验调整。若为存量合同，需取 Eff.* 相关项"
    )

    # [Sec 4.4] IACF 经验调整
    # 注意：实施时需按合同类型二选一（Eff 或 New）
    context.expected_iacf_nominal = context.actual_premium * acquisition_expense_ratio
    context.actual_iacf_incurred = context.expected_iacf_nominal  # 暂定实际=预期
    
    context.iacf_var = context.actual_iacf_incurred - context.expected_iacf_nominal
    logger.log_item(
        "IACF 经验调整",
        "[Sec 4.4] 实际获取费用与预期获取费用的差异（经验调整）",
        "Adj_IACF = (New.F_end^I + New.C_actual^I) - (New.F_init^I + New.C_init^I)",
        {
            "New.F_end^I": Decimal('0'),
            "New.C_actual^I": context.actual_iacf_incurred,
            "New.F_init^I": Decimal('0'),
            "New.C_init^I": context.expected_iacf_nominal
        },
        context.iacf_var,
        note="当前暂无实际IACF数据，假设为0偏差。若为存量合同，需取 Eff.* 相关项"
    )

    # 计算赔付和维费差异 (用于后续 CSM 调整)
    context.claim_var = context.actual_claim_incurred - context.expected_claim_nominal
    context.maint_var = context.actual_maint_incurred - context.expected_maint_nominal
    
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

