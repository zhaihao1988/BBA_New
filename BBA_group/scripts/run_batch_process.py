import os
import sys
from typing import List, Dict, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr
import io
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import time
from datetime import datetime

import pandas as pd

# 将项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from BBA_group.data_access.loader import get_all_policy_entries, preload_static_data, clear_static_cache
from BBA_group.scripts.run_lifecycle_simulation import LifecycleSimulator
from BBA_group.utils.async_csv_writer import AsyncCSVWriter

OUTPUT_FILE = os.path.join(PROJECT_ROOT, "logs", "bba_batch_results_202412.csv")
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# 异步写入配置
ASYNC_BUFFER_SIZE = 500  # 异步写入缓冲区大小（从100提升到500）
FLUSH_INTERVAL = 5.0     # 自动刷新间隔（秒）

# 多进程配置：充分利用32核CPU
MAX_WORKERS = 8  # 可根据实际情况调整（建议为CPU核心数）
RESULT_COLUMNS = [
    "policy_no",
    "certi_no",
    "year",
    "保险合同收入_预期赔付与费用_含亏损",
    "保险合同收入_预期赔付与费用_亏损分摊",
    "保险合同收入_预期释放的非金融风险调整_含亏损",
    "保险合同收入_预期释放的非金融风险调整_亏损分摊",
    "保险合同收入_摊销的CSM",
    "保险合同收入_摊销的IACF",
    "保险合同收入_经验调整",
    "赔付与费用_亏损分摊_预期现金流",
    "赔付与费用_亏损分摊_非金融风险调整",
    "赔付与费用_摊销的IACF",
    "亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损",
    "亏损合同损益_新增合同非金融风险调整_亏损",
    "亏损合同损益_不调整CSM的预期现金流变动",
    "亏损合同损益_不调整CSM的非金融风险调整变动",
    "IFIE_P&L_未到期_预期现金流_非亏损",
    "IFIE_P&L_未到期_预期现金流_亏损",
    "IFIE_P&L_未到期_非金融风险调整_非亏损",
    "IFIE_P&L_未到期_非金融风险调整_亏损",
    "IFIE_P&L_未到期_CSM",
    "IFIE_OCI_未到期_预期现金流_非亏损",
    "IFIE_OCI_未到期_预期现金流_亏损",
    "IFIE_OCI_未到期_非金融风险调整_非亏损",
    "IFIE_OCI_未到期_非金融风险调整_亏损",
    "未到期责任负债_预期现金流_非亏损",
    "未到期责任负债_预期现金流_亏损",
    "未到期责任负债_非金融风险调整_非亏损",
    "未到期责任负债_非金融风险调整_亏损",
    "未到期责任负债_CSM",
    "未到期_调整CSM的预期现金流变动",
    "未到期_调整CSM的非金融风险调整变动",
    "未到期_调整CSM的估计变更",
    "新增合同预期现金流_保费现金流_盈利合同",
    "新增合同预期现金流_IACF_盈利合同",
    "新增合同预期现金流_赔付与费用现金流_盈利合同",
    "新增合同非金融风险调整_盈利合同",
    "新增合同CSM_盈利合同",
    "新增合同预期现金流_保费现金流_亏损合同",
    "新增合同预期现金流_IACF_亏损合同",
    "新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损",
    "新增合同非金融风险调整_亏损合同_非亏损",
    "现金流_收到的保费",
    "现金流_支付的获取费用",
]


# 注意：CSV写入已改为异步模式，无需锁


def process_single_policy(
    policy_no: str,
    certi_no: Optional[str],
    run_date: str,
    val_method: str
) -> Tuple[str, Optional[List[Dict]], Optional[str]]:
    """
    处理单个保单/批单组合（在独立进程中运行）
    
    Returns:
        Tuple[policy_no, results, error_message]
        - results: 成功时返回结果列表，失败时返回None
        - error_message: 失败时返回错误信息，成功时返回None
    """
    try:
        simulator = LifecycleSimulator(
            policy_no,
            enable_logging=False,
            certi_no=certi_no,
            dynamic_pv_mode=True,
            run_date=run_date,
            val_method=val_method,
            enable_reports=False  # 批量处理时不生成报表
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            results = simulator.run()
        output = buffer.getvalue()
        
        # 检查警告
        if "⚠️" in output:
            return (policy_no, None, "检测到警告，停止批量执行")
        
        return (policy_no, results, None)
    except Exception as exc:
        return (policy_no, None, str(exc))
    finally:
        # 每个子进程结束时清理数据库连接池
        try:
            from BBA_group.data_access.db_utils import dispose_all_engines
            dispose_all_engines()
        except Exception:
            pass  # 静默失败，避免影响主进程


def run_batch(run_date: str = "202412", val_method: str = "7", max_workers: int = MAX_WORKERS, limit: int = None, policy_no: str = None):
    """
    多进程并行批处理
    
    Args:
        run_date: 运行批次
        val_method: 计量方法
        max_workers: 最大进程数（默认32，充分利用32核CPU）
        limit: 限制处理的保单数量（用于测试，None表示处理全部）
        policy_no: 指定单个保单号进行测试（优先级高于limit参数）
    """
    # 记录开始时间
    start_time = time.time()
    start_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"=" * 80)
    print(f"批处理开始时间: {start_datetime}")
    print(f"运行批次: {run_date}")
    print(f"计量方法: {val_method}")
    print(f"最大进程数: {max_workers}")
    print(f"=" * 80)
    
    # 预加载静态数据（利率曲线和精算假设）
    print(f"\n{'='*80}")
    print("步骤1：预加载静态数据...")
    print(f"{'='*80}")
    try:
        preload_result = preload_static_data(run_date=run_date, val_method=val_method)
        if preload_result['status'] == 'success':
            print(f"✅ 静态数据预加载成功")
            print(f"   - 利率曲线: {preload_result['rates_loaded']} 个月份")
            print(f"   - 精算假设: {preload_result['assumptions_loaded']} 条记录")
            print(f"   - 险类数量: {preload_result['class_codes_count']} 个")
        else:
            print(f"⚠️ 静态数据预加载失败，将在运行时动态加载")
    except Exception as e:
        print(f"⚠️ 静态数据预加载异常: {e}，将在运行时动态加载")
    
    # 检查并处理旧的CSV文件
    if os.path.exists(OUTPUT_FILE):
        try:
            existing_df = pd.read_csv(OUTPUT_FILE, nrows=0)
            existing_columns = list(existing_df.columns)
            if existing_columns != RESULT_COLUMNS:
                # 备份旧文件
                backup_file = OUTPUT_FILE.replace('.csv', '_backup.csv')
                import shutil
                shutil.copy2(OUTPUT_FILE, backup_file)
                print(f"⚠️ 检测到旧CSV文件表头不匹配，已备份到 {backup_file}")
                os.remove(OUTPUT_FILE)
                print(f"✅ 已删除旧CSV文件，将重新生成")
        except Exception as e:
            print(f"⚠️ 检查旧CSV文件时出错: {e}，将重新生成")
            if os.path.exists(OUTPUT_FILE):
                os.remove(OUTPUT_FILE)
    
    policy_entries = get_all_policy_entries(run_date=run_date, val_method=val_method)
    if not policy_entries:
        print("⚠️ 未获取到保单号列表，任务结束")
        return
    
    # 如果指定了保单号，优先执行单保单测试模式
    if policy_no is not None:
        # 筛选出指定的保单
        matching_entries = [entry for entry in policy_entries if entry[0] == policy_no]
        if not matching_entries:
            print(f"❌ 未找到保单号 {policy_no}，请检查保单号是否正确")
            print(f"提示：可用的保单号示例: {[entry[0] for entry in policy_entries[:5]]}")
            return
        policy_entries = matching_entries
        print(f"🔍 单保单测试模式：仅处理保单号 {policy_no}")
    # 如果没有指定保单号但设置了limit，只处理前N条
    elif limit is not None and limit > 0:
        policy_entries = policy_entries[:limit]
        print(f"⚠️ 批量测试模式：仅处理前 {limit} 条保单")

    total = len(policy_entries)
    print(f"共需处理 {total} 条保单/批单组合")
    print(f"使用 {max_workers} 个进程并行处理")
    
    # 创建异步CSV写入器
    print(f"\n{'='*80}")
    print("步骤2：初始化异步CSV写入器...")
    print(f"{'='*80}")
    csv_writer = AsyncCSVWriter(
        output_file=OUTPUT_FILE,
        columns=RESULT_COLUMNS,
        buffer_size=ASYNC_BUFFER_SIZE,
        flush_interval=FLUSH_INTERVAL
    )
    csv_writer.start()
    
    # 进度跟踪（线程安全）
    completed_count = 0
    completed_lock = threading.Lock()
    stop_flag = False
    
    def update_progress():
        """更新进度显示"""
        nonlocal completed_count
        with completed_lock:
            completed_count += 1
            progress_pct = completed_count / total * 100
            # 每10%或每100条显示一次进度（减少输出）
            if completed_count % 100 == 0 or completed_count % (total // 10 + 1) == 0:
                stats = csv_writer.get_stats()
                print(f"进度: {completed_count}/{total} ({progress_pct:.2f}%) | "
                      f"已写入: {stats['total_written']} | 队列: {stats['queue_size']}")
    
    # 使用 ProcessPoolExecutor 并行处理
    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_policy = {
                executor.submit(process_single_policy, policy_no, certi_no, run_date, val_method): (policy_no, certi_no)
                for policy_no, certi_no in policy_entries
            }
            
            # 处理完成的任务
            try:
                for future in as_completed(future_to_policy):
                    policy_no, certi_no = future_to_policy[future]
                    try:
                        result_policy_no, results, error_msg = future.result()
                        
                        if error_msg:
                            # 遇到错误或警告，停止批处理
                            print(f"❌ Policy {result_policy_no} 失败: {error_msg}")
                            print("检测到错误，批处理已停止。")
                            stop_flag = True
                            # 取消剩余任务
                            for f in future_to_policy:
                                f.cancel()
                            break
                        
                        if results:
                            # 写入前调整三个字段符号：CSM摊销、IACF摊销、IFIE_CSM
                            for r in results:
                                for k in [
                                    "保险合同收入_摊销的CSM",
                                    "IFIE_P&L_未到期_CSM",
                                ]:
                                    if k in r and r[k] is not None:
                                        r[k] = -r[k]
                            # 直接添加到异步写入器队列（非阻塞）
                            csv_writer.append(results, block=False)
                        
                        update_progress()
                        
                    except Exception as exc:
                        print(f"❌ Policy {policy_no} 处理异常: {exc}")
                        print("检测到错误，批处理已停止。")
                        stop_flag = True
                        # 取消剩余任务
                        for f in future_to_policy:
                            f.cancel()
                        break
            except KeyboardInterrupt:
                print("\n⚠️ 用户中断，正在停止...")
                stop_flag = True
                for f in future_to_policy:
                    f.cancel()
    finally:
        # 停止异步写入器，等待所有数据写入完成
        print(f"\n{'='*80}")
        print("正在停止异步CSV写入器...")
        print(f"{'='*80}")
        csv_writer.stop(timeout=60.0)  # 最多等待60秒
        
        # 获取最终统计信息
        final_stats = csv_writer.get_stats()
        print(f"✅ 异步CSV写入器已停止")
        print(f"   - 总写入记录: {final_stats['total_written']}")
        print(f"   - 写入操作次数: {final_stats['write_count']}")
        print(f"   - 平均批次大小: {final_stats['avg_batch_size']:.1f}")
    
    # 记录结束时间并计算耗时
    end_time = time.time()
    end_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    elapsed_time = end_time - start_time
    elapsed_minutes = elapsed_time / 60
    elapsed_hours = elapsed_time / 3600
    
    # 清理缓存
    try:
        clear_static_cache()
        print("✅ 已清理静态数据缓存")
    except Exception as e:
        print(f"⚠️ 清理缓存失败: {e}")
    
    print(f"=" * 80)
    print(f"✅ 批处理完成，共处理 {completed_count}/{total} 条保单")
    print(f"开始时间: {start_datetime}")
    print(f"结束时间: {end_datetime}")
    print(f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_minutes:.2f} 分钟 / {elapsed_hours:.2f} 小时)")
    if completed_count > 0:
        avg_time = elapsed_time / completed_count
        print(f"平均每张保单耗时: {avg_time:.2f} 秒")
    print(f"输出文件: {OUTPUT_FILE}")
    print(f"=" * 80)
    
    # 清理数据库连接池（主进程）
    try:
        from BBA_group.data_access.db_utils import dispose_all_engines
        dispose_all_engines()
        print("✓ 主进程数据库连接已清理")
    except Exception as e:
        print(f"⚠️ 清理主进程数据库连接时出错: {e}")


if __name__ == "__main__":
    import sys
    # 支持命令行参数：
    # python run_batch_process.py [limit]                   # 批量测试模式
    # python run_batch_process.py --policy [policy_no]     # 单保单测试模式
    limit = None
    policy_no = None
    
    # 解析命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--policy":
            # 单保单测试模式
            if len(sys.argv) > 2:
                policy_no = sys.argv[2]
                print(f"🔍 使用命令行参数：单保单测试模式，保单号={policy_no}")
            else:
                print("❌ --policy 参数需要指定保单号")
                print("使用方法：python run_batch_process.py --policy [保单号]")
                sys.exit(1)
        elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
            # 显示帮助信息
            print("="*80)
            print("批量处理脚本使用方法:")
            print("="*80)
            print("1. 处理全部保单:")
            print("   python run_batch_process.py")
            print()
            print("2. 批量测试模式（处理前N张保单）:")
            print("   python run_batch_process.py [数量]")
            print("   例如: python run_batch_process.py 10")
            print()
            print("3. 单保单测试模式:")
            print("   python run_batch_process.py --policy [保单号]")
            print("   例如: python run_batch_process.py --policy YSAIC2019000001")
            print()
            print("4. 显示此帮助信息:")
            print("   python run_batch_process.py --help")
            print("="*80)
            sys.exit(0)
        else:
            # 批量测试模式（指定数量）
            try:
                limit = int(sys.argv[1])
                print(f"📊 使用命令行参数：批量测试模式，limit={limit}")
            except ValueError:
                print(f"⚠️ 无效的limit参数: {sys.argv[1]}，将处理全部保单")
                print("提示：使用 --help 查看使用方法")
    
    run_batch(limit=limit, policy_no=policy_no)

