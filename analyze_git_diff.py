#!/usr/bin/env python3
"""
Git 差异分析脚本
分析当前项目和远程仓库的差异
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime


def run_git_command(command):
    """执行 git 命令并返回结果"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def print_section(title):
    """打印分节标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def analyze_git_status():
    """分析 Git 状态"""
    print_section("[STATUS] Git 状态概览")
    
    # 获取当前分支
    branch, _, _ = run_git_command("git branch --show-current")
    print(f"当前分支: {branch}")
    
    # 获取远程分支状态
    status, _, _ = run_git_command("git status -sb")
    print(f"\n分支状态:\n{status}")
    
    # 获取最后一次提交
    last_commit, _, _ = run_git_command("git log -1 --oneline")
    print(f"\n最后一次提交: {last_commit}")


def analyze_local_remote_diff():
    """分析本地和远程的差异"""
    print_section("🔄 本地与远程差异")
    
    # 获取本地和远程的提交差异
    print("\n📍 本地领先的提交:")
    ahead, _, _ = run_git_command("git log origin/main..HEAD --oneline")
    if ahead:
        print(ahead)
    else:
        print("  无")
    
    print("\n📍 远程领先的提交:")
    behind, _, _ = run_git_command("git log HEAD..origin/main --oneline")
    if behind:
        print(behind)
    else:
        print("  无")


def analyze_modified_files():
    """分析已修改的文件"""
    print_section("📝 已修改但未暂存的文件")
    
    modified, _, _ = run_git_command("git diff --name-status")
    if modified:
        lines = modified.split('\n')
        for line in lines:
            if line:
                status, *file_parts = line.split('\t')
                file_path = '\t'.join(file_parts)
                status_map = {
                    'M': '修改',
                    'A': '新增',
                    'D': '删除',
                    'R': '重命名',
                    'C': '复制'
                }
                status_text = status_map.get(status, status)
                print(f"  [{status_text}] {file_path}")
    else:
        print("  无")


def analyze_staged_files():
    """分析已暂存的文件"""
    print_section("✅ 已暂存待提交的文件")
    
    staged, _, _ = run_git_command("git diff --cached --name-status")
    if staged:
        lines = staged.split('\n')
        for line in lines:
            if line:
                status, *file_parts = line.split('\t')
                file_path = '\t'.join(file_parts)
                status_map = {
                    'M': '修改',
                    'A': '新增',
                    'D': '删除',
                    'R': '重命名',
                    'C': '复制'
                }
                status_text = status_map.get(status, status)
                print(f"  [{status_text}] {file_path}")
    else:
        print("  无")


def analyze_untracked_files():
    """分析未跟踪的文件"""
    print_section("❓ 未跟踪的文件")
    
    untracked, _, _ = run_git_command("git ls-files --others --exclude-standard")
    if untracked:
        files = untracked.split('\n')
        for file in files:
            if file:
                print(f"  {file}")
        print(f"\n  总计: {len(files)} 个未跟踪文件")
    else:
        print("  无")


def analyze_ignored_files():
    """分析被忽略的文件"""
    print_section("🚫 被 .gitignore 忽略的文件（示例）")
    
    ignored, _, _ = run_git_command("git ls-files --others --ignored --exclude-standard")
    if ignored:
        files = ignored.split('\n')
        # 只显示前20个
        display_files = files[:20]
        for file in display_files:
            if file:
                print(f"  {file}")
        if len(files) > 20:
            print(f"\n  ... 还有 {len(files) - 20} 个文件")
        print(f"\n  总计: {len(files)} 个被忽略的文件")
    else:
        print("  无")


def analyze_file_stats():
    """分析文件统计"""
    print_section("📈 文件变更统计")
    
    # 统计未暂存的修改
    modified_stats, _, _ = run_git_command("git diff --stat")
    if modified_stats:
        print("\n未暂存的修改:")
        print(modified_stats)
    
    # 统计已暂存的修改
    staged_stats, _, _ = run_git_command("git diff --cached --stat")
    if staged_stats:
        print("\n已暂存的修改:")
        print(staged_stats)


def generate_summary_report():
    """生成汇总报告"""
    print_section("📋 汇总报告")
    
    # 统计各类文件数量
    modified, _, _ = run_git_command("git diff --name-only")
    modified_count = len([f for f in modified.split('\n') if f])
    
    staged, _, _ = run_git_command("git diff --cached --name-only")
    staged_count = len([f for f in staged.split('\n') if f])
    
    untracked, _, _ = run_git_command("git ls-files --others --exclude-standard")
    untracked_count = len([f for f in untracked.split('\n') if f])
    
    ahead, _, _ = run_git_command("git log origin/main..HEAD --oneline")
    ahead_count = len([c for c in ahead.split('\n') if c])
    
    behind, _, _ = run_git_command("git log HEAD..origin/main --oneline")
    behind_count = len([c for c in behind.split('\n') if c])
    
    print(f"""
  文件状态:
    - 已修改未暂存: {modified_count}
    - 已暂存待提交: {staged_count}
    - 未跟踪文件: {untracked_count}
  
  提交状态:
    - 本地领先提交: {ahead_count}
    - 远程领先提交: {behind_count}
  
  建议操作:
    """)
    
    if staged_count > 0:
        print(f"    ✓ 有 {staged_count} 个文件已暂存，可以执行: git commit")
    if modified_count > 0:
        print(f"    ✓ 有 {modified_count} 个文件已修改，可以执行: git add <文件> 或 git restore <文件>")
    if untracked_count > 0:
        print(f"    ✓ 有 {untracked_count} 个未跟踪文件，可以执行: git add <文件> 或添加到 .gitignore")
    if ahead_count > 0:
        print(f"    ✓ 本地领先 {ahead_count} 个提交，可以执行: git push")
    if behind_count > 0:
        print(f"    ✓ 远程领先 {behind_count} 个提交，可以执行: git pull")
    if staged_count == 0 and modified_count == 0 and ahead_count == 0 and behind_count == 0:
        print("    ✓ 工作区干净，与远程同步")


def check_git_repo():
    """检查是否在 Git 仓库中"""
    _, _, returncode = run_git_command("git rev-parse --git-dir")
    return returncode == 0


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("  Git 差异分析工具")
    print(f"  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # 检查是否在 Git 仓库中
    if not check_git_repo():
        print("\n❌ 错误: 当前目录不是 Git 仓库")
        sys.exit(1)
    
    # 获取远程信息
    print_section("🌐 远程仓库信息")
    remote_info, _, _ = run_git_command("git remote -v")
    if remote_info:
        print(remote_info)
    else:
        print("  未配置远程仓库")
    
    # 更新远程分支信息
    print("\n正在获取远程分支信息...")
    run_git_command("git fetch origin")
    
    # 执行各项分析
    analyze_git_status()
    analyze_local_remote_diff()
    analyze_staged_files()
    analyze_modified_files()
    analyze_untracked_files()
    analyze_file_stats()
    analyze_ignored_files()
    generate_summary_report()
    
    print("\n" + "=" * 80)
    print("  分析完成")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

