"""
IFRS 17 BBA 组维度生命周期仿真器 (Group Lifecycle Simulator)

本程序实现按合同组（group_id）维度进行全生命周期计量仿真。
核心特性：
1. 先逐单计算明细（初始确认、CSM计息、LC分摊IFIE）
2. 再按组汇总，判断合同组是CSM还是LC状态
3. 基于CSM权重的组级利率曲线构建
4. 基于保费权重的组级覆盖单元计算
5. 生成组级别的103、104报表

数据流向：
组内所有保单 -> 逐单初始确认 -> 逐年循环：
    - 逐单计算CSM计息、LC分摊IFIE
    - 按组汇总CSM和LC
    - 构建/更新组级利率曲线
    - 计算组级覆盖单元
    - 组级计量（摊销、IFIE等）
    - 期末结转
"""

import pandas as pd
from decimal import Decimal
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Tuple, List
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from contextlib import redirect_stdout, redirect_stderr
import io

from BBA_group.config import VAL_METHOD
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
    csm_lc_measurement,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)
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
        
        Returns:
            Tuple[Assumptions, pd.DataFrame, str]: (初始精算假设, 初始利率曲线, 险类代码)
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
        
        # 4. 读取初始精算假设和利率曲线（使用第一张保单的签单月份）
        if not self.policy_states:
            raise ValueError("组内没有有效保单")
        
        first_policy = self.policy_states[0]
        val_month_str = first_policy.valuation_date.strftime('%Y%m') if first_policy.valuation_date else '202401'
        
        self.logger.log_text(f"### [Step 0.1] 读取初始精算假设和利率曲线")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        # 读取精算假设
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
        
        # 读取利率曲线
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
        """
        对单张保单执行初始确认
        
        Returns:
            CalculationContext: 该保单的计算上下文
        """
        # 创建计算上下文
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
        
        # 确保PV数据
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
        
        # 创建单张保单的CohortState（用于初始确认）
        cohort_state = CohortState(
            cohort_id=assumptions.class_code,
            weighted_locked_rate=Decimal('0'),
            total_written_premium=Decimal('0')
        )
        
        # 执行初始确认
        # 为避免在组级日志中重复输出大量逐单推导过程，这里使用静默日志记录器，
        # 仅在本文件中记录简要汇总值（初始 CSM / LC 等）。
        silent_logger = _SilentLogger()
        initial_recognition.run(context, silent_logger, assumptions, cohort_state)
        
        # 更新保单状态
        policy_state.initial_csm = context.nb_initial_csm or Decimal('0')
        policy_state.initial_lc = context.nb_initial_lc or Decimal('0')
        policy_state.initial_csm_for_weight = policy_state.initial_csm  # 用于利率曲线权重
        
        # 保存单张保单的初始确认结果
        self.policy_results[policy_state.policy_no] = {
            'initial_csm': policy_state.initial_csm,
            'initial_lc': policy_state.initial_lc,
            'context': context
        }
        
        return context
    
    def run_initial_recognition(self, assumptions: Assumptions, rates_df: pd.DataFrame):
        """
        对组内所有保单执行初始确认
        
        对应文档：第1-3节
        """
        self.logger.log_section(f"Part 1: 组内所有保单初始确认 (Initial Recognition)")
        
        # 逐单初始确认
        for policy_state in self.policy_states:
            self.logger.log_text(f"### 处理保单: {policy_state.policy_no}")
            
            # 获取该保单签单月份的利率曲线
            uw_month_str = policy_state.uw_month_str
            if uw_month_str not in self.rates_history:
                rates_df_policy = loader.get_rates(uw_month_str)
                if not rates_df_policy.empty:
                    self.rates_history[uw_month_str] = rates_df_policy
                else:
                    rates_df_policy = rates_df  # 使用默认利率曲线
            else:
                rates_df_policy = self.rates_history[uw_month_str]
            
            # 执行初始确认
            context = self.run_initial_recognition_for_policy(
                policy_state,
                assumptions,
                rates_df_policy
            )

            # 在组级日志中仅输出该保单初始确认的关键结果（简化版）
            self.logger.log_text(
                f"- 初始CSM: {policy_state.initial_csm:,.2f}, "
                f"初始LC: {policy_state.initial_lc:,.2f}"
            )
        
        # 汇总组级CSM和LC（仅用于构建组级利率曲线，不在此阶段输出“合同组CSM/LC”判定）
        group_csm_total = sum(p.initial_csm for p in self.policy_states)
        group_lc_total = sum(p.initial_lc for p in self.policy_states)
        self.group_cohort_state.new_csm = group_csm_total
        self.group_cohort_state.new_lc = group_lc_total
        
        # 构建组级利率曲线（基于CSM权重）
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
        """
        计算组级CSM摊销比例（基于保费权重）
        
        公式：
        Ratio = Σ(保费_i × 当期服务量_i) / Σ(保费_i × (当期服务量_i + 未来服务量_i))
        
        Args:
            valuation_date: 评估日期
            start_of_year: 年初日期
            is_initial_year: 是否为初始确认年度
            
        Returns:
            Decimal: 组级CSM摊销比例
        """
        numerator = Decimal('0')  # Σ(保费_i × 当期服务量_i)
        denominator = Decimal('0')  # Σ(保费_i × (当期服务量_i + 未来服务量_i))
        
        # 为了更清晰展示计算过程，这里对每张保单单独计算并记录：保费、当期服务天数、未来服务天数、当期/未来覆盖单元
        self.logger.log_text("#### 组级CSM摊销比例 - 明细分解")
        self.logger.log_text(f"- 评估日期: {valuation_date}, 年初: {start_of_year}, 是否初始年度: {is_initial_year}")
        
        for policy in self.policy_states:
            policy_no = getattr(policy, "policy_no", "")
            premium = policy.written_premium
            
            # 1. 过滤不在当年服务期内的保单
            if policy.end_date < start_of_year or policy.start_date > valuation_date:
                self.logger.log_text(
                    f"- 保单 {policy_no}: 不在当年服务期内（start_date={policy.start_date}, end_date={policy.end_date}），跳过"
                )
                continue
            
            # 2. 确定质保结束日及是否仍在质保期
            warranty_end = getattr(policy, 'warranty_end_date', None) or policy.start_date
            is_in_warranty = valuation_date < warranty_end
            
            # 3. 计算当期服务区间 [service_start, service_end]
            if is_initial_year:
                service_start = warranty_end
            else:
                service_start = max(warranty_end, start_of_year)
            service_end = min(policy.end_date, valuation_date)
            
            if is_in_warranty or service_end < service_start:
                current_service_days = 0
            else:
                current_service_days = (service_end - service_start).days + 1
            
            # 4. 计算未来服务天数
            if policy.end_date <= valuation_date:
                future_service_days = 0
            else:
                if is_in_warranty:
                    future_service_days = (policy.end_date - warranty_end).days
                else:
                    future_service_days = (policy.end_date - valuation_date).days
            
            if future_service_days < 0:
                future_service_days = 0
            
            # 5. 使用保费作为权重，将“服务天数”转换为“覆盖单元”
            current_cu = premium * Decimal(current_service_days)
            future_cu = premium * Decimal(future_service_days)
            
            numerator += current_cu
            denominator += current_cu + future_cu
            
            # 6. 逐单记录计算过程
            self.logger.log_text(
                f"- 保单 {policy_no}: 保费={premium:,.2f}, "
                f"当期服务天数={current_service_days}, 未来服务天数={future_service_days}, "
                f"当期覆盖单元(保费×天数)={current_cu:,.2f}, 未来覆盖单元={future_cu:,.2f}"
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
                "分子（当期）Σ(保费×当期服务天数)": numerator,
                "分母（当期+未来）Σ(保费×(当期+未来)服务天数)": denominator
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
        """
        组级汇总阶段沿用单张口径：PV与计量全程按原始符号运行，汇总时直接输出原值。
        保留该方法接口，仅为与单张的_extract_yearly_result保持一致。
        """
        _ = is_reversal  # 未使用，仅为兼容接口
        return self._to_number(value)
    
    def _derive_gross_from_net(self, net_value: Decimal, lc_ratio: Decimal) -> Decimal:
        """从净额和亏损比例反推含亏损总额（与单张脚本口径一致）"""
        denominator = Decimal('1') - lc_ratio
        if denominator == 0:
            return net_value
        return net_value / denominator
    
    def _is_new_business_year_for_context(self, context: CalculationContext) -> bool:
        """判断context对应年度是否为签单年（与单张脚本口径一致）"""
        if hasattr(context, 'is_new_business') and context.is_new_business is not None:
            return context.is_new_business
        if getattr(context, 'under_write_date', None) and getattr(context, 'year', None):
            return context.year == context.under_write_date.year
        return False
    
    def _extract_policy_yearly_result(self, year: int, context: CalculationContext) -> Dict:
        """
        从单张保单的context中提取年度结果（复制自单张脚本的_extract_yearly_result逻辑），
        供组级按字段求和汇总。
        """
        lc_ratio = self._to_decimal(getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'))
        
        # 1. 赔付与费用收入口径（含亏损 + 亏损分摊）
        claims_lc_alloc = self._to_decimal(getattr(context, 'revenue_claims_expenses_lc_alloc', None))
        if claims_lc_alloc is None:
            claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
            claims_gross = self._derive_gross_from_net(claims_net, lc_ratio)
            claims_lc_alloc = claims_gross - claims_net
        else:
            claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
            claims_gross = claims_net + claims_lc_alloc
        
        ra_net = self._to_decimal(getattr(context, 'ra_release_net', Decimal('0')))
        ra_gross = self._to_decimal(getattr(context, 'ra_release_gross', None)) or self._derive_gross_from_net(ra_net, lc_ratio)
        ra_lc_alloc = self._to_decimal(getattr(context, 'ra_release_lc_alloc', None))
        if ra_lc_alloc == Decimal('0') and ra_gross != ra_net:
            ra_lc_alloc = ra_gross - ra_net
        
        # 2. LC分摊 & 被LC吸收的变化（预期现金流 / RA）
        allocated_lc_cf = self._to_decimal(getattr(context, 'allocated_lc_cf', Decimal('0')))
        allocated_lc_ra = self._to_decimal(getattr(context, 'allocated_lc_ra', Decimal('0')))
        allocated_lc_exp_adj_cf = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_cf', Decimal('0')))
        allocated_lc_exp_adj_ra = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_ra', Decimal('0')))
        
        # 3. IACF 摊销
        iacf_amort_expense = self._to_decimal(getattr(context, 'iacf_amort_amount', Decimal('0')))
        
        # 4. 新增LC（签单年）
        nb_initial_lc = self._to_decimal(context.nb_initial_lc if self._is_new_business_year_for_context(context) else Decimal('0'))
        nb_initial_lc_cf = self._to_decimal(getattr(context, 'nb_initial_lc_cf', Decimal('0')) if self._is_new_business_year_for_context(context) else Decimal('0'))
        nb_initial_lc_ra = self._to_decimal(getattr(context, 'nb_initial_lc_ra', Decimal('0')) if self._is_new_business_year_for_context(context) else Decimal('0'))
        
        # 5. IFIE_P&L
        ifie_pl_cf_non_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_non_lc', Decimal('0')))
        ifie_pl_cf_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_lc', Decimal('0')))
        ifie_pl_ra_non_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_non_lc', Decimal('0')))
        ifie_pl_ra_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_lc', Decimal('0')))
        ifie_pl_cf = ifie_pl_cf_non_lc + ifie_pl_cf_lc
        ifie_pl_ra = ifie_pl_ra_non_lc + ifie_pl_ra_lc
        
        # 6. IFIE_CSM
        is_new_business = self._is_new_business_year_for_context(context)
        ifie_csm = -self._to_decimal(
            getattr(context, 'nb_interest_csm', Decimal('0')) if is_new_business
            else getattr(context, 'if_interest_csm', Decimal('0'))
        )
        
        # 7. IFIE_OCI
        ifie_oci_cf_non_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_non_lc', Decimal('0')))
        ifie_oci_cf_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_lc', Decimal('0')))
        ifie_oci_ra_non_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_non_lc', Decimal('0')))
        ifie_oci_ra_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_lc', Decimal('0')))
        
        # 8. 未到期责任负债（BEL / RA / CSM）
        lrc_bel_total = self._to_decimal(getattr(context, 'lrc_bel_total', None))
        if lrc_bel_total is None:
            lrc_bel_total = self._to_decimal(getattr(context, 'pv_eop_claims_current', Decimal('0'))) + \
                self._to_decimal(getattr(context, 'pv_eop_maint_current', Decimal('0')))
        lrc_ra = self._to_decimal(getattr(context, 'lrc_ra', Decimal('0')))
        lrc_total = self._to_decimal(getattr(context, 'lrc_total', None))
        if lrc_total is None:
            end_csm = self._to_decimal(getattr(context, 'end_csm_final', getattr(context, 'end_csm_before_amort', Decimal('0'))))
            lrc_total = lrc_bel_total + lrc_ra + end_csm
        else:
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
        """
        对单张保单执行完整的年度计量
        
        参考BBA_group/scripts/run_lifecycle_simulation.py的run_yearly_measurement方法。
        允许通过传入自定义 logger（例如 _SilentLogger）控制单张保单的日志输出，
        便于在组级日志中只展示汇总信息。
        """
        if logger is None:
            logger = self.logger
        # 获取该保单的初始确认context（如果存在）
        if policy_state.policy_no in self.policy_results:
            init_context = self.policy_results[policy_state.policy_no].get('context')
        else:
            init_context = None
        
        # 创建年度计算上下文
        context = CalculationContext()
        
        # 设置基础信息
        context.policy_no = policy_state.policy_no
        context.certi_no = getattr(policy_state, 'certi_no', None)
        context.under_write_date = policy_state.valuation_date
        context.start_date = policy_state.start_date
        context.end_date = policy_state.end_date
        context.warranty_end_date = policy_state.warranty_end_date
        context.year = year
        context.val_month_str = val_month_str
        context.eop_date = date(year, 12, 31)
        
        # 设置利率曲线
        context.rates_df = rates_df_current
        context.rates_df_eop = rates_df_current
        
        # 获取该保单签单月份的锁定利率曲线
        uw_month_str = policy_state.uw_month_str
        if uw_month_str in self.rates_history:
            context.rates_df_locked = self.rates_history[uw_month_str]
        else:
            context.rates_df_locked = rates_df_current
        
        # 确保PV数据
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
        
        # 设置期初余额（从上一年的结果或初始确认结果）
        if init_context:
            # 从初始确认结果获取
            context.bop_csm = self._to_decimal(getattr(init_context, 'nb_initial_csm', Decimal('0')))
            context.bop_lc = self._to_decimal(getattr(init_context, 'nb_initial_lc', Decimal('0')))
            context.bop_iacf = self._to_decimal(getattr(init_context, 'actual_iacf_incurred', Decimal('0')))
            # 从初始确认获取其他必要字段
            context.actual_premium = self._to_decimal(getattr(init_context, 'actual_premium', policy_state.written_premium))
            context.init_fut_claim = self._to_decimal(getattr(init_context, 'init_fut_claim', Decimal('0')))
            context.init_fut_maint = self._to_decimal(getattr(init_context, 'init_fut_maint', Decimal('0')))
            context.init_ra = self._to_decimal(getattr(init_context, 'init_ra', Decimal('0')))
        else:
            context.bop_csm = Decimal('0')
            context.bop_lc = Decimal('0')
            context.bop_iacf = Decimal('0')
            context.actual_premium = policy_state.written_premium
            context.init_fut_claim = Decimal('0')
            context.init_fut_maint = Decimal('0')
            context.init_ra = Decimal('0')
        
        # 设置保单数据
        context.policy_data = pd.Series({
            'policy_no': policy_state.policy_no,
            'certi_no': getattr(policy_state, 'certi_no', None),
            'sum_premium_no_tax': float(policy_state.written_premium),
            'under_write_date': policy_state.valuation_date,
            'start_date': policy_state.start_date,
            'end_date': policy_state.end_date,
            'class_code': assumptions.class_code
        })
        
        # 计算总月数和服务月份
        from dateutil.relativedelta import relativedelta
        delta = relativedelta(policy_state.end_date, policy_state.start_date)
        context.total_months = delta.years * 12 + delta.months
        if context.total_months == 0 and (policy_state.end_date - policy_state.start_date).days > 0:
            context.total_months = 1
        
        # 计算服务月份
        period_start = date(year, 1, 1) if not is_initial_year else policy_state.valuation_date
        context.start_date = period_start
        context.months_passed = self._calculate_months_between(period_start, context.eop_date)
        context.is_initial_year = is_initial_year
        
        # 设置累计月份（用于锁定曲线偏移）
        if init_context:
            context.cumulative_months_start = getattr(init_context, 'cumulative_months_end', 0)
        else:
            context.cumulative_months_start = 0
        context.cumulative_months_end = context.cumulative_months_start + (context.months_passed or 0)
        
        # 创建单张保单的CohortState（用于计量）
        cohort_state = CohortState(
            cohort_id=assumptions.class_code,
            weighted_locked_rate=Decimal('0'),
            total_written_premium=Decimal('0')
        )
        cohort_state.bop_csm = context.bop_csm
        cohort_state.bop_lc = context.bop_lc
        cohort_state.bop_iacf = context.bop_iacf
        
        # 设置保单列表（用于覆盖单元计算）
        context.policies = [policy_state]
        
        # 判断是否为新业务
        is_new_business = (year == policy_state.valuation_date.year)
        context.is_new_business = is_new_business
        
        # 执行完整的计量流水线（与单张保单仿真一致）
        # 5.1 履约现金流变化
        fulfillment_cashflow_changes.run(
            context,
            logger,
            assumptions=assumptions,
            cohort_state=cohort_state,
            policies=[policy_state],
            is_new_business=is_new_business
        )
        
        # 5.2 CSM/LC计量
        csm_lc_measurement.run(
            context,
            logger,
            cohort_state=cohort_state,
            policy_state=policy_state,
            policies=[policy_state],
            assumptions=assumptions
        )
        
        # 5.3 IACF摊销
        iacf_amortization.run(context, logger)
        
        # 5.4 保险合同收入
        revenue.run(context, logger)
        
        # 5.5 IFIE
        ifie.run(context, logger, assumptions, cohort_state)
        
        # 5.6 期末负债
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
        """
        执行年度计量
        
        对应文档：第4-14节
        
        Args:
            year: 评估年度
            is_initial_year: 是否为初始确认所在年度
        """
        self.logger.log_section(f"Year {year} 年度计量")
        
        # 1. 确定评估日期
        eval_date = date(year, 12, 31)
        val_month_str = eval_date.strftime('%Y%m')
        
        self.logger.log_text(f"### [Step 1] 确定评估时点")
        self.logger.log_text(f"- **评估日期**: {eval_date}")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        # 2. 读取最新数据
        self.logger.log_text(f"### [Step 2] 读取最新数据")
        
        # 2.1 读取最新利率曲线
        if val_month_str not in self.rates_history:
            rates_df_current = loader.get_rates(val_month_str)
            if not rates_df_current.empty:
                self.rates_history[val_month_str] = rates_df_current
            else:
                # 使用最近的利率曲线
                if self.rates_history:
                    rates_df_current = list(self.rates_history.values())[-1]
                else:
                    raise ValueError(f"无法获取利率曲线数据")
        else:
            rates_df_current = self.rates_history[val_month_str]
        
        self.logger.log_text(f"✅ 成功获取 {val_month_str} 利率曲线 ({len(rates_df_current)} 条记录)")
        
        # 2.2 读取最新精算假设
        class_code = 'UNKNOWN'
        if self.policy_states:
            # 从第一张保单获取class_code
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
        
        # 2.3 组级期初/新增 CSM、LC（供组维度口径使用）
        # 说明：
        # - IF_年初CSM余额（组级） = 上一年度合同组CSM期末余额（上一年的GroupCohortState.eop_csm）
        # - IF_年初LC（组级）     = 上一年度合同组LC期末余额（上一年的GroupCohortState.eop_lc）
        # - 当年新增合同CSM（组级） = 逐单新增CSM的合计（首年即初始确认CSM合计）
        # - 当年新增合同LC（组级） = 逐单新增LC的合计
        from decimal import Decimal as _D
        if is_initial_year:
            # 首年：年初CSM视为0，当年新增=初始确认汇总（在run_initial_recognition中已写入new_csm）
            self.group_cohort_state.bop_csm = _D('0')
            self.group_cohort_state.bop_lc = _D('0')
            # new_csm 已在 run_initial_recognition 中设为组内初始CSM合计，这里仅确保为Decimal类型
            self.group_cohort_state.new_csm = self._to_decimal(getattr(self.group_cohort_state, 'new_csm', _D('0')))
            # new_lc 同理，使用初始确认阶段汇总的组级LC（通常为负值）
            self.group_cohort_state.new_lc = self._to_decimal(getattr(self.group_cohort_state, 'new_lc', _D('0')))
        else:
            # 后续年度：年初CSM取上一年期末合同组CSM余额
            prev_eop_csm = self._to_decimal(getattr(self.group_cohort_state, 'eop_csm', _D('0')))
            self.group_cohort_state.bop_csm = prev_eop_csm
            # 年初LC取上一年期末合同组LC余额（组级IF_年初LC）
            prev_eop_lc = self._to_decimal(getattr(self.group_cohort_state, 'eop_lc', _D('0')))
            self.group_cohort_state.bop_lc = prev_eop_lc
            # 当前年度是否存在新增业务，取逐单nb_initial_csm汇总（目前大多数情况下为0）
            nb_csm_group = _D('0')
            nb_lc_group = _D('0')
            for policy_state in self.policy_states:
                ctx_prev = self.policy_results.get(policy_state.policy_no, {}).get('context')
                if ctx_prev is None:
                    continue
                nb_initial_csm = self._to_decimal(getattr(ctx_prev, 'nb_initial_csm', _D('0')))
                nb_initial_lc = self._to_decimal(getattr(ctx_prev, 'nb_initial_lc', _D('0')))
                # 只有新增为正（CSM）的部分计入新增合同CSM
                if nb_initial_csm > 0:
                    nb_csm_group += nb_initial_csm
                # 只有新增为负（LC）的部分计入新增合同LC
                if nb_initial_lc < 0:
                    nb_lc_group += nb_initial_lc
            self.group_cohort_state.new_csm = nb_csm_group
            self.group_cohort_state.new_lc = nb_lc_group

        # 在日志中简要展示组级年初/新增CSM（组口径），后续组级CSM计息将以此为基础
        self.logger.log_text("### 组级CSM期初与新增（组口径）")
        self.logger.log_text(f"- IF_年初CSM余额（组级）: {self.group_cohort_state.bop_csm:,.2f}")
        self.logger.log_text(f"- 当年新增合同CSM（组级）: {self.group_cohort_state.new_csm:,.2f}")
        self.logger.log_text(f"- IF_年初LC（组级）: {self.group_cohort_state.bop_lc:,.2f}")
        self.logger.log_text(f"- 当年新增合同LC（组级）: {self.group_cohort_state.new_lc:,.2f}")

        # 3. 逐单计算（完整的年度计量流水线）
        self.logger.log_text(f"### [Step 3] 逐单计算明细")
        
        # 存储每张保单的计算上下文（用于后续组级汇总）
        policy_contexts: Dict[str, CalculationContext] = {}
        
        group_csm_total = Decimal('0')
        group_lc_total = Decimal('0')
        group_csm_interest_total = Decimal('0')
        group_lc_ifie_total = Decimal('0')
        
        # 单保单内部使用静默日志，只在本函数中做“mock1/mock2/组合计”的组级展示
        per_policy_logger = self.logger if not self.enable_logging else _SilentLogger()
        
        for policy_state in self.policy_states:
            self.logger.log_text(f"#### 处理保单: {policy_state.policy_no}")
            
            # 对每张保单执行完整的年度计量（内部不再写入大量md，只保留组级汇总）
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
            
            # 使用合同组判定口径的 CSM/LC（cohort_csm / cohort_lc），而不是单张期末余额
            policy_csm = self._to_decimal(
                getattr(
                    policy_context,
                    'cohort_csm',
                    getattr(policy_context, 'end_csm_final', getattr(policy_context, 'end_csm_before_amort', Decimal('0')))
                )
            )
            policy_lc = self._to_decimal(
                getattr(
                    policy_context,
                    'cohort_lc',
                    getattr(policy_context, 'end_lc_final', getattr(policy_context, 'end_lc_before_amort', Decimal('0')))
                )
            )

            # 将逐单“合同组CSM/LC判定口径”的结果，显式写回对应的GroupPolicyState，供未来作为分摊因子使用
            if isinstance(policy_state, GroupPolicyState):
                policy_state.group_cohort_csm = policy_csm
                policy_state.group_cohort_lc = policy_lc
            
            group_csm_total += policy_csm
            group_lc_total += policy_lc
            
            # 汇总计息（仅用于分析，不改变状态判定）
            if_interest_csm = self._to_decimal(getattr(policy_context, 'if_interest_csm', Decimal('0')))
            nb_interest_csm = self._to_decimal(getattr(policy_context, 'nb_interest_csm', Decimal('0')))
            group_csm_interest_total += if_interest_csm + nb_interest_csm
            
            if_interest_lc = self._to_decimal(getattr(policy_context, 'if_interest_lc', Decimal('0')))
            nb_interest_lc = self._to_decimal(getattr(policy_context, 'nb_interest_lc', Decimal('0')))
            group_lc_ifie_total += if_interest_lc + nb_interest_lc
        
        # 3.1 经验调整 – 先逐单展示，再给出组级合计
        self.logger.log_section("Part 2: 经验调整（组维度汇总）")
        
        # 保费现金流经验调整
        self.logger.log_text("### 经验调整-保费现金流（组内保单明细）")
        group_adj_prem = Decimal('0')
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            adj_prem = self._to_decimal(getattr(ctx, 'prem_var', Decimal('0')))
            group_adj_prem += adj_prem
            self.logger.log_text(f"- 保单 {policy_state.policy_no}: Adj_Prem = {adj_prem:,.2f}")
        self.logger.log_text(f"**组级保费经验调整合计 Adj_Prem_Total**: {group_adj_prem:,.2f}")
        
        # IACF 经验调整
        self.logger.log_text("### 经验调整-IACF（组内保单明细）")
        group_adj_iacf = Decimal('0')
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            adj_iacf = self._to_decimal(getattr(ctx, 'iacf_var', Decimal('0')))
            group_adj_iacf += adj_iacf
            self.logger.log_text(f"- 保单 {policy_state.policy_no}: Adj_IACF = {adj_iacf:,.2f}")
        self.logger.log_text(f"**组级IACF经验调整合计 Adj_IACF_Total**: {group_adj_iacf:,.2f}")
        
        total_adj = group_adj_prem + group_adj_iacf
        self.logger.log_text(f"**组级经验调整合计 Adj_Total**: {total_adj:,.2f}")
        
        # 4. 按组汇总，判断合同组状态（真正的合同组口径）
        self.logger.log_text(f"### [Step 4] 按组汇总并判断状态")
        
        # 先求出组级 Net_trial（等价于 Σ[IF_计息后CSM + NB_计息后CSM + IF/NB分摊后IFIE后LC]），仅作为内部判定用
        net_trial = group_csm_total + group_lc_total
        self.group_cohort_state.net_trial = net_trial
        
        # 按文档公式：
        # 合同组CSM = IF(Net_trial >= 0, Net_trial, 0)
        # 合同组LC  = IF(Net_trial < 0, Net_trial, 0)
        if net_trial >= 0:
            group_csm_status = net_trial
            group_lc_status = Decimal('0')
            self.group_cohort_state.is_profitable = True
            status = "盈利（CSM）"
        else:
            group_csm_status = Decimal('0')
            group_lc_status = net_trial
            self.group_cohort_state.is_profitable = False
            status = "亏损（LC）"
        
        # 将判定口径的合同组CSM/LC 回写到 group_cohort_state，供报表与后续模块使用
        self.group_cohort_state.eop_csm = group_csm_status
        self.group_cohort_state.eop_lc = group_lc_status
        
        # 日志中仅展示“合同组口径”的CSM/LC和状态，不再展示 Net_trial 这个中间量
        self.logger.log_text(f"- **合同组CSM（判定口径）**: {group_csm_status:,.2f}")
        self.logger.log_text(f"- **合同组LC（判定口径）**: {group_lc_status:,.2f}")
        self.logger.log_text(f"- **合同组状态**: {status}")
        
        # 5. 计算组级覆盖单元和摊销比例
        self.logger.log_text(f"### [Step 5] 计算组级覆盖单元和摊销比例")
        
        start_of_year = date(year, 1, 1)
        group_csm_amort_ratio = self.calculate_group_coverage_units_ratio(
            eval_date,
            start_of_year,
            is_initial_year
        )
        
        # 6. 组级计量：先对每张保单提取年度结果，再按字段做组级汇总
        per_policy_results: List[Dict] = []
        for policy_state in self.policy_states:
            ctx = policy_contexts.get(policy_state.policy_no)
            if not ctx:
                continue
            per_policy_results.append(self._extract_policy_yearly_result(year, ctx))
        
        # 按字段逐项求和，形成组级年度结果
        yearly_result: Dict[str, float] = {}
        for res in per_policy_results:
            for field_name, value in res.items():
                # 标识字段使用组ID和当前年度
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
        
        # 7. 组级年度结果汇总（只展示数值，不展开逐步推导）
        self.logger.log_section("Part 6: 年度结果汇总（组级关键指标）")
        self.logger.log_text(f"- 年度: {year}")
        for field_name, value in yearly_result.items():
            # 只输出最终数值，不附带详细公式说明，避免日志过长
            self.logger.log_text(f"- {field_name}: {value}")
        
        return yearly_result
    
    def run(self) -> List[Dict]:
        """
        执行完整的组维度生命周期仿真
        """
        yearly_results: List[Dict] = []
        try:
            # 1. 初始化
            initial_assumptions, initial_rates, class_code = self.initialize()
            
            # 2. 初始确认（逐单）
            self.run_initial_recognition(initial_assumptions, initial_rates)
            
            # 3. 确定仿真年份范围
            if not self.policy_states:
                raise ValueError("组内没有有效保单")
            
            start_year = min(p.valuation_date.year for p in self.policy_states if p.valuation_date)
            end_year = max(p.end_date.year for p in self.policy_states)
            
            # 限制最大计算年度
            max_year = 2024
            if end_year > max_year:
                self.logger.log_text(f"⚠️  **警告**: 保单终止日期最晚为 {end_year}年，但数据库仅配置到 {max_year}年")
                self.logger.log_text(f"   将仅计算到 {max_year}年底")
                end_year = max_year
            
            self.logger.log_section("开始组维度生命周期仿真")
            self.logger.log_text(f"- **起始年度**: {start_year}")
            self.logger.log_text(f"- **终止年度**: {end_year}")
            
            # 4. 逐年循环计量
            for year in range(start_year, end_year + 1):
                result = self.run_yearly_measurement(year, is_initial_year=(year == start_year))
                yearly_results.append(result)
            
            # 5. 最终汇总
            self.logger.log_section("组维度生命周期仿真完成 - 最终汇总")
            
            # 6. 生成组级别的103、104报表
            if self.enable_reports:
                try:
                    from BBA_group.utils.generate_ifrs17_104_report import main as generate_report_104
                    from BBA_group.utils.generate_ifrs17_103_report import main as generate_report_103
                    
                    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
                    os.makedirs(logs_dir, exist_ok=True)
                    
                    # 生成104报表（合同负债余额调节表）
                    # 注意：104报表需要init_context，但组级别没有单一context
                    # 我们创建一个模拟的context对象，或者修改报表生成函数支持init_data
                    # 暂时使用None，报表生成函数会使用默认值
                    html_report_path_104 = os.path.join(logs_dir, f"ifrs17_104_report_group_{self.group_id}.html")
                    html_report_path_104 = generate_report_104(
                        yearly_results=yearly_results,
                        init_context=None,  # 组级别没有单一context
                        output_html_path=html_report_path_104,
                        policy_no=self.group_id,
                        certi_no=None
                    )
                    if html_report_path_104:
                        self.logger.log_text(f"\n✅ IFRS 17 104报表已生成: {html_report_path_104}")
                        print(f"\n[SUCCESS] IFRS 17 104报表已生成: {html_report_path_104}")
                    
                    # 生成103报表（未到期/已发生调节表）
                    html_report_path_103 = os.path.join(logs_dir, f"ifrs17_103_report_group_{self.group_id}.html")
                    html_report_path_103 = generate_report_103(
                        yearly_results=yearly_results,
                        output_html_path=html_report_path_103,
                        policy_no=self.group_id,
                        certi_no=None
                    )
                    if html_report_path_103:
                        self.logger.log_text(f"\n✅ IFRS 17 103报表已生成: {html_report_path_103}")
                        print(f"\n[SUCCESS] IFRS 17 103报表已生成: {html_report_path_103}")
                    
                    self.logger.log_text(f"\n✅ 组维度生命周期仿真完成")
                    self.logger.log_text(f"   组ID: {self.group_id}")
                    self.logger.log_text(f"   组内保单数: {len(self.policy_states)}")
                    
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
    
    # 设置组ID
    GROUP_ID = 'QHPLIA2023ABBA300'
    
    # 生成日志文件名
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    md_log_file = os.path.join(logs_dir, f"group_lifecycle_simulation_log_{GROUP_ID}.md")
    
    print(f"[INFO] 日志将保存到: {md_log_file}\n")
    
    simulator = GroupLifecycleSimulator(
        group_id=GROUP_ID,
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

