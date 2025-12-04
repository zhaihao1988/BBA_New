"""
PV计算JIT加速模块 (可选)

使用Numba JIT编译核心计算循环，提供接近C语言的性能。
如果系统未安装Numba，会自动降级使用原有的向量化版本。

性能提升预期：10-100倍（相比纯Python）

技术说明：
- JIT (Just-In-Time) 编译：第一次调用时编译为机器码，后续直接执行
- nopython=True：强制不使用Python对象，确保最大性能
- fastmath=True：允许浮点数优化（略微降低精度换取速度）
- parallel=True：自动并行化循环（多核加速）

兼容性：
- 如果没有安装Numba，自动使用空装饰器（降级为普通Python）
- 保证逻辑完全不变
"""

import numpy as np
from decimal import Decimal
from typing import Dict, Tuple

# 尝试导入Numba
try:
    from numba import jit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    # 空装饰器，保证代码可以运行
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    prange = range


# ==================== JIT编译的核心函数 ====================

@jit(nopython=True, fastmath=True)
def build_discount_table_jit(rates_array: np.ndarray) -> np.ndarray:
    """
    JIT编译：构建累积折现因子表
    
    算法：
    DF[0] = 1.0
    DF[1] = 1 / (1 + r1)
    DF[2] = 1 / ((1 + r1) * (1 + r2))
    DF[t] = 1 / (累乘(1 + r[i]) for i in 1..t)
    
    Args:
        rates_array: 利率数组，索引0不使用，索引1开始是r1, r2, ...
    
    Returns:
        折现因子表
    """
    max_term = len(rates_array) - 1
    if max_term <= 0:
        return np.ones(1, dtype=np.float64)
    
    discount_factors = np.ones(max_term + 1, dtype=np.float64)
    
    # 累积计算折现因子
    cumulative_product = 1.0
    for t in range(1, max_term + 1):
        cumulative_product *= (1.0 + rates_array[t])
        discount_factors[t] = 1.0 / cumulative_product
    
    return discount_factors


@jit(nopython=True)
def compute_months_diff_jit(dates_years: np.ndarray, dates_months: np.ndarray, 
                            base_year: int, base_month: int) -> np.ndarray:
    """
    JIT编译：批量计算月份差
    
    公式：months_diff = (year2 - year1) * 12 + (month2 - month1)
    
    Args:
        dates_years: 日期的年份数组
        dates_months: 日期的月份数组
        base_year: 基准日期的年份
        base_month: 基准日期的月份
    
    Returns:
        月份差数组
    """
    n = len(dates_years)
    months_diff = np.zeros(n, dtype=np.int32)
    
    for i in range(n):
        months_diff[i] = (dates_years[i] - base_year) * 12 + (dates_months[i] - base_month)
    
    return months_diff


@jit(nopython=True, fastmath=True)
def compute_discount_factors_current_curve_jit(
    months_diff: np.ndarray,
    discount_table: np.ndarray,
    rates_array: np.ndarray,
    max_term: int
) -> np.ndarray:
    """
    JIT编译：计算折现因子（Current Curve模式）
    
    Current Curve：从评估日折现，term_month从1开始
    
    Args:
        months_diff: 月份差数组
        discount_table: 预计算的折现因子表
        rates_array: 利率数组
        max_term: 最大期限
    
    Returns:
        折现因子数组
    """
    n = len(months_diff)
    factors = np.ones(n, dtype=np.float64)
    last_rate = rates_array[max_term] if max_term > 0 else 0.0
    
    for i in range(n):
        m_diff = months_diff[i]
        
        if m_diff == 0:
            factors[i] = 1.0
        elif m_diff > 0:
            # 折现：未来 -> 现在
            m_abs = int(m_diff)
            if 0 < m_abs <= max_term and m_abs < len(discount_table):
                # 在表范围内，直接查表
                factors[i] = discount_table[m_abs]
            else:
                # 超出范围，手动计算（外推）
                factor = 1.0
                for t in range(1, m_abs + 1):
                    if t <= max_term:
                        rate = rates_array[t]
                    else:
                        rate = last_rate
                    factor /= (1.0 + rate)
                factors[i] = factor
        else:
            # 累积：过去 -> 现在（反向折现）
            abs_m = abs(int(m_diff))
            if 0 < abs_m <= max_term and abs_m < len(discount_table):
                factors[i] = 1.0 / discount_table[abs_m]
            else:
                factor = 1.0
                for t in range(1, abs_m + 1):
                    if t <= max_term:
                        rate = rates_array[t]
                    else:
                        rate = last_rate
                    factor *= (1.0 + rate)
                factors[i] = factor
    
    return factors


@jit(nopython=True, fastmath=True)
def compute_discount_factors_locked_curve_jit(
    cf_dates_years: np.ndarray,
    cf_dates_months: np.ndarray,
    val_year: int,
    val_month: int,
    curve_base_year: int,
    curve_base_month: int,
    discount_table: np.ndarray,
    rates_array: np.ndarray,
    max_term: int
) -> np.ndarray:
    """
    JIT编译：计算折现因子（Locked Curve模式）
    
    Locked Curve：从签单日折现，term_month = (现金流日期 - 签单日期)的月数差
    
    Args:
        cf_dates_years: 现金流日期的年份数组
        cf_dates_months: 现金流日期的月份数组
        val_year: 评估日期年份
        val_month: 评估日期月份
        curve_base_year: 曲线基准日期年份（签单日）
        curve_base_month: 曲线基准日期月份
        discount_table: 预计算的折现因子表
        rates_array: 利率数组
        max_term: 最大期限
    
    Returns:
        折现因子数组
    """
    n = len(cf_dates_years)
    factors = np.ones(n, dtype=np.float64)
    last_rate = rates_array[max_term] if max_term > 0 else 0.0
    
    # 计算评估日相对签单日的月数差
    idx_val = (val_year - curve_base_year) * 12 + (val_month - curve_base_month)
    
    for i in range(n):
        # 计算现金流日期相对签单日的月数差
        idx_cf = (cf_dates_years[i] - curve_base_year) * 12 + (cf_dates_months[i] - curve_base_month)
        
        # 倒签单情况：现金流在签单日之前
        if idx_cf < 0:
            factors[i] = 1.0
        # 现金流正好在评估日
        elif cf_dates_years[i] == val_year and cf_dates_months[i] == val_month:
            factors[i] = 1.0
        # 现金流在评估日之后（折现）
        elif cf_dates_years[i] > val_year or (cf_dates_years[i] == val_year and cf_dates_months[i] > val_month):
            start_step = max(1, idx_val + 2)
            end_step = idx_cf + 1
            
            if start_step <= end_step:
                if end_step <= max_term and start_step > 0 and end_step < len(discount_table):
                    # 在表范围内，使用表查找
                    # DF(start->end) = DF[end] / DF[start-1]
                    if start_step == 1:
                        factors[i] = discount_table[end_step]
                    else:
                        factors[i] = discount_table[end_step] / discount_table[start_step - 1]
                else:
                    # 超出范围，手动计算
                    factor = 1.0
                    for t in range(start_step, end_step + 1):
                        if t <= max_term:
                            rate = rates_array[t]
                        else:
                            rate = last_rate
                        factor /= (1.0 + rate)
                    factors[i] = factor
        # 现金流在评估日之前（累积）
        else:
            start_step = max(1, idx_cf + 1)
            end_step = idx_val
            
            if start_step <= end_step:
                if end_step <= max_term and start_step > 0 and end_step < len(discount_table):
                    # 累积因子 = 1 / 折现因子
                    if start_step == 1:
                        factors[i] = 1.0 / discount_table[end_step]
                    else:
                        factors[i] = 1.0 / (discount_table[end_step] / discount_table[start_step - 1])
                else:
                    factor = 1.0
                    for t in range(start_step, end_step + 1):
                        if t <= max_term:
                            rate = rates_array[t]
                        else:
                            rate = last_rate
                        factor *= (1.0 + rate)
                    factors[i] = factor
    
    return factors


@jit(nopython=True, fastmath=True, parallel=True)
def calculate_pv_batch_jit(
    amounts_matrix: np.ndarray,
    discount_factors: np.ndarray
) -> np.ndarray:
    """
    JIT编译：批量计算多个字段的PV（矩阵化 + 并行化）
    
    使用矩阵乘法一次性计算所有字段的现值，利用多核并行加速
    
    Args:
        amounts_matrix: (M, F) 现金流金额矩阵，M个月，F个字段
        discount_factors: (M,) 折现因子数组
    
    Returns:
        (F,) PV结果数组
    """
    M, F = amounts_matrix.shape
    pv_results = np.zeros(F, dtype=np.float64)
    
    # 并行化：每个字段独立计算
    for f in prange(F):
        pv_sum = 0.0
        for m in range(M):
            pv_sum += amounts_matrix[m, f] * discount_factors[m]
        pv_results[f] = pv_sum
    
    return pv_results


@jit(nopython=True, fastmath=True)
def calculate_pv_initial_recognition_jit(
    amounts: np.ndarray,
    dates_years: np.ndarray,
    dates_months: np.ndarray,
    dates_days: np.ndarray,
    uw_year: int,
    uw_month: int,
    uw_day: int,
    rates_array: np.ndarray,
    max_term: int,
    is_premium_or_iacf: bool
) -> float:
    """
    JIT编译：初始确认PV计算（核心瓶颈函数）
    
    这是整个系统中最耗时的函数之一，使用Decimal循环极慢
    用JIT编译可以获得50-100倍加速
    
    Args:
        amounts: 现金流金额数组
        dates_years: 日期年份数组
        dates_months: 日期月份数组
        dates_days: 日期天数数组
        uw_year: 签单日期年份
        uw_month: 签单日期月份
        uw_day: 签单日期天数
        rates_array: 利率数组
        max_term: 最大期限
        is_premium_or_iacf: 是否为保费或获取费用字段
    
    Returns:
        现值（float）
    """
    total_pv = 0.0
    uw_year_month = (uw_year, uw_month)
    last_rate = rates_array[max_term] if max_term > 0 else 0.0
    
    for i in range(len(amounts)):
        if amounts[i] == 0.0:
            continue
        
        cf_year = dates_years[i]
        cf_month = dates_months[i]
        
        # 计算月份差
        idx_cf = (cf_year - uw_year) * 12 + (cf_month - uw_month)
        
        is_uw_month = (cf_year == uw_year and cf_month == uw_month)
        
        # 计算折现因子
        if is_uw_month:
            if is_premium_or_iacf:
                factor = 1.0
            else:
                # 签单月的Claims/Expenses：半月折现
                r1 = rates_array[1] if max_term >= 1 else 0.0
                factor = 1.0 / (1.0 + r1 / 2.0)
        else:
            if idx_cf <= 0:
                factor = 1.0
            else:
                # 累积折现
                r1 = rates_array[1] if max_term >= 1 else 0.0
                factor = 1.0 / (1.0 + r1 / 2.0)
                
                for t in range(2, idx_cf + 1):
                    if t <= max_term:
                        r = rates_array[t]
                    else:
                        r = last_rate
                    factor /= (1.0 + r)
        
        total_pv += amounts[i] * factor
    
    return total_pv


# ==================== 高级封装函数 ====================

def calculate_pv_exact_jit(
    cf_df,
    col_name: str,
    rates_df,
    valuation_date,
    curve_base_date
) -> Decimal:
    """
    JIT加速版：精确PV计算
    
    完全兼容原有的 calculate_pv_exact_fast 函数
    逻辑不变，只是用JIT编译提速
    
    Args:
        cf_df: 现金流DataFrame
        col_name: 列名
        rates_df: 利率曲线DataFrame
        valuation_date: 评估日期
        curve_base_date: 曲线基准日期
    
    Returns:
        现值（Decimal）
    """
    if cf_df.empty:
        return Decimal('0')
    
    # 1. 提取数据为NumPy数组
    amounts = cf_df[col_name].values.astype(np.float64)
    dates = cf_df['Date_Obj'].values
    
    # 过滤零值（优化）
    non_zero_mask = amounts != 0
    if not non_zero_mask.any():
        return Decimal('0')
    
    amounts = amounts[non_zero_mask]
    dates = dates[non_zero_mask]
    
    # 2. 构建利率数组和折现因子表
    max_term = int(rates_df['term_month'].max()) if not rates_df.empty else 0
    if max_term == 0:
        return Decimal('0')
    
    rates_array = np.zeros(max_term + 1, dtype=np.float64)
    for term, rate in zip(rates_df['term_month'].values, rates_df['forward_disrate_value'].values):
        if 0 < term <= max_term:
            rates_array[int(term)] = float(rate)
    
    # 构建折现因子表（JIT加速）
    discount_table = build_discount_table_jit(rates_array)
    
    # 3. 计算折现因子
    is_current_curve = (curve_base_date == valuation_date)
    
    if is_current_curve:
        # Current Curve模式
        # 提取日期的年月
        dates_years = np.array([d.year for d in dates], dtype=np.int32)
        dates_months = np.array([d.month for d in dates], dtype=np.int32)
        
        # 计算月份差（JIT加速）
        months_diff = compute_months_diff_jit(
            dates_years, dates_months,
            valuation_date.year, valuation_date.month
        )
        
        # 计算折现因子（JIT加速）
        discount_factors = compute_discount_factors_current_curve_jit(
            months_diff, discount_table, rates_array, max_term
        )
    else:
        # Locked Curve模式
        dates_years = np.array([d.year for d in dates], dtype=np.int32)
        dates_months = np.array([d.month for d in dates], dtype=np.int32)
        
        # 计算折现因子（JIT加速）
        discount_factors = compute_discount_factors_locked_curve_jit(
            dates_years, dates_months,
            valuation_date.year, valuation_date.month,
            curve_base_date.year, curve_base_date.month,
            discount_table, rates_array, max_term
        )
    
    # 4. 计算PV（向量点积）
    pv = np.dot(amounts, discount_factors)
    
    return Decimal(str(pv))


def calculate_pv_cca_jit(
    cf_df,
    col_name: str,
    rates_df,
    valuation_date,
    curve_base_date
) -> Decimal:
    """
    JIT加速版：当期现金流PV计算
    
    完全兼容原有的 calculate_pv_cca_fast 函数
    
    规则：
    - 评估月及之前：原值（不计息）
    - 评估月之后：折现
    
    Args:
        cf_df: 现金流DataFrame
        col_name: 列名
        rates_df: 利率曲线DataFrame
        valuation_date: 评估日期
        curve_base_date: 曲线基准日期
    
    Returns:
        现值（Decimal）
    """
    if cf_df.empty:
        return Decimal('0')
    
    val_year_month = (valuation_date.year, valuation_date.month)
    
    # 提取数据
    amounts = cf_df[col_name].values.astype(np.float64)
    dates = cf_df['Date_Obj'].values
    
    # 过滤零值
    non_zero_mask = amounts != 0
    if not non_zero_mask.any():
        return Decimal('0')
    
    amounts = amounts[non_zero_mask]
    dates = dates[non_zero_mask]
    
    # 分离已发生和未发生的现金流
    occurred_mask = np.array([
        (d.year, d.month) <= val_year_month for d in dates
    ])
    
    # 已发生：原值（不计息）
    occurred_pv = np.sum(amounts[occurred_mask])
    
    # 未发生：折现
    future_amounts = amounts[~occurred_mask]
    future_dates = dates[~occurred_mask]
    
    if len(future_dates) > 0:
        # 对未发生的现金流计算PV（复用exact函数的逻辑）
        max_term = int(rates_df['term_month'].max()) if not rates_df.empty else 0
        if max_term == 0:
            future_pv = 0.0
        else:
            rates_array = np.zeros(max_term + 1, dtype=np.float64)
            for term, rate in zip(rates_df['term_month'].values, rates_df['forward_disrate_value'].values):
                if 0 < term <= max_term:
                    rates_array[int(term)] = float(rate)
            
            discount_table = build_discount_table_jit(rates_array)
            
            is_current_curve = (curve_base_date == valuation_date)
            
            if is_current_curve:
                dates_years = np.array([d.year for d in future_dates], dtype=np.int32)
                dates_months = np.array([d.month for d in future_dates], dtype=np.int32)
                months_diff = compute_months_diff_jit(
                    dates_years, dates_months,
                    valuation_date.year, valuation_date.month
                )
                discount_factors = compute_discount_factors_current_curve_jit(
                    months_diff, discount_table, rates_array, max_term
                )
            else:
                dates_years = np.array([d.year for d in future_dates], dtype=np.int32)
                dates_months = np.array([d.month for d in future_dates], dtype=np.int32)
                discount_factors = compute_discount_factors_locked_curve_jit(
                    dates_years, dates_months,
                    valuation_date.year, valuation_date.month,
                    curve_base_date.year, curve_base_date.month,
                    discount_table, rates_array, max_term
                )
            
            future_pv = np.dot(future_amounts, discount_factors)
    else:
        future_pv = 0.0
    
    total_pv = occurred_pv + future_pv
    return Decimal(str(total_pv))


def calculate_all_fields_batch_jit(
    cf_df,
    fields: list,
    rates_df,
    valuation_date,
    curve_base_date
) -> Dict[str, Decimal]:
    """
    JIT加速版：批量计算多个字段的PV（矩阵化）
    
    一次性计算所有字段，避免重复折现因子计算
    
    Args:
        cf_df: 现金流DataFrame
        fields: 字段列表，如 ['Premium', 'IACF', 'Claims', 'Expenses']
        rates_df: 利率曲线DataFrame
        valuation_date: 评估日期
        curve_base_date: 曲线基准日期
    
    Returns:
        字典 {field_name: pv_value}
    """
    if cf_df.empty or not fields:
        return {f: Decimal('0') for f in fields}
    
    # 1. 构建现金流矩阵 (M × F)
    amounts_list = []
    for field in fields:
        if field in cf_df.columns:
            amounts_list.append(cf_df[field].values.astype(np.float64))
        else:
            amounts_list.append(np.zeros(len(cf_df), dtype=np.float64))
    
    amounts_matrix = np.column_stack(amounts_list)  # (M, F)
    dates = cf_df['Date_Obj'].values
    
    # 2. 构建利率数组和折现因子表
    max_term = int(rates_df['term_month'].max()) if not rates_df.empty else 0
    if max_term == 0:
        return {f: Decimal('0') for f in fields}
    
    rates_array = np.zeros(max_term + 1, dtype=np.float64)
    for term, rate in zip(rates_df['term_month'].values, rates_df['forward_disrate_value'].values):
        if 0 < term <= max_term:
            rates_array[int(term)] = float(rate)
    
    discount_table = build_discount_table_jit(rates_array)
    
    # 3. 计算折现因子
    is_current_curve = (curve_base_date == valuation_date)
    
    if is_current_curve:
        dates_years = np.array([d.year for d in dates], dtype=np.int32)
        dates_months = np.array([d.month for d in dates], dtype=np.int32)
        months_diff = compute_months_diff_jit(
            dates_years, dates_months,
            valuation_date.year, valuation_date.month
        )
        discount_factors = compute_discount_factors_current_curve_jit(
            months_diff, discount_table, rates_array, max_term
        )
    else:
        dates_years = np.array([d.year for d in dates], dtype=np.int32)
        dates_months = np.array([d.month for d in dates], dtype=np.int32)
        discount_factors = compute_discount_factors_locked_curve_jit(
            dates_years, dates_months,
            valuation_date.year, valuation_date.month,
            curve_base_date.year, curve_base_date.month,
            discount_table, rates_array, max_term
        )
    
    # 4. 矩阵化计算PV（JIT加速 + 并行）
    pv_vector = calculate_pv_batch_jit(amounts_matrix, discount_factors)
    
    # 5. 转换为Decimal并返回
    results = {}
    for i, field in enumerate(fields):
        results[field] = Decimal(str(pv_vector[i]))
    
    return results


# ==================== 性能测试函数 ====================

def benchmark_jit_speedup():
    """
    性能基准测试：对比JIT版本和原始版本的速度
    """
    import pandas as pd
    from datetime import date
    import time
    
    # 构造测试数据
    test_cf = pd.DataFrame({
        'YYYYMM': [f'2024{m:02d}' for m in range(1, 13)] * 10,
        'Premium': np.random.random(120) * 1000,
        'IACF': np.random.random(120) * 100,
        'Claims': np.random.random(120) * 800,
        'Expenses': np.random.random(120) * 50,
    })
    test_cf['Date_Obj'] = pd.to_datetime(test_cf['YYYYMM'], format='%Y%m').dt.date
    
    test_rates = pd.DataFrame({
        'term_month': range(1, 121),
        'forward_disrate_value': np.random.random(120) * 0.05
    })
    
    val_date = date(2024, 12, 31)
    base_date = date(2024, 1, 1)
    
    # 测试JIT版本
    start = time.time()
    for _ in range(100):
        result_jit = calculate_pv_exact_jit(test_cf, 'Premium', test_rates, val_date, base_date)
    jit_time = time.time() - start
    
    print(f"JIT版本 (100次): {jit_time:.3f}秒")
    print(f"平均每次: {jit_time/100*1000:.2f}ms")
    
    # 尝试导入原始版本进行对比
    try:
        from BBA_dev.pv_calculator_vectorized import calculate_pv_exact_fast
        
        start = time.time()
        for _ in range(100):
            result_orig = calculate_pv_exact_fast(test_cf, 'Premium', test_rates, val_date, base_date)
        orig_time = time.time() - start
        
        print(f"原始版本 (100次): {orig_time:.3f}秒")
        print(f"平均每次: {orig_time/100*1000:.2f}ms")
        print(f"加速倍数: {orig_time/jit_time:.1f}x")
        print(f"结果一致性: {abs(float(result_jit) - float(result_orig)) < 0.01}")
    except ImportError:
        print("无法导入原始版本进行对比")


if __name__ == "__main__":
    print("=" * 80)
    print("PV计算JIT加速模块 - 性能测试")
    print("=" * 80)
    
    if HAS_NUMBA:
        print("✓ Numba已安装，JIT加速已启用")
        print("\n运行性能测试...")
        benchmark_jit_speedup()
    else:
        print("⚠️ Numba未安装")
        print("安装命令: pip install numba")
        print("预期性能提升: 10-100倍")

