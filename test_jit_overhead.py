"""
测试JIT编译开销 vs 计算收益
"""
import time
import numpy as np
from BBA_dev.pv_calculator_jit import calculate_pv_initial_recognition_jit, build_discount_table_jit

# 模拟一个保单的现金流数据（60个月）
n_months = 60
amounts = np.random.random(n_months) * 1000
dates_years = np.array([2024 + i//12 for i in range(n_months)], dtype=np.int32)
dates_months = np.array([1 + i%12 for i in range(n_months)], dtype=np.int32)
dates_days = np.ones(n_months, dtype=np.int32) * 15
rates_array = np.random.random(121) * 0.05
rates_array[0] = 0.0

print("=" * 70)
print("JIT编译开销 vs 计算收益分析")
print("=" * 70)

# 第1次调用：包含编译时间
t0 = time.time()
result1 = calculate_pv_initial_recognition_jit(
    amounts, dates_years, dates_months, dates_days,
    2024, 1, 1, rates_array, 120, True
)
t1 = time.time()
time_first = (t1 - t0) * 1000
print(f"第1次调用（含编译）: {time_first:.2f}ms")

# 第2-100次调用：纯计算时间
times = []
for _ in range(100):
    t0 = time.time()
    result = calculate_pv_initial_recognition_jit(
        amounts, dates_years, dates_months, dates_days,
        2024, 1, 1, rates_array, 120, True
    )
    t1 = time.time()
    times.append((t1 - t0) * 1000)

avg_time = np.mean(times)
print(f"后续100次平均: {avg_time:.2f}ms")
print(f"编译开销: {time_first - avg_time:.2f}ms")
print(f"开销倍数: {time_first / avg_time:.1f}x")

print("\n" + "=" * 70)
print("结论:")
print(f"  - 每个进程首次调用需要额外 {time_first - avg_time:.0f}ms 编译时间")
print(f"  - 32个进程 × {time_first - avg_time:.0f}ms = {32 * (time_first - avg_time)/1000:.1f}秒总开销")
print(f"  - 如果每个保单只有60个月现金流，JIT收益不明显")
print("=" * 70)
