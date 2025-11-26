from decimal import Decimal
from datetime import datetime
import sys
from typing import Optional

class CalculationLogger:
    def __init__(self, md_file_path: Optional[str] = None):
        """
        初始化日志记录器
        
        Args:
            md_file_path: 可选的 Markdown 文件路径，如果提供，日志将同时写入文件
        """
        self.md_file_path = md_file_path
        self.md_file = None
        if md_file_path:
            self.md_file = open(md_file_path, 'w', encoding='utf-8')
            # 写入 Markdown 文件头部
            self.md_file.write(f"# IFRS 17 BBA 生命周期仿真日志\n\n")
            self.md_file.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            self.md_file.write("---\n\n")
    
    def __del__(self):
        """关闭 Markdown 文件"""
        if self.md_file:
            self.md_file.close()
    
    def _write(self, text: str):
        """同时输出到控制台和 Markdown 文件"""
        print(text, end='')
        if self.md_file:
            self.md_file.write(text)
            self.md_file.flush()
    
    def log_section(self, title):
        """记录章节标题"""
        # 控制台输出
        print(f"\n{'='*100}")
        print(f" {title}")
        print(f"{'='*100}")
        
        # Markdown 输出
        if self.md_file:
            self.md_file.write(f"\n## {title}\n\n")
    
    def _format_decimal(self, value: Decimal) -> str:
        """根据数值大小选择合适的精度"""
        if value == 0:
            return "0.00"
        precision = 6 if abs(value) < Decimal('10') else 2
        fmt = f"{{:,.{precision}f}}"
        return fmt.format(value)
    
    def _format_value(self, value):
        """统一格式化输出"""
        if isinstance(value, Decimal):
            return self._format_decimal(value)
        return value
    
    def log_item(self, item_name, definition, formula, values, result, note=None):
        """记录计算项"""
        # 控制台输出
        print(f"\n[{item_name}]")
        print(f"  定义: {definition}")
        print(f"  公式: {formula}")
        
        # Format values for display
        val_str_list = []
        for k, v in values.items():
            val_str_list.append(f"{k}={self._format_value(v)}")
        
        print(f"  数值: {', '.join(val_str_list)}")
        
        print(f"  结果: {self._format_value(result)}")
            
        if note:
            print(f"  说明: {note}")
        
        # Markdown 输出
        if self.md_file:
            self.md_file.write(f"### {item_name}\n\n")
            self.md_file.write(f"**定义**: {definition}\n\n")
            self.md_file.write(f"**公式**: `{formula}`\n\n")
            
            # 格式化数值
            val_md_list = []
            for k, v in values.items():
                val_md_list.append(f"{k} = {self._format_value(v)}")
            self.md_file.write(f"**数值**: {', '.join(val_md_list)}\n\n")
            
            self.md_file.write(f"**结果**: `{self._format_value(result)}`\n\n")
            
            if note:
                self.md_file.write(f"*说明*: {note}\n\n")
            
            self.md_file.write("---\n\n")
    
    def log_text(self, text: str):
        """记录普通文本（同时输出到控制台和 Markdown）"""
        print(text)
        if self.md_file:
            self.md_file.write(f"{text}\n\n")
    
    def close(self):
        """关闭 Markdown 文件"""
        if self.md_file:
            self.md_file.close()
            self.md_file = None

