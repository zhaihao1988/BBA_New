"""
性能瓶颈分析脚本

分析单个保单处理过程中各个步骤的耗时，找出真正的性能瓶颈
"""

import sys
import time
from pathlib import Path
from datetime import date
from decimal import Decimal

# 添加项目根目录到 sys.path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from BBA_dev.data_loader import load_full_data
from BBA_dev.data_access.loader import load_rate_curve, load_assumptions
from BBA_dev.scripts.run_lifecycle_simulation_new import LifecycleSimulatorNew

def profile_single_policy():
    """分析单个保单的性能瓶颈"""
    
    print("=" * 80)
    print("性能瓶颈分析 - 单保单详细耗时")
    print("=" * 80)
    
    run_date = "202412"
    
    # 1. 加载数据
    t0 = time.time()
    df = load_full_data(run_date, limit=1)
    if df.empty:
        print("No data found")
        return
    
    row = df.iloc[0]
    policy_no = row['policy_no']
    class_code = row['class_code']
    t1 = time.time()
    print(f"✓ 数据加载: {(t1-t0)*1000:.1f}ms")
    print(f"  Policy: {policy_no}, Class: {class_code}")
    
    # 2. 加载利率曲线（多个月）
    t0 = time.time()
    rates_map = {}
    for m in range(202001, 202413):
        month_str = str(m)
        if len(month_str) == 6 and month_str[4:6] <= '12':
            try:
                rates_df = load_rate_curve(month_str)
                if rates_df is not None and not rates_df.empty:
                    rates_map[month_str] = rates_df
            except:
                pass
    t1 = time.time()
    print(f"✓ 利率曲线加载 ({len(rates_map)}个月): {(t1-t0)*1000:.1f}ms")
    
    # 3. 加载假设
    t0 = time.time()
    assumptions_map = {}
    for month_str in rates_map.keys():
        try:
            assump_dict = load_assumptions(month_str, class_code)
            if assump_dict:
                assumptions_map[month_str] = assump_dict
        except:
            pass
    t1 = time.time()
    print(f"✓ 假设加载 ({len(assumptions_map)}个月): {(t1-t0)*1000:.1f}ms")
    
    # 4. 准备数据包
    t0 = time.time()
    policy_row_dict = row.to_dict()
    if 'sum_premium_no_tax' not in policy_row_dict and 'premium_cny' in policy_row_dict:
        policy_row_dict['sum_premium_no_tax'] = policy_row_dict['premium_cny']
    
    prem = Decimal(str(row['premium_cny']))
    acq_ratio = Decimal('0.40')
    policy_row_dict['iacf_amount'] = float(prem * acq_ratio)
    
    preloaded_data = {
        'policy_row': policy_row_dict,
        'written_premium': prem,
        'rates_map': rates_map,
        'assumptions_map': assumptions_map,
        'initial_spot_rate': Decimal('0.03')
    }
    t1 = time.time()
    print(f"✓ 数据准备: {(t1-t0)*1000:.1f}ms")
    
    # 5. 执行生命周期模拟（详细计时）
    print("\n--- 生命周期模拟详细耗时 ---")
    
    t_total_start = time.time()
    
    # 5.1 初始化
    t0 = time.time()
    simulator = LifecycleSimulatorNew(
        policy_no=policy_no,
        certi_no=row.get('certi_no'),
        preloaded_data=preloaded_data
    )
    simulator.initialize()
    t1 = time.time()
    print(f"  ├─ 初始化: {(t1-t0)*1000:.1f}ms")
    
    # 5.2 运行模拟
    t0 = time.time()
    results = simulator.run()
    t1 = time.time()
    t_simulation = (t1 - t0) * 1000
    print(f"  └─ 运行模拟: {t_simulation:.1f}ms")
    
    t_total_end = time.time()
    t_total = (t_total_end - t_total_start) * 1000
    
    print(f"\n总耗时: {t_total:.1f}ms ({t_total/1000:.2f}秒)")
    print(f"  其中模拟占比: {t_simulation/t_total*100:.1f}%")
    
    # 6. 分析PV计算占比（需要在pv_calculator_core中添加计时器）
    print("\n" + "=" * 80)
    print("结论：")
    print("  - 如果'运行模拟'占总时间 < 50%，说明瓶颈在数据加载/准备")
    print("  - 如果'运行模拟'占总时间 > 80%，说明瓶颈在业务逻辑/PV计算")
    print("=" * 80)

if __name__ == "__main__":
    profile_single_policy()


