import os
import sys
from typing import List, Dict, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr
import io
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
from datetime import datetime

import pandas as pd

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from BBA_group.data_access.loader import (
    get_all_group_ids,
    preload_static_data,
    clear_static_cache
)
from BBA_group.scripts.run_group_lifecycle_simulation import GroupLifecycleSimulator
from BBA_group.utils.async_csv_writer import AsyncCSVWriter

# 输出配置
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "logs", "bba_group_batch_results_202412.csv")
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# 异步写入配置
ASYNC_BUFFER_SIZE = 500
FLUSH_INTERVAL = 5.0

# 并发配置
MAX_WORKERS = 8

# 表头：新增 group_id 其余沿用原 RESULT_COLUMNS
RESULT_COLUMNS = ["group_id"] + [
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


def process_single_group(
    group_id: str,
    run_date: str,
    val_method: str
) -> Tuple[str, Optional[List[Dict]], Optional[str]]:
    """
    独立进程处理单个 group_id
    """
    try:
        simulator = GroupLifecycleSimulator(
            group_id,
            enable_logging=False,
            dynamic_pv_mode=True,
            run_date=run_date,
            val_method=val_method,
            enable_reports=False
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            results = simulator.run()
        output = buffer.getvalue()

        # 遇到警告符号则中断
        if "⚠️" in output:
            return group_id, None, "检测到警告，停止批量执行"

        # 添加 group_id 字段并调整符号
        if results:
            for r in results:
                r["group_id"] = group_id
                for k in [
                    "保险合同收入_摊销的CSM",
                    "IFIE_P&L_未到期_CSM",
                ]:
                    if k in r and r[k] is not None:
                        r[k] = -r[k]

        return group_id, results, None
    except Exception as exc:
        return group_id, None, str(exc)
    finally:
        try:
            from BBA_group.data_access.db_utils import dispose_all_engines
            dispose_all_engines()
        except Exception:
            pass


def run_group_batch(
    run_date: str = "202412",
    val_method: str = "7",
    max_workers: int = MAX_WORKERS,
    limit: int = None,
    group_id: str = None,
    output_file: Optional[str] = None,
    buffer_size: int = ASYNC_BUFFER_SIZE,
    flush_interval: float = FLUSH_INTERVAL,
    preload: bool = True,
):
    start_time = time.time()
    start_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    output_path = output_file or OUTPUT_FILE
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print("=" * 80)
    print(f"组批处理开始时间: {start_datetime}")
    print(f"运行批次: {run_date} | 计量方法: {val_method}")
    print(f"最大进程数: {max_workers}")
    print("=" * 80)

    if preload:
        try:
            preload_result = preload_static_data(run_date=run_date, val_method=val_method)
            if preload_result.get("status") == "success":
                print(f"✅ 静态数据预加载成功 | 利率: {preload_result['rates_loaded']} | 假设: {preload_result['assumptions_loaded']}")
            else:
                print("⚠️ 静态数据预加载失败，将在运行时动态加载")
        except Exception as e:
            print(f"⚠️ 静态数据预加载异常: {e}，将运行时动态加载")

    # 校验旧文件表头
    if os.path.exists(output_path):
        try:
            existing_df = pd.read_csv(output_path, nrows=0)
            if list(existing_df.columns) != RESULT_COLUMNS:
                backup_file = output_path.replace(".csv", "_backup.csv")
                import shutil
                shutil.copy2(output_path, backup_file)
                print(f"⚠️ 旧CSV表头不匹配，已备份到 {backup_file} 并删除原文件")
                os.remove(output_path)
        except Exception as e:
            print(f"⚠️ 检查旧CSV出错: {e}，将重新生成")
            if os.path.exists(output_path):
                os.remove(output_path)

    group_ids = get_all_group_ids(run_date=run_date, val_method=val_method)
    if not group_ids:
        print("⚠️ 未获取到 group_id 列表，任务结束")
        return

    if group_id is not None:
        group_ids = [gid for gid in group_ids if gid == group_id]
        if not group_ids:
            print(f"❌ 未找到 group_id {group_id}")
            return
        print(f"🔍 单组测试模式：仅处理 group_id={group_id}")
    elif limit is not None and limit > 0:
        group_ids = group_ids[:limit]
        print(f"⚠️ 测试模式：仅处理前 {limit} 个 group_id")

    total = len(group_ids)
    print(f"共需处理 {total} 个 group_id，使用 {max_workers} 个进程")

    csv_writer = AsyncCSVWriter(
        output_file=output_path,
        columns=RESULT_COLUMNS,
        buffer_size=buffer_size,
        flush_interval=flush_interval
    )
    csv_writer.start()

    completed_count = 0
    completed_lock = threading.Lock()
    stop_flag = False

    def update_progress():
        nonlocal completed_count
        with completed_lock:
            completed_count += 1
            progress_pct = completed_count / total * 100
            if completed_count % 50 == 0 or completed_count % (total // 10 + 1) == 0:
                stats = csv_writer.get_stats()
                print(f"进度: {completed_count}/{total} ({progress_pct:.2f}%) | 已写入: {stats['total_written']} | 队列: {stats['queue_size']}")

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_group = {
                executor.submit(process_single_group, gid, run_date, val_method): gid
                for gid in group_ids
            }

            try:
                for future in as_completed(future_to_group):
                    gid = future_to_group[future]
                    try:
                        result_gid, results, error_msg = future.result()

                        if error_msg:
                            print(f"❌ Group {result_gid} 失败: {error_msg}")
                            print("检测到错误，批处理已停止。")
                            stop_flag = True
                            for f in future_to_group:
                                f.cancel()
                            break

                        if results:
                            csv_writer.append(results, block=False)

                        update_progress()

                    except Exception as exc:
                        print(f"❌ Group {gid} 处理异常: {exc}")
                        print("检测到错误，批处理已停止。")
                        stop_flag = True
                        for f in future_to_group:
                            f.cancel()
                        break
            except KeyboardInterrupt:
                print("\n⚠️ 用户中断，正在停止...")
                stop_flag = True
                for f in future_to_group:
                    f.cancel()
    finally:
        print(f"\n{'='*80}")
        print("正在停止异步CSV写入器...")
        print(f"{'='*80}")
        csv_writer.stop(timeout=60.0)
        final_stats = csv_writer.get_stats()
        print(f"✅ 异步CSV写入器已停止 | 总写入: {final_stats['total_written']} | 写入次数: {final_stats['write_count']} | 平均批次: {final_stats['avg_batch_size']:.1f}")

    end_time = time.time()
    end_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    elapsed_time = end_time - start_time
    elapsed_minutes = elapsed_time / 60
    elapsed_hours = elapsed_time / 3600

    try:
        clear_static_cache()
        print("✅ 已清理静态数据缓存")
    except Exception as e:
        print(f"⚠️ 清理缓存失败: {e}")

    print("=" * 80)
    print(f"✅ 组批处理完成，共处理 {completed_count}/{total} 个组")
    print(f"开始时间: {start_datetime} | 结束时间: {end_datetime}")
    print(f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_minutes:.2f} 分钟 / {elapsed_hours:.2f} 小时)")
    if completed_count > 0:
        avg_time = elapsed_time / completed_count
        print(f"平均每组耗时: {avg_time:.2f} 秒")
    print(f"输出文件: {output_path}")
    print("=" * 80)

    try:
        from BBA_group.data_access.db_utils import dispose_all_engines
        dispose_all_engines()
        print("✓ 主进程数据库连接已清理")
    except Exception as e:
        print(f"⚠️ 清理主进程数据库连接时出错: {e}")


if __name__ == "__main__":
    import sys
    limit = None
    target_group = None
    output_file = None
    buffer_size = ASYNC_BUFFER_SIZE
    flush_interval = FLUSH_INTERVAL
    preload = True

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--group":
            if i + 1 < len(args):
                target_group = args[i + 1]
                i += 2
                continue
        elif arg == "--limit":
            if i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    print(f"⚠️ 无效的 limit 参数: {args[i + 1]}")
                i += 2
                continue
        elif arg == "--output":
            if i + 1 < len(args):
                output_file = args[i + 1]
                i += 2
                continue
        elif arg == "--buffer":
            if i + 1 < len(args):
                try:
                    buffer_size = int(args[i + 1])
                except ValueError:
                    print(f"⚠️ 无效的 buffer 参数: {args[i + 1]}")
                i += 2
                continue
        elif arg == "--flush":
            if i + 1 < len(args):
                try:
                    flush_interval = float(args[i + 1])
                except ValueError:
                    print(f"⚠️ 无效的 flush 参数: {args[i + 1]}")
                i += 2
                continue
        elif arg == "--no-preload":
            preload = False
            i += 1
            continue
        elif arg in ("-h", "--help"):
            print("=" * 80)
            print("组批处理脚本使用方法:")
            print("=" * 80)
            print("1) 全量处理: python run_group_batch_lifecycle.py")
            print("2) 单组测试: python run_group_batch_lifecycle.py --group [group_id]")
            print("3) 限量测试: python run_group_batch_lifecycle.py --limit [N]")
            print("4) 自定义输出: python run_group_batch_lifecycle.py --output [path]")
            print("5) 调整并发: python run_group_batch_lifecycle.py --max_workers [N]")
            print("6) 调整写入: --buffer [size] --flush [seconds]")
            print("7) 跳过预加载: --no-preload")
            print("=" * 80)
            sys.exit(0)
        elif arg == "--max_workers":
            if i + 1 < len(args):
                try:
                    MAX_WORKERS = int(args[i + 1])
                except ValueError:
                    print(f"⚠️ 无效的 max_workers 参数: {args[i + 1]}")
                i += 2
                continue
        i += 1

    run_group_batch(
        limit=limit,
        group_id=target_group,
        output_file=output_file,
        buffer_size=buffer_size,
        flush_interval=flush_interval,
        preload=preload,
        max_workers=MAX_WORKERS,
    )


