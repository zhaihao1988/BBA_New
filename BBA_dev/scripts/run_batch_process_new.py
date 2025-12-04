import os
import sys
import time
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal
from datetime import date, datetime

# 将项目根目录加入路径，防止 ModuleNotFoundError
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 引入新模块
from BBA_dev.scripts.run_lifecycle_simulation_new import LifecycleSimulatorNew
from BBA_dev.data_loader import load_full_data
from BBA_dev.data_access.loader import get_rates, get_assumptions, clear_static_cache
from BBA_dev.utils.async_csv_writer import AsyncCSVWriter
# 复用旧脚本的列定义，确保输出格式完全一致
from BBA_dev.scripts.run_batch_process import RESULT_COLUMNS


# 定义输出文件路径 (使用新文件名以区分，避免冲突，日志目录向上两级)
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "logs", "bba_batch_results_new_202412.csv")

def process_single_policy_wrapper(args):
    """Worker 函数"""
    policy_no, certi_no, preloaded_data = args
    try:
        sim = LifecycleSimulatorNew(policy_no, preloaded_data)
        return policy_no, sim.run(), None
    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        return policy_no, None, error_detail
    finally:
        # 每个子进程结束时清理数据库连接池（关键！）
        try:
            from BBA_dev.data_access.db_utils import dispose_all_engines
            dispose_all_engines()
        except Exception:
            pass  # 静默失败，避免影响主进程

def run_batch_new(run_date="202412", val_method="7", max_workers=32, limit=None):
    start_time = time.time()
    # 检测JIT状态
    try:
        from BBA_dev.pv_calculator_jit import HAS_NUMBA
        jit_status = "JIT加速" if HAS_NUMBA else "标准模式"
    except:
        jit_status = "标准模式"
    
    print(f"=" * 80)
    print(f"New Batch Process (Memory Optimized) Start: {datetime.now()}")
    print(f"Run Date: {run_date} | 性能模式: {jit_status}")
    print(f"Output File: {OUTPUT_FILE}")
    print(f"=" * 80)

    # 清理旧文件
    if os.path.exists(OUTPUT_FILE):
        try:
            os.remove(OUTPUT_FILE)
            print(f"Removed existing output file: {OUTPUT_FILE}")
        except Exception as e:
            print(f"Warning: Could not remove existing file: {e}")

    print(">>> 1. 批量加载保单数据 (一次性 I/O)...")
    # 一次性把所有保单（含IACF）拉到内存
    df_all = load_full_data(run_date=run_date, val_method=val_method, limit=limit)
    
    if df_all.empty:
        print("No policies found.")
        return

    total_policies = len(df_all)
    print(f"Loaded {total_policies} policies.")

    print(f">>> 2. 准备静态资源 (Rate & Assumptions)...")
    # 找出所有涉及的月份：签单月 + 2017-2024的所有年底
    all_months = set()
    for d in df_all['under_write_date']:
        if d: 
            # 确保是 datetime 对象或 date 对象
            if isinstance(d, (date, datetime)):
                all_months.add(d.strftime('%Y%m'))
            elif isinstance(d, str):
                # 尝试解析字符串日期，假设格式为 YYYY-MM-DD
                try:
                    dt = pd.to_datetime(d)
                    all_months.add(dt.strftime('%Y%m'))
                except:
                    pass

    # 补充评估期间的月份 (覆盖2017年至运行年份的所有年初年末)
    try:
        current_year = int(run_date[:4])
    except:
        current_year = 2024
        
    for y in range(2017, current_year + 1):
        all_months.add(f"{y}12")
        all_months.add(f"{y}01") 
    
    # 批量加载这些月份的利率和假设到字典
    rates_cache = {}
    assumptions_cache = {}
    
    print(f"Preloading data for {len(all_months)} unique months...")
    
    for m in all_months:
        # 加载利率
        try:
            r_df = get_rates(m)
            if not r_df.empty:
                rates_cache[m] = r_df
        except Exception as e:
            print(f"Warning: Failed to load rates for {m}: {e}")

        # 加载假设 (对每个涉及的险类)
        for cls_code in df_all['class_code'].unique():
            k = f"{cls_code}_{m}"
            try:
                # 注意：这里val_method传递进去，确保匹配正确
                # 获取的假设字典中，acquisition_expense_ratio 已从数据库读取
                assump = get_assumptions(cls_code, m, val_method=val_method)
                if assump:
                    assumptions_cache[k] = assump
            except Exception as e:
                pass

    print(f"Loaded {len(rates_cache)} rate curves and {len(assumptions_cache)} assumption sets.")

    print(">>> 3. 组装数据包并分发任务...")
    tasks = []
    for _, row in df_all.iterrows():
        p_no = row['policy_no']
        c_no = row.get('certi_no') # 使用 get 防止列不存在
        uw_date = row['under_write_date']
        cls_code = row['class_code']
        
        # 确保数据类型正确
        # 注意：数据库表中只有 premium_cny 字段，没有 sum_premium_no_tax
        try:
            prem = Decimal(str(row['premium_cny']))
        except:
            prem = Decimal('0')
            
        # 获取初始确认月对应的假设（用于确定获取费用率）
        uw_month_str = ""
        if uw_date:
            if isinstance(uw_date, (date, datetime)):
                uw_month_str = uw_date.strftime('%Y%m')
            elif isinstance(uw_date, str):
                try:
                    uw_month_str = pd.to_datetime(uw_date).strftime('%Y%m')
                except:
                    pass
                    
        # 默认获取费用率（如果找不到假设）
        acq_ratio = Decimal('0.20') 
        
        # 查找对应的假设以获取 acquisition_expense_ratio
        k_uw = f"{cls_code}_{uw_month_str}"
        if k_uw in assumptions_cache:
             acq_ratio = assumptions_cache[k_uw].get('acquisition_expense_ratio', Decimal('0.20'))
        elif assumptions_cache:
             # 如果找不到当月的，随便找一个同险类的
             for k, v in assumptions_cache.items():
                 if k.startswith(f"{cls_code}_"):
                     acq_ratio = v.get('acquisition_expense_ratio', Decimal('0.20'))
                     break
        
        # ---------------------------------------------------------------------
        # 方案B：实际获取费用 = 预期获取费用 = 签单保费 * 数据库费率
        # ---------------------------------------------------------------------
        
        # 1. 计算目标IACF（先计算，供调试日志使用）
        target_iacf = prem * acq_ratio
        
        # 调试日志：打印前几条保单的获取费用率
        if len(tasks) < 5:
            print(f"  [DEBUG] Policy: {p_no}, Class: {cls_code}, UW_Month: {uw_month_str}, Acq_Ratio: {acq_ratio}, Prem: {prem}, IACF: {target_iacf}")
        
        # 2. 修改实际费用 (Actual) 并添加字段映射
        policy_row_dict = row.to_dict()
        policy_row_dict['iacf_amount'] = float(target_iacf)
        # 添加sum_premium_no_tax字段映射（因为data_loader已复原）
        if 'sum_premium_no_tax' not in policy_row_dict and 'premium_cny' in policy_row_dict:
            policy_row_dict['sum_premium_no_tax'] = policy_row_dict['premium_cny']
        
        # 2. 准备假设数据 (以字典形式传递，避免 Pickle 问题)
        # 不创建 Assumptions 对象，直接传递字典数据，让子进程自己构建对象
        policy_assumps = {}
        for m in all_months:
            k = f"{cls_code}_{m}"
            if k in assumptions_cache:
                # 直接传递原始字典数据
                policy_assumps[m] = assumptions_cache[k]
        
        preloaded_data = {
            'policy_row': policy_row_dict, # 使用修改后的 dict
            'written_premium': prem,
            'rates_map': rates_cache, 
            'assumptions_map': policy_assumps, 
            'initial_spot_rate': Decimal('0.03') 
        }
        
        tasks.append((p_no, c_no, preloaded_data))

    print(f">>> 4. 启动 {max_workers} 进程并行计算...")
    
    # 初始化 CSV Writer
    csv_writer = AsyncCSVWriter(
        output_file=OUTPUT_FILE,
        columns=RESULT_COLUMNS,
        buffer_size=500,
        flush_interval=5.0
    )
    csv_writer.start()

    completed_count = 0
    
    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 使用 submit + as_completed 模式
            future_to_task = {
                executor.submit(process_single_policy_wrapper, task): task[0]
                for task in tasks
            }
            
            for future in as_completed(future_to_task):
                p_no = future_to_task[future]
                try:
                    _, results, err = future.result()
                    if err:
                         print(f"Error processing {p_no}: {err}")
                    elif results:
                        # 写入结果
                        csv_writer.append(results, block=False)
                    
                    completed_count += 1
                    if completed_count % 100 == 0 or completed_count == total_policies:
                        stats = csv_writer.get_stats()
                        pct = (completed_count / total_policies) * 100
                        print(f"Progress: {completed_count}/{total_policies} ({pct:.1f}%) | Written: {stats['total_written']} | Queue: {stats['queue_size']}")
                        
                except Exception as e:
                    print(f"Critical error for {p_no}: {e}")

    finally:
        print(">>> Stopping CSV Writer...")
        csv_writer.stop()
        
    end_time = time.time()
    duration = end_time - start_time
    print(f"=" * 80)
    print(f"DONE. Total time: {duration:.2f}s ({duration/60:.2f} min)")
    print(f"Output: {OUTPUT_FILE}")
    print(f"=" * 80)
    
    # 清理静态数据缓存
    try:
        clear_static_cache()
        print("✓ 静态数据缓存已清空")
    except Exception as e:
        print(f"⚠️ 清理缓存失败: {e}")
    
    # 清理数据库连接池（主进程，关键！）
    try:
        from BBA_dev.data_access.db_utils import dispose_all_engines
        dispose_all_engines()
        print("✓ 主进程数据库连接已清理")
    except Exception as e:
        print(f"⚠️ 清理主进程数据库连接时出错: {e}")

if __name__ == "__main__":
    # 支持命令行参数：python run_batch_process_new.py [limit]
    limit_arg = None
    if len(sys.argv) > 1:
        try:
            limit_arg = int(sys.argv[1])
            print(f"Limit set to: {limit_arg}")
        except:
            pass
            
    run_batch_new(limit=limit_arg)
