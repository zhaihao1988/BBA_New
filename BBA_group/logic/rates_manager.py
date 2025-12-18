"""
加权初始确认利率管理器 (Weighted Average Locked-in Rate Manager)

对应文档：第1.5节 初始加权利率曲线

核心功能：
1. 递归更新加权锁定利率（按签单保费作为权重）
2. 新单初始确认时使用即期利率（Spot Rate），计算完成后权重并入加权锁定利率
3. 后续计量统一使用加权初始确认利率
"""

from decimal import Decimal
from typing import Optional, Any
from BBA_group.models import CohortState


def calculate_spot_rate(rates_df) -> Decimal:
    """
    计算即期利率（Spot Rate）
    
    对应文档：第1.5节
    
    说明：新单初始确认时使用即期利率计算现值。
    简化实现：使用利率曲线的第一个值作为即期利率。
    
    Args:
        rates_df: 利率曲线 DataFrame，包含 term_month 和 forward_disrate_value
        
    Returns:
        Decimal: 即期利率（月化）
    """
    if rates_df is None or len(rates_df) == 0:
        return Decimal('0')
    
    # 简化：使用第一个期限的利率作为即期利率
    spot_rate = Decimal(str(rates_df.iloc[0]['forward_disrate_value']))
    return spot_rate


def update_weighted_locked_rate(
    cohort_state: CohortState,
    new_spot_rate: Decimal,
    new_written_premium: Decimal,
    logger: Optional[Any] = None
) -> Decimal:
    """
    递归更新加权初始确认利率
    
    对应文档：第1.5.2节 递归更新公式
    
    公式：
        R_new = (R_old * W_old + R_spot * W_new) / (W_old + W_new)
    
    其中：
        R_new: 更新后的加权初始确认利率
        R_old: 期初存量保单的加权初始确认利率
        R_spot: 本月新单的即期利率（Spot Rate）
        W_old: 期初存量保单的签单保费累计
        W_new: 本月新单的签单保费累计
    
    Args:
        cohort_state: 合同组状态对象
        new_spot_rate: 新单的即期利率（Spot Rate）
        new_written_premium: 新单的签单保费
        logger: 日志记录器（可选）
        
    Returns:
        Decimal: 更新后的加权锁定利率
    """
    # 获取期初存量数据
    R_old = cohort_state.weighted_locked_rate
    W_old = cohort_state.total_written_premium
    
    # 新单数据
    R_spot = new_spot_rate
    W_new = new_written_premium
    
    # 特殊情况：如果期初权重为0（第一张单），直接使用即期利率
    if W_old == 0:
        R_new = R_spot
        if logger:
            logger.log_item(
                "加权初始确认利率更新（首单）",
                "[Sec 1.5.2] 第一张单，直接使用即期利率",
                "R_new = R_spot",
                {
                    "R_spot": R_spot,
                    "W_new": W_new
                },
                R_new,
                note="期初权重为0，无需加权"
            )
    else:
        # 递归更新公式
        numerator = R_old * W_old + R_spot * W_new
        denominator = W_old + W_new
        
        if denominator > 0:
            R_new = numerator / denominator
        else:
            R_new = Decimal('0')
        
        if logger:
            logger.log_item(
                "加权初始确认利率更新",
                "[Sec 1.5.2] 递归更新公式：R_new = (R_old * W_old + R_spot * W_new) / (W_old + W_new)",
                "加权平均",
                {
                    "R_old": R_old,
                    "W_old": W_old,
                    "R_spot": R_spot,
                    "W_new": W_new,
                    "Numerator": numerator,
                    "Denominator": denominator
                },
                R_new,
                note=f"期初存量保单权重: {W_old:,.2f}, 新单权重: {W_new:,.2f}"
            )
    
    # 更新合同组状态
    cohort_state.weighted_locked_rate = R_new
    cohort_state.total_written_premium = W_old + W_new
    
    return R_new


def get_locked_rate_for_discounting(cohort_state: CohortState) -> Decimal:
    """
    获取用于折现的锁定利率
    
    对应文档：第1.5节
    
    说明：
    - 新单初始确认时使用即期利率（Spot Rate）
    - 后续计量（计息、IFIE_P&C等）统一使用加权初始确认利率
    
    Args:
        cohort_state: 合同组状态对象
        
    Returns:
        Decimal: 加权初始确认利率（锁定利率）
    """
    return cohort_state.weighted_locked_rate

