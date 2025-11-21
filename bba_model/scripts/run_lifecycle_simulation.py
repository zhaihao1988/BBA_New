"""
IFRS 17 BBA 生命周期仿真器 (Lifecycle Simulator)

本程序实现从初始确认日到保单终止日的全生命周期计量仿真。
按年（Yearly）为步长进行循环计算，模拟每年的年末评估，并生成详尽的日志。

核心特性：
1. 真实数据库驱动：从数据库读取保单、利率曲线、精算假设
2. 动态假设更新：每年读取最新的利率和精算假设
3. 状态滚存机制：每年的期初余额严格等于上一年的期末余额
4. 合同组计量：支持单单转组的模拟（虽然只跑一张单，但逻辑上属于一个合同组）

数据流向：
保单数据 -> 初始确认 -> 逐年循环：
    - 读取最新利率曲线
    - 读取最新精算假设
    - 现金流重估
    - 经验调整
    - CSM计息
    - 变化吸收
    - 摊销
    - 期末结转
"""

import pandas as pd
from decimal import Decimal
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Tuple
import sys
import os

# 添加项目根目录到路径（scripts 目录在 bba_model 下，需要向上两级到项目根目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from bba_model.config import POLICY_NO, RATIO_IACF, VAL_METHOD
from bba_model.models import PolicyState, CohortState, Assumptions
from bba_model.data_access import loader
from bba_model.context import CalculationContext
from bba_model.utils.logger import CalculationLogger
from bba_model.logic import (
    initial_recognition,
    experience_adj,
    interest_accretion,
    csm_allocation,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)
from bba_model.utils.math_tools import calculate_future_pv_with_rates


class LifecycleSimulator:
    """
    生命周期仿真器
    
    负责管理整个生命周期的计量流程，包括：
    - 初始确认
    - 逐年循环计量
    - 状态滚存
    - 日志输出
    """
    
    def __init__(self, policy_no: str, md_log_file: Optional[str] = None):
        self.policy_no = policy_no
        self.logger = CalculationLogger(md_file_path=md_log_file)
        self.policy_state: Optional[PolicyState] = None
        self.cohort_state: Optional[CohortState] = None
        self.assumptions_history: Dict[str, Assumptions] = {}  # 存储每年的假设
        self.initial_rates_df: Optional[pd.DataFrame] = None  # 保存初始锁定利率曲线
        
    def initialize(self) -> Tuple[Assumptions, pd.DataFrame, str]:
        """
        初始化：读取保单数据，确定初始确认日
        
        对应文档：第0节 合同类型判定
        
        Returns:
            Tuple[Assumptions, pd.DataFrame, str]: (初始精算假设, 初始利率曲线, 险类代码)
        """
        self.logger.log_section(f"IFRS 17 BBA 生命周期仿真器 - 初始化")
        self.logger.log_text(f"**保单号**: {self.policy_no}")
        
        # 1. 读取保单数据
        self.logger.log_text("### [Step 0] 获取保单数据")
        df_policy = loader.get_policy_data(self.policy_no)
        if df_policy.empty:
            raise ValueError(f"未找到保单号 {self.policy_no} 的数据")
        
        policy_row = df_policy.iloc[0]
        
        # 提取保单信息
        written_premium = Decimal(str(policy_row['sum_premium_no_tax'] or 0))
        under_write_date = policy_row['under_write_date']
        if isinstance(under_write_date, pd.Timestamp):
            under_write_date = under_write_date.date()
        start_date = policy_row['start_date']
        if isinstance(start_date, pd.Timestamp):
            start_date = start_date.date()
        end_date = policy_row['end_date']
        if isinstance(end_date, pd.Timestamp):
            end_date = end_date.date()
        class_code = str(policy_row.get('class_code', 'UNKNOWN'))
        
        self.logger.log_text(f"- ✅ **签单日期**: {under_write_date}")
        self.logger.log_text(f"- ✅ **起保日期**: {start_date}")
        self.logger.log_text(f"- ✅ **终保日期**: {end_date}")
        self.logger.log_text(f"- ✅ **签单保费**: {written_premium:,.2f}")
        self.logger.log_text(f"- ✅ **险类代码**: {class_code}")
        
        # 2. 判定合同类型（文档第0节）
        val_year = under_write_date.year
        if under_write_date.year < datetime.now().year:
            self.logger.log_text(f"- ℹ️  **合同类型判定**：签单日期({under_write_date.year})早于当前年度，认定为存量合同")
            self.logger.log_text(f"  注意：本仿真器从初始确认日开始模拟，因此按新业务处理")
        else:
            self.logger.log_text(f"- ℹ️  **合同类型判定**：签单日期({under_write_date.year})与评估基准日同年，认定为新业务")
        
        # 3. 创建保单状态
        self.policy_state = PolicyState(
            policy_no=self.policy_no,
            start_date=start_date,
            end_date=end_date,
            written_premium=written_premium,
            valuation_date=under_write_date  # 初始确认日
        )
        
        # 4. 创建合同组状态（虽然只有一张单，但逻辑上属于一个合同组）
        self.cohort_state = CohortState(
            cohort_id=class_code,  # 使用险类代码作为合同组标识
            weighted_locked_rate=Decimal('0'),  # 初始为0，将在初始确认时计算
            total_written_premium=Decimal('0')
        )
        
        # 5. 读取初始确认时的精算假设和利率曲线
        val_month_str = under_write_date.strftime('%Y%m')
        self.logger.log_text(f"### [Step 0.1] 读取初始确认时的精算假设和利率曲线")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        # 读取精算假设（从数据库读取获取费用率）
        assumptions_dict = loader.get_assumptions(class_code, val_month_str, VAL_METHOD, use_db_acquisition_expense=True)
        if assumptions_dict is None:
            raise ValueError(f"未找到险类 {class_code} 在 {val_month_str} 的精算假设数据")
        
        # 如果数据库中有获取费用率，使用数据库的值；否则使用配置的值
        acquisition_expense = assumptions_dict.get('acquisition_expense_ratio', RATIO_IACF)
        
        initial_assumptions = Assumptions(
            val_month=val_month_str,
            class_code=class_code,
            loss_ratio=assumptions_dict['loss_ratio'],
            indirect_claims_expense_ratio=assumptions_dict['indirect_claims_expense_ratio'],
            maintenance_expense_ratio=assumptions_dict['maintenance_expense_ratio'],
            ra_ratio=assumptions_dict['ra_ratio'],
            acquisition_expense_ratio=acquisition_expense  # 优先从数据库读取，否则使用配置
        )
        self.assumptions_history[val_month_str] = initial_assumptions
        
        self.logger.log_text(f"✅ **初始精算假设**:")
        self.logger.log_text(f"   - 赔付率: {initial_assumptions.loss_ratio:.4f}")
        self.logger.log_text(f"   - 间接理赔费用率: {initial_assumptions.indirect_claims_expense_ratio:.4f}")
        self.logger.log_text(f"   - 维持费用率: {initial_assumptions.maintenance_expense_ratio:.4f}")
        self.logger.log_text(f"   - 非金融风险调整率: {initial_assumptions.ra_ratio:.4f}")
        if 'acquisition_expense_ratio' in assumptions_dict:
            self.logger.log_text(f"   - 获取费用率: {initial_assumptions.acquisition_expense_ratio:.4f} (从数据库读取)")
        else:
            self.logger.log_text(f"   - 获取费用率: {initial_assumptions.acquisition_expense_ratio:.4f} (从配置读取)")
        
        # 读取利率曲线
        rates_df = loader.get_rates(val_month_str)
        if rates_df.empty:
            raise ValueError(f"未找到 {val_month_str} 的利率曲线数据")
        self.logger.log_text(f"✅ 成功获取 {val_month_str} 利率曲线 ({len(rates_df)} 条记录)")
        self.initial_rates_df = rates_df
        
        return initial_assumptions, rates_df, class_code
    
    def run_initial_recognition(self, assumptions: Assumptions, rates_df: pd.DataFrame):
        """
        执行初始确认
        
        对应文档：第1-3节
        """
        self.logger.log_section(f"Part 1: 初始确认 (Initial Recognition) - Year {self.policy_state.valuation_date.year}")
        
        # 创建计算上下文
        context = CalculationContext()
        context.policy_data = pd.Series({
            'sum_premium_no_tax': float(self.policy_state.written_premium),
            'under_write_date': self.policy_state.valuation_date,
            'start_date': self.policy_state.start_date,
            'end_date': self.policy_state.end_date,
            'class_code': self.cohort_state.cohort_id
        })
        context.under_write_date = self.policy_state.valuation_date
        context.start_date = self.policy_state.start_date
        context.end_date = self.policy_state.end_date
        context.year = self.policy_state.valuation_date.year
        context.val_month_str = self.policy_state.valuation_date.strftime('%Y%m')
        context.total_months = self.policy_state.months_passed + self.policy_state.months_remaining
        context.rates_df = rates_df
        context.rates_df_locked = rates_df
        
        # 使用动态假设（从数据库读取）
        # 注意：这里需要修改 initial_recognition 模块以接受 assumptions 参数
        # 暂时先使用旧的逻辑，后续需要重构
        
        # 执行初始确认（传递 assumptions 和 cohort_state）
        initial_recognition.run(context, self.logger, assumptions, self.cohort_state)
        
        # 更新保单状态
        self.policy_state.initial_csm = context.nb_initial_csm or Decimal('0')
        self.policy_state.initial_lc = context.nb_initial_lc or Decimal('0')
        
        # 更新合同组状态（rates_manager 已在 initial_recognition 中更新加权锁定利率）
        self.cohort_state.new_csm = self.policy_state.initial_csm
        self.cohort_state.new_lc = self.policy_state.initial_lc
        
        # 将保单添加到 context，用于后续的覆盖单元计算
        context.policies = [self.policy_state]
        
        return context
    
    def _prepare_initial_year_context(self, context: CalculationContext) -> CalculationContext:
        """
        初始化首年上下文（初始确认年）
        """
        context.bop_csm = Decimal('0')
        context.bop_lc = Decimal('0')
        context.bop_iacf = Decimal('0')
        context.start_date = context.under_write_date or self.policy_state.valuation_date
        context.end_date = date(context.year, 12, 31)
        if not context.total_months:
            context.total_months = self._calculate_total_contract_months()
        if context.policy_data is None and self.policy_state:
            context.policy_data = pd.Series({
                'sum_premium_no_tax': float(self.policy_state.written_premium),
                'under_write_date': self.policy_state.valuation_date,
                'start_date': self.policy_state.start_date,
                'end_date': self.policy_state.end_date,
                'class_code': self.cohort_state.cohort_id
            })
        return context
    
    def _build_rollforward_context(self, prev_context: CalculationContext, target_year: int) -> CalculationContext:
        """
        构建后续年度的全新 CalculationContext，避免上一年NB数据污染
        """
        context = CalculationContext()
        copy_attrs = [
            'policy_data', 'actual_premium', 'init_fut_claim', 'init_fut_maint',
            'init_ra', 'total_months', 'rates_df', 'rates_df_locked', 'rates_df_eop',
            'under_write_date'
        ]
        for attr in copy_attrs:
            setattr(context, attr, getattr(prev_context, attr, None))
        if context.actual_premium is None and self.policy_state:
            context.actual_premium = self.policy_state.written_premium
        if context.total_months is None:
            context.total_months = self._calculate_total_contract_months()
        if context.rates_df is None:
            context.rates_df = self.initial_rates_df
        if context.rates_df_locked is None:
            context.rates_df_locked = context.rates_df or self.initial_rates_df
        context.year = target_year
        context.start_date = date(target_year, 1, 1)
        context.end_date = date(target_year, 12, 31)
        context.bop_csm = self.cohort_state.bop_csm
        context.bop_lc = self.cohort_state.bop_lc
        context.bop_iacf = self.cohort_state.bop_iacf
        context.nb_initial_csm = Decimal('0')
        context.nb_initial_lc = Decimal('0')
        context.nb_iacf_addition = Decimal('0')
        if context.policy_data is None:
            context.policy_data = prev_context.policy_data
        return context
    
    def _calculate_total_contract_months(self) -> int:
        delta = relativedelta(self.policy_state.end_date, self.policy_state.start_date)
        total_months = delta.years * 12 + delta.months
        if total_months == 0 and (self.policy_state.end_date - self.policy_state.start_date).days > 0:
            total_months = 1
        return max(total_months, 1)
    
    def _get_previous_assumptions(self, current_val_month: str) -> Optional[Assumptions]:
        """获取当前评估月之前最近一次的精算假设"""
        if not self.assumptions_history:
            return None
        earlier_keys = [k for k in self.assumptions_history.keys() if k < current_val_month]
        if not earlier_keys:
            return None
        prev_key = max(earlier_keys)
        return self.assumptions_history.get(prev_key)
    
    def _calculate_bel_change_from_assumptions(
        self,
        context: CalculationContext,
        prev_assumptions: Optional[Assumptions],
        current_assumptions: Optional[Assumptions]
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """计算由于非金融假设变更引起的未来现金流现值变化"""
        if prev_assumptions is None or current_assumptions is None:
            return (Decimal('0'), Decimal('0'), Decimal('0'))
        
        rates_df_locked = context.rates_df if context.rates_df is not None else self.initial_rates_df
        if rates_df_locked is None or getattr(rates_df_locked, "empty", False):
            return (Decimal('0'), Decimal('0'), Decimal('0'))
        
        actual_premium = context.actual_premium or (self.policy_state.written_premium if self.policy_state else None)
        if actual_premium is None:
            return (Decimal('0'), Decimal('0'), Decimal('0'))
        
        total_months = context.total_months or self._calculate_total_contract_months()
        months_passed = context.months_passed or 0
        rate_offset = months_passed
        
        prev_claim_ratio = prev_assumptions.loss_ratio * (Decimal('1') + prev_assumptions.indirect_claims_expense_ratio)
        curr_claim_ratio = current_assumptions.loss_ratio * (Decimal('1') + current_assumptions.indirect_claims_expense_ratio)
        
        prev_maint_ratio = prev_assumptions.maintenance_expense_ratio
        curr_maint_ratio = current_assumptions.maintenance_expense_ratio
        
        pv_claim_prev = calculate_future_pv_with_rates(
            actual_premium,
            prev_claim_ratio,
            total_months,
            months_passed,
            rates_df_locked,
            rate_offset=rate_offset
        )
        pv_claim_curr = calculate_future_pv_with_rates(
            actual_premium,
            curr_claim_ratio,
            total_months,
            months_passed,
            rates_df_locked,
            rate_offset=rate_offset
        )
        pv_maint_prev = calculate_future_pv_with_rates(
            actual_premium,
            prev_maint_ratio,
            total_months,
            months_passed,
            rates_df_locked,
            rate_offset=rate_offset
        )
        pv_maint_curr = calculate_future_pv_with_rates(
            actual_premium,
            curr_maint_ratio,
            total_months,
            months_passed,
            rates_df_locked,
            rate_offset=rate_offset
        )
        
        bel_prev = pv_claim_prev + pv_maint_prev
        bel_curr = pv_claim_curr + pv_maint_curr
        delta = bel_curr - bel_prev
        
        return (bel_prev, bel_curr, delta)
    
    @staticmethod
    def _calculate_months_between(start_date: date, end_date: date) -> int:
        if not start_date or not end_date or start_date >= end_date:
            return 0
        delta = relativedelta(end_date, start_date)
        months = delta.years * 12 + delta.months
        if end_date.day >= start_date.day:
            months += 1
        return max(months, 0)
    
    def run_yearly_measurement(self, year: int, context: CalculationContext, is_initial_year: bool = False):
        """
        执行年度计量
        
        对应文档：第4-14节
        
        Args:
            year: 评估年度
            context: 计算上下文（从上一年结转）
            is_initial_year: 是否为初始确认所在年度
        """
        self.logger.log_section(f"Year {year} 年度计量")
        
        # 1. 确定评估日期（年末）
        eval_date = date(year, 12, 31)
        val_month_str = eval_date.strftime('%Y%m')
        
        self.logger.log_text(f"### [Step 1] 确定评估时点")
        self.logger.log_text(f"- **评估日期**: {eval_date}")
        self.logger.log_text(f"- **评估月份**: {val_month_str}")
        
        # 2. 读取最新数据
        self.logger.log_text(f"### [Step 2] 读取最新数据（动态假设更新）")
        
        # 2.1 读取最新利率曲线
        rates_df_current = loader.get_rates(val_month_str)
        if rates_df_current.empty:
            self.logger.log_text(f"⚠️  **警告**: 未找到 {val_month_str} 的利率曲线，使用上一年利率曲线")
            rates_df_current = context.rates_df
        else:
            self.logger.log_text(f"✅ 成功获取 {val_month_str} 利率曲线 ({len(rates_df_current)} 条记录)")
        context.rates_df_eop = rates_df_current
        
        # 2.2 读取最新精算假设（从数据库读取获取费用率）
        class_code = self.cohort_state.cohort_id
        assumptions_dict = loader.get_assumptions(class_code, val_month_str, VAL_METHOD, use_db_acquisition_expense=True)
        if assumptions_dict is None:
            self.logger.log_text(f"⚠️  **警告**: 未找到险类 {class_code} 在 {val_month_str} 的精算假设，使用上一年假设")
            # 使用上一年假设
            prev_val_month = (eval_date - relativedelta(years=1)).strftime('%Y%m')
            if prev_val_month in self.assumptions_history:
                current_assumptions = self.assumptions_history[prev_val_month]
            else:
                raise ValueError(f"无法获取精算假设数据")
        else:
            # 如果数据库中有获取费用率，使用数据库的值；否则使用配置的值
            acquisition_expense = assumptions_dict.get('acquisition_expense_ratio', RATIO_IACF)
            
            current_assumptions = Assumptions(
                val_month=val_month_str,
                class_code=class_code,
                loss_ratio=assumptions_dict['loss_ratio'],
                indirect_claims_expense_ratio=assumptions_dict['indirect_claims_expense_ratio'],
                maintenance_expense_ratio=assumptions_dict['maintenance_expense_ratio'],
                ra_ratio=assumptions_dict['ra_ratio'],
                acquisition_expense_ratio=acquisition_expense  # 优先从数据库读取，否则使用配置
            )
            self.assumptions_history[val_month_str] = current_assumptions
        
        self.logger.log_text(f"✅ **本期使用精算假设**:")
        self.logger.log_text(f"   - 赔付率: {current_assumptions.loss_ratio:.4f}")
        self.logger.log_text(f"   - 间接理赔费用率: {current_assumptions.indirect_claims_expense_ratio:.4f}")
        self.logger.log_text(f"   - 维持费用率: {current_assumptions.maintenance_expense_ratio:.4f}")
        self.logger.log_text(f"   - 非金融风险调整率: {current_assumptions.ra_ratio:.4f}")
        if assumptions_dict and 'acquisition_expense_ratio' in assumptions_dict:
            self.logger.log_text(f"   - 获取费用率: {current_assumptions.acquisition_expense_ratio:.4f} (从数据库读取)")
        else:
            self.logger.log_text(f"   - 获取费用率: {current_assumptions.acquisition_expense_ratio:.4f} (从配置读取)")
        
        # 3. 更新上下文
        context.eop_date = eval_date
        context.end_date = eval_date
        context.val_month_str = val_month_str
        context.year = year
        if context.total_months is None:
            context.total_months = self._calculate_total_contract_months()
        
        # 计算当年服务月份
        period_start = context.start_date
        if is_initial_year:
            # 首年特殊处理：如存在倒签单，需追溯至起保日，以包含过往服务
            start_candidates = [d for d in [context.under_write_date, self.policy_state.start_date if self.policy_state else None] if d]
            if start_candidates:
                period_start = min(start_candidates)
            else:
                period_start = period_start or date(year, 1, 1)
        else:
            period_start = date(year, 1, 1)
        if context.rates_df is None and self.initial_rates_df is not None:
            context.rates_df = self.initial_rates_df
        if context.rates_df_locked is None:
            context.rates_df_locked = context.rates_df or self.initial_rates_df

        context.start_date = period_start
        context.months_passed = self._calculate_months_between(period_start, eval_date)
        context.cumulative_months_start = getattr(self.cohort_state, 'months_since_initial', 0)
        context.cumulative_months_end = context.cumulative_months_start + (context.months_passed or 0)
        context.is_initial_year = is_initial_year
        
        # 更新保单状态
        self.policy_state.valuation_date = eval_date
        self.policy_state.months_passed = context.months_passed
        
        # 4. 现金流重估（使用最新假设）
        self.logger.log_text(f"### [Step 3] 现金流重估（使用最新精算假设）")
        # 注意：这里需要修改相关模块以接受动态假设
        # 暂时先使用旧的逻辑，后续需要重构
        
        # 5. 执行计量流水线
        self.logger.log_text(f"### [Step 4] 执行计量流水线")
        
        # 将保单添加到 context，用于后续的覆盖单元计算和合同组状态判定
        context.policies = [self.policy_state]
        
        # 5.1 经验调整（文档第4节）
        experience_adj.run(context, self.logger, current_assumptions, is_new_business=(year == self.policy_state.valuation_date.year))
        
        # 5.2 CSM计息（文档第6节）- 使用加权锁定利率
        interest_accretion.run(context, self.logger, self.cohort_state, self.policy_state)
        
        # 5.2.1 会计估计变更（非金融假设）
        prev_assumptions = self._get_previous_assumptions(val_month_str)
        bel_prev, bel_curr, delta_changes = self._calculate_bel_change_from_assumptions(
            context,
            prev_assumptions,
            current_assumptions
        )
        context.changes_in_estimates = delta_changes
        self.logger.log_item(
            "会计估计变更（非金融假设）",
            "[Sec 5] 使用锁定利率折现的未来现金流现值变动",
            "Δ_BEL = BEL_new(锁定) - BEL_old(锁定)",
            {
                "BEL_old (Locked)": bel_prev,
                "BEL_new (Locked)": bel_curr,
                "Prev Assumption": prev_assumptions.loss_ratio if prev_assumptions else Decimal('0'),
                "Curr Assumption": current_assumptions.loss_ratio,
                "Prev Maint Ratio": prev_assumptions.maintenance_expense_ratio if prev_assumptions else Decimal('0'),
                "Curr Maint Ratio": current_assumptions.maintenance_expense_ratio,
                "Prev ULAE Ratio": prev_assumptions.indirect_claims_expense_ratio if prev_assumptions else Decimal('0'),
                "Curr ULAE Ratio": current_assumptions.indirect_claims_expense_ratio
            },
            delta_changes,
            note="仅捕捉非金融假设（赔付率/费用率）对未来现金流的影响，折现使用加权锁定利率"
        )
        
        # 5.3 被CSM/LC吸收的变化（文档第5节）和合同组状态判定（文档第8.5.5节）
        csm_allocation.calculate_absorption(context, self.logger, self.cohort_state, [self.policy_state])
        
        # 5.4 IACF摊销（文档第10节）
        iacf_amortization.run(context, self.logger)
        
        # 5.5 保险合同收入（文档第11节）- 使用覆盖单元动态比例法
        revenue.run(context, self.logger)
        
        # 5.6 IFIE（文档第13-14节）- 严格区分 IFIE_P&C 和 IFIE_OCI
        ifie.run(context, self.logger, current_assumptions, self.cohort_state)
        
        # 5.7 期末负债（文档第12节）
        lrc_closing.run_closing(context, self.logger)
        
        # 6. 更新状态
        self.update_states_from_context(context)
        if hasattr(self.cohort_state, 'months_since_initial'):
            self.cohort_state.months_since_initial = context.cumulative_months_end
        
        # 7. 状态滚存（为下一年准备）
        self.cohort_state.calculate_eop_balances()
        self.logger.log_section(f"Year {year} 期末状态汇总")
        self.print_state_summary(context)
        
        # 滚存到下一年
        self.cohort_state.roll_forward()
        
        return context
    
    def update_states_from_context(self, context: CalculationContext):
        """
        从计算上下文更新状态对象
        
        对应文档：第8.10节 期末CSM余额
        """
        # 更新合同组状态（从 context 中读取计算结果）
        if hasattr(context, 'end_csm_final') and context.end_csm_final is not None:
            self.cohort_state.eop_csm = Decimal(str(context.end_csm_final))
        elif hasattr(context, 'end_csm_before_amort') and context.end_csm_before_amort is not None:
            # 如果没有摊销后的值，使用摊销前的值（摊销会在 revenue 模块中计算）
            self.cohort_state.eop_csm = Decimal(str(context.end_csm_before_amort))
        
        if hasattr(context, 'end_lc_before_amort') and context.end_lc_before_amort is not None:
            self.cohort_state.eop_lc = Decimal(str(context.end_lc_before_amort))
        
        if hasattr(context, 'eop_iacf_balance') and context.eop_iacf_balance is not None:
            self.cohort_state.eop_iacf = Decimal(str(context.eop_iacf_balance))
        
        # 更新计息（从 interest_accretion 模块中读取）
        if hasattr(context, 'if_interest_csm') or hasattr(context, 'nb_interest_csm'):
            if_interest_csm = getattr(context, 'if_interest_csm', None) or Decimal('0')
            nb_interest_csm = getattr(context, 'nb_interest_csm', None) or Decimal('0')
            total_csm_interest = Decimal(str(if_interest_csm + nb_interest_csm))
            self.cohort_state.csm_interest = total_csm_interest
            context.total_csm_interest = total_csm_interest
        
        if hasattr(context, 'if_interest_lc') or hasattr(context, 'nb_interest_lc'):
            if_interest_lc = getattr(context, 'if_interest_lc', None) or Decimal('0')
            nb_interest_lc = getattr(context, 'nb_interest_lc', None) or Decimal('0')
            total_lc_interest = Decimal(str(if_interest_lc + nb_interest_lc))
            context.total_lc_interest = total_lc_interest
            setattr(self.cohort_state, 'lc_interest', total_lc_interest)
        
        # 更新被吸收的变化（从 csm_allocation 模块中读取）
        if hasattr(context, 'csm_absorbed') and context.csm_absorbed is not None:
            self.cohort_state.csm_absorbed_changes = Decimal(str(context.csm_absorbed))
        if hasattr(context, 'allocated_lc_exp_adj') and context.allocated_lc_exp_adj is not None:
            self.cohort_state.lc_absorbed_changes = -Decimal(str(context.allocated_lc_exp_adj))
        
        # 更新摊销（从 revenue 模块中读取）
        if hasattr(context, 'csm_amort_amount') and context.csm_amort_amount is not None:
            self.cohort_state.csm_amortization = Decimal(str(context.csm_amort_amount))
        if hasattr(context, 'iacf_amort_amount') and context.iacf_amort_amount is not None:
            self.cohort_state.iacf_amortization = Decimal(str(context.iacf_amort_amount))
    
    def print_state_summary(self, context: Optional[CalculationContext] = None):
        """
        打印状态汇总
        
        Args:
            context: 计算上下文（可选，用于打印财务报表摘要）
        """
        self.logger.log_section("期末状态汇总")
        self.logger.log_text(f"**合同组状态**:")
        self.logger.log_text(f"- 加权锁定利率: {self.cohort_state.weighted_locked_rate:.6f}")
        self.logger.log_text(f"- 累计签单保费: {self.cohort_state.total_written_premium:,.2f}")
        self.logger.log_text(f"- 年初CSM余额: {self.cohort_state.bop_csm:,.2f}")
        self.logger.log_text(f"- 年初LC余额: {self.cohort_state.bop_lc:,.2f}")
        self.logger.log_text(f"- 年初IACF余额: {self.cohort_state.bop_iacf:,.2f}")
        self.logger.log_text(f"- 当年新增CSM: {self.cohort_state.new_csm:,.2f}")
        self.logger.log_text(f"- 当年新增LC: {self.cohort_state.new_lc:,.2f}")
        self.logger.log_text(f"- CSM计息: {self.cohort_state.csm_interest:,.2f}")
        self.logger.log_text(f"- 被CSM吸收的变化: {self.cohort_state.csm_absorbed_changes:,.2f}")
        self.logger.log_text(f"- CSM摊销: {self.cohort_state.csm_amortization:,.2f}")
        self.logger.log_text(f"- 期末CSM余额: {self.cohort_state.eop_csm:,.2f}")
        self.logger.log_text(f"- 期末LC余额: {self.cohort_state.eop_lc:,.2f}")
        self.logger.log_text(f"- 期末IACF余额: {self.cohort_state.eop_iacf:,.2f}")
        self.logger.log_text(f"- 合同组状态: **{'盈利' if self.cohort_state.is_profitable else '亏损'}**")
        self.logger.log_text(f"- 净余额试算值: {self.cohort_state.net_trial:,.2f}")
        
        # 打印财务报表摘要
        if context and hasattr(context, 'total_revenue') and context.total_revenue is not None:
            self.logger.log_text(f"\n**财务报表摘要**:")
            self.logger.log_text(f"- 保险合同收入: {context.total_revenue:,.2f}")
            if hasattr(context, 'ifie_pl') and context.ifie_pl is not None:
                self.logger.log_text(f"- IFIE_P&L: {context.ifie_pl:,.2f}")
            if hasattr(context, 'ifie_oci') and context.ifie_oci is not None:
                self.logger.log_text(f"- IFIE_OCI: {context.ifie_oci:,.2f}")
    
    def run(self):
        """
        执行完整的生命周期仿真
        """
        try:
            # 1. 初始化
            initial_assumptions, initial_rates, class_code = self.initialize()
            
            # 2. 初始确认
            context = self.run_initial_recognition(initial_assumptions, initial_rates)
            
            # 3. 确定仿真年份范围
            start_year = self.policy_state.valuation_date.year
            end_year = self.policy_state.end_date.year
            
            # 限制最大计算年度为2025年（因为数据库中没有2026年的数据）
            max_year = 2025
            if end_year > max_year:
                self.logger.log_text(f"⚠️  **警告**: 保单终止日期为 {end_year}年，但数据库仅配置到 {max_year}年")
                self.logger.log_text(f"   将仅计算到 {max_year}年底")
                end_year = max_year
            
            self.logger.log_section("开始生命周期仿真")
            self.logger.log_text(f"- **起始年度**: {start_year}")
            self.logger.log_text(f"- **终止年度**: {end_year} (保单原终止日期: {self.policy_state.end_date.year}年)")
            
            # 4. 逐年循环计量（首年也需要期末计量）
            for year in range(start_year, end_year + 1):
                if year == start_year:
                    year_context = self._prepare_initial_year_context(context)
                else:
                    year_context = self._build_rollforward_context(context, year)
                
                context = self.run_yearly_measurement(year, year_context, is_initial_year=(year == start_year))
            
            # 5. 最终汇总
            self.logger.log_section("生命周期仿真完成 - 最终汇总")
            self.print_state_summary(context)
            
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
            # 关闭 Markdown 文件
            self.logger.close()


def main():
    """
    主函数
    """
    # 生成 Markdown 日志文件名（基于保单号和当前时间）
    from datetime import datetime
    import os
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    # 确保 logs 目录存在
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    md_log_file = os.path.join(logs_dir, f"lifecycle_simulation_log_{POLICY_NO}_{timestamp}.md")
    
    print(f"📝 日志将保存到: {md_log_file}\n")
    
    simulator = LifecycleSimulator(POLICY_NO, md_log_file=md_log_file)
    simulator.run()
    
    print(f"\n✅ 日志已保存到: {md_log_file}")


if __name__ == "__main__":
    main()

