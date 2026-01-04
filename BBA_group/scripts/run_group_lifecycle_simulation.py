"""
IFRS 17 BBA 组维度生命周期仿真器 (Group Lifecycle Simulator) - Fixed CSM/LC Logic

本程序实现按合同组（group_id）维度进行全生命周期计量仿真。
核心特性：
1. 先逐单计算明细（初始确认、CSM计息、LC分摊IFIE）
2. 再按组汇总，判断合同组是CSM还是LC状态
3. 严格执行 CSM/LC 吸收逻辑（被CSM吸收的变化、被LC吸收的变化）
4. 基于吸收后的余额进行CSM摊销
5. 生成组级别的103、104报表

数据流向：
组内所有保单 -> 逐单初始确认 -> 逐年循环：
    - 逐单计算CSM计息、LC分摊IFIE
    - 按组汇总CSM和LC
    - 构建/更新组级利率曲线
    - 计算组级覆盖单元
    - 组级计量（吸收判定、摊销、IFIE等）
    - 期末结转
"""

import pandas as pd
from decimal import Decimal
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Tuple, List, Any
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from contextlib import redirect_stdout, redirect_stderr
import io

from BBA_group.config import VAL_METHOD, GROUP_ID
from BBA_group.models import PolicyState, CohortState, Assumptions
from BBA_group.models.group_cohort_state import GroupCohortState
from BBA_group.models.group_policy_state import GroupPolicyState
from BBA_group.data_access.group_loader import load_policies_by_group, load_group_full_data
from BBA_group.data_access import loader
from BBA_group.context import CalculationContext
from BBA_group.utils.logger import CalculationLogger
from BBA_group.projector import CashFlowProjector
from BBA_group.utils.pv_field_desc import describe_field
from BBA_group.logic import (
    initial_recognition,
    fulfillment_cashflow_changes,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)
from BBA_group.logic.group_csm_lc_measurement import run_group_absorption_allocation
from BBA_group.logic.coverage_units import (
    calculate_coverage_units_released,
    calculate_coverage_units_remaining
)
from BBA_group.logic.group_rates_manager import (
    build_group_rate_curve,
    update_group_rate_curve
)
from BBA_group.utils.pv_source_loader import load_pv_source_data
from BBA_group.models.pv_source_data import PVSourceDataCollection
import BBA_group.pv_calculator as pv_calculator


class _SilentLogger:
    """空实现，用于静默模式避免文件输出。"""
    md_file = None
    def log_section(self, *args, **kwargs): pass
    def log_text(self, *args, **kwargs): pass
    def log_item(self, *args, **kwargs): pass
    def close(self): pass


class GroupLifecycleSimulator:
    """
    组维度生命周期仿真器
    
    负责管理整个合同组的生命周期计量流程，包括：
    - 加载组内所有保单
    - 逐单初始确认
    - 逐年循环计量（先逐单，再汇总）
    - 组级利率曲线构建
    - 组级覆盖单元计算
    - 状态滚存
    - 日志输出
    """
    
    def __init__(
        self,
        group_id: str,
        md_log_file: Optional[str] = None,
        enable_logging: bool = True,
        dynamic_pv_mode: bool = True,
        run_date: str = '202412',
        val_method: str = VAL_METHOD,
        enable_reports: bool = True
    ):
        self.group_id = group_id
        self.enable_logging = enable_logging
        self.dynamic_pv_mode = dynamic_pv_mode
        self.run_date = run_date
        self.val_method = val_method
        self.enable_reports = enable_reports
        
        if enable_logging:
            self.logger = CalculationLogger(md_file_path=md_log_file)
        else:
            self.logger = _SilentLogger()
        
        # 组内所有保单的状态
        self.policy_states: List[GroupPolicyState] = []
        self.group_cohort_state: Optional[GroupCohortState] = None
        self.assumptions_history: Dict[str, Assumptions] = {}
        self.rates_history: Dict[str, pd.DataFrame] = {}  # 历史利率曲线（按月份）
        self._pv_collections: Dict[str, PVSourceDataCollection] = {}  # 每张保单的PV数据
        
        # 逐单计算结果（用于后续汇总）
        self.policy_results: Dict[str, Dict] = {}  # policy_no -> {计算结果}
        
        # 每张保单的年度结果（用于生成逐单报表）
        self.policy_yearly_results: Dict[str, List[Dict]] = {}  # policy_no -> [年度结果列表]
    
    def cleanup(self):
        """清理资源，包括数据库连接池"""
        from BBA_group.data_access.db_utils import dispose_all_engines
        dispose_all_engines()
        if self.enable_logging:
            self.logger.close()
    
    def _merge_pv_collection(self, policy_no: str, new_collection: PVSourceDataCollection) -> PVSourceDataCollection:
        """合并PV数据集合"""
        if policy_no not in self._pv_collections:
            self._pv_collections[policy_no] = new_collection
            return self._pv_collections[policy_no]
        self._pv_collections[policy_no].data_by_month.update(new_collection.data_by_month)
        return self._pv_collections[policy_no]
    
    def _generate_dynamic_pv_data(self, policy_no: str, certi_no: Optional[str], months: List[str]) -> Tuple[PVSourceDataCollection, Optional[str]]:
        """动态生成PV数据"""
        normalized = [m.replace('-', '') for m in months]
        buffer = io.StringIO()
        original_policy = getattr(pv_calculator, "TARGET_POLICY_NO", None)
        original_certi = getattr(pv_calculator, "TARGET_CERTI_NO", None)
        original_run_date = getattr(pv_calculator, "TARGET_RUN_DATE", None)
        original_val_method = getattr(pv_calculator, "TARGET_VAL_METHOD", None)
        original_month_filter = getattr(pv_calculator, "TARGET_VAL_MONTH_FILTER", None)
        try:
            pv_calculator.TARGET_POLICY_NO = policy_no
            pv_calculator.TARGET_CERTI_NO = certi_no
            pv_calculator.TARGET_RUN_DATE = self.run_date
            pv_calculator.TARGET_VAL_METHOD = self.val_method
            pv_calculator.TARGET_VAL_MONTH_FILTER = normalized
            with redirect_stdout(buffer), redirect_stderr(buffer):
                pv_collection, output_file = pv_calculator.main()
        finally:
            pv_calculator.TARGET_POLICY_NO = original_policy
            pv_calculator.TARGET_CERTI_NO = original_certi
            pv_calculator.TARGET_RUN_DATE = original_run_date
            pv_calculator.TARGET_VAL_METHOD = original_val_method
            pv_calculator.TARGET_VAL_MONTH_FILTER = original_month_filter
        return pv_collection, output_file
    
    def initialize(self) -> Tuple[Assumptions, pd.DataFrame, str]:
        """
        初始化：加载组内所有保单数据
        """
        self.logger.log_section(f"IFRS 17 BBA 组维度生命周期仿真器 - 初始化")
        self.logger.log_text(f"**合同组ID**: {self.group_id}")
        
        # 1. 加载组内所有保单数据
        self.logger.log_text("### [Step 0] 获取组内所有保单数据")
        df_policies = load_policies_by_group(
            self.group_id,
            run_date=self.run_date,
            val_method=self.val_method
        )
        
        if df_policies.empty:
            raise ValueError(f"未找到group_id={self.group_id}的保单数据（查询条件: run_date={self.run_date}, val_method={self.val_method}）")
        
        self.logger.log_text(f"- ✅ **组内保单数量**: {len(df_policies)}")
        
        # 2. 创建组级合同组状态
        portfolio_id = df_policies.iloc[0].get('portfolio_id')
        self.group_cohort_state = GroupCohortState(
            group_id=self.group_id,
            portfolio_id=portfolio_id
        )
        
        # 3. 初始化每张保单的状态
        class_code = None
        for idx, row in df_policies.iterrows():
            policy_no = str(row['policy_no'])
            certi_no = str(row['certi_no']) if pd.notna(row['certi_no']) else None
            
            written_premium = Decimal(str(row['premium_cny'] or 0))
            under_write_date = row['under_write_date']
            if isinstance(under_write_date, pd.Timestamp):
                under_write_date = under_write_date.date()
            start_date = row['start_date']
            if isinstance(start_date, pd.Timestamp):
                start_date = start_date.date()
            end_date = row['end_date']
            if isinstance(end_date, pd.Timestamp):
                end_date = end_date.date()
            warranty_end_date = row.get('warranty_end_date')
            if warranty_end_date is not None and isinstance(warranty_end_date, pd.Timestamp):
                warranty_end_date = warranty_end_date.date()
            elif warranty_end_date is None:
                warranty_end_date = start_date
            
            if class_code is None:
                class_code = str(row.get('class_code', 'UNKNOWN'))
            
            # 创建组维度保单状态
            policy_state = GroupPolicyState(
                policy_no=policy_no,
                start_date=start_date,
                end_date=end_date,
                warranty_end_date=warranty_end_date,
                written_premium=written_premium,
                valuation_date=under_write_date,
                group_id=self.group_id,
                portfolio_id=portfolio_id,
                certi_no=certi_no,
                uw_month_str=under_write_date.strftime('%Y%m') if under_write_date else None
            )
            
            self.policy_states.append(policy_state)
            self.group_cohort_state.group_policies.append(policy_state)
        
        self.logger.log_text(f"- ✅ **险类代码**: {class_code}")
        
        # 4. 读取初始精算假设和利率曲线
        if not self.policy_states:
            raise ValueError("组内没有有效保单")
        
        first_policy = self.policy_states[0]
        val_month_str = first_policy.valuation_date.strftime('%Y%m') if first_policy.valuation_date else '202401'
        
        self.logger.log_text(f"### [Step 0.1] 读取初始精算假设和利率曲线")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        assumptions_dict = loader.get_assumptions(class_code, val_month_str, VAL_METHOD, use_db_acquisition_expense=True)
        if assumptions_dict is None:
            raise ValueError(f"未找到险类 {class_code} 在 {val_month_str} 的精算假设数据")
        
        from BBA_group.config import RATIO_IACF
        acquisition_expense = assumptions_dict.get('acquisition_expense_ratio', RATIO_IACF)
        
        initial_assumptions = Assumptions(
            val_month=val_month_str,
            class_code=class_code,
            loss_ratio=assumptions_dict['loss_ratio'],
            indirect_claims_expense_ratio=assumptions_dict['indirect_claims_expense_ratio'],
            maintenance_expense_ratio=assumptions_dict['maintenance_expense_ratio'],
            ra_ratio=assumptions_dict['ra_ratio'],
            acquisition_expense_ratio=acquisition_expense
        )
        self.assumptions_history[val_month_str] = initial_assumptions
        
        rates_df = loader.get_rates(val_month_str)
        if rates_df.empty:
            raise ValueError(f"未找到 {val_month_str} 的利率曲线数据")
        self.rates_history[val_month_str] = rates_df
        self.logger.log_text(f"✅ 成功获取 {val_month_str} 利率曲线 ({len(rates_df)} 条记录)")
        
        return initial_assumptions, rates_df, class_code
    
    def run_initial_recognition_for_policy(
        self,
        policy_state: GroupPolicyState,
        assumptions: Assumptions,
        rates_df: pd.DataFrame
    ) -> CalculationContext:
        """对单张保单执行初始确认"""
        context = CalculationContext()
        context.policy_data = pd.Series({
            'policy_no': policy_state.policy_no,
            'certi_no': getattr(policy_state, 'certi_no', None),
            'sum_premium_no_tax': float(policy_state.written_premium),
            'under_write_date': policy_state.valuation_date,
            'start_date': policy_state.start_date,
            'end_date': policy_state.end_date,
            'class_code': assumptions.class_code
        })
        context.policy_no = policy_state.policy_no
        context.certi_no = getattr(policy_state, 'certi_no', None)
        context.under_write_date = policy_state.valuation_date
        context.start_date = policy_state.start_date
        context.end_date = policy_state.end_date
        context.warranty_end_date = policy_state.warranty_end_date
        context.year = policy_state.valuation_date.year
        context.val_month_str = policy_state.valuation_date.strftime('%Y%m')
        context.total_months = policy_state.months_passed + policy_state.months_remaining
        context.rates_df = rates_df
        context.rates_df_locked = rates_df
        
        init_month = context.val_month_str
        if self.dynamic_pv_mode:
            if policy_state.policy_no not in self._pv_collections:
                pv_collection, file_path = self._generate_dynamic_pv_data(
                    policy_state.policy_no,
                    getattr(policy_state, 'certi_no', None),
                    [init_month]
                )
                self._merge_pv_collection(policy_state.policy_no, pv_collection)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            context.pv_source_data = self._pv_collections[policy_state.policy_no]
        else:
            pv_source_data = load_pv_source_data(policy_state.policy_no)
            if pv_source_data is None:
                raise ValueError(f"❌ 错误: 无法加载保单{policy_state.policy_no}的PV原材料数据")
            context.pv_source_data = pv_source_data
        
        cohort_state = CohortState(
            cohort_id=assumptions.class_code,
            weighted_locked_rate=Decimal('0'),
            total_written_premium=Decimal('0')
        )
        
        silent_logger = _SilentLogger()
        initial_recognition.run(context, silent_logger, assumptions, cohort_state)
        
        policy_state.initial_csm = context.nb_initial_csm or Decimal('0')
        policy_state.initial_lc = context.nb_initial_lc or Decimal('0')
        policy_state.initial_csm_for_weight = policy_state.initial_csm
        
        self.policy_results[policy_state.policy_no] = {
            'initial_csm': policy_state.initial_csm,
            'initial_lc': policy_state.initial_lc,
            'context': context
        }
        
        return context
    
    def run_initial_recognition(self, assumptions: Assumptions, rates_df: pd.DataFrame):
        """对组内所有保单执行初始确认"""
        self.logger.log_section(f"Part 1: 组内所有保单初始确认 (Initial Recognition)")
        
        for policy_state in self.policy_states:
            self.logger.log_text(f"### 处理保单: {policy_state.policy_no}")
            
            uw_month_str = policy_state.uw_month_str
            if uw_month_str not in self.rates_history:
                rates_df_policy = loader.get_rates(uw_month_str)
                if not rates_df_policy.empty:
                    self.rates_history[uw_month_str] = rates_df_policy
                else:
                    rates_df_policy = rates_df
            else:
                rates_df_policy = self.rates_history[uw_month_str]
            
            context = self.run_initial_recognition_for_policy(
                policy_state,
                assumptions,
                rates_df_policy
            )

            self.logger.log_text(
                f"- 初始CSM: {policy_state.initial_csm:,.2f}, "
                f"初始LC: {policy_state.initial_lc:,.2f}"
            )
        
        group_csm_total = sum(p.initial_csm for p in self.policy_states)
        group_lc_total = sum(p.initial_lc for p in self.policy_states)
        self.group_cohort_state.new_csm = group_csm_total
        self.group_cohort_state.new_lc = group_lc_total
        
        self.logger.log_section("Part 1.5: 构建组级利率曲线")
        build_group_rate_curve(
            self.group_cohort_state,
            self.policy_states,
            self.rates_history,
            self.logger
        )
        
        return self.policy_results
    
    def calculate_group_coverage_units_ratio(
        self,
        valuation_date: date,
        start_of_year: date,
        is_initial_year: bool = False
    ) -> Decimal:
        """计算组级CSM摊销比例（基于保费权重）"""
        numerator = Decimal('0')
        denominator = Decimal('0')
        
        self.logger.log_text("#### 组级CSM摊销比例 - 明细分解")
        self.logger.log_text(f"- 评估日期: {valuation_date}, 年初: {start_of_year}, 是否初始年度: {is_initial_year}")
        
        for policy in self.policy_states:
            policy_no = getattr(policy, "policy_no", "")
            premium = policy.written_premium
            
            if policy.end_date < start_of_year or policy.start_date > valuation_date:
                continue
            
            warranty_end = getattr(policy, 'warranty_end_date', None) or policy.start_date
            is_in_warranty = valuation_date < warranty_end
            
            if is_initial_year:
                service_start = warranty_end
            else:
                service_start = max(warranty_end, start_of_year)
            service_end = min(policy.end_date, valuation_date)
            
            if is_in_warranty or service_end < service_start:
                current_service_days = 0
            else:
                current_service_days = (service_end - service_start).days + 1
            
            if policy.end_date <= valuation_date:
                future_service_days = 0
            else:
                if is_in_warranty:
                    future_service_days = (policy.end_date - warranty_end).days
                else:
                    future_service_days = (policy.end_date - valuation_date).days
            
            if future_service_days < 0:
                future_service_days = 0
            
            current_cu = premium * Decimal(current_service_days)
            future_cu = premium * Decimal(future_service_days)
            
            numerator += current_cu
            denominator += current_cu + future_cu
            
            self.logger.log_text(
                f"- 保单 {policy_no}: 保费={premium:,.2f}, "
                f"当期服务天数={current_service_days}, 未来服务天数={future_service_days}, "
                f"当期覆盖单元={current_cu:,.2f}, 未来覆盖单元={future_cu:,.2f}"
            )
        
        if denominator > 0:
            ratio = numerator / denominator
        else:
            ratio = Decimal('0')
        
        self.logger.log_item(
            "组级CSM摊销比例",
            "[Sec 8.2] 基于保费权重的覆盖单元比例",
            "Σ(保费_i × 当期服务量_i) / Σ(保费_i × (当期服务量_i + 未来服务量_i))",
            {
                "分子": numerator,
                "分母": denominator
            },
            ratio,
            note="逐单计算当期/未来服务天数，将其与保费相乘得到覆盖单元，再进行组级加总"
        )
        
        return ratio
    
    def _to_decimal(self, value) -> Decimal:
        """转换为Decimal"""
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal('0')
    
    def _to_number(self, value) -> float:
        """转换为float"""
        decimal_value = self._to_decimal(value)
        return float(decimal_value)
    
    def _apply_reversal_if_needed(self, value: Decimal, is_reversal: bool) -> float:
        _ = is_reversal
        return self._to_number(value)
    
    def _derive_gross_from_net(self, net_value: Decimal, lc_ratio: Decimal) -> Decimal:
        """从净额和亏损比例反推含亏损总额"""
        denominator = Decimal('1') - lc_ratio
        if denominator == 0:
            return net_value
        return net_value / denominator
    
    def _is_new_business_year_for_context(self, context: CalculationContext) -> bool:
        """判断context对应年度是否为签单年"""
        if hasattr(context, 'is_new_business') and context.is_new_business is not None:
            return context.is_new_business
        if getattr(context, 'under_write_date', None) and getattr(context, 'year', None):
            return context.year == context.under_write_date.year
        return False
    
    def _log_detailed_yearly_results(
        self,
        year: int,
        policy_contexts: Dict[str, CalculationContext],
        group_result: Any,
        group_csm_status: Decimal,
        group_lc_status: Decimal,
        group_csm_absorbed_total: Decimal,
        group_lc_absorbed_total: Decimal,
        group_csm_final: Decimal,
        group_lc_final: Decimal,
        group_csm_amort_amount: Decimal,
        current_assumptions: Assumptions
    ):
        """
        按照用户要求的顺序输出详细的年度结果日志
        先展示合同组字段值，然后展示逐单结果
        """
        self.logger.log_section("Part 5: 年度详细结果（按字段顺序）")
        
        # ========== 第一部分：合同组字段值 ==========
        self.logger.log_text("### 合同组字段值")
        
        # 汇总逐单的IF和NB相关字段
        group_if_bop_csm = Decimal('0')
        group_nb_initial_csm = Decimal('0')
        group_if_interest_csm = Decimal('0')
        group_nb_interest_csm = Decimal('0')
        group_if_csm_post = Decimal('0')
        group_nb_csm_post = Decimal('0')
        
        group_if_bop_lc = Decimal('0')
        group_nb_initial_lc = Decimal('0')
        group_if_lc_ifie_total = Decimal('0')
        group_nb_lc_ifie_total = Decimal('0')
        group_if_lc_post = Decimal('0')
        group_nb_lc_after_ifie = Decimal('0')
        
        # IF_LC IFIE分摊比例相关
        group_if_lc_ifie_ratio = Decimal('0')
        group_if_lc_ifie_cf = Decimal('0')
        group_if_lc_ifie_ra = Decimal('0')
        group_if_lc_ifie_interest_cf = Decimal('0')
        group_if_lc_ifie_interest_ra = Decimal('0')
        group_if_lc_ifie_rate_change_cf = Decimal('0')
        group_if_lc_ifie_rate_change_ra = Decimal('0')
        
        # NB_LC IFIE分摊比例相关
        group_nb_lc_ifie_ratio = Decimal('0')
        group_nb_lc_ifie_cf = Decimal('0')
        group_nb_lc_ifie_ra = Decimal('0')
        group_nb_lc_ifie_interest_cf = Decimal('0')
        group_nb_lc_ifie_interest_ra = Decimal('0')
        group_nb_lc_ifie_rate_change_cf = Decimal('0')
        group_nb_lc_ifie_rate_change_ra = Decimal('0')
        
        # IACF相关
        group_initial_iacf = Decimal('0')
        group_iacf_interest = Decimal('0')
        group_eop_iacf_pv = Decimal('0')
        group_nb_iacf_pv = Decimal('0')
        group_iacf_amort_ratio = Decimal('0')
        group_bop_iacf = Decimal('0')
        group_bop_iacf_interest = Decimal('0')
        group_nb_iacf = Decimal('0')
        group_nb_iacf_interest = Decimal('0')
        group_iacf_change = Decimal('0')
        group_iacf_exp_adj = Decimal('0')
        group_iacf_amort = Decimal('0')
        group_eop_iacf = Decimal('0')
        
        # 保险合同收入相关
        group_revenue_claims_gross = Decimal('0')
        group_revenue_claims_lc_alloc = Decimal('0')
        group_revenue_ra_gross = Decimal('0')
        group_revenue_ra_lc_alloc = Decimal('0')
        group_revenue_csm_amort = Decimal('0')
        group_revenue_iacf_amort = Decimal('0')
        group_revenue_exp_adj = Decimal('0')
        group_revenue_investment = Decimal('0')
        group_revenue_total = Decimal('0')
        
        # IFIE相关
        group_ifie_cf_if = Decimal('0')
        group_ifie_cf_nb = Decimal('0')
        group_ifie_cf_total = Decimal('0')
        group_ifie_ra_if = Decimal('0')
        group_ifie_ra_nb = Decimal('0')
        group_ifie_ra_total = Decimal('0')
        group_ifie_csm = Decimal('0')
        group_ifie_total = Decimal('0')
        group_ifie_cf_non_lc = Decimal('0')
        group_ifie_cf_lc = Decimal('0')
        group_ifie_ra_non_lc = Decimal('0')
        group_ifie_ra_lc = Decimal('0')
        
        # LC相关（期末余额）
        group_bop_lc_cf = Decimal('0')
        group_nb_initial_lc_cf = Decimal('0')
        group_lc_ifie_cf = Decimal('0')
        group_allocated_lc_cf = Decimal('0')
        group_lc_absorbed_cf = Decimal('0')
        group_lc_adjust_cf = Decimal('0')
        group_eop_lc_cf = Decimal('0')
        
        group_bop_lc_ra = Decimal('0')
        group_nb_initial_lc_ra = Decimal('0')
        group_lc_ifie_ra = Decimal('0')
        group_allocated_lc_ra = Decimal('0')
        group_lc_absorbed_ra = Decimal('0')
        group_lc_adjust_ra = Decimal('0')
        group_eop_lc_ra = Decimal('0')
        
        group_lc_ratio_total = Decimal('0')
        group_bop_lc_total = Decimal('0')
        group_nb_initial_lc_total = Decimal('0')
        group_lc_ifie_total = Decimal('0')
        group_allocated_lc_total = Decimal('0')
        group_lc_absorbed_total_sum = Decimal('0')
        group_lc_adjust_total = Decimal('0')
        group_eop_lc_total = Decimal('0')
        
        # 从逐单context中汇总数据
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            is_new_business = self._is_new_business_year_for_context(ctx)
            
            # IF CSM相关
            if_bop_csm = self._to_decimal(getattr(ctx, 'bop_csm', Decimal('0'))) or Decimal('0')
            if_interest_csm = self._to_decimal(getattr(ctx, 'if_interest_csm', Decimal('0'))) or Decimal('0')
            if is_new_business:
                if_csm_post = Decimal('0')
            else:
                if_csm_post = if_bop_csm + if_interest_csm
            
            # NB CSM相关
            nb_initial_csm = self._to_decimal(getattr(ctx, 'nb_initial_csm', Decimal('0'))) or Decimal('0')
            nb_interest_csm = self._to_decimal(getattr(ctx, 'nb_interest_csm', Decimal('0'))) or Decimal('0')
            nb_csm_post = nb_initial_csm + nb_interest_csm
            
            # IF LC相关
            if_bop_lc = self._to_decimal(getattr(ctx, 'bop_lc', Decimal('0'))) or Decimal('0')
            if_lc_ifie_total = self._to_decimal(getattr(ctx, 'if_lc_ifie_total', Decimal('0'))) or Decimal('0')
            if is_new_business:
                if_lc_post = Decimal('0')
            else:
                if_lc_post = if_bop_lc + if_lc_ifie_total
            
            # NB LC相关
            nb_initial_lc = self._to_decimal(getattr(ctx, 'nb_initial_lc', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_total = self._to_decimal(getattr(ctx, 'nb_lc_ifie_total', Decimal('0'))) or Decimal('0')
            # 使用 context 中保存的 nb_lc_after_ifie
            nb_lc_after_ifie = self._to_decimal(getattr(ctx, 'nb_lc_after_ifie', Decimal('0'))) or Decimal('0')
            
            # 汇总
            group_if_bop_csm += if_bop_csm
            group_nb_initial_csm += nb_initial_csm
            group_if_interest_csm += if_interest_csm
            group_nb_interest_csm += nb_interest_csm
            group_if_csm_post += if_csm_post
            group_nb_csm_post += nb_csm_post
            
            group_if_bop_lc += if_bop_lc
            group_nb_initial_lc += nb_initial_lc
            group_if_lc_ifie_total += if_lc_ifie_total
            group_nb_lc_ifie_total += nb_lc_ifie_total
            group_if_lc_post += if_lc_post
            group_nb_lc_after_ifie += nb_lc_after_ifie
            
            # IF_LC IFIE分摊比例相关
            if_lc_ifie_ratio = self._to_decimal(getattr(ctx, 'if_lc_ifie_ratio', Decimal('0'))) or Decimal('0')
            if_lc_ifie_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_ra', Decimal('0'))) or Decimal('0')
            if_lc_ifie_interest_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_interest_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_interest_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_interest_ra', Decimal('0'))) or Decimal('0')
            if_lc_ifie_rate_change_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_rate_change_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_rate_change_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_rate_change_ra', Decimal('0'))) or Decimal('0')
            
            group_if_lc_ifie_ratio += if_lc_ifie_ratio
            group_if_lc_ifie_cf += if_lc_ifie_cf
            group_if_lc_ifie_ra += if_lc_ifie_ra
            group_if_lc_ifie_interest_cf += if_lc_ifie_interest_cf
            group_if_lc_ifie_interest_ra += if_lc_ifie_interest_ra
            group_if_lc_ifie_rate_change_cf += if_lc_ifie_rate_change_cf
            group_if_lc_ifie_rate_change_ra += if_lc_ifie_rate_change_ra
            
            # NB_LC IFIE分摊比例相关
            nb_lc_ifie_ratio = self._to_decimal(getattr(ctx, 'nb_lc_ifie_ratio', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_ra', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_interest_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_interest_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_interest_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_interest_ra', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_rate_change_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_rate_change_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_rate_change_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_rate_change_ra', Decimal('0'))) or Decimal('0')
            
            group_nb_lc_ifie_ratio += nb_lc_ifie_ratio
            group_nb_lc_ifie_cf += nb_lc_ifie_cf
            group_nb_lc_ifie_ra += nb_lc_ifie_ra
            group_nb_lc_ifie_interest_cf += nb_lc_ifie_interest_cf
            group_nb_lc_ifie_interest_ra += nb_lc_ifie_interest_ra
            group_nb_lc_ifie_rate_change_cf += nb_lc_ifie_rate_change_cf
            group_nb_lc_ifie_rate_change_ra += nb_lc_ifie_rate_change_ra
            
            # IACF相关
            initial_iacf = self._to_decimal(getattr(ctx, 'actual_iacf_incurred', Decimal('0'))) or Decimal('0')
            iacf_interest = self._to_decimal(getattr(ctx, 'iacf_interest', Decimal('0'))) or Decimal('0')
            eop_iacf_pv = self._to_decimal(getattr(ctx, 'eop_iacf_balance', Decimal('0'))) or Decimal('0')
            nb_iacf_pv = self._to_decimal(getattr(ctx, 'nb_iacf_addition', Decimal('0'))) or Decimal('0')
            iacf_amort_ratio = self._to_decimal(getattr(ctx, 'iacf_amort_ratio', Decimal('0'))) or Decimal('0')
            bop_iacf = self._to_decimal(getattr(ctx, 'bop_iacf', Decimal('0'))) or Decimal('0')
            bop_iacf_interest = self._to_decimal(getattr(ctx, 'bop_iacf_interest', Decimal('0'))) or Decimal('0')
            nb_iacf = self._to_decimal(getattr(ctx, 'nb_iacf_addition', Decimal('0'))) or Decimal('0')
            nb_iacf_interest = self._to_decimal(getattr(ctx, 'nb_iacf_interest', Decimal('0'))) or Decimal('0')
            iacf_change = self._to_decimal(getattr(ctx, 'iacf_change', Decimal('0'))) or Decimal('0')
            iacf_exp_adj = self._to_decimal(getattr(ctx, 'iacf_exp_adj', Decimal('0'))) or Decimal('0')
            iacf_amort = self._to_decimal(getattr(ctx, 'iacf_amort_amount', Decimal('0'))) or Decimal('0')
            eop_iacf = self._to_decimal(getattr(ctx, 'eop_iacf_balance', Decimal('0'))) or Decimal('0')
            
            group_initial_iacf += initial_iacf
            group_iacf_interest += iacf_interest
            group_eop_iacf_pv += eop_iacf_pv
            group_nb_iacf_pv += nb_iacf_pv
            group_bop_iacf += bop_iacf
            group_bop_iacf_interest += bop_iacf_interest
            group_nb_iacf += nb_iacf
            group_nb_iacf_interest += nb_iacf_interest
            group_iacf_change += iacf_change
            group_iacf_exp_adj += iacf_exp_adj
            group_iacf_amort += iacf_amort
            group_eop_iacf += eop_iacf
            
            # 保险合同收入相关
            revenue_claims_gross = self._to_decimal(getattr(ctx, 'revenue_claims_expenses_gross', Decimal('0'))) or Decimal('0')
            revenue_claims_lc_alloc = self._to_decimal(getattr(ctx, 'revenue_claims_expenses_lc_alloc', Decimal('0'))) or Decimal('0')
            revenue_ra_gross = self._to_decimal(getattr(ctx, 'ra_release_gross', Decimal('0'))) or Decimal('0')
            revenue_ra_lc_alloc = self._to_decimal(getattr(ctx, 'ra_release_lc_alloc', Decimal('0'))) or Decimal('0')
            revenue_csm_amort = self._to_decimal(getattr(ctx, 'csm_amort_amount', Decimal('0'))) or Decimal('0')
            revenue_iacf_amort = self._to_decimal(getattr(ctx, 'revenue_iacf_amort', Decimal('0'))) or Decimal('0')
            revenue_exp_adj = self._to_decimal(getattr(ctx, 'revenue_exp_adj', Decimal('0'))) or Decimal('0')
            revenue_investment = Decimal('0')  # 投资成分，暂时为0
            revenue_total = revenue_claims_gross + revenue_ra_gross + revenue_csm_amort + revenue_iacf_amort + revenue_exp_adj + revenue_investment
            
            group_revenue_claims_gross += revenue_claims_gross
            group_revenue_claims_lc_alloc += revenue_claims_lc_alloc
            group_revenue_ra_gross += revenue_ra_gross
            group_revenue_ra_lc_alloc += revenue_ra_lc_alloc
            group_revenue_csm_amort += revenue_csm_amort
            group_revenue_iacf_amort += revenue_iacf_amort
            group_revenue_exp_adj += revenue_exp_adj
            group_revenue_investment += revenue_investment
            group_revenue_total += revenue_total
            
            # IFIE相关
            ifie_cf_if = self._to_decimal(getattr(ctx, 'ifie_pl_cf_non_lc', Decimal('0'))) or Decimal('0')
            ifie_cf_nb = Decimal('0')  # 新业务年度的IFIE_CF已经在ifie_pl_cf_non_lc中
            ifie_cf_total = ifie_cf_if + ifie_cf_nb
            ifie_ra_if = self._to_decimal(getattr(ctx, 'ifie_pl_ra_non_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_nb = Decimal('0')
            ifie_ra_total = ifie_ra_if + ifie_ra_nb
            ifie_csm_val = -self._to_decimal(getattr(ctx, 'if_interest_csm' if not is_new_business else 'nb_interest_csm', Decimal('0'))) or Decimal('0')
            ifie_total = ifie_cf_total + ifie_ra_total + ifie_csm_val
            ifie_cf_non_lc = self._to_decimal(getattr(ctx, 'ifie_pl_cf_non_lc', Decimal('0'))) or Decimal('0')
            ifie_cf_lc = self._to_decimal(getattr(ctx, 'ifie_pl_cf_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_non_lc = self._to_decimal(getattr(ctx, 'ifie_pl_ra_non_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_lc = self._to_decimal(getattr(ctx, 'ifie_pl_ra_lc', Decimal('0'))) or Decimal('0')
            
            group_ifie_cf_if += ifie_cf_if
            group_ifie_cf_nb += ifie_cf_nb
            group_ifie_cf_total += ifie_cf_total
            group_ifie_ra_if += ifie_ra_if
            group_ifie_ra_nb += ifie_ra_nb
            group_ifie_ra_total += ifie_ra_total
            group_ifie_csm += ifie_csm_val
            group_ifie_total += ifie_total
            group_ifie_cf_non_lc += ifie_cf_non_lc
            group_ifie_cf_lc += ifie_cf_lc
            group_ifie_ra_non_lc += ifie_ra_non_lc
            group_ifie_ra_lc += ifie_ra_lc
            
            # LC相关（期末余额）
            bop_lc_cf = self._to_decimal(getattr(ctx, 'bop_lc_cf', Decimal('0'))) or Decimal('0')
            nb_initial_lc_cf = self._to_decimal(getattr(ctx, 'nb_initial_lc_cf', Decimal('0'))) or Decimal('0')
            lc_ifie_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_cf', Decimal('0'))) + self._to_decimal(getattr(ctx, 'nb_lc_ifie_cf', Decimal('0'))) or Decimal('0')
            allocated_lc_cf = self._to_decimal(getattr(ctx, 'allocated_lc_cf', Decimal('0'))) or Decimal('0')
            lc_absorbed_cf = self._to_decimal(getattr(ctx, 'lc_absorbed_cf', Decimal('0'))) or Decimal('0')
            lc_adjust_cf = self._to_decimal(getattr(ctx, 'lc_adjust_cf', Decimal('0'))) or Decimal('0')
            eop_lc_cf = self._to_decimal(getattr(ctx, 'end_lc_cf', Decimal('0'))) or Decimal('0')
            
            bop_lc_ra = self._to_decimal(getattr(ctx, 'bop_lc_ra', Decimal('0'))) or Decimal('0')
            nb_initial_lc_ra = self._to_decimal(getattr(ctx, 'nb_initial_lc_ra', Decimal('0'))) or Decimal('0')
            lc_ifie_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_ra', Decimal('0'))) + self._to_decimal(getattr(ctx, 'nb_lc_ifie_ra', Decimal('0'))) or Decimal('0')
            allocated_lc_ra = self._to_decimal(getattr(ctx, 'allocated_lc_ra', Decimal('0'))) or Decimal('0')
            lc_absorbed_ra = self._to_decimal(getattr(ctx, 'lc_absorbed_ra', Decimal('0'))) or Decimal('0')
            lc_adjust_ra = self._to_decimal(getattr(ctx, 'lc_adjust_ra', Decimal('0'))) or Decimal('0')
            eop_lc_ra = self._to_decimal(getattr(ctx, 'end_lc_ra', Decimal('0'))) or Decimal('0')
            
            group_bop_lc_cf += bop_lc_cf
            group_nb_initial_lc_cf += nb_initial_lc_cf
            group_lc_ifie_cf += lc_ifie_cf
            group_allocated_lc_cf += allocated_lc_cf
            group_lc_absorbed_cf += lc_absorbed_cf
            group_lc_adjust_cf += lc_adjust_cf
            group_eop_lc_cf += eop_lc_cf
            
            group_bop_lc_ra += bop_lc_ra
            group_nb_initial_lc_ra += nb_initial_lc_ra
            group_lc_ifie_ra += lc_ifie_ra
            group_allocated_lc_ra += allocated_lc_ra
            group_lc_absorbed_ra += lc_absorbed_ra
            group_lc_adjust_ra += lc_adjust_ra
            group_eop_lc_ra += eop_lc_ra
            
            group_bop_lc_total += (bop_lc_cf + bop_lc_ra)
            group_nb_initial_lc_total += (nb_initial_lc_cf + nb_initial_lc_ra)
            group_lc_ifie_total += (lc_ifie_cf + lc_ifie_ra)
            group_allocated_lc_total += (allocated_lc_cf + allocated_lc_ra)
            group_lc_absorbed_total_sum += (lc_absorbed_cf + lc_absorbed_ra)
            group_lc_adjust_total += (lc_adjust_cf + lc_adjust_ra)
            group_eop_lc_total += (eop_lc_cf + eop_lc_ra)
        
        # 计算CSM摊销比例（组级）
        csm_amort_ratio_group = Decimal('0')
        if group_csm_status > 0:
            # 使用覆盖单元动态比例法计算组级CSM摊销比例
            from BBA_group.logic.coverage_units import calculate_csm_amortization_ratio
            if self.policy_states:
                start_of_year = date(year, 1, 1)
                eval_date = date(year, 12, 31)
                csm_amort_ratio_group = calculate_csm_amortization_ratio(
                    self.policy_states,
                    eval_date,
                    start_of_year,
                    self.logger,
                    is_initial_year=(year == min(p.valuation_date.year for p in self.policy_states if p.valuation_date))
                )
        
        # 计算LC分摊比例（组级）
        lc_ratio_total_group = Decimal('0')
        if group_lc_status != 0:
            total_lc_abs = abs(group_lc_status)
            if total_lc_abs > 0:
                lc_ratio_total_group = (group_eop_lc_total / total_lc_abs) * Decimal('100')
        
        # 按照用户要求的顺序输出合同组字段
        self.logger.log_text(f"- IF_年初CSM余额: {group_if_bop_csm:,.2f}")
        self.logger.log_text(f"- 当年新增合同CSM: {group_nb_initial_csm:,.2f}")
        self.logger.log_text(f"- 期初有效合同CSM计息: {group_if_interest_csm:,.2f}")
        self.logger.log_text(f"- 新增合同CSM计息: {group_nb_interest_csm:,.2f}")
        self.logger.log_text(f"- IF_计息后CSM: {group_if_csm_post:,.2f}")
        self.logger.log_text(f"- NB_计息后CSM: {group_nb_csm_post:,.2f}")
        self.logger.log_text(f"- IF_年初LC: {group_if_bop_lc:,.2f}")
        self.logger.log_text(f"- IF_LC IFIE分摊比例: {group_if_lc_ifie_ratio:,.4f}")
        self.logger.log_text(f"- IF_待分摊IFIE_计息_赔付与费用: {group_if_lc_ifie_interest_cf:,.2f}")
        self.logger.log_text(f"- IF_待分摊IFIE_计息_非金融风险调整: {group_if_lc_ifie_interest_ra:,.2f}")
        self.logger.log_text(f"- IF_待分摊IFIE_利率变化的影响_赔付与费用: {group_if_lc_ifie_rate_change_cf:,.2f}")
        self.logger.log_text(f"- IF_待分摊IFIE_利率变化的影响_非金融风险调整: {group_if_lc_ifie_rate_change_ra:,.2f}")
        self.logger.log_text(f"- IF_LC分摊IFIE_赔付与费用: {group_if_lc_ifie_cf:,.2f}")
        self.logger.log_text(f"- IF_LC分摊IFIE_非金融风险调整: {group_if_lc_ifie_ra:,.2f}")
        self.logger.log_text(f"- IF_LC分摊IFIE: {group_if_lc_ifie_total:,.2f}")
        self.logger.log_text(f"- IF_分摊后IFIE后LC: {group_if_lc_post:,.2f}")
        self.logger.log_text(f"- NB_新增LC: {group_nb_initial_lc:,.2f}")
        self.logger.log_text(f"- NB_LC IFIE分摊比例: {group_nb_lc_ifie_ratio:,.4f}")
        self.logger.log_text(f"- NB_待分摊IFIE_计息_赔付与费用: {group_nb_lc_ifie_interest_cf:,.2f}")
        self.logger.log_text(f"- NB_待分摊IFIE_计息_非金融风险调整: {group_nb_lc_ifie_interest_ra:,.2f}")
        self.logger.log_text(f"- NB_待分摊IFIE_利率变化的影响_赔付与费用: {group_nb_lc_ifie_rate_change_cf:,.2f}")
        self.logger.log_text(f"- NB_待分摊IFIE_利率变化的影响_非金融风险调整: {group_nb_lc_ifie_rate_change_ra:,.2f}")
        self.logger.log_text(f"- NB_LC分摊IFIE_赔付与费用: {group_nb_lc_ifie_cf:,.2f}")
        self.logger.log_text(f"- NB_LC分摊IFIE_非金融风险调整: {group_nb_lc_ifie_ra:,.2f}")
        self.logger.log_text(f"- NB_LC分摊IFIE: {group_nb_lc_ifie_total:,.2f}")
        self.logger.log_text(f"- NB_分摊后IFIE后LC: {group_nb_lc_after_ifie:,.2f}")
        self.logger.log_text(f"- 合同组CSM: {group_csm_status:,.2f}")
        self.logger.log_text(f"- 合同组LC: {group_lc_status:,.2f}")
        self.logger.log_text(f"- CSM摊销比例: {csm_amort_ratio_group:,.4f}")
        self.logger.log_text(f"- 年初CSM余额: {self.group_cohort_state.bop_csm:,.2f}")
        self.logger.log_text(f"- 当年新增CSM: {group_nb_initial_csm:,.2f}")
        self.logger.log_text(f"- CSM计息: {group_if_interest_csm + group_nb_interest_csm:,.2f}")
        self.logger.log_text(f"- 被CSM吸收的变化: {group_csm_absorbed_total:,.2f}")
        self.logger.log_text(f"- 被CSM吸收的现金流变化: {group_result.group_csm_absorbed_cf:,.2f}")
        self.logger.log_text(f"- 被CSM吸收的非金融风险调整变化: {group_result.group_csm_absorbed_ra:,.2f}")
        self.logger.log_text(f"- 摊销的CSM: {group_csm_amort_amount:,.2f}")
        self.logger.log_text(f"- 期末CSM余额: {group_csm_final:,.2f}")
        self.logger.log_text(f"- 年初LC余额_预期现金流: {group_bop_lc_cf:,.2f}")
        self.logger.log_text(f"- 当年新增LC_预期现金流: {group_nb_initial_lc_cf:,.2f}")
        self.logger.log_text(f"- LC分摊IFIE_预期现金流: {group_lc_ifie_cf:,.2f}")
        self.logger.log_text(f"- 分摊的LC_预期现金流: {group_allocated_lc_cf:,.2f}")
        self.logger.log_text(f"- 被LC吸收的变化_预期现金流: {group_result.group_lc_absorbed_cf:,.2f}")
        self.logger.log_text(f"- 待调整LC余额_预期现金流: {group_bop_lc_cf + group_nb_initial_lc_cf + group_lc_ifie_cf + group_allocated_lc_cf:,.2f}")
        self.logger.log_text(f"- LC调整_预期现金流: {group_lc_adjust_cf:,.2f}")
        self.logger.log_text(f"- 期末LC余额_预期现金流: {group_eop_lc_cf:,.2f}")
        self.logger.log_text(f"- 年初LC余额_非金融风险调整: {group_bop_lc_ra:,.2f}")
        self.logger.log_text(f"- 当年新增LC_非金融风险调整: {group_nb_initial_lc_ra:,.2f}")
        self.logger.log_text(f"- LC分摊IFIE_非金融风险调整: {group_lc_ifie_ra:,.2f}")
        self.logger.log_text(f"- 分摊的LC_非金融风险调整: {group_allocated_lc_ra:,.2f}")
        self.logger.log_text(f"- 被LC吸收的变化_非金融风险调整: {group_result.group_lc_absorbed_ra:,.2f}")
        self.logger.log_text(f"- 待调整LC余额_非金融风险调整: {group_bop_lc_ra + group_nb_initial_lc_ra + group_lc_ifie_ra + group_allocated_lc_ra:,.2f}")
        self.logger.log_text(f"- LC调整_非金融风险调整: {group_lc_adjust_ra:,.2f}")
        self.logger.log_text(f"- 期末LC余额_非金融风险调整: {group_eop_lc_ra:,.2f}")
        self.logger.log_text(f"- LC分摊比例_合计: {lc_ratio_total_group:,.4f}")
        self.logger.log_text(f"- 年初LC余额_合计: {group_bop_lc_total:,.2f}")
        self.logger.log_text(f"- 当年新增LC_合计: {group_nb_initial_lc_total:,.2f}")
        self.logger.log_text(f"- LC分摊IFIE_合计: {group_lc_ifie_total:,.2f}")
        self.logger.log_text(f"- 分摊的LC_合计: {group_allocated_lc_total:,.2f}")
        self.logger.log_text(f"- 被LC吸收的变化_合计: {group_lc_absorbed_total:,.2f}")
        self.logger.log_text(f"- 待调整LC余额_合计: {group_bop_lc_total + group_nb_initial_lc_total + group_lc_ifie_total + group_allocated_lc_total:,.2f}")
        self.logger.log_text(f"- LC调整_合计: {group_lc_adjust_total:,.2f}")
        self.logger.log_text(f"- 期末LC余额_合计: {group_eop_lc_total:,.2f}")
        self.logger.log_text(f"- 初始确认预期当年IACF: {group_initial_iacf:,.2f}")
        self.logger.log_text(f"- 当年IACF计息: {group_iacf_interest:,.2f}")
        self.logger.log_text(f"- 期末预期未来IACF现值: {group_eop_iacf_pv:,.2f}")
        self.logger.log_text(f"- 当年新增总IACF期末现值: {group_nb_iacf_pv:,.2f}")
        self.logger.log_text(f"- IACF摊销比例: {group_iacf_amort_ratio:,.4f}")
        self.logger.log_text(f"- 年初待摊IACF余额: {group_bop_iacf:,.2f}")
        self.logger.log_text(f"- 年初待摊IACF计息: {group_bop_iacf_interest:,.2f}")
        self.logger.log_text(f"- 当年新增IACF: {group_nb_iacf:,.2f}")
        self.logger.log_text(f"- 当年新增IACF计息: {group_nb_iacf_interest:,.2f}")
        self.logger.log_text(f"- IACF变化: {group_iacf_change:,.2f}")
        self.logger.log_text(f"- IACF经验调整: {group_iacf_exp_adj:,.2f}")
        self.logger.log_text(f"- 摊销的IACF: {group_iacf_amort:,.2f}")
        self.logger.log_text(f"- 期末待摊IACF余额: {group_eop_iacf:,.2f}")
        self.logger.log_text(f"- 保险合同收入_预期赔付与费用_含亏损: {group_revenue_claims_gross:,.2f}")
        self.logger.log_text(f"- 保险合同收入_预期赔付与费用_亏损分摊: {group_revenue_claims_lc_alloc:,.2f}")
        self.logger.log_text(f"- 保险合同收入_预期释放的非金融风险调整_含亏损: {group_revenue_ra_gross:,.2f}")
        self.logger.log_text(f"- 保险合同收入_预期释放的非金融风险调整_亏损分摊: {group_revenue_ra_lc_alloc:,.2f}")
        self.logger.log_text(f"- 保险合同收入_摊销的CSM: {group_revenue_csm_amort:,.2f}")
        self.logger.log_text(f"- 保险合同收入_摊销的IACF: {group_revenue_iacf_amort:,.2f}")
        self.logger.log_text(f"- 保险合同收入_经验调整: {group_revenue_exp_adj:,.2f}")
        self.logger.log_text(f"- 保险合同收入_分解的投资成分: {group_revenue_investment:,.2f}")
        self.logger.log_text(f"- 保险合同收入: {group_revenue_total:,.2f}")
        self.logger.log_text(f"- 年初有效合同_预期现金流: {group_ifie_cf_if:,.2f}")
        self.logger.log_text(f"- 当年新增合同_预期现金流: {group_ifie_cf_nb:,.2f}")
        self.logger.log_text(f"- IFIE_预期现金流: {group_ifie_cf_total:,.2f}")
        self.logger.log_text(f"- 年初有效合同_非金融风险调整: {group_ifie_ra_if:,.2f}")
        self.logger.log_text(f"- 当年新增合同_非金融风险调整: {group_ifie_ra_nb:,.2f}")
        self.logger.log_text(f"- IFIE_非金融风险调整: {group_ifie_ra_total:,.2f}")
        self.logger.log_text(f"- IFIE_CSM: {group_ifie_csm:,.2f}")
        self.logger.log_text(f"- IFIE: {group_ifie_total:,.2f}")
        self.logger.log_text(f"- IFIE_预期现金流_非亏损: {group_ifie_cf_non_lc:,.2f}")
        self.logger.log_text(f"- IFIE_预期现金流_亏损: {group_ifie_cf_lc:,.2f}")
        self.logger.log_text(f"- IFIE_非金融风险调整_非亏损: {group_ifie_ra_non_lc:,.2f}")
        self.logger.log_text(f"- IFIE_非金融风险调整_亏损: {group_ifie_ra_lc:,.2f}")
        
        # ========== 第二部分：被CSM吸收的变化（合同组值 -> 分摊因子 -> 逐单值） ==========
        self.logger.log_text("### 被CSM吸收的变化")
        self.logger.log_text(f"- 合同组值: {group_csm_absorbed_total:,.2f}")
        
        # 计算CSM分摊因子
        total_csm_after_interest = Decimal('0')
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            csm_after_interest = self._to_decimal(getattr(ctx, 'end_csm_before_amort', Decimal('0'))) or Decimal('0')
            if csm_after_interest > 0:
                total_csm_after_interest += csm_after_interest
        
        if total_csm_after_interest > 0:
            self.logger.log_text(f"- CSM分摊因子（基于计息后CSM）:")
            for policy_state in self.policy_states:
                ctx = policy_contexts.get(policy_state.policy_no)
                if not ctx:
                    continue
                csm_after_interest = self._to_decimal(getattr(ctx, 'end_csm_before_amort', Decimal('0'))) or Decimal('0')
                if csm_after_interest > 0:
                    csm_weight = csm_after_interest / total_csm_after_interest
                    self.logger.log_text(f"  - 保单 {policy_state.policy_no}: {csm_weight:,.4f} ({csm_weight * Decimal('100'):,.2f}%)")
            
            self.logger.log_text(f"- 逐单分摊值:")
            for policy_state in self.policy_states:
                ctx = policy_contexts.get(policy_state.policy_no)
                if not ctx:
                    continue
                csm_absorbed = self._to_decimal(getattr(ctx, 'csm_absorbed', Decimal('0'))) or Decimal('0')
                self.logger.log_text(f"  - 保单 {policy_state.policy_no}: {csm_absorbed:,.2f}")
        else:
            self.logger.log_text(f"- CSM分摊因子: 无（无计息后CSM）")
            self.logger.log_text(f"- 逐单分摊值: 无")
        
        # ========== 第三部分：被LC吸收的变化_合计（合同组值 -> 分摊因子 -> 逐单值） ==========
        self.logger.log_text("### 被LC吸收的变化_合计")
        self.logger.log_text(f"- 合同组值: {group_lc_absorbed_total:,.2f}")
        
        # 计算LC分摊因子
        total_lc_after_ifie_abs = Decimal('0')
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            lc_after_ifie = self._to_decimal(getattr(ctx, 'end_lc_before_amort', Decimal('0'))) or Decimal('0')
            is_reversal = getattr(ctx, 'is_reversal_policy', False)
            if (not is_reversal and lc_after_ifie < 0) or (is_reversal and lc_after_ifie > 0):
                total_lc_after_ifie_abs += abs(lc_after_ifie)
        
        if total_lc_after_ifie_abs > 0:
            self.logger.log_text(f"- LC分摊因子（基于分摊后LC）:")
            for policy_state in self.policy_states:
                ctx = policy_contexts.get(policy_state.policy_no)
                if not ctx:
                    continue
                lc_after_ifie = self._to_decimal(getattr(ctx, 'end_lc_before_amort', Decimal('0'))) or Decimal('0')
                is_reversal = getattr(ctx, 'is_reversal_policy', False)
                if (not is_reversal and lc_after_ifie < 0) or (is_reversal and lc_after_ifie > 0):
                    lc_weight = abs(lc_after_ifie) / total_lc_after_ifie_abs
                    self.logger.log_text(f"  - 保单 {policy_state.policy_no}: {lc_weight:,.4f} ({lc_weight * Decimal('100'):,.2f}%)")
            
            self.logger.log_text(f"- 逐单分摊值:")
            for policy_state in self.policy_states:
                ctx = policy_contexts.get(policy_state.policy_no)
                if not ctx:
                    continue
                lc_absorbed_total = self._to_decimal(getattr(ctx, 'lc_absorbed_total', Decimal('0'))) or Decimal('0')
                self.logger.log_text(f"  - 保单 {policy_state.policy_no}: {lc_absorbed_total:,.2f}")
        else:
            self.logger.log_text(f"- LC分摊因子: 无（无分摊后LC）")
            self.logger.log_text(f"- 逐单分摊值: 无")
        
        # ========== 第四部分：逐单结果 ==========
        self.logger.log_text("### 逐单结果")
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            is_new_business = self._is_new_business_year_for_context(ctx)
            
            # 提取逐单字段值
            if_bop_csm = self._to_decimal(getattr(ctx, 'bop_csm', Decimal('0'))) or Decimal('0')
            nb_initial_csm = self._to_decimal(getattr(ctx, 'nb_initial_csm', Decimal('0'))) or Decimal('0')
            if_interest_csm = self._to_decimal(getattr(ctx, 'if_interest_csm', Decimal('0'))) or Decimal('0')
            nb_interest_csm = self._to_decimal(getattr(ctx, 'nb_interest_csm', Decimal('0'))) or Decimal('0')
            if is_new_business:
                if_csm_post = Decimal('0')
            else:
                if_csm_post = if_bop_csm + if_interest_csm
            nb_csm_post = nb_initial_csm + nb_interest_csm
            
            if_bop_lc = self._to_decimal(getattr(ctx, 'bop_lc', Decimal('0'))) or Decimal('0')
            if_lc_ifie_ratio = self._to_decimal(getattr(ctx, 'if_lc_ifie_ratio', Decimal('0'))) or Decimal('0')
            if_lc_ifie_interest_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_interest_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_interest_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_interest_ra', Decimal('0'))) or Decimal('0')
            if_lc_ifie_rate_change_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_rate_change_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_rate_change_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_rate_change_ra', Decimal('0'))) or Decimal('0')
            if_lc_ifie_cf = self._to_decimal(getattr(ctx, 'if_lc_ifie_cf', Decimal('0'))) or Decimal('0')
            if_lc_ifie_ra = self._to_decimal(getattr(ctx, 'if_lc_ifie_ra', Decimal('0'))) or Decimal('0')
            if_lc_ifie_total = self._to_decimal(getattr(ctx, 'if_lc_ifie_total', Decimal('0'))) or Decimal('0')
            if is_new_business:
                if_lc_post = Decimal('0')
            else:
                if_lc_post = if_bop_lc + if_lc_ifie_total
            
            nb_initial_lc = self._to_decimal(getattr(ctx, 'nb_initial_lc', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_ratio = self._to_decimal(getattr(ctx, 'nb_lc_ifie_ratio', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_interest_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_interest_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_interest_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_interest_ra', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_rate_change_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_rate_change_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_rate_change_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_rate_change_ra', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_cf = self._to_decimal(getattr(ctx, 'nb_lc_ifie_cf', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_ra = self._to_decimal(getattr(ctx, 'nb_lc_ifie_ra', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_total = self._to_decimal(getattr(ctx, 'nb_lc_ifie_total', Decimal('0'))) or Decimal('0')
            # 【修复】：使用 context 中保存的 nb_lc_after_ifie，而不是重新计算
            # nb_lc_after_ifie 已经在 csm_lc_measurement.py 中计算并保存到 context
            nb_lc_after_ifie = self._to_decimal(getattr(ctx, 'nb_lc_after_ifie', Decimal('0'))) or Decimal('0')
            
            csm_amort_ratio = self._to_decimal(getattr(ctx, 'csm_amort_ratio', Decimal('0'))) or Decimal('0')
            bop_csm = self._to_decimal(getattr(ctx, 'bop_csm', Decimal('0'))) or Decimal('0')
            csm_interest = if_interest_csm + nb_interest_csm
            csm_absorbed = self._to_decimal(getattr(ctx, 'csm_absorbed', Decimal('0'))) or Decimal('0')
            csm_absorbed_cf = self._to_decimal(getattr(ctx, 'csm_absorbed_cf', Decimal('0'))) or Decimal('0')
            csm_absorbed_ra = self._to_decimal(getattr(ctx, 'csm_absorbed_ra', Decimal('0'))) or Decimal('0')
            csm_amort = self._to_decimal(getattr(ctx, 'csm_amort_amount', Decimal('0'))) or Decimal('0')
            eop_csm = self._to_decimal(getattr(ctx, 'end_csm_final', Decimal('0'))) or Decimal('0')
            
            bop_lc_cf = self._to_decimal(getattr(ctx, 'bop_lc_cf', Decimal('0'))) or Decimal('0')
            nb_initial_lc_cf = self._to_decimal(getattr(ctx, 'nb_initial_lc_cf', Decimal('0'))) or Decimal('0')
            lc_ifie_cf = if_lc_ifie_cf + nb_lc_ifie_cf
            allocated_lc_cf = self._to_decimal(getattr(ctx, 'allocated_lc_cf', Decimal('0'))) or Decimal('0')
            lc_absorbed_cf = self._to_decimal(getattr(ctx, 'lc_absorbed_cf', Decimal('0'))) or Decimal('0')
            lc_adjust_cf = self._to_decimal(getattr(ctx, 'lc_adjust_cf', Decimal('0'))) or Decimal('0')
            eop_lc_cf = self._to_decimal(getattr(ctx, 'end_lc_cf', Decimal('0'))) or Decimal('0')
            
            bop_lc_ra = self._to_decimal(getattr(ctx, 'bop_lc_ra', Decimal('0'))) or Decimal('0')
            nb_initial_lc_ra = self._to_decimal(getattr(ctx, 'nb_initial_lc_ra', Decimal('0'))) or Decimal('0')
            lc_ifie_ra = if_lc_ifie_ra + nb_lc_ifie_ra
            allocated_lc_ra = self._to_decimal(getattr(ctx, 'allocated_lc_ra', Decimal('0'))) or Decimal('0')
            lc_absorbed_ra = self._to_decimal(getattr(ctx, 'lc_absorbed_ra', Decimal('0'))) or Decimal('0')
            lc_adjust_ra = self._to_decimal(getattr(ctx, 'lc_adjust_ra', Decimal('0'))) or Decimal('0')
            eop_lc_ra = self._to_decimal(getattr(ctx, 'end_lc_ra', Decimal('0'))) or Decimal('0')
            
            lc_ratio_total = self._to_decimal(getattr(ctx, 'lc_allocation_ratio_total', Decimal('0'))) or Decimal('0')
            bop_lc_total = bop_lc_cf + bop_lc_ra
            nb_initial_lc_total = nb_initial_lc_cf + nb_initial_lc_ra
            lc_ifie_total = lc_ifie_cf + lc_ifie_ra
            allocated_lc_total = allocated_lc_cf + allocated_lc_ra
            lc_absorbed_total = self._to_decimal(getattr(ctx, 'lc_absorbed_total', Decimal('0'))) or Decimal('0')
            lc_adjust_total = lc_adjust_cf + lc_adjust_ra
            eop_lc_total = eop_lc_cf + eop_lc_ra
            
            initial_iacf = self._to_decimal(getattr(ctx, 'actual_iacf_incurred', Decimal('0'))) or Decimal('0')
            iacf_interest = self._to_decimal(getattr(ctx, 'iacf_interest', Decimal('0'))) or Decimal('0')
            eop_iacf_pv = self._to_decimal(getattr(ctx, 'eop_iacf_balance', Decimal('0'))) or Decimal('0')
            nb_iacf_pv = self._to_decimal(getattr(ctx, 'nb_iacf_addition', Decimal('0'))) or Decimal('0')
            iacf_amort_ratio = self._to_decimal(getattr(ctx, 'iacf_amort_ratio', Decimal('0'))) or Decimal('0')
            bop_iacf = self._to_decimal(getattr(ctx, 'bop_iacf', Decimal('0'))) or Decimal('0')
            bop_iacf_interest = self._to_decimal(getattr(ctx, 'bop_iacf_interest', Decimal('0'))) or Decimal('0')
            nb_iacf = self._to_decimal(getattr(ctx, 'nb_iacf_addition', Decimal('0'))) or Decimal('0')
            nb_iacf_interest = self._to_decimal(getattr(ctx, 'nb_iacf_interest', Decimal('0'))) or Decimal('0')
            iacf_change = self._to_decimal(getattr(ctx, 'iacf_change', Decimal('0'))) or Decimal('0')
            iacf_exp_adj = self._to_decimal(getattr(ctx, 'iacf_exp_adj', Decimal('0'))) or Decimal('0')
            iacf_amort = self._to_decimal(getattr(ctx, 'iacf_amort_amount', Decimal('0'))) or Decimal('0')
            eop_iacf = self._to_decimal(getattr(ctx, 'eop_iacf_balance', Decimal('0'))) or Decimal('0')
            
            revenue_claims_gross = self._to_decimal(getattr(ctx, 'revenue_claims_expenses_gross', Decimal('0'))) or Decimal('0')
            revenue_claims_lc_alloc = self._to_decimal(getattr(ctx, 'revenue_claims_expenses_lc_alloc', Decimal('0'))) or Decimal('0')
            revenue_ra_gross = self._to_decimal(getattr(ctx, 'ra_release_gross', Decimal('0'))) or Decimal('0')
            revenue_ra_lc_alloc = self._to_decimal(getattr(ctx, 'ra_release_lc_alloc', Decimal('0'))) or Decimal('0')
            revenue_csm_amort = self._to_decimal(getattr(ctx, 'csm_amort_amount', Decimal('0'))) or Decimal('0')
            revenue_iacf_amort = self._to_decimal(getattr(ctx, 'revenue_iacf_amort', Decimal('0'))) or Decimal('0')
            revenue_exp_adj = self._to_decimal(getattr(ctx, 'revenue_exp_adj', Decimal('0'))) or Decimal('0')
            revenue_investment = Decimal('0')
            revenue_total = revenue_claims_gross + revenue_ra_gross + revenue_csm_amort + revenue_iacf_amort + revenue_exp_adj + revenue_investment
            
            ifie_cf_if = self._to_decimal(getattr(ctx, 'ifie_pl_cf_non_lc', Decimal('0'))) or Decimal('0')
            ifie_cf_nb = Decimal('0')
            ifie_cf_total = ifie_cf_if + ifie_cf_nb
            ifie_ra_if = self._to_decimal(getattr(ctx, 'ifie_pl_ra_non_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_nb = Decimal('0')
            ifie_ra_total = ifie_ra_if + ifie_ra_nb
            ifie_csm_val = -self._to_decimal(getattr(ctx, 'if_interest_csm' if not is_new_business else 'nb_interest_csm', Decimal('0'))) or Decimal('0')
            ifie_total = ifie_cf_total + ifie_ra_total + ifie_csm_val
            ifie_cf_non_lc = self._to_decimal(getattr(ctx, 'ifie_pl_cf_non_lc', Decimal('0'))) or Decimal('0')
            ifie_cf_lc = self._to_decimal(getattr(ctx, 'ifie_pl_cf_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_non_lc = self._to_decimal(getattr(ctx, 'ifie_pl_ra_non_lc', Decimal('0'))) or Decimal('0')
            ifie_ra_lc = self._to_decimal(getattr(ctx, 'ifie_pl_ra_lc', Decimal('0'))) or Decimal('0')
            
            # 输出逐单字段值（按照用户要求的顺序）
            self.logger.log_text(f"#### 保单 {policy_state.policy_no}")
            self.logger.log_text(f"- IF_年初CSM余额: {if_bop_csm:,.2f}")
            self.logger.log_text(f"- 当年新增合同CSM: {nb_initial_csm:,.2f}")
            self.logger.log_text(f"- 期初有效合同CSM计息: {if_interest_csm:,.2f}")
            self.logger.log_text(f"- 新增合同CSM计息: {nb_interest_csm:,.2f}")
            self.logger.log_text(f"- IF_计息后CSM: {if_csm_post:,.2f}")
            self.logger.log_text(f"- NB_计息后CSM: {nb_csm_post:,.2f}")
            self.logger.log_text(f"- IF_年初LC: {if_bop_lc:,.2f}")
            self.logger.log_text(f"- IF_LC IFIE分摊比例: {if_lc_ifie_ratio:,.4f}")
            self.logger.log_text(f"- IF_待分摊IFIE_计息_赔付与费用: {if_lc_ifie_interest_cf:,.2f}")
            self.logger.log_text(f"- IF_待分摊IFIE_计息_非金融风险调整: {if_lc_ifie_interest_ra:,.2f}")
            self.logger.log_text(f"- IF_待分摊IFIE_利率变化的影响_赔付与费用: {if_lc_ifie_rate_change_cf:,.2f}")
            self.logger.log_text(f"- IF_待分摊IFIE_利率变化的影响_非金融风险调整: {if_lc_ifie_rate_change_ra:,.2f}")
            self.logger.log_text(f"- IF_LC分摊IFIE_赔付与费用: {if_lc_ifie_cf:,.2f}")
            self.logger.log_text(f"- IF_LC分摊IFIE_非金融风险调整: {if_lc_ifie_ra:,.2f}")
            self.logger.log_text(f"- IF_LC分摊IFIE: {if_lc_ifie_total:,.2f}")
            self.logger.log_text(f"- IF_分摊后IFIE后LC: {if_lc_post:,.2f}")
            self.logger.log_text(f"- NB_新增LC: {nb_initial_lc:,.2f}")
            self.logger.log_text(f"- NB_LC IFIE分摊比例: {nb_lc_ifie_ratio:,.4f}")
            self.logger.log_text(f"- NB_待分摊IFIE_计息_赔付与费用: {nb_lc_ifie_interest_cf:,.2f}")
            self.logger.log_text(f"- NB_待分摊IFIE_计息_非金融风险调整: {nb_lc_ifie_interest_ra:,.2f}")
            self.logger.log_text(f"- NB_待分摊IFIE_利率变化的影响_赔付与费用: {nb_lc_ifie_rate_change_cf:,.2f}")
            self.logger.log_text(f"- NB_待分摊IFIE_利率变化的影响_非金融风险调整: {nb_lc_ifie_rate_change_ra:,.2f}")
            self.logger.log_text(f"- NB_LC分摊IFIE_赔付与费用: {nb_lc_ifie_cf:,.2f}")
            self.logger.log_text(f"- NB_LC分摊IFIE_非金融风险调整: {nb_lc_ifie_ra:,.2f}")
            self.logger.log_text(f"- NB_LC分摊IFIE: {nb_lc_ifie_total:,.2f}")
            self.logger.log_text(f"- NB_分摊后IFIE后LC: {nb_lc_after_ifie:,.2f}")
            # 注意：合同组CSM和合同组LC只展示合同组的，不展示逐单的
            self.logger.log_text(f"- CSM摊销比例: {csm_amort_ratio:,.4f}")
            self.logger.log_text(f"- 年初CSM余额: {bop_csm:,.2f}")
            self.logger.log_text(f"- 当年新增CSM: {nb_initial_csm:,.2f}")
            self.logger.log_text(f"- CSM计息: {csm_interest:,.2f}")
            self.logger.log_text(f"- 被CSM吸收的变化: {csm_absorbed:,.2f}")
            self.logger.log_text(f"- 被CSM吸收的现金流变化: {csm_absorbed_cf:,.2f}")
            self.logger.log_text(f"- 被CSM吸收的非金融风险调整变化: {csm_absorbed_ra:,.2f}")
            self.logger.log_text(f"- 摊销的CSM: {csm_amort:,.2f}")
            self.logger.log_text(f"- 期末CSM余额: {eop_csm:,.2f}")
            self.logger.log_text(f"- 年初LC余额_预期现金流: {bop_lc_cf:,.2f}")
            self.logger.log_text(f"- 当年新增LC_预期现金流: {nb_initial_lc_cf:,.2f}")
            self.logger.log_text(f"- LC分摊IFIE_预期现金流: {lc_ifie_cf:,.2f}")
            self.logger.log_text(f"- 分摊的LC_预期现金流: {allocated_lc_cf:,.2f}")
            self.logger.log_text(f"- 被LC吸收的变化_预期现金流: {lc_absorbed_cf:,.2f}")
            self.logger.log_text(f"- 待调整LC余额_预期现金流: {bop_lc_cf + nb_initial_lc_cf + lc_ifie_cf + allocated_lc_cf:,.2f}")
            self.logger.log_text(f"- LC调整_预期现金流: {lc_adjust_cf:,.2f}")
            self.logger.log_text(f"- 期末LC余额_预期现金流: {eop_lc_cf:,.2f}")
            self.logger.log_text(f"- 年初LC余额_非金融风险调整: {bop_lc_ra:,.2f}")
            self.logger.log_text(f"- 当年新增LC_非金融风险调整: {nb_initial_lc_ra:,.2f}")
            self.logger.log_text(f"- LC分摊IFIE_非金融风险调整: {lc_ifie_ra:,.2f}")
            self.logger.log_text(f"- 分摊的LC_非金融风险调整: {allocated_lc_ra:,.2f}")
            self.logger.log_text(f"- 被LC吸收的变化_非金融风险调整: {lc_absorbed_ra:,.2f}")
            self.logger.log_text(f"- 待调整LC余额_非金融风险调整: {bop_lc_ra + nb_initial_lc_ra + lc_ifie_ra + allocated_lc_ra:,.2f}")
            self.logger.log_text(f"- LC调整_非金融风险调整: {lc_adjust_ra:,.2f}")
            self.logger.log_text(f"- 期末LC余额_非金融风险调整: {eop_lc_ra:,.2f}")
            self.logger.log_text(f"- LC分摊比例_合计: {lc_ratio_total:,.4f}")
            self.logger.log_text(f"- 年初LC余额_合计: {bop_lc_total:,.2f}")
            self.logger.log_text(f"- 当年新增LC_合计: {nb_initial_lc_total:,.2f}")
            self.logger.log_text(f"- LC分摊IFIE_合计: {lc_ifie_total:,.2f}")
            self.logger.log_text(f"- 分摊的LC_合计: {allocated_lc_total:,.2f}")
            self.logger.log_text(f"- 被LC吸收的变化_合计: {lc_absorbed_total:,.2f}")
            self.logger.log_text(f"- 待调整LC余额_合计: {bop_lc_total + nb_initial_lc_total + lc_ifie_total + allocated_lc_total:,.2f}")
            self.logger.log_text(f"- LC调整_合计: {lc_adjust_total:,.2f}")
            self.logger.log_text(f"- 期末LC余额_合计: {eop_lc_total:,.2f}")
            self.logger.log_text(f"- 初始确认预期当年IACF: {initial_iacf:,.2f}")
            self.logger.log_text(f"- 当年IACF计息: {iacf_interest:,.2f}")
            self.logger.log_text(f"- 期末预期未来IACF现值: {eop_iacf_pv:,.2f}")
            self.logger.log_text(f"- 当年新增总IACF期末现值: {nb_iacf_pv:,.2f}")
            self.logger.log_text(f"- IACF摊销比例: {iacf_amort_ratio:,.4f}")
            self.logger.log_text(f"- 年初待摊IACF余额: {bop_iacf:,.2f}")
            self.logger.log_text(f"- 年初待摊IACF计息: {bop_iacf_interest:,.2f}")
            self.logger.log_text(f"- 当年新增IACF: {nb_iacf:,.2f}")
            self.logger.log_text(f"- 当年新增IACF计息: {nb_iacf_interest:,.2f}")
            self.logger.log_text(f"- IACF变化: {iacf_change:,.2f}")
            self.logger.log_text(f"- IACF经验调整: {iacf_exp_adj:,.2f}")
            self.logger.log_text(f"- 摊销的IACF: {iacf_amort:,.2f}")
            self.logger.log_text(f"- 期末待摊IACF余额: {eop_iacf:,.2f}")
            self.logger.log_text(f"- 保险合同收入_预期赔付与费用_含亏损: {revenue_claims_gross:,.2f}")
            self.logger.log_text(f"- 保险合同收入_预期赔付与费用_亏损分摊: {revenue_claims_lc_alloc:,.2f}")
            self.logger.log_text(f"- 保险合同收入_预期释放的非金融风险调整_含亏损: {revenue_ra_gross:,.2f}")
            self.logger.log_text(f"- 保险合同收入_预期释放的非金融风险调整_亏损分摊: {revenue_ra_lc_alloc:,.2f}")
            self.logger.log_text(f"- 保险合同收入_摊销的CSM: {revenue_csm_amort:,.2f}")
            self.logger.log_text(f"- 保险合同收入_摊销的IACF: {revenue_iacf_amort:,.2f}")
            self.logger.log_text(f"- 保险合同收入_经验调整: {revenue_exp_adj:,.2f}")
            self.logger.log_text(f"- 保险合同收入_分解的投资成分: {revenue_investment:,.2f}")
            self.logger.log_text(f"- 保险合同收入: {revenue_total:,.2f}")
            self.logger.log_text(f"- 年初有效合同_预期现金流: {ifie_cf_if:,.2f}")
            self.logger.log_text(f"- 当年新增合同_预期现金流: {ifie_cf_nb:,.2f}")
            self.logger.log_text(f"- IFIE_预期现金流: {ifie_cf_total:,.2f}")
            self.logger.log_text(f"- 年初有效合同_非金融风险调整: {ifie_ra_if:,.2f}")
            self.logger.log_text(f"- 当年新增合同_非金融风险调整: {ifie_ra_nb:,.2f}")
            self.logger.log_text(f"- IFIE_非金融风险调整: {ifie_ra_total:,.2f}")
            self.logger.log_text(f"- IFIE_CSM: {ifie_csm_val:,.2f}")
            self.logger.log_text(f"- IFIE: {ifie_total:,.2f}")
            self.logger.log_text(f"- IFIE_预期现金流_非亏损: {ifie_cf_non_lc:,.2f}")
            self.logger.log_text(f"- IFIE_预期现金流_亏损: {ifie_cf_lc:,.2f}")
            self.logger.log_text(f"- IFIE_非金融风险调整_非亏损: {ifie_ra_non_lc:,.2f}")
            self.logger.log_text(f"- IFIE_非金融风险调整_亏损: {ifie_ra_lc:,.2f}")

    def _extract_policy_yearly_result(self, year: int, context: CalculationContext) -> Dict:
        """从单张保单的context中提取年度结果，供组级汇总"""
        lc_ratio = self._to_decimal(getattr(context, 'nb_lc_ifie_ratio', Decimal('0')) or Decimal('0'))
        
        # 关键修复：claims_gross应该直接使用revenue_claims_expenses_gross
        # 而不是通过claims_net + claims_lc_alloc计算，因为：
        # - claims_net = gross - allocated_lc_cf（只减去了allocated_lc_cf）
        # - claims_lc_alloc = allocated_lc_cf + lc_adjust_cf（包含了lc_adjust_cf）
        # - 如果使用claims_net + claims_lc_alloc，会多加了lc_adjust_cf
        # 正确的做法是直接使用revenue_claims_expenses_gross
        claims_gross = self._to_decimal(getattr(context, 'revenue_claims_expenses_gross', None))
        if claims_gross is None:
            # 如果没有gross值，则从net和lc_alloc反推（兼容旧代码）
            claims_lc_alloc = self._to_decimal(getattr(context, 'revenue_claims_expenses_lc_alloc', None))
            if claims_lc_alloc is None:
                claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
                claims_gross = self._derive_gross_from_net(claims_net, lc_ratio)
                claims_lc_alloc = claims_gross - claims_net
            else:
                claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
                # 注意：不能直接用claims_net + claims_lc_alloc，因为会多加了lc_adjust_cf
                # 应该只加allocated_lc_cf，而不是allocated_lc_cf + lc_adjust_cf
                allocated_lc_cf = self._to_decimal(getattr(context, 'allocated_lc_cf', Decimal('0')))
                claims_gross = claims_net + allocated_lc_cf
                claims_lc_alloc = claims_gross - claims_net
        else:
            # 如果已经有gross值，直接使用revenue_claims_expenses_lc_alloc
            # 注意：不能通过claims_gross - claims_net计算，因为：
            # - claims_net = gross - allocated_lc_cf（只减去了allocated_lc_cf）
            # - claims_lc_alloc应该包含allocated_lc_cf + lc_adjust_cf
            # - 如果使用claims_gross - claims_net，只会得到allocated_lc_cf，缺少lc_adjust_cf
            claims_lc_alloc = self._to_decimal(getattr(context, 'revenue_claims_expenses_lc_alloc', None))
            if claims_lc_alloc is None:
                # 如果没有lc_alloc值，则从gross和net反推（但这样会缺少lc_adjust_cf）
                claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
                # 这里只能得到allocated_lc_cf，缺少lc_adjust_cf
                claims_lc_alloc = claims_gross - claims_net
                # 尝试补充lc_adjust_cf
                lc_adjust_cf = self._to_decimal(getattr(context, 'lc_adjust_cf', Decimal('0')))
                claims_lc_alloc = claims_lc_alloc + lc_adjust_cf
        
        ra_net = self._to_decimal(getattr(context, 'ra_release_net', Decimal('0')))
        ra_gross = self._to_decimal(getattr(context, 'ra_release_gross', None)) or self._derive_gross_from_net(ra_net, lc_ratio)
        ra_lc_alloc = self._to_decimal(getattr(context, 'ra_release_lc_alloc', None))
        if ra_lc_alloc == Decimal('0') and ra_gross != ra_net:
            ra_lc_alloc = ra_gross - ra_net
        
        allocated_lc_cf = self._to_decimal(getattr(context, 'allocated_lc_cf', Decimal('0')))
        allocated_lc_ra = self._to_decimal(getattr(context, 'allocated_lc_ra', Decimal('0')))
        allocated_lc_exp_adj_cf = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_cf', Decimal('0')))
        allocated_lc_exp_adj_ra = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_ra', Decimal('0')))
        
        iacf_amort_expense = self._to_decimal(getattr(context, 'iacf_amort_amount', Decimal('0')))
        
        nb_initial_lc = self._to_decimal(context.nb_initial_lc if self._is_new_business_year_for_context(context) else Decimal('0'))
        nb_initial_lc_cf = self._to_decimal(getattr(context, 'nb_initial_lc_cf', Decimal('0')) if self._is_new_business_year_for_context(context) else Decimal('0'))
        nb_initial_lc_ra = self._to_decimal(getattr(context, 'nb_initial_lc_ra', Decimal('0')) if self._is_new_business_year_for_context(context) else Decimal('0'))
        
        ifie_pl_cf_non_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_non_lc', Decimal('0')))
        ifie_pl_cf_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_lc', Decimal('0')))
        ifie_pl_ra_non_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_non_lc', Decimal('0')))
        ifie_pl_ra_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_lc', Decimal('0')))
        
        is_new_business = self._is_new_business_year_for_context(context)
        ifie_csm = -self._to_decimal(
            getattr(context, 'nb_interest_csm', Decimal('0')) if is_new_business
            else getattr(context, 'if_interest_csm', Decimal('0'))
        )
        
        ifie_oci_cf_non_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_non_lc', Decimal('0')))
        ifie_oci_cf_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_lc', Decimal('0')))
        ifie_oci_ra_non_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_non_lc', Decimal('0')))
        ifie_oci_ra_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_lc', Decimal('0')))
        
        lrc_bel_total = self._to_decimal(getattr(context, 'lrc_bel_total', None))
        if lrc_bel_total is None:
            lrc_bel_total = self._to_decimal(getattr(context, 'pv_eop_claims_current', Decimal('0'))) + \
                self._to_decimal(getattr(context, 'pv_eop_maint_current', Decimal('0')))
        lrc_ra = self._to_decimal(getattr(context, 'lrc_ra', Decimal('0')))
        
        # 注意：这里的 CSM/LC 期末值需要取组维度判定后的分摊值
        # 这里暂时取 context 中的值，后续会被组级结果覆盖或重算，
        # 但为了 104 报表的某些明细，我们可能需要保留原始值
        end_csm = self._to_decimal(getattr(context, 'end_csm_final', getattr(context, 'end_csm_before_amort', Decimal('0'))))
        end_lc_cf = self._to_decimal(getattr(context, 'end_lc_cf', Decimal('0')))
        end_lc_ra = self._to_decimal(getattr(context, 'end_lc_ra', Decimal('0')))
        lrc_bel_lc = end_lc_cf
        lrc_ra_lc = -end_lc_ra
        lrc_bel_non_lc = lrc_bel_total - lrc_bel_lc
        lrc_ra_non_lc = lrc_ra - lrc_ra_lc
        
        is_reversal = getattr(context, 'is_reversal_policy', False)
        
        result = {
            "policy_no": getattr(context, 'policy_no', ''),
            "certi_no": getattr(context, 'certi_no', '') or "",
            "year": year,
            "nb_initial_lc": self._to_number(nb_initial_lc),
            "保险合同收入_预期赔付与费用_含亏损": self._apply_reversal_if_needed(claims_gross, is_reversal),
            "保险合同收入_预期赔付与费用_亏损分摊": self._apply_reversal_if_needed(claims_lc_alloc, is_reversal),
            "保险合同收入_预期释放的非金融风险调整_含亏损": self._apply_reversal_if_needed(ra_gross, is_reversal),
            "保险合同收入_预期释放的非金融风险调整_亏损分摊": self._apply_reversal_if_needed(ra_lc_alloc, is_reversal),
            "保险合同收入_摊销的CSM": self._apply_reversal_if_needed(getattr(context, 'csm_amort_amount', Decimal('0')), is_reversal),
            "保险合同收入_摊销的IACF": self._apply_reversal_if_needed(getattr(context, 'revenue_iacf_amort', Decimal('0')), is_reversal),
            "保险合同收入_经验调整": self._apply_reversal_if_needed(getattr(context, 'revenue_exp_adj', Decimal('0')), is_reversal),
            "赔付与费用_亏损分摊_预期现金流": self._apply_reversal_if_needed(allocated_lc_cf, is_reversal),
            "赔付与费用_亏损分摊_非金融风险调整": self._apply_reversal_if_needed(allocated_lc_ra, is_reversal),
            "赔付与费用_摊销的IACF": self._apply_reversal_if_needed(iacf_amort_expense, is_reversal),
            "亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损": self._apply_reversal_if_needed(nb_initial_lc_cf, is_reversal),
            "亏损合同损益_新增合同非金融风险调整_亏损": self._apply_reversal_if_needed(nb_initial_lc_ra, is_reversal),
            "亏损合同损益_不调整CSM的预期现金流变动": self._apply_reversal_if_needed(allocated_lc_exp_adj_cf, is_reversal),
            "亏损合同损益_不调整CSM的非金融风险调整变动": self._apply_reversal_if_needed(allocated_lc_exp_adj_ra, is_reversal),
            "IFIE_P&L_未到期_预期现金流_非亏损": self._apply_reversal_if_needed(ifie_pl_cf_non_lc, is_reversal),
            "IFIE_P&L_未到期_预期现金流_亏损": self._apply_reversal_if_needed(ifie_pl_cf_lc, is_reversal),
            "IFIE_P&L_未到期_非金融风险调整_非亏损": self._apply_reversal_if_needed(ifie_pl_ra_non_lc, is_reversal),
            "IFIE_P&L_未到期_非金融风险调整_亏损": self._apply_reversal_if_needed(ifie_pl_ra_lc, is_reversal),
            "IFIE_P&L_未到期_CSM": self._apply_reversal_if_needed(ifie_csm, is_reversal),
            "IFIE_OCI_未到期_预期现金流_非亏损": self._apply_reversal_if_needed(ifie_oci_cf_non_lc, is_reversal),
            "IFIE_OCI_未到期_预期现金流_亏损": self._apply_reversal_if_needed(ifie_oci_cf_lc, is_reversal),
            "IFIE_OCI_未到期_非金融风险调整_非亏损": self._apply_reversal_if_needed(ifie_oci_ra_non_lc, is_reversal),
            "IFIE_OCI_未到期_非金融风险调整_亏损": self._apply_reversal_if_needed(ifie_oci_ra_lc, is_reversal),
            "未到期责任负债_预期现金流_非亏损": self._apply_reversal_if_needed(lrc_bel_non_lc, is_reversal),
            "未到期责任负债_预期现金流_亏损": self._apply_reversal_if_needed(lrc_bel_lc, is_reversal),
            "未到期责任负债_非金融风险调整_非亏损": self._apply_reversal_if_needed(lrc_ra_non_lc, is_reversal),
            "未到期责任负债_非金融风险调整_亏损": self._apply_reversal_if_needed(lrc_ra_lc, is_reversal),
            "未到期责任负债_CSM": self._apply_reversal_if_needed(end_csm, is_reversal),
            "未到期_调整CSM的预期现金流变动": self._apply_reversal_if_needed(getattr(context, 'csm_absorbed', Decimal('0')), is_reversal),
            "未到期_调整CSM的非金融风险调整变动": 0.0,
            "未到期_调整CSM的估计变更": self._apply_reversal_if_needed(getattr(context, 'csm_absorbed', Decimal('0')), is_reversal),
            "新增合同预期现金流_保费现金流_盈利合同": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business and nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_IACF_盈利合同": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business and nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_赔付与费用现金流_盈利合同": self._apply_reversal_if_needed((getattr(context, 'init_fut_claim', Decimal('0')) + getattr(context, 'init_fut_maint', Decimal('0'))) if is_new_business and nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同非金融风险调整_盈利合同": self._apply_reversal_if_needed(getattr(context, 'init_ra', Decimal('0')) if is_new_business and nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同CSM_盈利合同": self._apply_reversal_if_needed(getattr(context, 'nb_initial_csm', Decimal('0')) if is_new_business and nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_保费现金流_亏损合同": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business and nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_IACF_亏损合同": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business and nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损": self._apply_reversal_if_needed((getattr(context, 'init_fut_claim', Decimal('0')) + getattr(context, 'init_fut_maint', Decimal('0'))) if is_new_business and nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同非金融风险调整_亏损合同_非亏损": self._apply_reversal_if_needed(getattr(context, 'init_ra', Decimal('0')) if is_new_business and nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "现金流_收到的保费": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business else Decimal('0'), is_reversal),
            "现金流_支付的获取费用": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business else Decimal('0'), is_reversal),
            "closing_bel": self._apply_reversal_if_needed(lrc_bel_total, is_reversal),
            "closing_ra": self._apply_reversal_if_needed(lrc_ra, is_reversal),
            "closing_csm": self._apply_reversal_if_needed(end_csm, is_reversal),
            "closing_lc": self._apply_reversal_if_needed(getattr(context, 'end_lc_final', getattr(context, 'end_lc_before_amort', Decimal('0'))), is_reversal),
            "closing_lic": 0.0,
        }
        return result
    
    def _run_yearly_measurement_for_policy(
        self,
        policy_state: GroupPolicyState,
        year: int,
        val_month_str: str,
        assumptions: Assumptions,
        rates_df_current: pd.DataFrame,
        is_initial_year: bool = False,
        logger: Optional[CalculationLogger] = None,
    ) -> CalculationContext:
        if logger is None:
            logger = self.logger
        if policy_state.policy_no in self.policy_results:
            init_context = self.policy_results[policy_state.policy_no].get('context')
            # 调试：检查init_context中的nb_initial_lc
            if init_context and hasattr(logger, 'log_text') and logger != _SilentLogger():
                init_nb_lc = getattr(init_context, 'nb_initial_lc', 'NOT_SET')
                logger.log_text(f"🔍 调试：init_context存在，init_context.nb_initial_lc={init_nb_lc}")
        else:
            init_context = None
            if hasattr(logger, 'log_text') and logger != _SilentLogger():
                logger.log_text(f"🔍 调试：⚠️ init_context为None，policy_no={policy_state.policy_no}不在policy_results中")
        
        context = CalculationContext()
        context.policy_no = policy_state.policy_no
        context.certi_no = getattr(policy_state, 'certi_no', None)
        context.under_write_date = policy_state.valuation_date
        context.start_date = policy_state.start_date
        context.end_date = policy_state.end_date
        context.warranty_end_date = policy_state.warranty_end_date
        context.year = year
        context.val_month_str = val_month_str
        context.eop_date = date(year, 12, 31)
        
        context.rates_df = rates_df_current
        context.rates_df_eop = rates_df_current
        
        uw_month_str = policy_state.uw_month_str
        if uw_month_str in self.rates_history:
            context.rates_df_locked = self.rates_history[uw_month_str]
        else:
            context.rates_df_locked = rates_df_current
        
        if self.dynamic_pv_mode:
            bop_month_str = date(year, 1, 1).strftime('%Y%m')
            months_needed = [bop_month_str, val_month_str] if not is_initial_year else [val_month_str]
            for month in months_needed:
                if policy_state.policy_no not in self._pv_collections or month not in self._pv_collections[policy_state.policy_no].data_by_month:
                    pv_collection, file_path = self._generate_dynamic_pv_data(
                        policy_state.policy_no,
                        getattr(policy_state, 'certi_no', None),
                        [month]
                    )
                    self._merge_pv_collection(policy_state.policy_no, pv_collection)
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
            context.pv_source_data = self._pv_collections[policy_state.policy_no]
        else:
            pv_source_data = load_pv_source_data(policy_state.policy_no)
            if pv_source_data:
                context.pv_source_data = pv_source_data
        
        # 判断是否为初始年度（新业务年度）
        is_new_business = (year == policy_state.valuation_date.year)
        
        # 在初始年度，bop_csm和bop_lc必须为0（因为这是年初余额，初始年度没有年初余额）
        # 只有在非初始年度，才从上一年的期末值获取期初值
        if is_initial_year or is_new_business:
            # 初始年度：bop_csm和bop_lc必须为0
            context.bop_csm = Decimal('0')
            context.bop_lc = Decimal('0')
            context.bop_iacf = Decimal('0')
            context.actual_premium = policy_state.written_premium
            # 关键修复：初始年度的 init_fut_claim、init_fut_maint、init_ra 应该从初始确认的 context 中获取
            # 而不是设置为 0，因为这些值用于计算 nb_lc_ifie_ratio 的分母
            if init_context:
                context.init_fut_claim = self._to_decimal(getattr(init_context, 'init_fut_claim', Decimal('0')))
                context.init_fut_maint = self._to_decimal(getattr(init_context, 'init_fut_maint', Decimal('0')))
                context.init_ra = self._to_decimal(getattr(init_context, 'init_ra', Decimal('0')))
            else:
                # 如果没有初始确认的 context，尝试从 policy_results 中获取
                init_recognition_context = self.policy_results.get(policy_state.policy_no, {}).get('context')
                if init_recognition_context:
                    context.init_fut_claim = self._to_decimal(getattr(init_recognition_context, 'init_fut_claim', Decimal('0')))
                    context.init_fut_maint = self._to_decimal(getattr(init_recognition_context, 'init_fut_maint', Decimal('0')))
                    context.init_ra = self._to_decimal(getattr(init_recognition_context, 'init_ra', Decimal('0')))
                else:
                    # 如果仍然没有，设置为 0（这种情况不应该发生）
                    context.init_fut_claim = Decimal('0')
                    context.init_fut_maint = Decimal('0')
                    context.init_ra = Decimal('0')
        elif init_context:
            # 非初始年度：从上一年的期末值获取期初值
            # 注意：这里应该从上一年的期末值（eop_csm, eop_lc, eop_iacf_balance）获取，而不是从nb_initial_csm/nb_initial_lc/actual_iacf_incurred获取
            # 因为nb_initial_csm/nb_initial_lc/actual_iacf_incurred是初始确认时的值，不应该作为期初值
            context.bop_csm = self._to_decimal(getattr(init_context, 'eop_csm', Decimal('0'))) or Decimal('0')
            context.bop_lc = self._to_decimal(getattr(init_context, 'eop_lc', Decimal('0'))) or Decimal('0')
            # 修复：bop_iacf应该从上一年的期末IACF余额获取，而不是从actual_iacf_incurred获取
            context.bop_iacf = self._to_decimal(getattr(init_context, 'eop_iacf_balance', Decimal('0'))) or Decimal('0')
            context.actual_premium = self._to_decimal(getattr(init_context, 'actual_premium', policy_state.written_premium))
            context.init_fut_claim = self._to_decimal(getattr(init_context, 'init_fut_claim', Decimal('0')))
            context.init_fut_maint = self._to_decimal(getattr(init_context, 'init_fut_maint', Decimal('0')))
            context.init_ra = self._to_decimal(getattr(init_context, 'init_ra', Decimal('0')))
        else:
            # 如果没有上一年的context，也设置为0
            context.bop_csm = Decimal('0')
            context.bop_lc = Decimal('0')
            context.bop_iacf = Decimal('0')
            context.actual_premium = policy_state.written_premium
            context.init_fut_claim = Decimal('0')
            context.init_fut_maint = Decimal('0')
            context.init_ra = Decimal('0')
        
        context.policy_data = pd.Series({
            'policy_no': policy_state.policy_no,
            'certi_no': getattr(policy_state, 'certi_no', None),
            'sum_premium_no_tax': float(policy_state.written_premium),
            'under_write_date': policy_state.valuation_date,
            'start_date': policy_state.start_date,
            'end_date': policy_state.end_date,
            'class_code': assumptions.class_code
        })
        
        from dateutil.relativedelta import relativedelta
        delta = relativedelta(policy_state.end_date, policy_state.start_date)
        context.total_months = delta.years * 12 + delta.months
        if context.total_months == 0 and (policy_state.end_date - policy_state.start_date).days > 0:
            context.total_months = 1
        
        period_start = date(year, 1, 1) if not is_initial_year else policy_state.valuation_date
        context.start_date = period_start
        context.months_passed = self._calculate_months_between(period_start, context.eop_date)
        context.is_initial_year = is_initial_year
        
        if init_context:
            context.cumulative_months_start = getattr(init_context, 'cumulative_months_end', 0)
        else:
            context.cumulative_months_start = 0
        context.cumulative_months_end = context.cumulative_months_start + (context.months_passed or 0)
        
        cohort_state = CohortState(
            cohort_id=assumptions.class_code,
            weighted_locked_rate=Decimal('0'),
            total_written_premium=Decimal('0')
        )
        cohort_state.bop_csm = context.bop_csm
        cohort_state.bop_lc = context.bop_lc
        cohort_state.bop_iacf = context.bop_iacf
        
        context.policies = [policy_state]
        is_new_business = (year == policy_state.valuation_date.year)
        context.is_new_business = is_new_business
        
        # 关键修正：如果是新业务年度，需要将初始确认的nb_initial_lc和nb_initial_csm设置到context
        # 这样_extract_policy_yearly_result才能正确提取初始确认亏损
        # 注意：init_fut_claim, init_fut_maint, init_ra 已经在上面设置了，这里不需要重复设置
        if is_new_business and init_context:
            context.nb_initial_lc = self._to_decimal(getattr(init_context, 'nb_initial_lc', Decimal('0')))
            context.nb_initial_csm = self._to_decimal(getattr(init_context, 'nb_initial_csm', Decimal('0')))
            # 调试：确保nb_initial_lc被正确设置
            if hasattr(logger, 'log_text') and logger != _SilentLogger():
                logger.log_text(f"🔍 调试：新业务年度，从init_context获取 nb_initial_lc={context.nb_initial_lc}, nb_initial_csm={context.nb_initial_csm}")
        elif is_new_business and not init_context:
            # 如果没有init_context，尝试从policy_state获取
            if hasattr(policy_state, 'initial_lc'):
                context.nb_initial_lc = self._to_decimal(policy_state.initial_lc)
                context.nb_initial_csm = self._to_decimal(getattr(policy_state, 'initial_csm', Decimal('0')))
                if hasattr(logger, 'log_text') and logger != _SilentLogger():
                    logger.log_text(f"🔍 调试：新业务年度，从policy_state获取 nb_initial_lc={context.nb_initial_lc}, nb_initial_csm={context.nb_initial_csm}")
        elif not is_new_business:
            # 非新业务年度，nb_initial_lc和nb_initial_csm应该为0（用于当前年度的计算）
            # 但为了计算NB_LC IFIE分摊比例，我们需要保留初始确认时的值
            # 关键修复：在非新业务年度，也从init_context获取初始确认时的nb_initial_lc和nb_initial_csm
            # 这样在计算NB_LC IFIE分摊比例时，可以使用初始确认时的值
            if init_context:
                # 尝试从init_context获取初始确认时的值（如果存在）
                init_nb_initial_lc = self._to_decimal(getattr(init_context, 'nb_initial_lc', Decimal('0')))
                init_nb_initial_csm = self._to_decimal(getattr(init_context, 'nb_initial_csm', Decimal('0')))
                # 如果init_context中有这些值，说明这是初始确认时的context，保留这些值用于IFIE分摊比例计算
                if init_nb_initial_lc != Decimal('0') or init_nb_initial_csm != Decimal('0'):
                    context.nb_initial_lc = init_nb_initial_lc
                    context.nb_initial_csm = init_nb_initial_csm
                else:
                    # 如果init_context中没有这些值，说明这不是初始确认时的context，设置为0
                    context.nb_initial_lc = Decimal('0')
                    context.nb_initial_csm = Decimal('0')
            else:
                # 如果没有init_context，设置为0
                context.nb_initial_lc = Decimal('0')
                context.nb_initial_csm = Decimal('0')
        
        fulfillment_cashflow_changes.run(
            context,
            logger,
            assumptions=assumptions,
            cohort_state=cohort_state,
            policies=[policy_state],
            is_new_business=is_new_business
        )
        
        # 第一部分：逐单计算CSM计息和LC分摊IFIE（不做CSM摊销和LC计量）
        from BBA_group.logic.group_csm_lc_measurement import run_per_policy_part1
        run_per_policy_part1(
            context,
            logger,
            cohort_state=cohort_state,
            policy_state=policy_state,
            assumptions=assumptions
        )
        
        # 此处只做IACF摊销，不再在组级分摊前调用 revenue.run
        # 组级分摊后会在年度汇总阶段重新按每张单的摊销比例计算CSM摊销并调用一次 revenue.run
        iacf_amortization.run(context, logger)
        ifie.run(context, logger, assumptions, cohort_state)
        lrc_closing.run_closing(context, logger)
        
        return context
    
    @staticmethod
    def _calculate_months_between(start_date: date, end_date: date) -> int:
        """计算两个日期之间的月数"""
        if not start_date or not end_date or start_date >= end_date:
            return 0
        delta = relativedelta(end_date, start_date)
        months = delta.years * 12 + delta.months
        if end_date.day >= start_date.day:
            months += 1
        return max(months, 0)
    
    def run_yearly_measurement(self, year: int, is_initial_year: bool = False):
        """执行年度计量"""
        self.logger.log_section(f"Year {year} 年度计量")
        
        eval_date = date(year, 12, 31)
        val_month_str = eval_date.strftime('%Y%m')
        
        self.logger.log_text(f"### [Step 1] 确定评估时点")
        self.logger.log_text(f"- **评估日期**: {eval_date}")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        self.logger.log_text(f"### [Step 2] 读取最新数据")
        if val_month_str not in self.rates_history:
            rates_df_current = loader.get_rates(val_month_str)
            if not rates_df_current.empty:
                self.rates_history[val_month_str] = rates_df_current
            else:
                if self.rates_history:
                    rates_df_current = list(self.rates_history.values())[-1]
                else:
                    raise ValueError(f"无法获取利率曲线数据")
        else:
            rates_df_current = self.rates_history[val_month_str]
        self.logger.log_text(f"✅ 成功获取 {val_month_str} 利率曲线 ({len(rates_df_current)} 条记录)")
        
        class_code = 'UNKNOWN'
        if self.policy_states:
            df_policy = load_policies_by_group(self.group_id, self.run_date, self.val_method)
            if not df_policy.empty:
                class_code = str(df_policy.iloc[0].get('class_code', 'UNKNOWN'))
        
        assumptions_dict = loader.get_assumptions(class_code, val_month_str, VAL_METHOD, use_db_acquisition_expense=True)
        if assumptions_dict is None:
            prev_val_month = (eval_date - relativedelta(years=1)).strftime('%Y%m')
            if prev_val_month in self.assumptions_history:
                current_assumptions = self.assumptions_history[prev_val_month]
            else:
                raise ValueError(f"无法获取精算假设数据")
        else:
            from BBA_group.config import RATIO_IACF
            acquisition_expense = assumptions_dict.get('acquisition_expense_ratio', RATIO_IACF)
            current_assumptions = Assumptions(
                val_month=val_month_str,
                class_code=class_code,
                loss_ratio=assumptions_dict['loss_ratio'],
                indirect_claims_expense_ratio=assumptions_dict['indirect_claims_expense_ratio'],
                maintenance_expense_ratio=assumptions_dict['maintenance_expense_ratio'],
                ra_ratio=assumptions_dict['ra_ratio'],
                acquisition_expense_ratio=acquisition_expense
            )
            self.assumptions_history[val_month_str] = current_assumptions
        
        from decimal import Decimal as _D
        if is_initial_year:
            self.group_cohort_state.bop_csm = _D('0')
            self.group_cohort_state.bop_lc = _D('0')
            self.group_cohort_state.new_csm = self._to_decimal(getattr(self.group_cohort_state, 'new_csm', _D('0')))
            self.group_cohort_state.new_lc = self._to_decimal(getattr(self.group_cohort_state, 'new_lc', _D('0')))
        else:
            prev_eop_csm = self._to_decimal(getattr(self.group_cohort_state, 'eop_csm', _D('0')))
            self.group_cohort_state.bop_csm = prev_eop_csm
            prev_eop_lc = self._to_decimal(getattr(self.group_cohort_state, 'eop_lc', _D('0')))
            self.group_cohort_state.bop_lc = prev_eop_lc
            nb_csm_group = _D('0')
            nb_lc_group = _D('0')
            for policy_state in self.policy_states:
                ctx_prev = self.policy_results.get(policy_state.policy_no, {}).get('context')
                if ctx_prev is None:
                    continue
                nb_initial_csm = self._to_decimal(getattr(ctx_prev, 'nb_initial_csm', _D('0')))
                nb_initial_lc = self._to_decimal(getattr(ctx_prev, 'nb_initial_lc', _D('0')))
                if nb_initial_csm > 0:
                    nb_csm_group += nb_initial_csm
                if nb_initial_lc < 0:
                    nb_lc_group += nb_initial_lc
            self.group_cohort_state.new_csm = nb_csm_group
            self.group_cohort_state.new_lc = nb_lc_group

        self.logger.log_text("### 组级CSM期初与新增（组口径）")
        self.logger.log_text(f"- IF_年初CSM余额（组级）: {self.group_cohort_state.bop_csm:,.2f}")
        self.logger.log_text(f"- 当年新增合同CSM（组级）: {self.group_cohort_state.new_csm:,.2f}")
        self.logger.log_text(f"- IF_年初LC（组级）: {self.group_cohort_state.bop_lc:,.2f}")
        self.logger.log_text(f"- 当年新增合同LC（组级）: {self.group_cohort_state.new_lc:,.2f}")

        self.logger.log_text(f"### [Step 3] 逐单计算明细")
        policy_contexts: Dict[str, CalculationContext] = {}
        
        group_if_csm_post = Decimal('0')
        group_nb_csm_post = Decimal('0')
        group_if_lc_post = Decimal('0')
        group_nb_lc_after_ifie = Decimal('0')
        
        # 修复：如果enable_logging为True，使用self.logger；否则使用静默日志器
        per_policy_logger = self.logger if self.enable_logging else _SilentLogger()
        
        for policy_state in self.policy_states:
            self.logger.log_text(f"#### 处理保单: {policy_state.policy_no}")
            
            policy_context = self._run_yearly_measurement_for_policy(
                policy_state=policy_state,
                year=year,
                val_month_str=val_month_str,
                assumptions=current_assumptions,
                rates_df_current=rates_df_current,
                is_initial_year=is_initial_year,
                logger=per_policy_logger,
            )
            policy_contexts[policy_state.policy_no] = policy_context
            
            # 判断是否为初始年度（新业务年度）
            is_new_business = self._is_new_business_year_for_context(policy_context)
            
            if_bop_csm = self._to_decimal(getattr(policy_context, 'bop_csm', Decimal('0'))) or Decimal('0')
            if_bop_lc = self._to_decimal(getattr(policy_context, 'bop_lc', Decimal('0'))) or Decimal('0')
            if_interest_csm = self._to_decimal(getattr(policy_context, 'if_interest_csm', Decimal('0'))) or Decimal('0')
            if_lc_ifie_total = self._to_decimal(getattr(policy_context, 'if_lc_ifie_total', Decimal('0'))) or Decimal('0')
            
            nb_initial_csm = self._to_decimal(getattr(policy_context, 'nb_initial_csm', Decimal('0'))) or Decimal('0')
            nb_initial_lc = self._to_decimal(getattr(policy_context, 'nb_initial_lc', Decimal('0'))) or Decimal('0')
            nb_interest_csm = self._to_decimal(getattr(policy_context, 'nb_interest_csm', Decimal('0'))) or Decimal('0')
            nb_lc_ifie_total = self._to_decimal(getattr(policy_context, 'nb_lc_ifie_total', Decimal('0'))) or Decimal('0')
            
            # 在初始年度（新业务年度），IF值应该为0（因为bop_csm和bop_lc都是0）
            # 但为了保险起见，如果is_new_business为True，强制IF值为0
            if is_new_business:
                if_csm_post = Decimal('0')
                if_lc_post = Decimal('0')
            else:
                if_csm_post = if_bop_csm + if_interest_csm
                if_lc_post = if_bop_lc + if_lc_ifie_total
            
            nb_csm_post = nb_initial_csm + nb_interest_csm
            # 使用 context 中保存的 nb_lc_after_ifie
            nb_lc_after_ifie = self._to_decimal(getattr(policy_context, 'nb_lc_after_ifie', Decimal('0'))) or Decimal('0')
            
            group_if_csm_post += if_csm_post
            group_nb_csm_post += nb_csm_post
            group_if_lc_post += if_lc_post
            group_nb_lc_after_ifie += nb_lc_after_ifie
            
            # 在初始年度，只显示NB值；非初始年度，显示IF和NB值
            if is_new_business:
                self.logger.log_text(
                    f"  - IF_计息后CSM: 0.00 (初始年度无IF), "
                    f"NB_计息后CSM: {nb_csm_post:,.2f}, "
                    f"IF_分摊后IFIE后LC: 0.00 (初始年度无IF), "
                    f"NB_分摊后IFIE后LC: {nb_lc_after_ifie:,.2f}"
                )
            else:
                self.logger.log_text(
                    f"  - IF_计息后CSM: {if_csm_post:,.2f}, "
                    f"NB_计息后CSM: {nb_csm_post:,.2f}, "
                    f"IF_分摊后IFIE后LC: {if_lc_post:,.2f}, "
                    f"NB_分摊后IFIE后LC: {nb_lc_after_ifie:,.2f}"
                )
        
        # =================================================================
        # 第二部分：合同组汇总（计算合同组CSM和合同组LC）
        # =================================================================
        self.logger.log_section("第二部分: 合同组状态判定")
        
        # 收集所有保单的context
        policy_contexts_list = list(policy_contexts.values())
        
        # 判断是否为批减单（从第一张保单的context获取）
        is_reversal = False
        if policy_contexts_list:
            is_reversal = getattr(policy_contexts_list[0], 'is_reversal_policy', False)
        
        # 调用合同组状态判定函数
        from BBA_group.logic.group_csm_lc_measurement import (
            calculate_group_status, 
            collect_policy_data,
            calculate_lc_measurement,
            calculate_csm_measurement,
            calculate_closing_balances,
            run_group_absorption_allocation
        )
        
        policy_inputs = collect_policy_data(policy_contexts_list)
        group_status = calculate_group_status(
            policy_inputs=policy_inputs,
            is_reversal=is_reversal,
            logger=self.logger
        )
        
        # 保存合同组状态供后续使用
        group_csm_status = group_status.cohort_csm
        group_lc_status = group_status.cohort_lc
        net_trial = group_status.net_trial
        
        # 更新组级状态
        self.group_cohort_state.net_trial = net_trial
        self.group_cohort_state.is_profitable = (group_csm_status > 0)
        
        # 数据验证：确保组级别CSM和LC不会同时非零（IFRS 17核心要求）
        assert (group_csm_status == Decimal('0') or group_lc_status == Decimal('0')), \
            f"❌ 错误：合同组CSM和LC不能同时非零！CSM={group_csm_status}, LC={group_lc_status}。这违反了IFRS 17准则。"
        
        # =================================================================
        # 第三部分：CSM、LC计量
        # =================================================================
        self.logger.log_section("第三部分: CSM、LC计量")
        
        # 步骤1&2：逐单计算LC分摊比例和分摊的LC
        self.logger.log_text("### [第三部分-步骤1&2] 逐单计算LC分摊比例和分摊的LC")
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            # 使用合同组LC作为判断条件
            calculate_lc_measurement(ctx, per_policy_logger, group_lc_status)
        
        # 步骤3&4：组级别计算被LC/CSM吸收的变化并分摊到各保单
        self.logger.log_text("### [第三部分-步骤3&4] 组级别计算被LC/CSM吸收的变化并分摊到各保单")
        group_result = run_group_absorption_allocation(
            contexts=policy_contexts_list,
            group_status=group_status,
            logger=self.logger,
            is_reversal=is_reversal
        )
        
        group_csm_absorbed_total = group_result.group_csm_absorbed_total
        group_lc_absorbed_total = group_result.group_lc_absorbed_total
        
        self.logger.log_text(f"- 被CSM吸收的变化_合计: {group_csm_absorbed_total:,.2f}")
        self.logger.log_text(f"- 被LC吸收的变化_合计: {group_lc_absorbed_total:,.2f}")

        # 步骤5：逐单计算CSM计量
        self.logger.log_text("### [第三部分-步骤5] 逐单计算CSM计量")
        start_of_year = date(year, 1, 1)
        
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            # 计算该保单自己的CSM摊销比例（使用覆盖单元动态比例法）
            if hasattr(ctx, 'policies') and ctx.policies:
                from BBA_group.logic.coverage_units import calculate_csm_amortization_ratio
                policy_csm_amort_ratio = calculate_csm_amortization_ratio(
                    ctx.policies,
                    ctx.eop_date,
                    start_of_year,
                    per_policy_logger,
                    is_initial_year=is_initial_year
                )
            else:
                # 如果没有policies，使用IACF摊销比例作为参考
                policy_csm_amort_ratio = getattr(ctx, 'iacf_amort_ratio', Decimal('0')) or Decimal('0')
            
            # 保存CSM摊销比例到context（供calculate_csm_measurement使用）
            ctx.csm_amort_ratio = policy_csm_amort_ratio
            
            # 调用CSM计量函数
            calculate_csm_measurement(ctx, per_policy_logger)
        
        # 步骤6：逐单计算LC计量的后续部分
        self.logger.log_text("### [第三部分-步骤6] 逐单计算LC计量的后续部分")
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            # 调用LC计量的后续部分（待调整LC余额、LC调整、期末LC余额）
            calculate_closing_balances(ctx, per_policy_logger)
        
        # 汇总组级期末CSM和LC（用于日志显示）
        group_csm_final = Decimal('0')
        group_lc_final = Decimal('0')
        group_csm_amort_amount = Decimal('0')
        
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            # 调用Revenue模块（使用已计算的字段）
            revenue.run(ctx, per_policy_logger)
            
            # 汇总组级期末CSM和LC
            group_csm_final += getattr(ctx, 'end_csm_final', Decimal('0')) or Decimal('0')
            group_lc_final += getattr(ctx, 'end_lc_final', Decimal('0')) or Decimal('0')
            group_csm_amort_amount += getattr(ctx, 'csm_amort_amount', Decimal('0')) or Decimal('0')
        
        # 更新期末状态
        self.group_cohort_state.eop_csm = group_csm_final
        self.group_cohort_state.eop_lc = group_lc_final
        
        self.logger.log_text(f"- 组级期末 CSM: {group_csm_final:,.2f}")
        self.logger.log_text(f"- 组级期末 LC: {group_lc_final:,.2f}")
        
        # 6. 组级计量汇总输出
        per_policy_results: List[Dict] = []
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            # 为了让报表中的期末值正确，我们需要把组级的期末CSM/LC分摊回单保单
            # 这里简单处理：在 _extract_policy_yearly_result 中我们取的是 context 里的值
            # 但 context 里的 end_csm/lc 是单单算的。
            # 对于汇总报表 (104)，重要的是 总和 = 组级结果。
            # 我们可以添加特殊的调整项字段到结果中，或者在报表生成时处理差异。
            # 为了数据流完整，我们在这里计算"调整项"，并在 yearly_result 中体现
            res = self._extract_policy_yearly_result(year, ctx)
            per_policy_results.append(res)
            
            # 保存每张保单的年度结果（用于生成逐单报表）
            if policy_state.policy_no not in self.policy_yearly_results:
                self.policy_yearly_results[policy_state.policy_no] = []
            self.policy_yearly_results[policy_state.policy_no].append(res)
            
            # 关键修正：更新保存context到policy_results，确保下一年的init_context能获取到正确的期末值
            # 包括eop_csm, eop_lc, eop_iacf_balance等期末余额
            # 注意：必须显式设置eop_lc和eop_csm，因为它们在后续年度会作为bop_lc和bop_csm使用
            ctx.eop_csm = getattr(ctx, 'end_csm_final', Decimal('0')) or Decimal('0')
            ctx.eop_lc = getattr(ctx, 'end_lc_final', Decimal('0')) or Decimal('0')
            ctx.eop_iacf_balance = getattr(ctx, 'eop_iacf_balance', Decimal('0')) or Decimal('0')
            
            if policy_state.policy_no not in self.policy_results:
                self.policy_results[policy_state.policy_no] = {}
            self.policy_results[policy_state.policy_no]['context'] = ctx
        
        yearly_result: Dict[str, float] = {}
        for res in per_policy_results:
            for field_name, value in res.items():
                if field_name == "policy_no":
                    yearly_result[field_name] = self.group_id
                elif field_name == "certi_no":
                    yearly_result[field_name] = ""
                elif field_name == "year":
                    yearly_result[field_name] = year
                else:
                    prev = yearly_result.get(field_name, 0.0)
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        numeric = 0.0
                    yearly_result[field_name] = prev + numeric
        
        # 关键修正：用组级计算结果覆盖汇总值中的 CSM/LC 相关字段
        # 这是为了确保报表（103/104）展示的是 Netting 后的结果
        yearly_result["未到期_调整CSM的估计变更"] = float(group_csm_absorbed_total) # 复用此字段存放吸收额
        yearly_result["保险合同收入_摊销的CSM"] = float(group_csm_amort_amount) # 注意符号，这里通常是负数
        yearly_result["closing_csm"] = float(group_csm_final)
        yearly_result["closing_lc"] = float(group_lc_status)
        
        # 另外，LC 的吸收变化需要反映在 "亏损合同损益_不调整CSM的预期现金流变动" 或类似字段中
        # 或者我们增加特定的 key 供报表使用
        yearly_result["group_lc_absorbed"] = float(group_lc_absorbed_total)
        yearly_result["group_csm_absorbed"] = float(group_csm_absorbed_total)
        
        # 重要修正：以下字段应该只包含mock2（有新增CSM的保单）的值，而不是所有保单的汇总
        # 1. "当期初始确认的保险合同影响-合同服务边际" = 新增合同CSM_盈利合同（只包含mock2）
        # 2. "保险合同金融变动额(17)-合同服务边际" = IFIE_P&L_未到期_CSM（只包含mock2）
        # 筛选mock2保单：有新增CSM的保单（nb_initial_csm > 0 且是新业务年度）
        mock2_nb_csm_total = Decimal('0')
        mock2_ifie_csm_total = Decimal('0')
        
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            # 判断是否为mock2保单（有新增CSM的保单）
            is_new_business = self._is_new_business_year_for_context(ctx)
            nb_initial_csm = self._to_decimal(getattr(ctx, 'nb_initial_csm', Decimal('0'))) or Decimal('0')
            is_mock2 = is_new_business and nb_initial_csm > 0
            
            if is_mock2:
                # 提取mock2保单的这两个字段值
                res = self._extract_policy_yearly_result(year, ctx)
                mock2_nb_csm = self._to_decimal(res.get("新增合同CSM_盈利合同", 0.0))
                mock2_ifie_csm = self._to_decimal(res.get("IFIE_P&L_未到期_CSM", 0.0))
                
                mock2_nb_csm_total += mock2_nb_csm
                mock2_ifie_csm_total += mock2_ifie_csm
        
        # 覆盖汇总值，确保报表只显示mock2的值
        yearly_result["新增合同CSM_盈利合同"] = float(mock2_nb_csm_total)
        yearly_result["IFIE_P&L_未到期_CSM"] = float(mock2_ifie_csm_total)
        
        self.logger.log_text(f"- Mock2保单筛选：有新增CSM的保单（nb_initial_csm > 0 且是新业务年度）")
        self.logger.log_text(f"- Mock2新增合同CSM_盈利合同: {mock2_nb_csm_total:,.2f}")
        self.logger.log_text(f"- Mock2 IFIE_P&L_未到期_CSM: {mock2_ifie_csm_total:,.2f}")
        
        # 重要修正：以下字段应该只包含mock2（有新增CSM的保单）的值，而不是所有保单的汇总
        # 1. "当期初始确认的保险合同影响-合同服务边际" = 新增合同CSM_盈利合同（只包含mock2）
        # 2. "保险合同金融变动额(17)-合同服务边际" = IFIE_P&L_未到期_CSM（只包含mock2）
        # 筛选mock2保单：有新增CSM的保单（nb_initial_csm > 0 且是新业务年度）
        mock2_nb_csm_total = Decimal('0')
        mock2_ifie_csm_total = Decimal('0')
        mock2_count = 0
        
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            
            # 判断是否为mock2保单（有新增CSM的保单）
            is_new_business = self._is_new_business_year_for_context(ctx)
            nb_initial_csm = self._to_decimal(getattr(ctx, 'nb_initial_csm', Decimal('0'))) or Decimal('0')
            is_mock2 = is_new_business and nb_initial_csm > 0
            
            if is_mock2:
                mock2_count += 1
                # 提取mock2保单的这两个字段值
                res = self._extract_policy_yearly_result(year, ctx)
                mock2_nb_csm = self._to_decimal(res.get("新增合同CSM_盈利合同", 0.0))
                mock2_ifie_csm = self._to_decimal(res.get("IFIE_P&L_未到期_CSM", 0.0))
                
                mock2_nb_csm_total += mock2_nb_csm
                mock2_ifie_csm_total += mock2_ifie_csm
        
        # 覆盖汇总值，确保报表只显示mock2的值
        yearly_result["新增合同CSM_盈利合同"] = float(mock2_nb_csm_total)
        yearly_result["IFIE_P&L_未到期_CSM"] = float(mock2_ifie_csm_total)
        
        self.logger.log_text(f"- Mock2保单筛选：有新增CSM的保单（nb_initial_csm > 0 且是新业务年度）")
        self.logger.log_text(f"- Mock2保单数量: {mock2_count}")
        self.logger.log_text(f"- Mock2新增合同CSM_盈利合同: {mock2_nb_csm_total:,.2f}")
        self.logger.log_text(f"- Mock2 IFIE_P&L_未到期_CSM: {mock2_ifie_csm_total:,.2f}")

        # 按照用户要求的顺序输出详细日志
        self._log_detailed_yearly_results(
            year=year,
            policy_contexts=policy_contexts,
            group_result=group_result,
            group_csm_status=group_csm_status,
            group_lc_status=group_lc_status,
            group_csm_absorbed_total=group_csm_absorbed_total,
            group_lc_absorbed_total=group_lc_absorbed_total,
            group_csm_final=group_csm_final,
            group_lc_final=group_lc_final,
            group_csm_amort_amount=group_csm_amort_amount,
            current_assumptions=current_assumptions
        )
        
        self.logger.log_section("Part 6: 年度结果汇总（组级关键指标）")
        for field_name, value in yearly_result.items():
            self.logger.log_text(f"- {field_name}: {value}")
        
        return yearly_result
    
    def run(self) -> List[Dict]:
        """执行完整的组维度生命周期仿真"""
        yearly_results: List[Dict] = []
        try:
            initial_assumptions, initial_rates, class_code = self.initialize()
            self.run_initial_recognition(initial_assumptions, initial_rates)
            
            if not self.policy_states:
                raise ValueError("组内没有有效保单")
            
            start_year = min(p.valuation_date.year for p in self.policy_states if p.valuation_date)
            end_year = max(p.end_date.year for p in self.policy_states)
            
            max_year = 2024
            if end_year > max_year:
                self.logger.log_text(f"⚠️  **警告**: 保单终止日期最晚为 {end_year}年，但数据库仅配置到 {max_year}年")
                self.logger.log_text(f"   将仅计算到 {max_year}年底")
                end_year = max_year
            
            self.logger.log_section("开始组维度生命周期仿真")
            self.logger.log_text(f"- **起始年度**: {start_year}")
            self.logger.log_text(f"- **终止年度**: {end_year}")
            
            for year in range(start_year, end_year + 1):
                result = self.run_yearly_measurement(year, is_initial_year=(year == start_year))
                yearly_results.append(result)
            
            self.logger.log_section("组维度生命周期仿真完成 - 最终汇总")
            
            if self.enable_reports:
                try:
                    from BBA_group.utils.generate_ifrs17_104_report import main as generate_report_104
                    from BBA_group.utils.generate_ifrs17_103_report import main as generate_report_103
                    
                    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
                    os.makedirs(logs_dir, exist_ok=True)
                    
                    # 1. 生成组级报表
                    html_report_path_104 = os.path.join(logs_dir, f"ifrs17_104_report_group_{self.group_id}.html")
                    html_report_path_104 = generate_report_104(
                        yearly_results=yearly_results,
                        init_context=None,
                        output_html_path=html_report_path_104,
                        policy_no=self.group_id,
                        certi_no=None
                    )
                    if html_report_path_104:
                        self.logger.log_text(f"\n✅ IFRS 17 104报表（组级）已生成: {html_report_path_104}")
                        print(f"\n[SUCCESS] IFRS 17 104报表（组级）已生成: {html_report_path_104}")
                    
                    html_report_path_103 = os.path.join(logs_dir, f"ifrs17_103_report_group_{self.group_id}.html")
                    html_report_path_103 = generate_report_103(
                        yearly_results=yearly_results,
                        output_html_path=html_report_path_103,
                        policy_no=self.group_id,
                        certi_no=None
                    )
                    if html_report_path_103:
                        self.logger.log_text(f"\n✅ IFRS 17 103报表（组级）已生成: {html_report_path_103}")
                        print(f"\n[SUCCESS] IFRS 17 103报表（组级）已生成: {html_report_path_103}")
                    
                    # 2. 为组内每张保单生成报表
                    self.logger.log_text(f"\n### 生成逐单报表")
                    for policy_state in self.policy_states:
                        policy_no = policy_state.policy_no
                        certi_no = getattr(policy_state, 'certi_no', None)
                        
                        if policy_no not in self.policy_yearly_results:
                            self.logger.log_text(f"⚠️  保单 {policy_no} 没有年度结果，跳过报表生成")
                            continue
                        
                        policy_yearly_results = self.policy_yearly_results[policy_no]
                        
                        try:
                            # 生成104报表
                            certi_part = f"_{certi_no}" if certi_no else ""
                            html_report_path_104_policy = os.path.join(
                                logs_dir, 
                                f"ifrs17_104_report_{policy_no}{certi_part}_group.html"
                            )
                            html_report_path_104_policy = generate_report_104(
                                yearly_results=policy_yearly_results,
                                init_context=self.policy_results.get(policy_no, {}).get('context'),
                                output_html_path=html_report_path_104_policy,
                                policy_no=policy_no,
                                certi_no=certi_no
                            )
                            if html_report_path_104_policy:
                                self.logger.log_text(f"  ✅ 保单 {policy_no} 104报表已生成: {html_report_path_104_policy}")
                                print(f"[SUCCESS] 保单 {policy_no} 104报表已生成: {html_report_path_104_policy}")
                            
                            # 生成103报表
                            html_report_path_103_policy = os.path.join(
                                logs_dir, 
                                f"ifrs17_103_report_{policy_no}{certi_part}_group.html"
                            )
                            html_report_path_103_policy = generate_report_103(
                                yearly_results=policy_yearly_results,
                                init_context=self.policy_results.get(policy_no, {}).get('context'),
                                output_html_path=html_report_path_103_policy,
                                policy_no=policy_no,
                                certi_no=certi_no
                            )
                            if html_report_path_103_policy:
                                self.logger.log_text(f"  ✅ 保单 {policy_no} 103报表已生成: {html_report_path_103_policy}")
                                print(f"[SUCCESS] 保单 {policy_no} 103报表已生成: {html_report_path_103_policy}")
                                
                        except Exception as policy_report_error:
                            error_msg = f"  ⚠️  保单 {policy_no} 报表生成失败: {policy_report_error}"
                            print(error_msg)
                            self.logger.log_text(error_msg)
                            import traceback
                            traceback.print_exc()
                    
                    self.logger.log_text(f"\n✅ 组维度生命周期仿真完成")
                    self.logger.log_text(f"   组ID: {self.group_id}")
                    self.logger.log_text(f"   组内保单数: {len(self.policy_states)}")
                    self.logger.log_text(f"   已生成逐单报表数: {len(self.policy_yearly_results)}")
                    
                except Exception as report_error:
                    error_msg = f"\n⚠️  警告: 生成IFRS 17报表时发生错误: {report_error}"
                    print(error_msg)
                    self.logger.log_text(error_msg)
                    import traceback
                    traceback.print_exc()
            
        except Exception as e:
            error_msg = f"\n❌ 仿真过程中发生错误: {e}"
            print(error_msg)
            self.logger.log_text(error_msg)
            import traceback
            traceback.print_exc()
            if self.logger.md_file:
                self.logger.md_file.write(f"\n```\n{traceback.format_exc()}\n```\n")
            raise
        finally:
            self.logger.close()
        
        return yearly_results


def main():
    """主函数"""
    import sys
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    # 从config中获取组ID
    group_id = GROUP_ID
    
    # 生成日志文件名
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    md_log_file = os.path.join(logs_dir, f"group_lifecycle_simulation_log_{group_id}.md")
    
    print(f"[INFO] 使用组ID: {group_id}")
    print(f"[INFO] 日志将保存到: {md_log_file}\n")
    
    simulator = GroupLifecycleSimulator(
        group_id=group_id,
        md_log_file=md_log_file,
        enable_logging=True,
        dynamic_pv_mode=True
    )
    try:
        yearly_results = simulator.run()
        print(f"\n[SUCCESS] 日志已保存到: {md_log_file}")
        print(f"[SUCCESS] 组维度仿真完成，共计算 {len(yearly_results)} 年")
    finally:
        simulator.cleanup()
        print("[INFO] 资源已清理（包括数据库连接池）")


if __name__ == "__main__":
    main()