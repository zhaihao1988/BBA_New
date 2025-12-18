"""
实际现金流模块 (Actual Cashflows)

核心功能：
1. 从数据库读取实际发生的现金流（保费、IACF等）
2. 预设发生时间为签单日期
3. 提供统一的接口供其他模块调用

注意：
- 实际现金流是名义值，不计息
- 实际现金流只在签单年度发生，后续年度为0
"""

from decimal import Decimal
from datetime import date
from typing import Optional
from BBA_group.data_access.loader import get_policy_data
from BBA_group.data_loader import load_full_data


class ActualCashflows:
    """
    实际现金流数据类
    
    存储从数据库读取的实际现金流数据，包括：
    - 实际保费（actual_premium）
    - 实际获取费用（actual_iacf）
    - 发生时间（签单日期）
    """
    
    def __init__(
        self,
        policy_no: str,
        certi_no: Optional[str] = None,
        under_write_date: Optional[date] = None,
        actual_premium: Optional[Decimal] = None,
        actual_iacf: Optional[Decimal] = None
    ):
        """
        初始化实际现金流数据
        
        Args:
            policy_no: 保单号
            certi_no: 批单号（可选）
            under_write_date: 签单日期（发生时间）
            actual_premium: 实际保费（如果提供则直接使用，否则从数据库读取）
            actual_iacf: 实际获取费用（如果提供则直接使用，否则从数据库读取）
        """
        self.policy_no = policy_no
        self.certi_no = certi_no
        self.under_write_date = under_write_date
        
        # 如果提供了实际值，直接使用；否则从数据库读取
        if actual_premium is not None:
            self.actual_premium = Decimal(str(actual_premium))
        else:
            self.actual_premium = None
            
        if actual_iacf is not None:
            self.actual_iacf = Decimal(str(actual_iacf))
        else:
            self.actual_iacf = None
    
    def load_from_database(self, run_date: Optional[str] = None, val_method: Optional[str] = '7'):
        """
        从数据库加载实际现金流数据（使用data_loader统一加载）
        
        从以下数据源读取（通过data_loader.load_full_data）：
        - 实际保费：从保单数据表 zh.t_pp_jl_contract 的 premium_cny 字段（映射为 sum_premium_no_tax）
        - 实际IACF：从原始表 zh.summary_iacf_cost 的"合计费用"字段（按保单号和批单号分组求和）
        
        Args:
            run_date: 运行批次（可选，如果不提供则尝试从保单数据获取）
            val_method: 计量方法（默认'7'，表示BBA方法）
        """
        try:
            # 如果未提供run_date，先获取保单数据以确定run_date
            if run_date is None:
                df_policy = get_policy_data(self.policy_no, certi_no=self.certi_no, val_method=val_method)
                if not df_policy.empty and 'run_date' in df_policy.columns:
                    run_date = str(df_policy.iloc[0]['run_date'])
                else:
                    # 默认使用当前批次
                    from datetime import datetime
                    run_date = datetime.now().strftime('%Y%m')
            
            # 使用data_loader统一加载数据（包含IACF）
            df_full = load_full_data(run_date=run_date, val_method=val_method)
            
            # 筛选出当前保单的数据
            if self.certi_no is None:
                policy_subset = df_full[
                    (df_full['policy_no'] == self.policy_no) & 
                    (df_full['certi_no'].isna())
                ]
            else:
                policy_subset = df_full[
                    (df_full['policy_no'] == self.policy_no) & 
                    (df_full['certi_no'] == self.certi_no)
                ]
            
            if policy_subset.empty:
                raise ValueError(f"未找到保单号 {self.policy_no} 的数据")
            
            policy_row = policy_subset.iloc[0]
            
            # 读取实际保费（优先使用premium_cny，如果没有则使用sum_premium_no_tax）
            if 'premium_cny' in policy_row:
                self.actual_premium = Decimal(str(policy_row['premium_cny'] or 0))
            elif 'sum_premium_no_tax' in policy_row:
                self.actual_premium = Decimal(str(policy_row['sum_premium_no_tax'] or 0))
            else:
                self.actual_premium = Decimal('0')
            
            # 读取实际IACF（从data_loader合并后的iacf_amount字段）
            # 如果 self.actual_iacf 已经设置（通过传入参数），保留传入值，不从数据库读取
            if self.actual_iacf is None:
                if 'iacf_amount' in policy_row:
                    iacf_value = policy_row['iacf_amount']
                    if iacf_value is not None and not (isinstance(iacf_value, float) and (iacf_value != iacf_value)):  # 排除NaN
                        self.actual_iacf = Decimal(str(iacf_value))
                    else:
                        self.actual_iacf = Decimal('0')
                else:
                    self.actual_iacf = Decimal('0')
            # 如果 self.actual_iacf 已设置，保留传入值（不覆盖）
            
            # 如果签单日期未设置，从数据库读取
            if self.under_write_date is None and 'under_write_date' in policy_row:
                uw_date = policy_row['under_write_date']
                if hasattr(uw_date, 'date'):
                    self.under_write_date = uw_date.date()
                elif isinstance(uw_date, date):
                    self.under_write_date = uw_date
                else:
                    # 尝试解析字符串
                    from datetime import datetime
                    if isinstance(uw_date, str):
                        self.under_write_date = datetime.strptime(uw_date, '%Y-%m-%d').date()
            
        except Exception as e:
            raise RuntimeError(f"从数据库加载实际现金流数据失败: {e}")
    
    def get_actual_premium(self, valuation_year: int) -> Decimal:
        """
        获取实际保费
        
        Args:
            valuation_year: 评估年度
            
        Returns:
            实际保费（仅在签单年度返回实际值，其他年度返回0）
        """
        if self.actual_premium is None:
            return Decimal('0')
        
        if self.under_write_date and valuation_year == self.under_write_date.year:
            return self.actual_premium
        else:
            return Decimal('0')
    
    def get_actual_iacf(self, valuation_year: int) -> Decimal:
        """
        获取实际获取费用
        
        Args:
            valuation_year: 评估年度
            
        Returns:
            实际获取费用（仅在签单年度返回实际值，其他年度返回0）
        """
        if self.actual_iacf is None:
            return Decimal('0')
        
        if self.under_write_date and valuation_year == self.under_write_date.year:
            return self.actual_iacf
        else:
            return Decimal('0')
    
    def get_occurrence_date(self) -> Optional[date]:
        """
        获取实际现金流发生时间（签单日期）
        
        Returns:
            签单日期
        """
        return self.under_write_date


def get_actual_cashflows(
    policy_no: str,
    certi_no: Optional[str] = None,
    under_write_date: Optional[date] = None,
    actual_premium: Optional[Decimal] = None,
    actual_iacf: Optional[Decimal] = None,
    run_date: Optional[str] = None,
    val_method: Optional[str] = '7'
) -> ActualCashflows:
    """
    获取实际现金流数据（工厂函数）
    
    如果提供了actual_premium和actual_iacf，则直接使用；
    否则从数据库加载。
    
    Args:
        policy_no: 保单号
        certi_no: 批单号（可选）
        under_write_date: 签单日期（可选，如果提供则优先使用）
        actual_premium: 实际保费（可选，如果提供则直接使用）
        actual_iacf: 实际获取费用（可选，如果提供则直接使用）
        
    Returns:
        ActualCashflows对象
    """
    cashflows = ActualCashflows(
        policy_no=policy_no,
        certi_no=certi_no,
        under_write_date=under_write_date,
        actual_premium=actual_premium,
        actual_iacf=actual_iacf
    )
    
    # 如果未提供实际值，从数据库加载
    if actual_premium is None or actual_iacf is None:
        cashflows.load_from_database(run_date=run_date, val_method=val_method)
    
    return cashflows

