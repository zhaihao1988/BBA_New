"""
异步CSV写入器

使用专用线程和队列缓冲机制，避免CSV写入时的全局锁竞争。

特性：
1. 非阻塞写入：主进程将数据放入队列后立即返回
2. 批量写入：累积到一定数量后批量写入，提高效率
3. 自动刷新：定期刷新缓冲区，避免数据丢失
4. 线程安全：使用队列实现线程间通信
5. 优雅关闭：确保所有数据写入完成后才退出

性能提升预期：50-60%的I/O等待时间减少
"""

import os
import threading
import queue
import time
import pandas as pd
from typing import List, Dict, Optional
from pathlib import Path


class AsyncCSVWriter:
    """异步CSV写入器"""
    
    def __init__(
        self,
        output_file: str,
        columns: List[str],
        buffer_size: int = 500,
        flush_interval: float = 5.0,
        queue_maxsize: int = 2000
    ):
        """
        初始化异步CSV写入器
        
        Args:
            output_file: 输出文件路径
            columns: CSV列名列表
            buffer_size: 缓冲区大小（累积多少条数据后批量写入）
            flush_interval: 自动刷新间隔（秒），避免长时间不写入
            queue_maxsize: 队列最大大小（避免内存溢出）
        """
        self.output_file = output_file
        self.columns = columns
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        
        # 数据队列
        self.data_queue = queue.Queue(maxsize=queue_maxsize)
        
        # 写入线程
        self.writer_thread = threading.Thread(
            target=self._write_worker,
            name="AsyncCSVWriter",
            daemon=False  # 非守护线程，确保数据写完
        )
        
        # 控制标志
        self._running = False
        self._stopped = threading.Event()
        
        # 统计信息
        self.total_written = 0
        self.write_count = 0
        self._lock = threading.Lock()
        
        # 检查并处理旧文件
        self._initialize_file()
        
    def _initialize_file(self):
        """初始化输出文件"""
        # 确保目录存在
        output_dir = os.path.dirname(self.output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # 检查文件是否存在且表头是否匹配
        if os.path.exists(self.output_file):
            try:
                existing_df = pd.read_csv(self.output_file, nrows=0)
                existing_columns = list(existing_df.columns)
                
                if existing_columns != self.columns:
                    # 备份旧文件
                    backup_file = self.output_file.replace('.csv', '_backup.csv')
                    import shutil
                    shutil.copy2(self.output_file, backup_file)
                    print(f"⚠️  检测到旧CSV文件表头不匹配，已备份到 {backup_file}")
                    os.remove(self.output_file)
                    print(f"✅ 已删除旧CSV文件，将重新生成")
                else:
                    # 表头匹配，无需重新创建
                    pass
            except Exception as e:
                print(f"⚠️  检查旧CSV文件时出错: {e}，将重新生成")
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
    
    def start(self):
        """启动写入线程"""
        if self._running:
            return
        
        self._running = True
        self._stopped.clear()
        self.writer_thread.start()
        print(f"✓ 异步CSV写入器已启动（缓冲区大小: {self.buffer_size}）")
    
    def append(self, results: List[Dict], block: bool = True, timeout: Optional[float] = None):
        """
        添加数据到写入队列（非阻塞）
        
        Args:
            results: 要写入的数据列表
            block: 是否阻塞等待队列有空间（默认True）
            timeout: 超时时间（秒），None表示无限等待
        
        Returns:
            bool: 是否成功添加到队列
        
        Raises:
            queue.Full: 如果队列已满且block=False
        """
        if not results:
            return True
        
        try:
            self.data_queue.put(results, block=block, timeout=timeout)
            return True
        except queue.Full:
            print(f"⚠️  写入队列已满，等待中...")
            return False
    
    def _write_worker(self):
        """
        写入工作线程
        
        持续从队列中获取数据并写入文件。
        累积到buffer_size条数据后批量写入，或超过flush_interval秒后强制写入。
        """
        buffer: List[Dict] = []
        last_flush_time = time.time()
        
        while self._running or not self.data_queue.empty():
            try:
                # 从队列获取数据（带超时，避免死锁）
                data_batch = self.data_queue.get(timeout=1.0)
                buffer.extend(data_batch)
                self.data_queue.task_done()
                
                # 检查是否需要写入
                current_time = time.time()
                should_flush = (
                    len(buffer) >= self.buffer_size or  # 缓冲区已满
                    (current_time - last_flush_time) >= self.flush_interval  # 超过刷新间隔
                )
                
                if should_flush and buffer:
                    self._flush_buffer(buffer)
                    buffer = []
                    last_flush_time = current_time
                    
            except queue.Empty:
                # 队列为空，检查是否需要定时刷新
                current_time = time.time()
                if buffer and (current_time - last_flush_time) >= self.flush_interval:
                    self._flush_buffer(buffer)
                    buffer = []
                    last_flush_time = current_time
                continue
            
            except Exception as e:
                print(f"❌ 写入线程异常: {e}")
                import traceback
                traceback.print_exc()
        
        # 写入剩余数据
        if buffer:
            self._flush_buffer(buffer)
        
        self._stopped.set()
        print(f"✓ 异步CSV写入器已停止（共写入 {self.total_written} 条记录，{self.write_count} 次写入操作）")
    
    def _flush_buffer(self, buffer: List[Dict]):
        """
        刷新缓冲区，批量写入CSV
        
        Args:
            buffer: 待写入的数据列表
        """
        if not buffer:
            return
        
        try:
            # 转换为DataFrame
            df = pd.DataFrame(buffer)
            
            # 确保所有列都存在，缺失的填0
            df = df.reindex(columns=self.columns, fill_value=0)
            
            # 判断是否需要写入表头
            header_needed = not os.path.exists(self.output_file)
            
            # 写入CSV（追加模式）
            df.to_csv(self.output_file, mode='a', header=header_needed, index=False)
            
            # 更新统计信息
            with self._lock:
                self.total_written += len(buffer)
                self.write_count += 1
            
        except Exception as e:
            print(f"❌ CSV写入失败: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self, timeout: float = 30.0):
        """
        停止写入器，等待所有数据写入完成
        
        Args:
            timeout: 最大等待时间（秒）
        
        Returns:
            bool: 是否成功停止（所有数据已写入）
        """
        if not self._running:
            return True
        
        print(f"正在停止异步CSV写入器...")
        
        # 标记停止
        self._running = False
        
        # 等待队列清空
        try:
            self.data_queue.join()  # 等待所有任务完成
        except Exception as e:
            print(f"⚠️  等待队列清空时出错: {e}")
        
        # 等待写入线程结束
        success = self._stopped.wait(timeout=timeout)
        
        if not success:
            print(f"⚠️  警告: 写入线程在 {timeout} 秒内未能完成，可能有数据丢失")
            return False
        
        return True
    
    def get_stats(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            dict: 包含统计信息的字典
        """
        with self._lock:
            return {
                'total_written': self.total_written,
                'write_count': self.write_count,
                'queue_size': self.data_queue.qsize(),
                'avg_batch_size': self.total_written / self.write_count if self.write_count > 0 else 0
            }
    
    def __enter__(self):
        """上下文管理器：进入"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器：退出"""
        self.stop()
        return False


# 便捷函数
def create_async_csv_writer(
    output_file: str,
    columns: List[str],
    buffer_size: int = 500,
    auto_start: bool = True
) -> AsyncCSVWriter:
    """
    创建并启动异步CSV写入器
    
    Args:
        output_file: 输出文件路径
        columns: CSV列名列表
        buffer_size: 缓冲区大小
        auto_start: 是否自动启动
    
    Returns:
        AsyncCSVWriter实例
    """
    writer = AsyncCSVWriter(output_file, columns, buffer_size=buffer_size)
    if auto_start:
        writer.start()
    return writer


if __name__ == "__main__":
    # 测试代码
    import random
    
    print("="*80)
    print("异步CSV写入器测试")
    print("="*80)
    
    # 创建测试数据
    test_columns = ['id', 'value1', 'value2', 'value3']
    test_file = 'test_async_output.csv'
    
    # 使用上下文管理器
    with AsyncCSVWriter(test_file, test_columns, buffer_size=100) as writer:
        # 模拟写入1000条数据
        for batch_id in range(10):
            batch_data = [
                {
                    'id': i,
                    'value1': random.random() * 1000,
                    'value2': random.random() * 500,
                    'value3': random.random() * 100
                }
                for i in range(batch_id * 100, (batch_id + 1) * 100)
            ]
            writer.append(batch_data)
            print(f"已添加批次 {batch_id + 1}/10 到队列")
            time.sleep(0.1)  # 模拟计算时间
        
        print(f"\n统计信息: {writer.get_stats()}")
    
    print(f"\n✅ 测试完成！数据已写入到 {test_file}")
    
    # 验证数据
    df = pd.read_csv(test_file)
    print(f"验证: 写入了 {len(df)} 条记录")
    
    # 清理测试文件
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"已清理测试文件")

