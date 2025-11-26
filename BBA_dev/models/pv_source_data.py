"""
PV原材料数据模型 (PV Source Data Model)

用于存储pv_calculator.py计算出的所有现值指标，供后续所有计量环节使用。
避免重复计算，确保数据一致性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Optional


@dataclass
class PVSourceData:
    """
    PV原材料数据容器
    
    存储每个评估月的所有现值指标，按字段名索引。
    """
    policy_no: str
    valuation_month: str  # YYYYMM格式
    valuation_date: date  # 评估月末日期
    under_write_date: date  # 签单日期
    
    # 所有PV字段值，键为字段名（如"Pvfl_Nb_Ini_Cca_Rec_Lkd_Pre_Amt"），值为Decimal
    pv_fields: Dict[str, Decimal] = field(default_factory=dict)
    
    # 元数据：用于验证和调试
    metadata: Dict[str, any] = field(default_factory=dict)
    
    def get_field(self, field_name: str, default: Decimal = Decimal('0')) -> Decimal:
        """获取指定字段的值"""
        return self.pv_fields.get(field_name, default)
    
    def has_field(self, field_name: str) -> bool:
        """检查是否包含指定字段"""
        return field_name in self.pv_fields
    
    def to_dict(self) -> Dict:
        """转换为字典（用于序列化）"""
        return {
            'policy_no': self.policy_no,
            'valuation_month': self.valuation_month,
            'valuation_date': self.valuation_date.isoformat(),
            'under_write_date': self.under_write_date.isoformat(),
            'pv_fields': {k: str(v) for k, v in self.pv_fields.items()},
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> PVSourceData:
        """从字典创建（用于反序列化）"""
        from datetime import datetime
        return cls(
            policy_no=data['policy_no'],
            valuation_month=data['valuation_month'],
            valuation_date=datetime.fromisoformat(data['valuation_date']).date(),
            under_write_date=datetime.fromisoformat(data['under_write_date']).date(),
            pv_fields={k: Decimal(v) for k, v in data['pv_fields'].items()},
            metadata=data.get('metadata', {})
        )


@dataclass
class PVSourceDataCollection:
    """
    PV原材料数据集合
    
    存储多个评估月的PV数据，按评估月索引。
    """
    policy_no: str
    # 键为评估月（YYYYMM格式），值为PVSourceData对象
    data_by_month: Dict[str, PVSourceData] = field(default_factory=dict)
    
    def add_data(self, pv_data: PVSourceData):
        """添加一个评估月的PV数据"""
        if pv_data.policy_no != self.policy_no:
            raise ValueError(f"保单号不匹配: {self.policy_no} vs {pv_data.policy_no}")
        self.data_by_month[pv_data.valuation_month] = pv_data
    
    def get_data(self, valuation_month: str) -> Optional[PVSourceData]:
        """获取指定评估月的PV数据"""
        return self.data_by_month.get(valuation_month)
    
    def get_latest_data(self) -> Optional[PVSourceData]:
        """获取最新的评估月数据"""
        if not self.data_by_month:
            return None
        latest_month = max(self.data_by_month.keys())
        return self.data_by_month[latest_month]
    
    def to_dict(self) -> Dict:
        """转换为字典（用于序列化）"""
        return {
            'policy_no': self.policy_no,
            'data_by_month': {k: v.to_dict() for k, v in self.data_by_month.items()}
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> PVSourceDataCollection:
        """从字典创建（用于反序列化）"""
        collection = cls(policy_no=data['policy_no'])
        for month, pv_data_dict in data['data_by_month'].items():
            collection.add_data(PVSourceData.from_dict(pv_data_dict))
        return collection

