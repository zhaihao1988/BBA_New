import os
import sys
import time
import signal
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


# 动态输出文件路径函数
def get_output_file_path(policy_no=None):
    """根据是否指定保单号返回不同的输出文件名"""
    if policy_no:
        return os.path.join(PROJECT_ROOT, "logs", f"bba_single_policy_{policy_no}_202412.csv")
    else:
        return os.path.join(PROJECT_ROOT, "logs", "bba_batch_results_new_202412.csv")

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

def run_batch_new(run_date="202412", val_method="7", max_workers=32, limit=None, policy_no=None):
    start_time = time.time()
    # 检测JIT状态
    try:
        from BBA_dev.pv_calculator_jit import HAS_NUMBA
        jit_status = "JIT加速" if HAS_NUMBA else "标准模式"
    except:
        jit_status = "标准模式"
    
    # 动态生成输出文件路径
    OUTPUT_FILE = get_output_file_path(policy_no)
    
    # 确定运行模式
    mode = f"单保单模式: {policy_no}" if policy_no else "全量模式"
    
    print(f"=" * 80)
    print(f"New Batch Process (Memory Optimized) Start: {datetime.now()}")
    print(f"Run Date: {run_date} | 运行模式: {mode} | 性能模式: {jit_status}")
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

    # 如果指定了保单号，只处理该保单
    if policy_no is not None:
        original_count = len(df_all)
        df_all = df_all[df_all['policy_no'] == policy_no]
        if df_all.empty:
            print(f"错误: 未找到保单号 {policy_no} 的数据")
            return
        print(f"已过滤为单保单模式：{policy_no} (从 {original_count} 条记录中筛选出 {len(df_all)} 条)")

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
            # 锁定利率从0开始，与旧逻辑一致（后续在初始确认中由即期利率更新）
            'initial_spot_rate': Decimal('0') 
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
    executor = None
    future_to_task = None
    
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
                        # 与旧批处理保持一致：摊销的CSM、IFIE_CSM 取反
                        for r in results:
                            for k in [
                                "保险合同收入_摊销的CSM",
                                "IFIE_P&L_未到期_CSM",
                            ]:
                                if k in r and r[k] is not None:
                                    r[k] = -r[k]
                        # 写入结果
                        csv_writer.append(results, block=False)
                    
                    completed_count += 1
                    if completed_count % 100 == 0 or completed_count == total_policies:
                        stats = csv_writer.get_stats()
                        pct = (completed_count / total_policies) * 100
                        print(f"Progress: {completed_count}/{total_policies} ({pct:.1f}%) | Written: {stats['total_written']} | Queue: {stats['queue_size']}")
                        
                except Exception as e:
                    print(f"Critical error for {p_no}: {e}")
    
    except KeyboardInterrupt:
        print("\n>>> 收到中断信号 (Ctrl+C)，正在清理资源...")
        # 尝试取消未完成的任务
        if executor and future_to_task:
            try:
                for future in future_to_task:
                    if not future.done():
                        future.cancel()
            except:
                pass
        raise  # 重新抛出，让外层 finally 处理
    
    except Exception as e:
        print(f"\n>>> 发生异常: {e}")
        raise  # 重新抛出，让外层 finally 处理
    
    finally:
        # 无论正常结束还是异常中断，都要清理资源
        print(">>> 正在清理资源...")
        
        # 停止 CSV Writer
        try:
            csv_writer.stop()
            print("✓ CSV Writer 已停止")
        except Exception as e:
            print(f"⚠️ 停止 CSV Writer 时出错: {e}")
        
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
        
    end_time = time.time()
    duration = end_time - start_time
    print(f"=" * 80)
    print(f"DONE. Total time: {duration:.2f}s ({duration/60:.2f} min)")
    print(f"Output: {OUTPUT_FILE}")
    print(f"=" * 80)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='BBA批量处理脚本（新版）')
    parser.add_argument('--limit', type=int, help='限制处理的保单数量')
    parser.add_argument('--policy-no', type=str, help='只处理指定的保单号')
    parser.add_argument('--run-date', type=str, default='202412', help='运行日期')
    parser.add_argument('--val-method', type=str, default='7', help='估值方法')
    parser.add_argument('--max-workers', type=int, default=32, help='最大工作进程数')
    
    # 兼容旧的参数方式（第一个参数为limit）
    if len(sys.argv) == 2 and not any(arg.startswith('--') for arg in sys.argv[1:]):
        try:
            limit_arg = int(sys.argv[1])
            print(f"Limit set to: {limit_arg} (使用兼容模式)")
            run_batch_new(limit=limit_arg)
        except ValueError:
            print("参数格式错误，使用新的参数格式，请参考 --help")
    else:
        args = parser.parse_args()
        run_batch_new(
            run_date=args.run_date,
            val_method=args.val_method, 
            max_workers=args.max_workers,
            limit=args.limit,
            policy_no=args.policy_no
        )
