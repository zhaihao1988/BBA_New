"""
PV原材料数据加载工具

用于从JSON文件或直接传入的PVSourceDataCollection加载PV原材料数据。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from BBA_group.models.pv_source_data import PVSourceDataCollection


def load_pv_source_data(policy_no: str, json_file_path: Optional[str] = None) -> Optional[PVSourceDataCollection]:
    """
    加载PV原材料数据
    
    Args:
        policy_no: 保单号
        json_file_path: JSON文件路径。如果为None，则使用默认路径 logs/pv_source_data_{policy_no}.json
    
    Returns:
        PVSourceDataCollection对象，如果文件不存在则返回None
    """
    if json_file_path is None:
        # 默认路径：项目根目录下的logs目录
        project_root = Path(__file__).resolve().parents[2]
        json_file_path = project_root / "logs" / f"pv_source_data_{policy_no}.json"
    else:
        json_file_path = Path(json_file_path)
    
    if not json_file_path.exists():
        return None
    
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return PVSourceDataCollection.from_dict(data)
    except Exception as e:
        print(f"⚠️  警告: 加载PV原材料数据失败: {e}")
        return None


def ensure_pv_source_data(context) -> bool:
    """
    确保context中有PV原材料数据，如果没有则尝试加载
    
    Args:
        context: CalculationContext对象，需要包含policy_data或policy_no属性
    
    Returns:
        True如果成功加载或已存在，False如果无法加载
    """
    if context.pv_source_data is not None:
        return True
    
    # 尝试从context获取保单号
    policy_no = None
    if hasattr(context, 'policy_data') and context.policy_data is not None:
        if hasattr(context.policy_data, 'get'):
            policy_no = context.policy_data.get('policy_no')
        elif hasattr(context.policy_data, 'policy_no'):
            policy_no = context.policy_data.policy_no
    elif hasattr(context, 'policy_no'):
        policy_no = context.policy_no
    
    if not policy_no:
        return False
    
    # 尝试加载
    context.pv_source_data = load_pv_source_data(policy_no)
    return context.pv_source_data is not None

