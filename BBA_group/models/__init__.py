"""
BBA模型定义模块
"""

from BBA_group.models.pv_source_data import PVSourceData, PVSourceDataCollection

# 从上级目录的models.py导入（向后兼容）
import sys
import importlib.util
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
models_path = _project_root / 'models.py'

if models_path.exists():
    spec = importlib.util.spec_from_file_location("_models", models_path)
    _models_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_models_module)
    
    # 导出所有需要的类
    PolicyState = _models_module.PolicyState
    CohortState = _models_module.CohortState
    Assumptions = getattr(_models_module, 'Assumptions', None)
    
    __all__ = ['PVSourceData', 'PVSourceDataCollection', 'PolicyState', 'CohortState']
    if Assumptions:
        __all__.append('Assumptions')
else:
    __all__ = ['PVSourceData', 'PVSourceDataCollection']

