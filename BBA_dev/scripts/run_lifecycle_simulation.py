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
from typing import Optional, Dict, Tuple, List
import sys
import os

# 添加项目根目录到路径（scripts 目录在 bba_model 下，需要向上两级到项目根目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from contextlib import redirect_stdout, redirect_stderr
import io

from BBA_dev.config import POLICY_NO, RATIO_IACF, VAL_METHOD
from BBA_dev.models import PolicyState, CohortState, Assumptions
from BBA_dev.data_access import loader
from BBA_dev.context import CalculationContext
from BBA_dev.utils.logger import CalculationLogger
from BBA_dev.utils.pv_cashflow_excel_logger import PVCashFlowExcelLogger
from BBA_dev.projector import CashFlowProjector
from BBA_dev.utils.pv_field_desc import describe_field
from BBA_dev.utils.pv_cashflow_excel_logger import PVCashFlowExcelLogger
from BBA_dev.logic import (
    initial_recognition,
    experience_adj,
    interest_accretion,
    csm_allocation,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)
from BBA_dev.projector import CashFlowProjector
from BBA_dev.utils.pv_field_desc import describe_field
# 注意：所有现值计算必须从PV原材料数据读取，不允许使用旧的计算方式
from BBA_dev.utils.pv_source_loader import load_pv_source_data
from BBA_dev.models.pv_source_data import PVSourceDataCollection


class _SilentLogger:
    """空实现，用于静默模式避免文件输出。"""

    md_file = None

    def log_section(self, *args, **kwargs):
        pass

    def log_text(self, *args, **kwargs):
        pass

    def log_item(self, *args, **kwargs):
        pass

    def close(self):
        pass


class _SilentExcelLogger:
    """空Excel日志，实现相同接口但不做任何事。"""

    def add_year_data(self, *args, **kwargs):
        pass

    def save(self) -> str:
        return ""


class LifecycleSimulator:
    """
    生命周期仿真器
    
    负责管理整个生命周期的计量流程，包括：
    - 初始确认
    - 逐年循环计量
    - 状态滚存
    - 日志输出
    """
    
    def __init__(
        self,
        policy_no: str,
        md_log_file: Optional[str] = None,
        enable_logging: bool = True,
        certi_no: Optional[str] = None,
        pv_file_path: Optional[str] = None,
        dynamic_pv_mode: bool = False,
        run_date: str = '202412',
        val_method: str = VAL_METHOD
    ):
        self.policy_no = policy_no
        self.certi_no = certi_no
        self.pv_file_path = pv_file_path
        self.enable_logging = enable_logging
        self.dynamic_pv_mode = dynamic_pv_mode
        self.run_date = run_date
        self.val_method = val_method
        if enable_logging:
            self.logger = CalculationLogger(md_file_path=md_log_file)
            self.excel_logger = PVCashFlowExcelLogger(policy_no)
        else:
            self.logger = _SilentLogger()
            self.excel_logger = _SilentExcelLogger()
        self.policy_state: Optional[PolicyState] = None
        self.cohort_state: Optional[CohortState] = None
        self.assumptions_history: Dict[str, Assumptions] = {}  # 存储每年的假设
        self.initial_rates_df: Optional[pd.DataFrame] = None  # 保存初始锁定利率曲线
        self._pv_collection: Optional[PVSourceDataCollection] = None

    def _merge_pv_collection(self, new_collection: PVSourceDataCollection) -> PVSourceDataCollection:
        if self._pv_collection is None:
            self._pv_collection = new_collection
            return self._pv_collection
        self._pv_collection.data_by_month.update(new_collection.data_by_month)
        return self._pv_collection

    def _generate_dynamic_pv_data(self, months: List[str]) -> Tuple[PVSourceDataCollection, Optional[str]]:
        import BBA_dev.pv_calculator as pv_calculator

        normalized = [m.replace('-', '') for m in months]
        buffer = io.StringIO()
        original_policy = getattr(pv_calculator, "TARGET_POLICY_NO", None)
        original_certi = getattr(pv_calculator, "TARGET_CERTI_NO", None)
        original_run_date = getattr(pv_calculator, "TARGET_RUN_DATE", None)
        original_val_method = getattr(pv_calculator, "TARGET_VAL_METHOD", None)
        original_month_filter = getattr(pv_calculator, "TARGET_VAL_MONTH_FILTER", None)
        try:
            pv_calculator.TARGET_POLICY_NO = self.policy_no
            pv_calculator.TARGET_CERTI_NO = self.certi_no
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

    def _ensure_pv_data_for_context(self, context: CalculationContext, months: List[str]):
        normalized = [m.replace('-', '') for m in months if m]
        if not normalized:
            return
        if self.dynamic_pv_mode:
            missing = []
            if self._pv_collection is None:
                missing = normalized
            else:
                missing = [m for m in normalized if m not in self._pv_collection.data_by_month]
            if missing:
                pv_collection, file_path = self._generate_dynamic_pv_data(missing)
                self._merge_pv_collection(pv_collection)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            context.pv_source_data = self._pv_collection
        else:
            if context.pv_source_data is None:
                pv_source_data = load_pv_source_data(self.policy_no, self.pv_file_path)
                if pv_source_data is None:
                    raise ValueError(
                        f"❌ 错误: PV原材料数据不可用！请先运行 pv_calculator.py 生成: "
                        f"logs/pv_source_data_{self.policy_no}.json"
                    )
                context.pv_source_data = pv_source_data
        
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
        df_policy = loader.get_policy_data(self.policy_no, certi_no=self.certi_no)
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
        # 从get_policy_data获取warranty_end_date（现在get_policy_data已经从zh.t_pp_jl_contract表读取，包含此字段）
        warranty_end_date = policy_row.get('warranty_end_date')
        if warranty_end_date is not None and isinstance(warranty_end_date, pd.Timestamp):
            warranty_end_date = warranty_end_date.date()
        elif warranty_end_date is None:
            warranty_end_date = start_date  # 如果没有保修结束日期，默认使用起保日期
        class_code = str(policy_row.get('class_code', 'UNKNOWN'))
        
        self.logger.log_text(f"- ✅ **签单日期**: {under_write_date}")
        self.logger.log_text(f"- ✅ **起保日期**: {start_date}")
        self.logger.log_text(f"- ✅ **终保日期**: {end_date}")
        self.logger.log_text(f"- ✅ **保修结束日期**: {warranty_end_date}")
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
            warranty_end_date=warranty_end_date,
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
            'policy_no': self.policy_no,  # 添加保单号
            'sum_premium_no_tax': float(self.policy_state.written_premium),
            'under_write_date': self.policy_state.valuation_date,
            'start_date': self.policy_state.start_date,
            'end_date': self.policy_state.end_date,
            'class_code': self.cohort_state.cohort_id
        })
        context.policy_no = self.policy_no  # 同时在context中设置保单号
        context.under_write_date = self.policy_state.valuation_date
        context.start_date = self.policy_state.start_date
        context.end_date = self.policy_state.end_date
        context.warranty_end_date = self.policy_state.warranty_end_date
        context.year = self.policy_state.valuation_date.year
        context.val_month_str = self.policy_state.valuation_date.strftime('%Y%m')
        context.total_months = self.policy_state.months_passed + self.policy_state.months_remaining
        context.rates_df = rates_df
        context.rates_df_locked = rates_df
        
        init_month = context.under_write_date.strftime('%Y%m') if context.under_write_date else self.policy_state.valuation_date.strftime('%Y%m')
        self._ensure_pv_data_for_context(context, [init_month])
        if context.pv_source_data is None:
            raise ValueError("❌ 错误: 无法加载初始确认所需的PV原材料数据。")
        
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
        context.warranty_end_date = self.policy_state.warranty_end_date
        if not context.total_months:
            context.total_months = self._calculate_total_contract_months()
        if context.policy_data is None and self.policy_state:
            context.policy_data = pd.Series({
                'policy_no': self.policy_no,  # 添加保单号
                'sum_premium_no_tax': float(self.policy_state.written_premium),
                'under_write_date': self.policy_state.valuation_date,
                'start_date': self.policy_state.start_date,
                'end_date': self.policy_state.end_date,
                'class_code': self.cohort_state.cohort_id
            })
        if not hasattr(context, 'policy_no') or context.policy_no is None:
            context.policy_no = self.policy_no
        return context
    
    def _build_rollforward_context(self, prev_context: CalculationContext, target_year: int) -> CalculationContext:
        """
        构建后续年度的全新 CalculationContext，避免上一年NB数据污染
        """
        context = CalculationContext()
        copy_attrs = [
            'policy_data', 'actual_premium', 'init_fut_claim', 'init_fut_maint',
            'init_ra', 'total_months', 'rates_df', 'rates_df_locked', 'rates_df_eop',
            'under_write_date', 'pv_source_data', 'policy_no'  # 保留PV原材料数据和保单号
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
        context.warranty_end_date = self.policy_state.warranty_end_date
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
        """
        计算由于非金融假设变更引起的未来现金流现值变化
        
        注意：此函数需要从PV原材料数据读取现值。
        如果假设发生变更，需要重新运行pv_calculator.py生成新的PV原材料数据。
        """
        if prev_assumptions is None or current_assumptions is None:
            return (Decimal('0'), Decimal('0'), Decimal('0'))
        
        # 强制要求PV原材料数据必须存在
        if context.pv_source_data is None:
            pv_source_data = load_pv_source_data(self.policy_no)
            if pv_source_data:
                context.pv_source_data = pv_source_data
        
        if context.pv_source_data is None:
            raise ValueError(
                f"❌ 错误: PV原材料数据不可用！\n"
                f"   保单号: {self.policy_no}\n"
                f"   请先运行 pv_calculator.py 生成PV原材料数据文件: logs/pv_source_data_{self.policy_no}.json\n"
                f"   系统要求必须使用PV原材料数据，不允许使用旧的计算方式。\n"
                f"   注意：如果精算假设发生变更，需要重新运行pv_calculator.py生成新的PV原材料数据。"
            )
        
        current_month_str = current_assumptions.val_month
        prev_month_str = prev_assumptions.val_month
        pv_data_curr = context.pv_source_data.get_data(current_month_str)
        pv_data_prev = context.pv_source_data.get_data(prev_month_str)
        if pv_data_curr is None:
            raise ValueError(
                f"❌ 错误: 找不到评估月 {current_month_str} 的PV原材料数据！\n"
                f"   请先运行 pv_calculator.py 为该评估月生成PV原材料。"
            )
        if pv_data_prev is None:
            raise ValueError(
                f"❌ 错误: 找不到评估月 {prev_month_str} 的PV原材料数据！\n"
                f"   请确保已为上一评估月生成PV原材料。"
            )
        
        bel_prev = self._calculate_bel_from_pv(pv_data_prev)
        bel_curr = self._calculate_bel_from_pv(pv_data_curr)
        delta = bel_curr - bel_prev
        
        return (bel_prev, bel_curr, delta)

    @staticmethod
    def _calculate_bel_from_pv(pv_data) -> Decimal:
        """从PV原材料中抽取未来赔付与维费现值，用于比较BEL变化。"""
        fields = [
            'Pvfl_Nb_Eop_Cfa_Rep_Cur_Cla_Amt',
            'Pvfl_Nb_Eop_Cfa_Rep_Cur_Mtn_Amt',
            'Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt',
            'Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt'
        ]
        bel = Decimal('0')
        for field in fields:
            bel += pv_data.get_field(field)
        return bel
    
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
        
        # 判断是否为签单年：签单年不需要年初（1月1日）的PV数据，因为只有新增合同，没有有效合同
        is_new_business_year = (year == context.under_write_date.year)
        if is_new_business_year:
            # 签单年：只需要期末数据，不需要年初数据
            self._ensure_pv_data_for_context(context, [val_month_str])
        else:
            # 后续年份：需要年初和期末数据（用于计算有效合同的各项指标）
            bop_month_str = date(year, 1, 1).strftime('%Y%m')
            self._ensure_pv_data_for_context(context, [bop_month_str, val_month_str])
        
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
        context.warranty_end_date = self.policy_state.warranty_end_date
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
        # 判断是否为新业务：签单年 = 评估年 → 新业务，签单年 < 评估年 → 有效合同
        is_new_business = (year == context.under_write_date.year)
        experience_adj.run(context, self.logger, current_assumptions, is_new_business=is_new_business)
        
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
        # 确保 is_new_business 在 IFIE 执行前已正确设置
        if not hasattr(context, 'is_new_business') or context.is_new_business is None:
            context.is_new_business = (year == context.under_write_date.year)
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
        
        # 8. 收集Excel日志数据
        self._collect_excel_data(year, context, current_assumptions, rates_df_current)
        
        # 滚存到下一年
        self.cohort_state.roll_forward()
        
        return context
    
    def _collect_excel_data(self, year: int, context: CalculationContext, assumptions: Assumptions, rates_df_current: pd.DataFrame):
        """
        收集Excel日志所需的数据
        
        Args:
            year: 年份
            context: 计算上下文
            assumptions: 精算假设
            rates_df_current: 当前利率曲线
        """
        try:
            # 1. 保单信息
            policy_info = {
                'policy_no': self.policy_no,
                'under_write_date': context.under_write_date.strftime('%Y-%m-%d') if context.under_write_date else '',
                'start_date': self.policy_state.start_date.strftime('%Y-%m-%d') if self.policy_state and self.policy_state.start_date else '',
                'end_date': self.policy_state.end_date.strftime('%Y-%m-%d') if self.policy_state and self.policy_state.end_date else '',
                'warranty_end_date': self.policy_state.warranty_end_date.strftime('%Y-%m-%d') if self.policy_state and self.policy_state.warranty_end_date else '',
                'written_premium': self.policy_state.written_premium if self.policy_state else Decimal('0'),
            }
            
            # 2. 精算假设
            assumptions_dict = {
                'loss_ratio': assumptions.loss_ratio,
                'claim_expense_ratio': assumptions.indirect_claims_expense_ratio,
                'maintenance_expense_ratio': assumptions.maintenance_expense_ratio,
                'ra_ratio': assumptions.ra_ratio,
                'acquisition_expense_ratio': assumptions.acquisition_expense_ratio,
            }
            
            # 3. 利率曲线
            rate_curves = {}
            if context.rates_df_locked is not None and not context.rates_df_locked.empty:
                rate_curves['locked'] = context.rates_df_locked.copy()
            if rates_df_current is not None and not rates_df_current.empty:
                rate_curves['current'] = rates_df_current.copy()
            
            # 4. 现金流投射
            # 需要重新投射现金流（使用当前假设）
            cash_flows_df = pd.DataFrame()
            if self.policy_state:
                try:
                    # 构建policy_row用于现金流投射
                    policy_row = {
                        'sum_premium_no_tax': float(self.policy_state.written_premium),
                        'premium': float(self.policy_state.written_premium),
                        'iacf_amount': float(self.policy_state.written_premium * assumptions.acquisition_expense_ratio),
                        'start_date': self.policy_state.start_date,
                        'end_date': self.policy_state.end_date,
                        'under_write_date': context.under_write_date,
                        'warranty_end_date': self.policy_state.warranty_end_date,
                    }
                    
                    projector = CashFlowProjector()
                    cash_flows_df = projector.project_policy_flows(policy_row, assumptions)
                    cash_flows_df['Date_Obj'] = pd.to_datetime(cash_flows_df['YYYYMM'], format='%Y%m').dt.date
                except Exception as e:
                    self.logger.log_text(f"⚠️  警告: 现金流投射失败: {e}")
            
            # 5. PV原材料值计算明细
            pv_calculations = []
            if context.pv_source_data:
                eop_month_str = context.eop_date.strftime('%Y%m') if context.eop_date else ''
                pv_data = context.pv_source_data.get_data(eop_month_str)
                if pv_data:
                    # 获取所有PV字段
                    for field_name in sorted(pv_data.pv_fields.keys()):
                        field_value = pv_data.get_field(field_name)
                        description = describe_field(field_name)
                        pv_calculations.append({
                            'field_name': field_name,
                            'description': description,
                            'value': field_value
                        })
            
            # 6. 折现因子计算明细（简化版，从PV计算中提取关键信息）
            discount_factor_details = []
            # 这里可以添加详细的折现因子计算过程，但需要从PV计算逻辑中提取
            # 暂时留空，后续可以完善
            
            # 添加到Excel日志生成器
            self.excel_logger.add_year_data(
                year=year,
                policy_info=policy_info,
                assumptions=assumptions_dict,
                rate_curves=rate_curves,
                cash_flows=cash_flows_df,
                pv_calculations=pv_calculations,
                discount_factor_details=discount_factor_details
            )
        except Exception as e:
            self.logger.log_text(f"⚠️  警告: 收集Excel日志数据时发生错误: {e}")
            import traceback
            traceback.print_exc()
    
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
        
        # 更新当年新增IACF（从 iacf_amortization 模块中读取）
        if hasattr(context, 'nb_iacf_addition') and context.nb_iacf_addition is not None:
            self.cohort_state.new_iacf = Decimal(str(context.nb_iacf_addition))
    
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
    
    @staticmethod
    def _to_decimal(value) -> Decimal:
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal('0')

    def _to_number(self, value) -> float:
        decimal_value = self._to_decimal(value)
        return float(decimal_value)

    def _derive_gross_from_net(self, net_value: Decimal, lc_ratio: Decimal) -> Decimal:
        denominator = Decimal('1') - lc_ratio
        if denominator == 0:
            return net_value
        return net_value / denominator

    def _is_new_business_year(self, context: CalculationContext) -> bool:
        if hasattr(context, 'is_new_business') and context.is_new_business is not None:
            return context.is_new_business
        if context.under_write_date and context.year:
            return context.year == context.under_write_date.year
        return False

    def _extract_yearly_result(self, year: int, context: CalculationContext) -> Dict:
        """
        提取年度计算结果，供批量模式汇总使用。

        TODO: 未到期责任负债的亏损/非亏损拆分目前仅能返回总额，待有明确拆分口径后完善。
        """
        lc_ratio = self._to_decimal(getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'))

        claims_net = self._to_decimal(getattr(context, 'revenue_claims_expenses_net', Decimal('0')))
        claims_gross = self._derive_gross_from_net(claims_net, lc_ratio)
        claims_lc_alloc = claims_gross - claims_net

        ra_net = self._to_decimal(getattr(context, 'ra_release_net', Decimal('0')))
        ra_gross = self._to_decimal(getattr(context, 'ra_release_gross', None)) or self._derive_gross_from_net(ra_net, lc_ratio)
        ra_lc_alloc = self._to_decimal(getattr(context, 'ra_release_lc_alloc', None))
        if ra_lc_alloc == Decimal('0') and ra_gross != ra_net:
            ra_lc_alloc = ra_gross - ra_net

        allocated_lc_exp_adj = self._to_decimal(getattr(context, 'allocated_lc_exp_adj', Decimal('0')))
        iacf_amort_expense = self._to_decimal(getattr(context, 'iacf_amort_amount', Decimal('0')))
        nb_initial_lc = self._to_decimal(context.nb_initial_lc if self._is_new_business_year(context) else Decimal('0'))

        ifie_pl_cf_non_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_non_lc', Decimal('0')))
        ifie_pl_cf_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_lc', Decimal('0')))
        ifie_pl_ra_non_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_non_lc', Decimal('0')))
        ifie_pl_ra_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_lc', Decimal('0')))
        ifie_pl_cf = ifie_pl_cf_non_lc + ifie_pl_cf_lc
        ifie_pl_ra = ifie_pl_ra_non_lc + ifie_pl_ra_lc

        is_new_business = self._is_new_business_year(context)
        ifie_csm = -self._to_decimal(
            getattr(context, 'nb_interest_csm', Decimal('0')) if is_new_business
            else getattr(context, 'if_interest_csm', Decimal('0'))
        )

        ifie_oci_cf_non_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_non_lc', Decimal('0')))
        ifie_oci_cf_lc = self._to_decimal(getattr(context, 'ifie_oci_cf_lc', Decimal('0')))
        ifie_oci_ra_non_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_non_lc', Decimal('0')))
        ifie_oci_ra_lc = self._to_decimal(getattr(context, 'ifie_oci_ra_lc', Decimal('0')))

        # 未到期责任负债相关
        # BEL（预期现金流现值）：优先从context获取（lrc_closing.py已计算），否则使用赔付+维费
        lrc_bel_total = self._to_decimal(getattr(context, 'lrc_bel_total', None))
        if lrc_bel_total is None:
            # 如果context中没有，使用赔付+维费作为BEL（向后兼容）
            lrc_bel_total = self._to_decimal(getattr(context, 'pv_eop_claims_current', Decimal('0'))) + \
                self._to_decimal(getattr(context, 'pv_eop_maint_current', Decimal('0')))
        
        # RA（非金融风险调整）：从context获取
        lrc_ra = self._to_decimal(getattr(context, 'lrc_ra', Decimal('0')))
        
        # 完整的未到期责任负债（BEL + RA + CSM）：从context获取
        lrc_total = self._to_decimal(getattr(context, 'lrc_total', None))
        if lrc_total is None:
            # 如果context中没有，手动计算（向后兼容）
            end_csm = self._to_decimal(getattr(context, 'end_csm_final', getattr(context, 'end_csm_before_amort', Decimal('0'))))
            lrc_total = lrc_bel_total + lrc_ra + end_csm
        else:
            end_csm = self._to_decimal(getattr(context, 'end_csm_final', getattr(context, 'end_csm_before_amort', Decimal('0'))))

        result = {
            "policy_no": self.policy_no,
            "certi_no": self.certi_no if self.certi_no else "",
            "year": year,
            "保险合同收入_预期赔付与费用_含亏损": self._to_number(claims_gross),
            "保险合同收入_预期赔付与费用_亏损分摊": self._to_number(claims_lc_alloc),
            "保险合同收入_预期释放的非金融风险调整_含亏损": self._to_number(ra_gross),
            "保险合同收入_预期释放的非金融风险调整_亏损分摊": self._to_number(ra_lc_alloc),
            "保险合同收入_摊销的CSM": self._to_number(getattr(context, 'csm_amort_amount', Decimal('0'))),
            "保险合同收入_摊销的IACF": self._to_number(getattr(context, 'revenue_iacf_amort', Decimal('0'))),
            "保险合同收入_经验调整": self._to_number(getattr(context, 'revenue_exp_adj', Decimal('0'))),
            "保险合同收入_分解的投资成分": 0.0,  # TODO: 当投资成分拆分口径明确后替换
            "赔付与费用_亏损分摊_预期现金流": self._to_number(allocated_lc_exp_adj),
            "赔付与费用_摊销的IACF": self._to_number(iacf_amort_expense),
            "亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损": self._to_number(nb_initial_lc),
            "IFIE_P&L_未到期_预期现金流_非亏损": self._to_number(ifie_pl_cf_non_lc),
            "IFIE_P&L_未到期_预期现金流_亏损": self._to_number(ifie_pl_cf_lc),
            "IFIE_P&L_未到期_非金融风险调整_非亏损": self._to_number(ifie_pl_ra_non_lc),
            "IFIE_P&L_未到期_非金融风险调整_亏损": self._to_number(ifie_pl_ra_lc),
            "IFIE_P&L_未到期_CSM": self._to_number(ifie_csm),
            "IFIE_OCI_预期现金流_非亏损": self._to_number(ifie_oci_cf_non_lc),
            "IFIE_OCI_预期现金流_亏损": self._to_number(ifie_oci_cf_lc),
            "IFIE_OCI_非金融风险调整_非亏损": self._to_number(ifie_oci_ra_non_lc),
            "IFIE_OCI_非金融风险调整_亏损": self._to_number(ifie_oci_ra_lc),
            "未到期责任负债_CSM": self._to_number(end_csm),
            "未到期责任负债_预期现金流_非亏损": self._to_number(lrc_bel_total),  # TODO: 待确定亏损/非亏损拆分口径
            "未到期责任负债_非金融风险调整": self._to_number(lrc_ra),
            "未到期责任负债_总额": self._to_number(lrc_total),  # BEL + RA + CSM
        }

        return result

    def run(self) -> List[Dict]:
        """
        执行完整的生命周期仿真
        """
        yearly_results: List[Dict] = []
        try:
            # 1. 初始化
            initial_assumptions, initial_rates, class_code = self.initialize()
            
            # 2. 初始确认
            context = self.run_initial_recognition(initial_assumptions, initial_rates)
            
            # 3. 确定仿真年份范围
            start_year = self.policy_state.valuation_date.year
            end_year = self.policy_state.end_date.year
            
            # 限制最大计算年度为2024年（因为数据库中没有2025年的数据）
            max_year = 2024
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
                yearly_results.append(self._extract_yearly_result(year, context))
            
            # 5. 最终汇总
            self.logger.log_section("生命周期仿真完成 - 最终汇总")
            self.print_state_summary(context)
            
            # 6. 保存Excel日志
            excel_file_path = self.excel_logger.save()
            self.logger.log_text(f"\n✅ PV现金流明细Excel日志已保存到: {excel_file_path}")
            
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
        return yearly_results


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
    
    simulator = LifecycleSimulator(POLICY_NO, md_log_file=md_log_file, enable_logging=True)
    simulator.run()
    
    print(f"\n✅ 日志已保存到: {md_log_file}")


if __name__ == "__main__":
    main()

