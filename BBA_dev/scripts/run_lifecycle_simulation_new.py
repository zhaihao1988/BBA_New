import pandas as pd
import sys
import os
from typing import Optional, Dict, Tuple
from datetime import date
from decimal import Decimal

# 复用现有模块
from BBA_dev.models import Assumptions, PolicyState, CohortState
from BBA_dev.context import CalculationContext
from BBA_dev.utils.logger import CalculationLogger
from BBA_dev.utils.pv_cashflow_excel_logger import PVCashFlowExcelLogger
from BBA_dev.logic import (
    initial_recognition,
    fulfillment_cashflow_changes,
    csm_lc_measurement,
    iacf_amortization,
    revenue,
    ifie,
    lrc_closing
)
# 引入核心计算模块
try:
    from BBA_dev.pv_calculator_core import calculate_pv_core
except ImportError:
    # 兼容性处理：如果是从 pv_calculator_core.py 中导入失败，尝试从 BBA_dev.pv_calculator 导入
    # 这可能是因为 calculate_pv_core 函数实际上定义在 pv_calculator.py 中
    # 根据之前的上下文，calculate_pv_core 是新加的函数
    # 如果文件还不存在，我们可能需要从其他地方获取
    pass

class LifecycleSimulatorNew:
    """
    高速版生命周期仿真器
    完全依赖内存注入数据，无 DB I/O。
    """
    def __init__(self, policy_no: str, preloaded_data: Dict, enable_logging: bool = False):
        self.policy_no = policy_no
        self.preloaded_data = preloaded_data
        self.enable_logging = enable_logging
        
        # 初始化日志（如果需要）
        if enable_logging:
            self.logger = CalculationLogger()
            self.excel_logger = PVCashFlowExcelLogger(policy_no)
        else:
            # 简化的 Mock Logger
            class SilentLogger:
                def log_section(self, *a): pass
                def log_text(self, *a): pass
                def log_item(self, *a, **k): pass
                def close(self): pass
            self.logger = SilentLogger()
            self.excel_logger = None

        self.policy_state = None
        self.cohort_state = None
        self.assumptions_history = {}
        self._pv_collection = None

    def initialize(self):
        # 直接从预加载数据读取
        policy_row_dict = self.preloaded_data['policy_row']
        self.policy_row = pd.Series(policy_row_dict)
        
        # 构造 PolicyState
        self.policy_state = PolicyState(
            policy_no=self.policy_no,
            start_date=self.policy_row['start_date'],
            end_date=self.policy_row['end_date'],
            warranty_end_date=self.policy_row.get('warranty_end_date'),
            written_premium=self.preloaded_data['written_premium'], # Decimal
            valuation_date=self.policy_row['under_write_date']
        )
        
        # 构造 CohortState
        self.cohort_state = CohortState(
            cohort_id=self.policy_row['class_code'],
            weighted_locked_rate=self.preloaded_data['initial_spot_rate'], # 直接传入
            total_written_premium=self.preloaded_data['written_premium']
        )
        
        # 将字典数据转换为 Assumptions 对象（在子进程中执行）
        self.assumptions_history = {}
        for month, assump_dict in self.preloaded_data['assumptions_map'].items():
            if isinstance(assump_dict, dict):
                # 从字典创建 Assumptions 对象
                self.assumptions_history[month] = Assumptions(
                    val_month=month,
                    class_code=self.policy_row['class_code'],
                    loss_ratio=assump_dict.get('loss_ratio'),
                    indirect_claims_expense_ratio=assump_dict.get('indirect_claims_expense_ratio'),
                    maintenance_expense_ratio=assump_dict.get('maintenance_expense_ratio'),
                    ra_ratio=assump_dict.get('ra_ratio'),
                    acquisition_expense_ratio=assump_dict.get('acquisition_expense_ratio')
                )
            else:
                # 已经是对象了（向后兼容）
                self.assumptions_history[month] = assump_dict
        
        return self.assumptions_history, None, self.policy_row['class_code']

    def _ensure_pv_data(self):
        """核心：在内存中计算 PV"""
        if self._pv_collection is None:
            # 将字典数据转换为 Assumptions 对象（在子进程中执行）
            assumptions_map_objs = {}
            for month, assump_dict in self.preloaded_data['assumptions_map'].items():
                if isinstance(assump_dict, dict):
                    # 从字典创建 Assumptions 对象
                    assumptions_map_objs[month] = Assumptions(
                        val_month=month,
                        class_code=self.policy_row['class_code'],
                        loss_ratio=assump_dict.get('loss_ratio'),
                        indirect_claims_expense_ratio=assump_dict.get('indirect_claims_expense_ratio'),
                        maintenance_expense_ratio=assump_dict.get('maintenance_expense_ratio'),
                        ra_ratio=assump_dict.get('ra_ratio'),
                        acquisition_expense_ratio=assump_dict.get('acquisition_expense_ratio')
                    )
                else:
                    # 已经是对象了（向后兼容）
                    assumptions_map_objs[month] = assump_dict
            
            # 调用纯计算核心
            self._pv_collection = calculate_pv_core(
                self.policy_row,
                assumptions_map_objs,
                self.preloaded_data['rates_map']
            )
        return self._pv_collection

    def run(self):
        # 1. 初始化
        self.initialize()
        
        # 2. 计算 PV (内存操作)
        self._ensure_pv_data()
        
        # 3. 准备 Context
        context = CalculationContext()
        context.pv_source_data = self._pv_collection
        context.policy_data = self.policy_row
        context.policy_no = self.policy_no
        # 添加 certi_no 到 context
        context.certi_no = self.policy_row.get('certi_no')
        # 设置关键日期字段
        context.under_write_date = self.policy_state.valuation_date
        context.start_date = self.policy_state.start_date
        context.end_date = self.policy_state.end_date
        context.warranty_end_date = self.policy_state.warranty_end_date
        
        # 计算合同总月数
        from dateutil.relativedelta import relativedelta
        delta = relativedelta(self.policy_state.end_date, self.policy_state.start_date)
        total_months = delta.years * 12 + delta.months
        if total_months == 0 and (self.policy_state.end_date - self.policy_state.start_date).days > 0:
            total_months = 1
        context.total_months = max(total_months, 1)
        
        # 4. 执行初始确认
        # 获取初始确认时的假设和利率曲线
        under_write_date = self.policy_row['under_write_date']
        if under_write_date and hasattr(under_write_date, 'strftime'):
            init_uw_month = under_write_date.strftime('%Y%m')
        elif under_write_date:
            # 如果是字符串，尝试解析
            import pandas as pd
            init_uw_month = pd.to_datetime(under_write_date).strftime('%Y%m')
        else:
            # 如果没有签单日期，使用第一个可用的假设月份
            init_uw_month = sorted(self.assumptions_history.keys())[0] if self.assumptions_history else '202401'
        
        # 设置利率曲线（从预加载数据中获取）
        rates_map = self.preloaded_data.get('rates_map', {})
        context.rates_df = rates_map.get(init_uw_month)
        context.rates_df_locked = context.rates_df
        
        init_assump = self.assumptions_history.get(init_uw_month)
        # 如果找不到，尝试找最近的？或者报错？这里假设预加载逻辑保证了数据存在
        if not init_assump and self.assumptions_history:
             # 尝试找其他月份的假设
             for k in sorted(self.assumptions_history.keys()):
                 init_assump = self.assumptions_history[k]
                 break

        initial_recognition.run(context, self.logger, 
                              init_assump, 
                              self.cohort_state)
        
        # 更新状态
        self.policy_state.initial_csm = context.nb_initial_csm
        self.policy_state.initial_lc = context.nb_initial_lc
        self.cohort_state.new_csm = context.nb_initial_csm
        self.cohort_state.new_lc = context.nb_initial_lc

        # 5. 循环年度
        results = []
        start_year = self.policy_state.valuation_date.year
        end_year = min(self.policy_state.end_date.year, 2024)
        
        for year in range(start_year, end_year + 1):
            # 关键修复：后续年度重置 NB 相关字段，防止新业务影响后续年份
            if year > start_year:
                context.nb_initial_csm = Decimal('0')
                context.nb_initial_lc = Decimal('0')
                context.nb_interest_csm = Decimal('0') 
                context.is_new_business = False # 明确标记非新业务年

            # 更新 context 时间
            context.year = year
            context.eop_date = date(year, 12, 31)
            context.val_month_str = context.eop_date.strftime('%Y%m')
            
            # 获取当年假设
            curr_assump = self.assumptions_history.get(context.val_month_str)
            # 如果没有当年假设（可能是数据缺失），尝试使用上年末的假设
            if not curr_assump:
                prev_month = f"{year-1}12"
                curr_assump = self.assumptions_history.get(prev_month)
                
            # 如果还是没有，使用初始假设
            if not curr_assump:
                curr_assump = init_assump

            # 运行各模块 (它们只读 context.pv_source_data，不会查库)
            fulfillment_cashflow_changes.run(context, self.logger, curr_assump, self.cohort_state, [self.policy_state])
            csm_lc_measurement.run(context, self.logger, self.cohort_state, self.policy_state, [self.policy_state], curr_assump)
            iacf_amortization.run(context, self.logger)
            revenue.run(context, self.logger)
            ifie.run(context, self.logger, curr_assump, self.cohort_state)
            lrc_closing.run_closing(context, self.logger)
            
            # 收集结果
            res = self._extract_result(year, context)
            results.append(res)
            
            # 滚存状态
            self.cohort_state.calculate_eop_balances()
            self.cohort_state.roll_forward()

            # 更新 context 的 BOP 状态供下一年使用
            context.bop_csm = self.cohort_state.bop_csm
            context.bop_lc = self.cohort_state.bop_lc
            context.bop_iacf = self.cohort_state.bop_iacf

        return results

    # --- 辅助方法 ---

    def _to_decimal(self, value) -> Decimal:
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
    
    def _apply_reversal_if_needed(self, value, is_reversal: bool) -> float:
        num = self._to_number(value)
        return -num if is_reversal else num

    def _derive_gross_from_net(self, net_value: Decimal, lc_ratio: Decimal) -> Decimal:
        denominator = Decimal('1') - lc_ratio
        if denominator == 0:
            return net_value
        return net_value / denominator

    def _is_new_business_year(self, context: CalculationContext) -> bool:
        if hasattr(context, 'is_new_business') and context.is_new_business is not None:
            return context.is_new_business
        if self.policy_row is not None and context.year:
            uw_date = self.policy_row.get('under_write_date')
            if hasattr(uw_date, 'year'):
                 return context.year == uw_date.year
            try:
                return context.year == int(str(uw_date)[:4])
            except:
                pass
        return False

    def _extract_result(self, year, context):
        """
        提取年度计算结果，逻辑与原版 _extract_yearly_result 保持一致
        """
        lc_ratio = self._to_decimal(getattr(context, 'nb_lc_ratio', Decimal('0')) or Decimal('0'))

        # 优先使用revenue模块计算的值，如果没有则推导
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

        allocated_lc_cf = self._to_decimal(getattr(context, 'allocated_lc_cf', Decimal('0')))
        allocated_lc_ra = self._to_decimal(getattr(context, 'allocated_lc_ra', Decimal('0')))
        allocated_lc_exp_adj_cf = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_cf', Decimal('0')))
        allocated_lc_exp_adj_ra = self._to_decimal(getattr(context, 'allocated_lc_exp_adj_ra', Decimal('0')))
        iacf_amort_expense = self._to_decimal(getattr(context, 'iacf_amort_amount', Decimal('0')))
        
        is_new_business = self._is_new_business_year(context)
        
        nb_initial_lc_cf = self._to_decimal(getattr(context, 'nb_initial_lc_cf', Decimal('0')) if is_new_business else Decimal('0'))
        nb_initial_lc_ra = self._to_decimal(getattr(context, 'nb_initial_lc_ra', Decimal('0')) if is_new_business else Decimal('0'))
        # nb_initial_lc = self._to_decimal(context.nb_initial_lc if is_new_business else Decimal('0')) # 未使用

        ifie_pl_cf_non_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_non_lc', Decimal('0')))
        ifie_pl_cf_lc = self._to_decimal(getattr(context, 'ifie_pl_cf_lc', Decimal('0')))
        ifie_pl_ra_non_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_non_lc', Decimal('0')))
        ifie_pl_ra_lc = self._to_decimal(getattr(context, 'ifie_pl_ra_lc', Decimal('0')))
        
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
        
        lrc_total = self._to_decimal(getattr(context, 'lrc_total', None))
        end_csm = self._to_decimal(getattr(context, 'end_csm_final', getattr(context, 'end_csm_before_amort', Decimal('0'))))
        if lrc_total is None:
            lrc_total = lrc_bel_total + lrc_ra + end_csm
        
        end_lc_cf = self._to_decimal(getattr(context, 'end_lc_cf', Decimal('0')))
        end_lc_ra = self._to_decimal(getattr(context, 'end_lc_ra', Decimal('0')))
        lrc_bel_lc = end_lc_cf
        lrc_ra_lc = -end_lc_ra
        lrc_bel_non_lc = lrc_bel_total - lrc_bel_lc
        lrc_ra_non_lc = lrc_ra - lrc_ra_lc

        is_reversal = getattr(context, 'is_reversal_policy', False)
        
        certi_no = self.policy_row.get('certi_no')
        if pd.isna(certi_no): certi_no = ""

        return {
            "policy_no": self.policy_no,
            "certi_no": certi_no,
            "year": year,
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
            "未到期_调整CSM的非金融风险调整变动": 0.00,
            "未到期_调整CSM的估计变更": self._apply_reversal_if_needed(getattr(context, 'csm_absorbed', Decimal('0')), is_reversal),
            "新增合同预期现金流_保费现金流_盈利合同": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business and context.nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_IACF_盈利合同": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business and context.nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_赔付与费用现金流_盈利合同": self._apply_reversal_if_needed((getattr(context, 'init_fut_claim', Decimal('0')) + getattr(context, 'init_fut_maint', Decimal('0'))) if is_new_business and context.nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同非金融风险调整_盈利合同": self._apply_reversal_if_needed(getattr(context, 'init_ra', Decimal('0')) if is_new_business and context.nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同CSM_盈利合同": self._apply_reversal_if_needed(getattr(context, 'nb_initial_csm', Decimal('0')) if is_new_business and context.nb_initial_lc >= 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_保费现金流_亏损合同": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business and context.nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_IACF_亏损合同": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business and context.nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损": self._apply_reversal_if_needed((getattr(context, 'init_fut_claim', Decimal('0')) + getattr(context, 'init_fut_maint', Decimal('0'))) if is_new_business and context.nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "新增合同非金融风险调整_亏损合同_非亏损": self._apply_reversal_if_needed(getattr(context, 'init_ra', Decimal('0')) if is_new_business and context.nb_initial_lc < 0 else Decimal('0'), is_reversal),
            "现金流_收到的保费": self._apply_reversal_if_needed(getattr(context, 'actual_premium', Decimal('0')) if is_new_business else Decimal('0'), is_reversal),
            "现金流_支付的获取费用": self._apply_reversal_if_needed(getattr(context, 'actual_iacf_incurred', Decimal('0')) if is_new_business else Decimal('0'), is_reversal),
        }
