"""
异步CSV写入性能对比测试

对比同步写入和异步写入的性能差异
"""

import sys
import os
import time
import random
import threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from BBA_dev.utils.async_csv_writer import AsyncCSVWriter


def test_sync_write(output_file, columns, data_batches, num_workers=4):
    """测试同步写入性能（使用锁）"""
    print("\n" + "="*80)
    print("测试1：同步写入（使用全局锁）")
    print("="*80)
    
    lock = threading.Lock()
    
    def write_batch(batch_id, batch_data):
        """模拟同步写入"""
        # 模拟计算时间
        time.sleep(0.01)
        
        # 写入CSV（串行等待锁）
        with lock:
            df = pd.DataFrame(batch_data)
            df = df.reindex(columns=columns, fill_value=0)
            header_needed = not os.path.exists(output_file)
            df.to_csv(output_file, mode='a', header=header_needed, index=False)
    
    # 清理旧文件
    if os.path.exists(output_file):
        os.remove(output_file)
    
    # 并发写入
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(write_batch, i, batch)
            for i, batch in enumerate(data_batches)
        ]
        for future in futures:
            future.result()
    
    elapsed = time.time() - start_time
    
    # 验证数据
    df_result = pd.read_csv(output_file)
    total_records = len(df_result)
    
    print(f"✓ 完成")
    print(f"  写入记录: {total_records}")
    print(f"  总耗时: {elapsed:.4f} 秒")
    print(f"  平均每批次: {elapsed/len(data_batches):.4f} 秒")
    
    return elapsed, total_records


def test_async_write(output_file, columns, data_batches, num_workers=4):
    """测试异步写入性能"""
    print("\n" + "="*80)
    print("测试2：异步写入（使用队列和专用写入线程）")
    print("="*80)
    
    def write_batch(batch_id, batch_data, writer):
        """模拟异步写入"""
        # 模拟计算时间
        time.sleep(0.01)
        
        # 非阻塞写入（立即返回）
        writer.append(batch_data, block=False)
    
    # 清理旧文件
    if os.path.exists(output_file):
        os.remove(output_file)
    
    # 创建异步写入器
    writer = AsyncCSVWriter(
        output_file=output_file,
        columns=columns,
        buffer_size=100,
        flush_interval=1.0
    )
    writer.start()
    
    # 并发写入
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(write_batch, i, batch, writer)
            for i, batch in enumerate(data_batches)
        ]
        for future in futures:
            future.result()
    
    # 停止写入器
    writer.stop(timeout=30.0)
    elapsed = time.time() - start_time
    
    # 验证数据
    df_result = pd.read_csv(output_file)
    total_records = len(df_result)
    
    stats = writer.get_stats()
    
    print(f"✓ 完成")
    print(f"  写入记录: {total_records}")
    print(f"  总耗时: {elapsed:.4f} 秒")
    print(f"  平均每批次: {elapsed/len(data_batches):.4f} 秒")
    print(f"  写入操作次数: {stats['write_count']}")
    print(f"  平均批次大小: {stats['avg_batch_size']:.1f}")
    
    return elapsed, total_records


def main():
    """主测试函数"""
    print("="*80)
    print("异步CSV写入性能对比测试")
    print("="*80)
    
    # 测试参数
    num_batches = 200  # 模拟200个批次
    batch_size = 50    # 每批次50条记录
    num_workers = 8    # 8个并发线程
    
    columns = ['policy_no', 'year', 'value1', 'value2', 'value3', 'value4']
    
    print(f"\n测试配置:")
    print(f"  批次数量: {num_batches}")
    print(f"  每批次记录数: {batch_size}")
    print(f"  总记录数: {num_batches * batch_size}")
    print(f"  并发线程数: {num_workers}")
    
    # 生成测试数据
    print(f"\n正在生成测试数据...")
    data_batches = []
    for batch_id in range(num_batches):
        batch = [
            {
                'policy_no': f'P{batch_id}_{i}',
                'year': 2024,
                'value1': random.random() * 1000,
                'value2': random.random() * 500,
                'value3': random.random() * 100,
                'value4': random.random() * 50
            }
            for i in range(batch_size)
        ]
        data_batches.append(batch)
    
    print(f"✓ 测试数据生成完成")
    
    # 测试文件
    sync_file = 'test_sync_output.csv'
    async_file = 'test_async_output.csv'
    
    # 测试同步写入
    sync_time, sync_records = test_sync_write(sync_file, columns, data_batches, num_workers)
    
    # 测试异步写入
    async_time, async_records = test_async_write(async_file, columns, data_batches, num_workers)
    
    # 对比结果
    print("\n" + "="*80)
    print("性能对比结果")
    print("="*80)
    print(f"{'指标':<20} | {'同步写入':<20} | {'异步写入':<20} | {'提升':<15}")
    print("-"*80)
    print(f"{'总耗时(秒)':<20} | {sync_time:<20.4f} | {async_time:<20.4f} | {sync_time/async_time:<15.2f}x")
    print(f"{'平均延迟(毫秒)':<20} | {sync_time/num_batches*1000:<20.2f} | {async_time/num_batches*1000:<20.2f} | {sync_time/async_time:<15.2f}x")
    print(f"{'吞吐量(条/秒)':<20} | {sync_records/sync_time:<20.0f} | {async_records/async_time:<20.0f} | {(async_records/async_time)/(sync_records/sync_time):<15.2f}x")
    print(f"{'写入记录数':<20} | {sync_records:<20} | {async_records:<20} | {'一致' if sync_records==async_records else '不一致':<15}")
    
    # 验证数据一致性
    print("\n" + "="*80)
    print("数据一致性验证")
    print("="*80)
    
    df_sync = pd.read_csv(sync_file)
    df_async = pd.read_csv(async_file)
    
    # 按policy_no排序后对比
    df_sync_sorted = df_sync.sort_values('policy_no').reset_index(drop=True)
    df_async_sorted = df_async.sort_values('policy_no').reset_index(drop=True)
    
    is_equal = df_sync_sorted.equals(df_async_sorted)
    
    print(f"数据一致性: {'✓ 完全一致' if is_equal else '✗ 存在差异'}")
    print(f"同步写入记录数: {len(df_sync)}")
    print(f"异步写入记录数: {len(df_async)}")
    
    # 清理测试文件
    for f in [sync_file, async_file]:
        if os.path.exists(f):
            os.remove(f)
    
    print("\n" + "="*80)
    print("✅ 测试完成！")
    print("="*80)
    print(f"\n结论：")
    print(f"  1. 异步写入性能提升：{sync_time/async_time:.1f}倍")
    print(f"  2. 数据一致性：{'✓ 验证通过' if is_equal else '✗ 验证失败'}")
    print(f"  3. I/O等待时间减少：{(1 - async_time/sync_time)*100:.1f}%")
    print(f"  4. 适用场景：高并发、大批量数据写入")


if __name__ == "__main__":
    main()

