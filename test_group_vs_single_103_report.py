"""
测试脚本：循环运行组级和单级仿真，直到两个103报表一致

使用方法：
    python test_group_vs_single_103_report.py
"""

import os
import sys
import subprocess
import time
import re
from pathlib import Path
from typing import Dict, List, Tuple
from decimal import Decimal

# 设置UTF-8编码
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 设置虚拟环境Python路径
venv_python = project_root / ".venv" / "Scripts" / "python.exe"
if not venv_python.exists():
    venv_python = project_root / ".venv" / "bin" / "python"
if not venv_python.exists():
    venv_python = sys.executable  # 回退到当前Python

logs_dir = project_root / "logs"
# 根据实际生成的文件名调整
# 单级：ifrs17_103_report_mock3.html
# 组级：ifrs17_103_report_group_{GROUP_ID}.html 或 ifrs17_103_report_mock3_group.html
single_html = logs_dir / "ifrs17_103_report_mock3.html"
# 先尝试mock3_group，如果不存在则尝试使用GROUP_ID
group_html_mock3 = logs_dir / "ifrs17_103_report_mock3_group.html"
group_html_groupid = logs_dir / "ifrs17_103_report_group_QHPLIA2023ABBA300.html"
group_html = group_html_mock3 if group_html_mock3.exists() else group_html_groupid

# 组级和单级脚本路径
group_script = project_root / "BBA_group" / "scripts" / "run_group_lifecycle_simulation.py"
single_script = project_root / "BBA_group" / "scripts" / "run_lifecycle_simulation.py"


def extract_numeric_values_from_html(html_path: Path) -> Dict[str, List[float]]:
    """
    从HTML文件中提取所有数值，按表格行组织
    返回格式: {table_id: [values]}
    """
    if not html_path.exists():
        return {}
    
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取所有数值（包括负数，支持括号表示负数）
    # 匹配模式：数字、小数点、负号、括号（表示负数）
    # 先处理括号负数：(123.45) -> -123.45
    content_normalized = re.sub(r'\((\d+\.?\d*)\)', r'-\1', content)
    
    # 提取数值（包括负数）
    pattern = r'(-?\d+\.?\d*)'
    
    # 按表格提取
    tables = {}
    table_pattern = r'<table[^>]*>.*?</table>'
    table_matches = re.finditer(table_pattern, content_normalized, re.DOTALL)
    
    for idx, table_match in enumerate(table_matches):
        table_content = table_match.group(0)
        # 提取所有数值
        values = []
        for match in re.finditer(pattern, table_content):
            try:
                val = float(match.group(1))
                # 跳过明显不是数据的值（如年份、行号等）
                # 只保留合理的财务数值范围
                if abs(val) < 1e10 and abs(val) > 1e-10:  # 排除0和极小的值
                    values.append(val)
                elif val == 0.0:  # 保留0值
                    values.append(0.0)
            except ValueError:
                continue
        if values:  # 只保存非空表格
            tables[f"table_{idx}"] = values
    
    # 如果没有找到表格，直接提取所有数值
    if not tables:
        values = []
        for match in re.finditer(pattern, content_normalized):
            try:
                val = float(match.group(1))
                if abs(val) < 1e10:
                    values.append(val)
            except ValueError:
                continue
        if values:
            tables["all"] = values
    
    return tables


def compare_html_files(group_html_path: Path, single_html_path: Path, tolerance: float = 0.01) -> Tuple[bool, str]:
    """
    比较两个HTML文件中的数值是否一致
    
    返回: (是否一致, 差异说明)
    """
    if not group_html_path.exists():
        return False, f"组级HTML文件不存在: {group_html_path}"
    
    if not single_html_path.exists():
        return False, f"单级HTML文件不存在: {single_html_path}"
    
    group_values = extract_numeric_values_from_html(group_html_path)
    single_values = extract_numeric_values_from_html(single_html_path)
    
    # 比较主要数值（排除年份、行号等）
    group_nums = []
    single_nums = []
    
    for table_id, values in group_values.items():
        # 过滤掉明显不是数据的值
        filtered = [v for v in values if abs(v) > 0.001 or v == 0.0]
        group_nums.extend(filtered)
    
    for table_id, values in single_values.items():
        filtered = [v for v in values if abs(v) > 0.001 or v == 0.0]
        single_nums.extend(filtered)
    
    # 排序以便比较
    group_nums.sort()
    single_nums.sort()
    
    # 比较长度
    if len(group_nums) != len(single_nums):
        return False, f"数值数量不一致: 组级={len(group_nums)}, 单级={len(single_nums)}"
    
    # 逐个比较
    differences = []
    for i, (g_val, s_val) in enumerate(zip(group_nums, single_nums)):
        diff = abs(g_val - s_val)
        if diff > tolerance:
            differences.append(f"位置{i}: 组级={g_val:.2f}, 单级={s_val:.2f}, 差异={diff:.2f}")
    
    if differences:
        return False, f"发现 {len(differences)} 处差异:\n" + "\n".join(differences[:10])  # 只显示前10个
    
    return True, "所有数值一致"


def run_simulation(script_path: Path, script_type: str) -> bool:
    """
    运行仿真脚本
    
    返回: 是否成功
    """
    print(f"\n{'='*60}")
    print(f"运行 {script_type} 仿真...")
    print(f"{'='*60}")
    
    try:
        # 使用虚拟环境的Python运行脚本
        result = subprocess.run(
            [str(venv_python), str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=300  # 5分钟超时
        )
        
        if result.returncode != 0:
            print(f"[FAIL] {script_type} 仿真失败:")
            print(result.stderr)
            return False
        
        print(f"[SUCCESS] {script_type} 仿真完成")
        if result.stdout:
            # 只显示最后几行输出
            lines = result.stdout.strip().split('\n')
            print('\n'.join(lines[-10:]))
        
        return True
        
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {script_type} 仿真超时")
        return False
    except Exception as e:
        print(f"[FAIL] {script_type} 仿真出错: {e}")
        return False


def main():
    """主函数：循环运行直到两个报告一致"""
    global group_html
    
    print("="*60)
    print("组级 vs 单级 103报表一致性测试")
    print("="*60)
    
    # 如果组级HTML不存在，尝试使用mock3_group
    if not group_html.exists():
        print(f"[WARN] 组级HTML不存在: {group_html}")
        print(f"   尝试使用: {group_html_mock3}")
        if group_html_mock3.exists():
            group_html = group_html_mock3
        else:
            print(f"   也不存在: {group_html_mock3}")
            print(f"   将使用组ID生成的文件: {group_html_groupid}")
            group_html = group_html_groupid
    
    print(f"组级HTML: {group_html}")
    print(f"单级HTML: {single_html}")
    print(f"使用Python: {venv_python}")
    print("="*60)
    
    max_iterations = 10
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'#'*60}")
        print(f"第 {iteration} 次迭代")
        print(f"{'#'*60}")
        
        # 1. 运行单级仿真
        if not run_simulation(single_script, "单级"):
            print("❌ 单级仿真失败，退出")
            return False
        
        # 2. 运行组级仿真
        if not run_simulation(group_script, "组级"):
            print("❌ 组级仿真失败，退出")
            return False
        
        # 3. 等待文件生成
        time.sleep(1)
        
        # 4. 比较两个HTML文件
        print(f"\n{'='*60}")
        print("比较两个HTML文件...")
        print(f"{'='*60}")
        
        is_match, message = compare_html_files(group_html, single_html)
        
        if is_match:
            print("[SUCCESS] 两个HTML文件数值一致！")
            print(f"\n{'='*60}")
            print("测试通过！")
            print(f"{'='*60}")
            return True
        else:
            print(f"[FAIL] 两个HTML文件不一致:")
            print(message)
            print(f"\n继续下一次迭代...")
            time.sleep(2)  # 等待2秒再继续
    
    print(f"\n{'='*60}")
    print(f"[FAIL] 达到最大迭代次数 ({max_iterations})，仍未一致")
    print(f"{'='*60}")
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

