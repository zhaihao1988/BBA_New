from decimal import Decimal

def calculate_future_pv_with_rates(total_premium, ratio, total_months, passed_months, rates_df, rate_offset=0):
    """
    计算预期未来现金流现值 (基于UEP逻辑 + 真实月度远期利率折现)
    rate_offset: 利率曲线取值的偏移量。
                 例如：计算初始确认(T=0)的PV，offset=0。
                 计算T=7时刻基于T=0曲线的PV (Locked-in)，offset=7 (即使用第8个月及以后的利率)。
    """
    if total_months <= 0: return Decimal('0')
    
    remaining_months = max(0, total_months - passed_months)
    if remaining_months == 0: return Decimal('0')
    
    # 每月名义现金流 (假设均匀分布)
    monthly_cf_nominal = (total_premium / Decimal(total_months)) * ratio
    
    total_pv = Decimal('0')
    cum_discount_factor = Decimal('1.0')
    
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    
    # 循环计算未来剩余的每一个月
    # t 代表距离当前评估点的月数 (1, 2, ...)
    # 对应的利率 Term 应该是 rate_offset + t
    for t in range(1, remaining_months + 1):
        # 获取第 t 期的远期月利率
        r_t = rates_map.get(t + rate_offset, Decimal('0'))
        
        # 累积折现因子
        cum_discount_factor /= (Decimal('1') + r_t)
        
        # 现值 = 现金流 * 因子
        total_pv += monthly_cf_nominal * cum_discount_factor
        
    return total_pv

def get_accretion_rate_factor(rates_df, start_month, end_month):
    """
    计算在锁定利率曲线上，从 start_month (不含) 到 end_month (含) 的累积计息因子
    """
    if rates_df is None:
        return Decimal('0')
    if end_month is None or start_month is None:
        return Decimal('0')
    if end_month <= start_month:
        return Decimal('0')
    
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    
    cum_rate = Decimal('1.0')
    for term in range(start_month + 1, end_month + 1):
        r_t = rates_map.get(term, Decimal('0'))
        cum_rate *= (Decimal('1') + r_t)
    
    return cum_rate - Decimal('1')


