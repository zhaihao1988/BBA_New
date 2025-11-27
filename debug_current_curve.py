"""
调试Current Curve计算差异
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta

# 创建简单测试数据
test_df = pd.DataFrame({
    'Date_Obj': [
        date(2024, 10, 1),   # 过去2个月
        date(2024, 11, 1),   # 过去1个月
        date(2024, 12, 1),   # 当月
        date(2025, 1, 1),    # 未来1个月
        date(2025, 2, 1),    # 未来2个月
    ],
    'Premium': [1000.0] * 5
})

rates_df = pd.DataFrame({
    'term_month': list(range(1, 13)),
    'forward_disrate_value': [0.03/12] * 12
})

valuation_date = date(2024, 12, 31)
curve_base_date = date(2024, 12, 31)  # Current Curve

print("="*80)
print("Current Curve 月份差计算对比")
print("="*80)
print(f"评估日期: {valuation_date}")
print(f"曲线基准日: {curve_base_date}")
print("-"*80)

for i, row in test_df.iterrows():
    cf_date = row['Date_Obj']
    
    # 原始方法（使用relativedelta）
    rd = relativedelta(cf_date, valuation_date)
    months_diff_original = rd.years * 12 + rd.months
    
    # 我的快速方法
    months_diff_fast = (cf_date.year - valuation_date.year) * 12 + (cf_date.month - valuation_date.month)
    
    print(f"现金流日期: {cf_date}")
    print(f"  relativedelta: years={rd.years}, months={rd.months}")
    print(f"  原始计算: {months_diff_original} 个月")
    print(f"  快速计算: {months_diff_fast} 个月")
    print(f"  一致性: {'✓' if months_diff_original == months_diff_fast else '✗'}")
    print()

print("="*80)
print("详细折现因子计算对比")
print("="*80)

# 测试一个具体的案例
cf_date = date(2025, 2, 1)
rd = relativedelta(cf_date, valuation_date)
months_diff = rd.years * 12 + rd.months

print(f"现金流日期: {cf_date}")
print(f"评估日期: {valuation_date}")
print(f"月份差: {months_diff}")
print()

# 原始方法计算折现因子
print("原始方法（逐步乘除）：")
factor_original = Decimal('1.0')
for t in range(1, months_diff + 1):
    rate = Decimal(str(rates_df[rates_df['term_month'] == t]['forward_disrate_value'].iloc[0]))
    factor_original /= (Decimal('1.0') + rate)
    print(f"  第{t}期: rate={float(rate):.6f}, 累积factor={float(factor_original):.8f}")

print(f"\n最终折现因子（原始）: {float(factor_original):.8f}")

# 向量化方法的预计算表
print("\n向量化方法（预计算表）：")
rates_array = np.zeros(13)
for t in range(1, 13):
    rates_array[t] = rates_df[rates_df['term_month'] == t]['forward_disrate_value'].iloc[0]

# 计算累积折现因子表
discount_factors = 1.0 / np.cumprod(1.0 + rates_array[1:])
discount_factors = np.insert(discount_factors, 0, 1.0)

print(f"预计算折现因子表:")
for t in range(0, min(5, len(discount_factors))):
    print(f"  第{t}期: {discount_factors[t]:.8f}")

if months_diff < len(discount_factors):
    factor_vectorized = discount_factors[months_diff]
    print(f"\n最终折现因子（向量化）: {factor_vectorized:.8f}")
    print(f"差异: {abs(float(factor_original) - factor_vectorized):.8f}")
    print(f"相对误差: {abs(float(factor_original) - factor_vectorized) / float(factor_original):.2e}")

