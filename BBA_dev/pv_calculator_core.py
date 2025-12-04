import pandas as pd
import numpy as np
from datetime import date
from decimal import Decimal
import calendar
from typing import Dict, List, Optional

# 复用现有的向量化计算和投射引擎
from BBA_dev.projector import CashFlowProjector
from BBA_dev.models.pv_source_data import PVSourceData, PVSourceDataCollection

# 优先尝试使用JIT加速版本
try:
    from BBA_dev.pv_calculator_jit import (
        calculate_pv_exact_jit as calculate_pv_exact_fast,
        calculate_pv_cca_jit as calculate_pv_cca_fast,
        calculate_all_fields_batch_jit
    )
    USE_VECTORIZED_PV = True
    USE_JIT_BATCH = True
except ImportError:
    # 降级使用原始向量化版本
    try:
        from BBA_dev.pv_calculator_vectorized import calculate_pv_exact_fast, calculate_pv_cca_fast
        USE_VECTORIZED_PV = True
        USE_JIT_BATCH = False
    except ImportError:
        USE_VECTORIZED_PV = False
        USE_JIT_BATCH = False

DECIMAL_ZERO = Decimal('0')

# --- 辅助函数 ---

def get_monthly_rate(rates_map: Dict[int, Decimal], term_month: int, max_term: int) -> Decimal:
    if term_month <= 0: return Decimal('0')
    if term_month > max_term: return rates_map.get(max_term, Decimal('0'))
    return rates_map.get(term_month, Decimal('0'))

def set_cf_dates_for_initial_recognition(cf_df, uw_date, col_name):
    cf_df = cf_df.copy()
    uw_year_month = (uw_date.year, uw_date.month)
    is_premium_or_iacf = (col_name in ['Premium', 'IACF'])
    date_list = []
    for _, row in cf_df.iterrows():
        yyyymm = str(row['YYYYMM'])
        cf_year = int(yyyymm[:4])
        cf_month = int(yyyymm[4:6])
        if (cf_year, cf_month) == uw_year_month:
            if is_premium_or_iacf:
                date_list.append(date(cf_year, cf_month, 15))
            else:
                _, last_day = calendar.monthrange(cf_year, cf_month)
                date_list.append(date(cf_year, cf_month, last_day))
        else:
            _, last_day = calendar.monthrange(cf_year, cf_month)
            date_list.append(date(cf_year, cf_month, last_day))
    cf_df['Date_Obj'] = date_list
    return cf_df

def calculate_pv_initial_recognition_core(cf_df, col_name, rates_map, max_term, uw_date):
    """核心初始确认折现逻辑（优先使用JIT加速）"""
    # 尝试使用JIT加速版本
    if USE_JIT_BATCH:
        try:
            from BBA_dev.pv_calculator_jit import calculate_pv_initial_recognition_jit
            
            # 提取数据为NumPy数组
            amounts = cf_df[col_name].values.astype(np.float64)
            dates = cf_df['Date_Obj'].values
            dates_years = np.array([d.year for d in dates], dtype=np.int32)
            dates_months = np.array([d.month for d in dates], dtype=np.int32)
            dates_days = np.array([d.day for d in dates], dtype=np.int32)
            
            # 构建利率数组
            rates_array = np.zeros(max_term + 1, dtype=np.float64)
            for term, rate in rates_map.items():
                if 0 < term <= max_term:
                    rates_array[term] = float(rate)
            
            is_prem_iacf = (col_name in ['Premium', 'IACF'])
            
            # JIT加速计算
            pv_float = calculate_pv_initial_recognition_jit(
                amounts, dates_years, dates_months, dates_days,
                uw_date.year, uw_date.month, uw_date.day,
                rates_array, max_term, is_prem_iacf
            )
            return Decimal(str(pv_float))
        except Exception:
            pass  # 降级使用原始Decimal版本
    
    # 原始Decimal版本（降级路径）
    total_pv = Decimal('0')
    uw_year_month = (uw_date.year, uw_date.month)
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0: continue
        
        cf_date = row['Date_Obj']
        
        from dateutil.relativedelta import relativedelta
        rd = relativedelta(cf_date, uw_date)
        idx_cf = rd.years * 12 + rd.months
        
        factor = Decimal('1.0')
        
        cf_yyyymm = str(row['YYYYMM'])
        cf_year = int(cf_yyyymm[:4])
        cf_month = int(cf_yyyymm[4:6])
        is_uw_month = ((cf_year, cf_month) == uw_year_month)
        is_prem_iacf = (col_name in ['Premium', 'IACF'])

        if is_uw_month:
            if is_prem_iacf:
                factor = Decimal('1.0')
            else:
                r1 = get_monthly_rate(rates_map, 1, max_term)
                factor = Decimal('1.0') / (Decimal('1.0') + r1 / Decimal('2'))
        else:
            if idx_cf <= 0:
                factor = Decimal('1.0')
            else:
                r1 = get_monthly_rate(rates_map, 1, max_term)
                factor = Decimal('1.0') / (Decimal('1.0') + r1 / Decimal('2'))
                for t in range(2, idx_cf + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
        
        total_pv += amount * factor
    return total_pv

def calculate_pv_core(policy_row: pd.Series, assumptions_map: Dict[str, object], rates_map: Dict[str, pd.DataFrame]):
    """
    PV计算核心入口 (完整版)
    
    Args:
        policy_row: 保单数据行
        assumptions_map: 字典 { 'YYYYMM': Assumptions对象 }
        rates_map: 字典 { 'YYYYMM': Rates_DataFrame }
    
    Returns:
        PVSourceDataCollection 对象
    """
    policy_no = policy_row['policy_no']
    pv_collection = PVSourceDataCollection(policy_no=policy_no)
    
    # 1. 基础变量
    uw_date = pd.to_datetime(policy_row["under_write_date"]).date()
    
    # 确定评估时点
    val_months = [(uw_date, "初始确认评估月")]
    if uw_date.year <= 2024:
        val_months.append((date(uw_date.year, 12, 31), f"{uw_date.year}年年底"))
    for year in range(uw_date.year + 1, 2025):
        val_months.append((date(year, 1, 1), f"{year}年年初"))
        val_months.append((date(year, 12, 31), f"{year}年年底"))
        
    projector = CashFlowProjector()
    
    # 缓存上年现金流 (用于BOP计算)
    bop_cf_by_year = {}

    # 辅助计算函数
    def calc_all(cf_subset, val_d, curve_base_d, rates, ra_ratio):
        """计算所有字段的PV (Exact)"""
        if not USE_VECTORIZED_PV:
            return {}
        
        # 优化：如果有JIT批量计算，一次性计算所有字段（避免重复折现因子计算）
        if USE_JIT_BATCH and not cf_subset.empty:
            try:
                fields = ['Premium', 'IACF', 'Claims', 'Expenses']
                pv_dict = calculate_all_fields_batch_jit(cf_subset, fields, rates, val_d, curve_base_d)
                pre = pv_dict['Premium']
                acq = pv_dict['IACF']
                cla = pv_dict['Claims']
                mtn = pv_dict['Expenses']
            except Exception:
                # 降级使用逐字段计算
                pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
                acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
                cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
                mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            # 标准逐字段计算
            pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        
        rad = (cla + mtn) * ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    def calc_all_cca(cf_subset, val_d, curve_base_d, rates, ra_ratio):
        """计算所有字段的PV (CCA - Current Period)"""
        if USE_VECTORIZED_PV:
            pre = calculate_pv_cca_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_cca_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_cca_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_cca_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            return {}
        rad = (cla + mtn) * ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    def calc_all_beg_lcu(cf_subset, bop_d, rates, ra_ratio):
        """计算所有字段的PV (Beg - LCU)"""
        # 使用 calculate_pv_exact_fast，将 valuation_date 和 curve_base_date 都设为 bop_d
        # 这会触发 'current curve' 逻辑：term = 1, 2, ... 从 bop_d 开始
        if not USE_VECTORIZED_PV:
            return {}
        
        # 优化：批量计算
        if USE_JIT_BATCH and not cf_subset.empty:
            try:
                fields = ['Premium', 'IACF', 'Claims', 'Expenses']
                pv_dict = calculate_all_fields_batch_jit(cf_subset, fields, rates, bop_d, bop_d)
                pre = pv_dict['Premium']
                acq = pv_dict['IACF']
                cla = pv_dict['Claims']
                mtn = pv_dict['Expenses']
            except Exception:
                pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, bop_d, bop_d)
                acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, bop_d, bop_d)
                cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, bop_d, bop_d)
                mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, bop_d, bop_d)
        else:
            pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, bop_d, bop_d)
            acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, bop_d, bop_d)
            cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, bop_d, bop_d)
            mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, bop_d, bop_d)
        
        rad = (cla + mtn) * ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    def calc_bop_cca_rep(cf_subset, val_d, curve_base_d, rates, val_ra_ratio):
        """计算年初预期当期：已过去月份取原值，未来月份折现"""
        if cf_subset.empty:
            return {f"_Pre_Amt": DECIMAL_ZERO, f"_Acq_Amt": DECIMAL_ZERO, f"_Cla_Amt": DECIMAL_ZERO, f"_Mtn_Amt": DECIMAL_ZERO, f"_Rad_Amt": DECIMAL_ZERO}
        
        # 优化：使用searchsorted代替布尔索引
        dates = cf_subset['Date_Obj'].values
        idx_val = np.searchsorted(dates, val_d, side='left')
        cf_past = cf_subset.iloc[:idx_val].copy()
        cf_future = cf_subset.iloc[idx_val:].copy()
        
        past_pre = Decimal(str(cf_past['Premium'].sum())) if not cf_past.empty and 'Premium' in cf_past.columns else DECIMAL_ZERO
        past_acq = Decimal(str(cf_past['IACF'].sum())) if not cf_past.empty and 'IACF' in cf_past.columns else DECIMAL_ZERO
        past_cla = Decimal(str(cf_past['Claims'].sum())) if not cf_past.empty and 'Claims' in cf_past.columns else DECIMAL_ZERO
        past_mtn = Decimal(str(cf_past['Expenses'].sum())) if not cf_past.empty and 'Expenses' in cf_past.columns else DECIMAL_ZERO
        
        if USE_VECTORIZED_PV:
            future_pre = calculate_pv_exact_fast(cf_future, 'Premium', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
            future_acq = calculate_pv_exact_fast(cf_future, 'IACF', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
            future_cla = calculate_pv_exact_fast(cf_future, 'Claims', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
            future_mtn = calculate_pv_exact_fast(cf_future, 'Expenses', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
        else:
            future_pre = future_acq = future_cla = future_mtn = DECIMAL_ZERO

        pre = past_pre + future_pre
        acq = past_acq + future_acq
        cla = past_cla + future_cla
        mtn = past_mtn + future_mtn
        rad = (cla + mtn) * val_ra_ratio
        
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    # 2. 循环计算
    for val_month_date, val_month_label in val_months:
        val_month_yyyymm = val_month_date.strftime("%Y%m")
        uw_month_yyyymm = uw_date.strftime("%Y%m")
        
        is_new_business = (val_month_date.year == uw_date.year)
        is_bop = (val_month_date.month == 1 and val_month_date.day == 1)
        
        # 获取数据
        assump_val = assumptions_map.get(val_month_yyyymm)
        if not assump_val:
            assump_val = assumptions_map.get(uw_month_yyyymm)
            
        prev_year_end = date(val_month_date.year - 1, 12, 31)
        prev_ye_str = prev_year_end.strftime("%Y%m")
        assump_prev_ye = assumptions_map.get(prev_ye_str)
        if not assump_prev_ye:
            assump_prev_ye = assump_val # Fallback
            
        assump_uw = assumptions_map.get(uw_month_yyyymm, assump_val)

        # 利率
        rate_val_locked = rates_map.get(uw_month_yyyymm)
        rate_val_current = rates_map.get(val_month_yyyymm)
        rate_prev_year_locked = rates_map.get(uw_month_yyyymm) # Locked curve always same base
        # LCU curve (prev year end locked rate? No, LCU uses prev year end curve for valuation)
        # Wait, LCU calculation in pv_calculator.py uses "locked" curve from prev_year_end_month?
        # Actually line 1072 in pv_calculator.py: get_discount_factors("locked", prev_year_end_month)
        # Yes, so we need rate curve for prev_year_end_month
        rate_prev_year_end_curve = rates_map.get(prev_ye_str)

        if rate_val_locked is None or rate_val_current is None:
            continue

        # Rate dict for non-vectorized fallback (Initial Recognition)
        rate_locked_dict = dict(zip(rate_val_locked['term_month'], rate_val_locked['forward_disrate_value'].apply(Decimal)))
        max_term_locked = int(rate_val_locked['term_month'].max()) if not rate_val_locked.empty else 0

        # 投射现金流
        # 1. UW (Nb)
        cf_uw = projector.project_policy_flows(policy_row, assump_uw)
        # 日期修正 (月末) - 确保排序
        cf_uw['Date_Obj'] = (pd.to_datetime(cf_uw['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
        cf_uw = cf_uw.sort_values('Date_Obj').reset_index(drop=True)  # 优化：确保排序
        
        # 2. Prev YE (BOP)
        cf_prev_ye = projector.project_policy_flows(policy_row, assump_prev_ye)
        cf_prev_ye['Date_Obj'] = (pd.to_datetime(cf_prev_ye['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
        cf_prev_ye = cf_prev_ye.sort_values('Date_Obj').reset_index(drop=True)  # 优化：确保排序
        if not is_new_business:
            bop_cf_by_year[val_month_date.year] = cf_prev_ye
        
        # 3. Val (EOP)
        cf_val = projector.project_policy_flows(policy_row, assump_val)
        cf_val['Date_Obj'] = (pd.to_datetime(cf_val['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
        cf_val = cf_val.sort_values('Date_Obj').reset_index(drop=True)  # 优化：确保排序
        
        # Split Logic - 优化：使用numpy searchsorted代替布尔索引
        val_month_end = val_month_date
        year_start = date(val_month_date.year, 1, 1)
        
        # Split UW - 使用searchsorted（O(log n) vs O(n)）
        if not cf_uw.empty:
            dates_uw = cf_uw['Date_Obj'].values
            idx_year_start = np.searchsorted(dates_uw, year_start, side='left')
            idx_val_end = np.searchsorted(dates_uw, val_month_end, side='right')
            cf_uw_current = cf_uw.iloc[idx_year_start:idx_val_end].copy()
            cf_uw_future = cf_uw.iloc[idx_val_end:].copy()
        else:
            cf_uw_current = cf_uw.copy()
            cf_uw_future = cf_uw.copy()
        
        # Split Val - 使用searchsorted
        if not cf_val.empty:
            dates_val = cf_val['Date_Obj'].values
            idx_year_start_val = np.searchsorted(dates_val, year_start, side='left')
            idx_val_end_val = np.searchsorted(dates_val, val_month_end, side='right')
            cf_val_current = cf_val.iloc[idx_year_start_val:idx_val_end_val].copy()
            cf_val_future = cf_val.iloc[idx_val_end_val:].copy()
        else:
            cf_val_current = cf_val.copy()
            cf_val_future = cf_val.copy()
        
        results = {}

        # --- New Business (NB) ---
        if is_new_business:
            # 1. Nb_Ini_Rec
            uw_mid = date(uw_date.year, uw_date.month, 15)
            for col in ['Premium', 'IACF', 'Claims', 'Expenses']:
                cf_temp = set_cf_dates_for_initial_recognition(cf_uw, uw_date, col)
                val = calculate_pv_initial_recognition_core(cf_temp, col, rate_locked_dict, max_term_locked, uw_date)
                prefix = "Pvfl_Nb_Ini_Cfa_Rec_Lkd"
                field_map = {'Premium': 'Pre', 'IACF': 'Acq', 'Claims': 'Cla', 'Expenses': 'Mtn'}
                results[f"{prefix}_{field_map[col]}_Amt"] = val
            results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt"] = (results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt"] + results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt"]) * assump_uw.ra_ratio

            # 2. Nb_Ini_Rep
            # Cca
            res_cca = calc_all_cca(cf_uw_current, val_month_end, uw_date, rate_val_locked, assump_uw.ra_ratio)
            for k, v in res_cca.items(): results[f"Pvfl_Nb_Ini_Cca_Rep_Wlk{k}"] = v
            # Cfa
            res_cfa = calc_all(cf_uw_future, val_month_end, uw_date, rate_val_locked, assump_uw.ra_ratio)
            for k, v in res_cfa.items(): results[f"Pvfl_Nb_Ini_Cfa_Rep_Wlk{k}"] = v

            # 3. Nb_Eop_Rep
            # Cfa Wlk
            res_eop_wlk = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k, v in res_eop_wlk.items(): results[f"Pvfl_Nb_Eop_Cfa_Rep_Wlk{k}"] = v
            # Cca Wlk
            res_eop_cca = calc_all_cca(cf_val_current, val_month_end, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k, v in res_eop_cca.items(): results[f"Pvfl_Nb_Eop_Cca_Rep_Wlk{k}"] = v
            # Cfa Cur
            res_eop_cur = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current, assump_val.ra_ratio)
            for k, v in res_eop_cur.items(): results[f"Pvfl_Nb_Eop_Cfa_Rep_Cur{k}"] = v

        else:
            # Fill zeros for NB fields
            nb_fields = [
                "Pvfl_Nb_Ini_Cfa_Rec_Lkd", "Pvfl_Nb_Ini_Cca_Rep_Wlk", "Pvfl_Nb_Ini_Cfa_Rep_Wlk",
                "Pvfl_Nb_Eop_Cfa_Rep_Wlk", "Pvfl_Nb_Eop_Cca_Rep_Wlk", "Pvfl_Nb_Eop_Cfa_Rep_Cur"
            ]
            suffixes = ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]
            for pf in nb_fields:
                for sf in suffixes:
                    results[f"{pf}{sf}"] = DECIMAL_ZERO

        # --- In Force (IF) ---
        # 定义 suffixes 供 IF 字段填零使用
        suffixes = ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]
        
        if is_new_business:
            # IF fields are zero
            if_fields = [
                "Pvfl_If_Bop_Cca_Rep_Wlk", "Pvfl_If_Bop_Cfa_Rep_Wlk", "Pvfl_If_Bop_Cfa_Beg_Lcu",
                "Pvfl_If_Bop_Cfa_Beg_Wlk", "Pvfl_If_Eop_Cfa_Rep_Wlk", "Pvfl_If_Eop_Cca_Rep_Wlk",
                "Pvfl_If_Eop_Cfa_Rep_Cur"
            ]
            for pf in if_fields:
                for sf in suffixes:
                    results[f"{pf}{sf}"] = DECIMAL_ZERO
        else:
            bop_date = date(val_month_date.year, 1, 1)
            cf_bop = bop_cf_by_year.get(val_month_date.year, cf_prev_ye)
            
            # 优化：使用searchsorted代替布尔索引
            if not cf_bop.empty:
                dates_bop = cf_bop['Date_Obj'].values
                idx_year_start_bop = np.searchsorted(dates_bop, year_start, side='left')
                idx_val_end_bop = np.searchsorted(dates_bop, val_month_end, side='right')
                cf_bop_current = cf_bop.iloc[idx_year_start_bop:idx_val_end_bop].copy()
                cf_bop_future = cf_bop.iloc[idx_val_end_bop:].copy()
                cf_bop_beg = cf_bop.iloc[idx_year_start_bop:].copy()
            else:
                cf_bop_current = cf_bop.copy()
                cf_bop_future = cf_bop.copy()
                cf_bop_beg = cf_bop.copy()

            # 1. If_Bop_Cca_Rep
            res_bop_cca = calc_bop_cca_rep(cf_bop_current, val_month_end, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k, v in res_bop_cca.items(): results[f"Pvfl_If_Bop_Cca_Rep_Wlk{k}"] = v
            
            # 2. If_Bop_Cfa_Rep
            res_bop_cfa = calc_all(cf_bop_future, val_month_end, uw_date, rate_val_locked, assump_prev_ye.ra_ratio)
            for k, v in res_bop_cfa.items(): results[f"Pvfl_If_Bop_Cfa_Rep_Wlk{k}"] = v
            
            # 3. If_Bop_Cfa_Beg_Lcu & Wlk
            if rate_prev_year_end_curve is not None:
                res_beg_lcu = calc_all_beg_lcu(cf_bop_beg, bop_date, rate_prev_year_end_curve, assump_val.ra_ratio)
                # Keep Cla, Mtn, Rad
                for k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                     results[f"Pvfl_If_Bop_Cfa_Beg_Lcu{k}"] = res_beg_lcu.get(k, DECIMAL_ZERO)
            
            res_beg_wlk = calc_all(cf_bop_beg, bop_date, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                 results[f"Pvfl_If_Bop_Cfa_Beg_Wlk{k}"] = res_beg_wlk.get(k, DECIMAL_ZERO)

            # 4. If_Eop_Cfa_Rep
            res_eop_cfa_wlk = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k, v in res_eop_cfa_wlk.items(): results[f"Pvfl_If_Eop_Cfa_Rep_Wlk{k}"] = v
            
            # 5. If_Eop_Cca_Rep
            cf_eop_cca_src = cf_bop_current if is_bop else cf_val_current
            res_eop_cca = calc_bop_cca_rep(cf_eop_cca_src, val_month_end, uw_date, rate_val_locked, assump_val.ra_ratio)
            for k, v in res_eop_cca.items(): results[f"Pvfl_If_Eop_Cca_Rep_Wlk{k}"] = v

            # 6. If_Eop_Cfa_Rep_Cur
            res_eop_cfa_cur = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current, assump_val.ra_ratio)
            for k, v in res_eop_cfa_cur.items(): results[f"Pvfl_If_Eop_Cfa_Rep_Cur{k}"] = v

        # 3. 构造 PVSourceData
        pv_obj = PVSourceData(
            policy_no=policy_no,
            valuation_month=val_month_yyyymm,
            valuation_date=val_month_date,
            under_write_date=uw_date,
            pv_fields=results,
            metadata={'is_reversal_policy': False} 
        )
        pv_collection.add_data(pv_obj)

    return pv_collection
