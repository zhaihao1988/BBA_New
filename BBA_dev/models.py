"""
IFRS 17 BBA 计量模型定义

本模块定义了跨年生命周期仿真所需的状态管理类：
- PolicyState: 单单层面的状态（UPR, PV_CashFlows, CoverageUnits）
- CohortState: 合同组层面的状态（加权锁定利率, Group CSM, Group LC, 期末累计IFIE等）

状态滚存机制：每年的期初余额必须严格等于上一年的期末余额
"""

from decimal import Decimal
from datetime import date
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from dateutil.relativedelta import relativedelta


@dataclass
class PolicyState:
    """
    单单层面的状态
    
    存储每张保单在某个时点的计量状态，包括：
    - 未满期保费 (UPR)
    - 现金流现值 (PV_CashFlows)
    - 覆盖单元 (CoverageUnits)
    """
    # 保单基础信息
    policy_no: str
    start_date: date
    end_date: date
    warranty_end_date: Optional[date] = None  # 保修结束日期（质保期结束日期）
    written_premium: Decimal = Decimal('0')
    
    # 时间维度
    valuation_date: Optional[date] = None
    months_passed: int = 0
    months_remaining: int = 0
    
    # 未满期保费
    upr: Decimal = Decimal('0')
    
    # 现金流现值（使用加权初始确认利率）
    pv_premium: Decimal = Decimal('0')
    pv_iacf: Decimal = Decimal('0')
    pv_claims: Decimal = Decimal('0')
    pv_maintenance: Decimal = Decimal('0')
    pv_ra: Decimal = Decimal('0')
    
    # 覆盖单元（用于摊销计算）
    coverage_units_released: Decimal = Decimal('0')  # 本期释放的覆盖单元
    coverage_units_remaining: Decimal = Decimal('0')   # 剩余覆盖单元
    
    # 初始确认时的状态（用于后续计量）
    initial_csm: Decimal = Decimal('0')  # 初始确认时的 CSM（逐单计算）
    initial_lc: Decimal = Decimal('0')  # 初始确认时的 LC（逐单计算）
    
    def __post_init__(self):
        """计算剩余月数"""
        if self.start_date and self.end_date and self.valuation_date:
            from dateutil.relativedelta import relativedelta
            delta_total = relativedelta(self.end_date, self.start_date)
            self.months_passed = (self.valuation_date.year - self.start_date.year) * 12 + \
                                (self.valuation_date.month - self.start_date.month)
            if self.valuation_date.day >= self.start_date.day:
                self.months_passed += 1
            self.months_passed = max(0, self.months_passed)
            
            total_months = delta_total.years * 12 + delta_total.months
            if total_months == 0 and (self.end_date - self.start_date).days > 0:
                total_months = 1
            self.months_remaining = max(0, total_months - self.months_passed)


@dataclass
class CohortState:
    """
    合同组层面的状态（Cohort/Unit of Account）
    
    存储合同组在某个时点的聚合状态，包括：
    - 加权初始确认利率（锁定利率）
    - 合同组 CSM
    - 合同组 LC
    - 期末累计 IFIE
    - 年初余额（用于滚存）
    """
    # 合同组标识
    cohort_id: str  # 可以是险类代码或其他分组标识
    
    # 加权初始确认利率（锁定利率）
    weighted_locked_rate: Decimal = Decimal('0')
    total_written_premium: Decimal = Decimal('0')  # 累计签单保费（权重）
    
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

    def calculate_eop_balances(self):
        """
        计算期末余额
        
        公式：
        EOP_CSM = BOP_CSM + New_CSM + CSM_Interest + CSM_Absorbed_Changes + CSM_Amortization
        EOP_LC = BOP_LC + New_LC + LC_Absorbed_Changes
        EOP_IACF = BOP_IACF + New_IACF + IACF_Amortization
        
        注意：eop_iacf 应该已经从 context.eop_iacf_balance 通过 update_states_from_context() 设置，
        因此这里不再重新计算，避免覆盖正确的值。
        """
        self.eop_csm = self.bop_csm + self.new_csm + self.csm_interest + \
                      self.csm_absorbed_changes + self.csm_amortization
        self.eop_lc = self.bop_lc + self.new_lc + self.lc_absorbed_changes
        # eop_iacf 应该已经从 context.eop_iacf_balance 通过 update_states_from_context() 设置
        # 如果还没有设置（为0），则使用公式计算作为后备
        if self.eop_iacf == Decimal('0'):
            self.eop_iacf = self.bop_iacf + self.new_iacf + self.iacf_amortization
        
        # 判定合同组状态（文档 Sec 8.5.5）
        # 步骤1：计算合同组净余额试算值
        self.net_trial = self.eop_csm + self.eop_lc
        
        # 步骤2：确定合同组最终状态
        if self.net_trial >= 0:
            self.is_profitable = True
            self.eop_csm = self.net_trial
            self.eop_lc = Decimal('0')
        else:
            self.is_profitable = False
            self.eop_csm = Decimal('0')
            self.eop_lc = self.net_trial
    
    def roll_forward(self):
        """
        状态滚存：将期末余额转为下一年的期初余额
        
        用于跨年仿真时的状态结转
        """
        self.bop_csm = self.eop_csm
        self.bop_lc = self.eop_lc
        self.bop_iacf = self.eop_iacf
        
        # 重置当年新增和计息
        self.new_csm = Decimal('0')
        self.new_lc = Decimal('0')
        self.new_iacf = Decimal('0')
        self.csm_interest = Decimal('0')
        self.iacf_interest = Decimal('0')
        self.csm_absorbed_changes = Decimal('0')
        self.lc_absorbed_changes = Decimal('0')
        self.csm_amortization = Decimal('0')
        self.iacf_amortization = Decimal('0')
        
        # 注意：加权锁定利率和累计签单保费保持不变（除非有新单加入）


@dataclass
class Assumptions:
    """
    精算假设
    
    存储某个时点的精算假设参数
    """
    val_month: str  # 评估月份 'YYYYMM'
    class_code: str  # 险类代码
    
    # 精算假设（从数据库读取）
    loss_ratio: Decimal
    indirect_claims_expense_ratio: Decimal  # ULAE Ratio
    maintenance_expense_ratio: Decimal
    ra_ratio: Decimal  # 非金融风险调整因子
    
    # 获取费用率（可从数据库读取，也可从配置读取）
    acquisition_expense_ratio: Decimal = Decimal('0.20')  # 默认20%
    
    def __str__(self):
        return (f"Assumptions(val_month={self.val_month}, class_code={self.class_code}, "
                f"loss_ratio={self.loss_ratio:.4f}, "
                f"indirect_claims_expense_ratio={self.indirect_claims_expense_ratio:.4f}, "
                f"maintenance_expense_ratio={self.maintenance_expense_ratio:.4f}, "
                f"ra_ratio={self.ra_ratio:.4f}, "
                f"acquisition_expense_ratio={self.acquisition_expense_ratio:.4f})")

