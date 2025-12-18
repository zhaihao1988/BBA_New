"""
组维度合同组状态 (Group Cohort State)

扩展原有CohortState，增加组级利率曲线等组维度特有属性
"""

from decimal import Decimal
from datetime import date
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from BBA_group.models import PolicyState


@dataclass
class GroupCohortState:
    """
    组维度合同组状态
    
    在原有CohortState基础上，增加：
    - 组级利率曲线（多期）
    - 组级利率曲线基准月份
    - 组内保单列表
    - 组内保单CSM权重记录
    """
    # 合同组标识
    group_id: str  # 使用group_id作为合同组标识
    portfolio_id: Optional[str] = None  # 备用标识
    
    # 组级利率曲线（核心新增）
    group_rate_curve: Dict[int, Decimal] = field(default_factory=dict)  # 期数 -> 利率
    group_rate_curve_base_month: Optional[str] = None  # 第一期对应的签单月份（如'202405'）
    group_rate_curve_csm_weights: Dict[int, Decimal] = field(default_factory=dict)  # 期数 -> CSM权重
    
    # 组内保单列表
    group_policies: List[PolicyState] = field(default_factory=list)  # 组内所有保单的状态列表
    
    # 组内保单CSM权重记录（用于利率曲线更新）
    policy_csm_weights: Dict[str, Decimal] = field(default_factory=dict)  # policy_no -> 初始确认CSM
    
    # 加权初始确认利率（保留，用于兼容）
    weighted_locked_rate: Decimal = Decimal('0')
    total_written_premium: Decimal = Decimal('0')  # 累计签单保费（权重）
    total_csm_weight: Decimal = Decimal('0')  # 累计CSM权重（用于利率曲线）
    
    # 年初余额（期初状态）
    bop_csm: Decimal = Decimal('0')  # 年初 CSM 余额
    bop_lc: Decimal = Decimal('0')   # 年初 LC 余额
    bop_iacf: Decimal = Decimal('0')  # 年初待摊 IACF 余额
    
    # 当年新增
    new_csm: Decimal = Decimal('0')  # 当年新增 CSM
    new_lc: Decimal = Decimal('0')   # 当年新增 LC
    new_iacf: Decimal = Decimal('0')  # 当年新增 IACF
    
    # 计息
    csm_interest: Decimal = Decimal('0')  # CSM 计息
    iacf_interest: Decimal = Decimal('0')  # IACF 计息（通常为0，因为IACF不计息）
    
    # 被吸收的变化
    csm_absorbed_changes: Decimal = Decimal('0')  # 被 CSM 吸收的变化
    lc_absorbed_changes: Decimal = Decimal('0')   # 被 LC 吸收的变化
    
    # 摊销
    csm_amortization: Decimal = Decimal('0')  # CSM 摊销
    iacf_amortization: Decimal = Decimal('0')  # IACF 摊销
    
    # 期末余额（期末状态）
    eop_csm: Decimal = Decimal('0')  # 期末 CSM 余额
    eop_lc: Decimal = Decimal('0')   # 期末 LC 余额
    eop_iacf: Decimal = Decimal('0')  # 期末待摊 IACF 余额
    
    # IFIE 相关（累计）
    ifie_pl_total: Decimal = Decimal('0')  # IFIE_P&C 合计
    ifie_oci_total: Decimal = Decimal('0')  # IFIE_OCI 合计
    
    # 合同组状态判定结果（文档 Sec 8.5.5）
    is_profitable: bool = True  # True=盈利（CSM>0），False=亏损（LC<0）
    net_trial: Decimal = Decimal('0')  # 净余额试算值（用于合同组状态判定）
    
    # 累计服务月份（自初始确认起，用于锁定曲线的偏移）
    months_since_initial: int = 0
    
    def get_rate_for_term(self, term: int) -> Decimal:
        """
        根据期数获取组级利率
        
        Args:
            term: 期数（从1开始）
            
        Returns:
            Decimal: 该期数的组级利率
        """
        return self.group_rate_curve.get(term, Decimal('0'))
    
    def get_rate_for_valuation_month(self, valuation_month: str) -> Decimal:
        """
        根据评估月份获取对应的组级利率
        
        Args:
            valuation_month: 评估月份（格式：YYYYMM）
            
        Returns:
            Decimal: 对应的组级利率
        """
        if not self.group_rate_curve_base_month:
            return Decimal('0')
        
        # 计算期数
        base_year = int(self.group_rate_curve_base_month[:4])
        base_month = int(self.group_rate_curve_base_month[4:])
        val_year = int(valuation_month[:4])
        val_month = int(valuation_month[4:])
        
        term = (val_year - base_year) * 12 + (val_month - base_month) + 1
        
        return self.get_rate_for_term(term)
    
    def calculate_eop_balances(self):
        """
        计算期末余额
        """
        self.eop_csm = self.bop_csm + self.new_csm + self.csm_interest + self.csm_absorbed_changes + self.csm_amortization
        self.eop_lc = self.bop_lc + self.new_lc + self.lc_absorbed_changes
        self.eop_iacf = self.bop_iacf + self.new_iacf + self.iacf_interest + self.iacf_amortization

