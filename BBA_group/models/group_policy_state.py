"""
组维度保单状态 (Group Policy State)

扩展原有PolicyState，增加组维度计算所需的额外信息
"""

from decimal import Decimal
from datetime import date
from typing import Optional
from dataclasses import dataclass
from BBA_group.models import PolicyState


@dataclass
class GroupPolicyState(PolicyState):
    """
    组维度保单状态
    
    继承原有PolicyState，增加组维度相关字段
    """
    # 组标识
    group_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    certi_no: Optional[str] = None  # 批单号
    
    # 初始确认时的CSM（用于利率曲线权重）
    initial_csm_for_weight: Decimal = Decimal('0')
    
    # 签单月份（用于利率曲线构建）
    uw_month_str: Optional[str] = None  # 格式：YYYYMM
    
    # 该保单在组级利率曲线中的期数
    rate_curve_term: int = 1  # 该保单签单月份对应的组级利率曲线期数

    # 组维度CSM/LC判定口径下，该保单对“合同组CSM/LC”的逐单贡献（按年度滚动）
    # 说明：
    # - group_cohort_csm：在当前评估年度，该保单在“合同组CSM”中的贡献额
    # - group_cohort_lc：在当前评估年度，该保单在“合同组LC”中的贡献额
    # 后续如需按合同组CSM/LC进行分摊，可直接使用这两个字段作为权重
    group_cohort_csm: Decimal = Decimal('0')
    group_cohort_lc: Decimal = Decimal('0')

