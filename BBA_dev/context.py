from decimal import Decimal


class CalculationContext:
    def __init__(self):
        # --- 数据 ---
        self.policy_data = None
        self.under_write_date = None
        self.start_date = None
        self.end_date = None
        self.year = None
        self.val_month_str = None
        self.total_months = 0
        self.rates_df = None  # 兼容旧代码：默认指向锁定曲线
        self.rates_df_locked = None  # 初始确认的锁定利率曲线
        self.eop_date = None
        self.rates_df_eop = None # Part 8 used
        
        # --- 中间变量 ---
        self.actual_premium = None
        self.actual_premium_nb = Decimal('0')
        self.actual_premium_eff = Decimal('0')
        self.init_fut_claim = None
        self.init_fut_maint = None
        self.init_ra = None
        
        self.nb_initial_csm = None
        self.nb_initial_lc = None
        
        self.months_passed = 0  # 本年度服务月数
        self.cumulative_months_start = 0  # 自初始确认起累计到年初的月数
        self.cumulative_months_end = 0    # 自初始确认起累计到年末的月数
        self.expected_claim_nominal = None
        self.expected_maint_nominal = None
        self.actual_claim_incurred = None
        self.actual_maint_incurred = None
        self.expected_iacf_nominal = None
        self.actual_iacf_incurred = None
        self.actual_iacf_nb = Decimal('0')
        self.actual_iacf_eff = Decimal('0')
        
        self.prem_var = None
        self.iacf_var = None
        
        self.exp_adj_csm_impact = None # Part 4 used
        
        self.accretion_factor = None
        self.nb_interest_csm = None
        self.nb_interest_lc = None
        self.if_interest_csm = None
        self.if_interest_lc = None
        self.total_csm_interest = None
        
        self.nb_lc_ratio = None
        self.allocated_lc_exp_adj = None
        
        self.end_csm_before_amort = None
        self.end_lc_before_amort = None
        self.csm_absorbed = None
        self.lc_change = None
        
        self.iacf_amort_ratio = None
        self.iacf_amort_amount = None
        self.eop_iacf_balance = None
        self.bop_iacf = None
        self.bop_csm = None
        self.bop_lc = None
        self.nb_iacf_addition = None
        self.iacf_interest_nb = None
        self.iacf_change = None
        
        self.revenue_claims_expenses_net = None
        self.ra_release_net = None
        self.csm_amort_amount = None
        self.end_csm_final = None
        self.revenue_iacf_amort = None
        self.revenue_exp_adj = None
        self.total_revenue = None
        # self.changes_in_estimates = Decimal('0')
        
        self.pv_eop_claims_current = None # Part 8 & 9 used
        self.pv_eop_maint_current = None # Part 8 & 9 used
        
        # 未到期责任负债相关（Part 9 used）
        self.lrc_bel_total = None  # 预期现金流现值 (BEL)
        self.lrc_ra = None  # 预期非金融风险调整 (RA)
        self.lrc_total = None  # 期末未到期责任负债总额 (BEL + RA + CSM)
        
        self.ifie_pl = None
        self.ifie_oci = None
        self.ifie_pl_non_lc = None
        self.ifie_pl_lc = None
        self.ifie_oci_non_lc = None
        self.ifie_oci_lc = None
        
        # PV原材料数据（从pv_calculator.py计算得出，供所有后续计量环节使用）
        self.pv_source_data = None  # PVSourceDataCollection对象


