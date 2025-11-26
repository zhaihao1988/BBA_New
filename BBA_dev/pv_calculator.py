"""
Step 2 - PV Validator (Corrected Logic)

Target Policy: 1440003000004501220200000006
Corrections:
1. Precise Discounting: Date-based calculation (Accumulate Past / Discount Future).
2. Rate Extrapolation: Handle terms beyond curve length.
3. Full Fields: Added RAD (Risk Adjustment) and all requested breakdown fields.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
import calendar

import pandas as pd
import numpy as np
from datetime import date, datetime
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Optional, Sequence

# Ensure project root is importable when running as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local Imports
from BBA_dev.projector import CashFlowProjector
from BBA_dev.assumptions import get_discount_factors
from BBA_dev.data_loader import load_full_data
from BBA_dev.data_access.loader import get_assumptions as fetch_assumptions_from_db
from BBA_dev.models.pv_source_data import PVSourceData, PVSourceDataCollection

# Setup Logging
logger = logging.getLogger("pv_validator")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Configuration - 从config读取保单号
from BBA_dev.config import POLICY_NO
TARGET_POLICY_NO = POLICY_NO
TARGET_RUN_DATE = None
TARGET_VAL_METHOD = None
TARGET_CERTI_NO = None
TARGET_VAL_MONTH_FILTER = None  # Optional[List[str]] in 'YYYYMM' format
DECIMAL_ZERO = Decimal('0')
FIELD_NAME_WIDTH = 50
VALUE_WIDTH = 15
DESC_HEADER = "中文描述"

SEGMENT_TRANSLATIONS = {
    "Nb": "新增合同",
    "If": "有效合同",
    "Ini": "初始确认",
    "Bop": "年初预期",
    "Eop": "期末预期",
    "Cca": "预期当期",
    "Cfa": "预期未来",
    "Rec": "初始确认现值",
    "Rep": "期末现值",
    "Lkd": "当月初始利率",
    "Wlk": "加权初始确认利率",
    "Cur": "期末利率",
    "Pre": "保费现金流",
    "Acq": "保险获取现金流",
    "Cla": "赔付现金流",
    "Mtn": "维持费用现金流",
    "Rad": "未到期非金融风险调整",
    "Ors": "新增当期过去合同",
    "Exr": "经验调整",
    "Surre": "退保合同",
}


def describe_field(field_name: str) -> str:
    parts = field_name.split("_")
    desc_parts: List[str] = []
    for part in parts:
        translated = SEGMENT_TRANSLATIONS.get(part)
        if translated:
            desc_parts.append(translated)
    return " - ".join(desc_parts) if desc_parts else ""

# --- Helper Functions ---

def get_real_policy_data(policy_no: str, certi_no: Optional[str] = None) -> pd.Series:
    df = load_full_data(
        run_date=TARGET_RUN_DATE,
        val_method=TARGET_VAL_METHOD,
        unit_ids=None,
        limit=None
    )
    subset = df[df["policy_no"] == policy_no]
    if certi_no is not None:
        if "certi_no" not in subset.columns:
            raise ValueError("合同数据缺少 certi_no 字段，无法按批单号筛选。")
        subset = subset[subset["certi_no"].astype(str) == str(certi_no)]
    else:
        if "certi_no" in subset.columns:
            subset = subset[subset["certi_no"].isna()]
    if subset.empty:
        raise ValueError(f"Policy {policy_no} not found in DB.")
    return subset.iloc[0]

def get_real_assumptions(class_code: str, valuation_month: str, val_method: str = "7") -> object:
    assump = fetch_assumptions_from_db(class_code, valuation_month, val_method=val_method)
    if assump is None:
        raise RuntimeError(
            f"未在 conf_measure_actuarial_assumption 中找到 class_code={class_code}, "
            f"val_month={valuation_month}, val_method={val_method} 的精算假设，请确认配置。"
        )
    from types import SimpleNamespace
    return SimpleNamespace(
        loss_ratio=assump["loss_ratio"],
        claim_expense_ratio=assump.get("indirect_claims_expense_ratio") or Decimal("0"),
        maintenance_expense_ratio=assump["maintenance_expense_ratio"],
        ra_ratio=assump["ra_ratio"],
        acquisition_expense_ratio=assump.get("acquisition_expense_ratio"),
    )

def get_monthly_rate(rates_map: Dict[int, Decimal], term_month: int, max_term: int) -> Decimal:
    """
    Get forward rate for a specific term.
    Extrapolate using the last available rate if term exceeds max_term.
    """
    if term_month <= 0:
        return Decimal('0') # Rate at t=0 is usually irrelevant for forward step, or 0
    
    if term_month > max_term:
        return rates_map.get(max_term, Decimal('0'))
    
    return rates_map.get(term_month, Decimal('0'))

def calculate_pv_exact(
    cf_df: pd.DataFrame, 
    col_name: str, 
    rates_df: pd.DataFrame, 
    valuation_date: date,
    curve_base_date: date
) -> Decimal:
    """
    Precise PV Calculation based on Date Differences.
    
    Args:
        cf_df: Cash flow DataFrame with 'Date_Obj' column.
        col_name: Value column to discount.
        rates_df: Rate curve (term_month -> forward_rate).
        valuation_date: The date to which we are discounting/accumulating (Target).
        curve_base_date: The T=0 date of the rate curve.
            - For locked curve: UW Date (签单日期)
            - For current curve: Valuation Date (评估日期，此时curve_base_date == valuation_date)
    
    重要规则：
        - Locked curve: term_month = (现金流日期 - 签单日期) 的月数差
        - Current curve: term_month 从1开始（从评估日期开始的第一期、第二期...）
    """
    total_pv = Decimal('0')
    
    # Pre-process rates into a fast lookup map
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    # 判断是 current curve 还是 locked curve
    # 如果 curve_base_date == valuation_date，说明是 current curve
    is_current_curve = (curve_base_date == valuation_date)
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
            
        cf_date = row['Date_Obj']
        
        if cf_date == valuation_date:
            total_pv += amount
            continue
        
        # Calculate Factor
        factor = Decimal('1.0')
        
        if is_current_curve:
            # Current curve: term_month 从1开始（从评估日期开始的第一期、第二期...）
            # 计算从评估日期到现金流日期的月数差
            rd = relativedelta(cf_date, valuation_date)
            months_diff = rd.years * 12 + rd.months
            
            if months_diff > 0:
                # Discounting: Future -> Present
                # term_month 从1开始：第1期、第2期...第months_diff期
                for t in range(1, months_diff + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            elif months_diff < 0:
                # Accumulation: Past -> Present
                # term_month 从1开始：第1期、第2期...第|months_diff|期
                for t in range(1, abs(months_diff) + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
        else:
            # Locked curve: term_month = (现金流日期 - 签单日期) 的月数差
            def get_month_idx(d):
                rd = relativedelta(d, curve_base_date)
                return rd.years * 12 + rd.months
            
            idx_cf = get_month_idx(cf_date)
            idx_val = get_month_idx(valuation_date)
            
            if cf_date > valuation_date:
                # Discounting: Future -> Present
                # Range: (idx_val + 1) to idx_cf
                start_step = max(1, idx_val + 1)
                end_step = idx_cf
                
                for t in range(start_step, end_step + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            elif cf_date < valuation_date:
                # Accumulation: Past -> Present
                # Range: (idx_cf + 1) to idx_val
                start_step = max(1, idx_cf + 1)
                end_step = idx_val
                
                for t in range(start_step, end_step + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
        
        total_pv += amount * factor
        
    return total_pv

def calculate_pv_current_period_no_interest_after_occurrence(
    cf_df: pd.DataFrame, 
    col_name: str, 
    rates_df: pd.DataFrame, 
    valuation_date: date,
    curve_base_date: date
) -> Decimal:
    """
    Calculate PV for "Current Period - End of Period" metrics with special rule:
    - If cash flow occurs in or before the valuation month, use original value (no interest)
    - If cash flow occurs after the valuation month, discount to valuation date
    
    This is for fields like: Pvfl_Nb_Ini_Cca_Rep_* (预期当期-期末现值)
    
    Args:
        cf_df: Cash flow DataFrame with 'Date_Obj' column.
        col_name: Value column to discount.
        rates_df: Rate curve (term_month -> forward_rate).
        valuation_date: The valuation month end date (e.g., 2020-12-31).
        curve_base_date: The T=0 date of the rate curve.
            - For locked curve: UW Date (签单日期)
            - For current curve: Valuation Date (评估日期，此时curve_base_date == valuation_date)
    
    重要规则：
        - Locked curve: term_month = (现金流日期 - 签单日期) 的月数差
        - Current curve: term_month 从1开始（从评估日期开始的第一期、第二期...）
    """
    total_pv = Decimal('0')
    
    # Get valuation month (YYYYMM format for comparison)
    val_year_month = (valuation_date.year, valuation_date.month)
    
    # Pre-process rates into a fast lookup map
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    # 判断是 current curve 还是 locked curve
    is_current_curve = (curve_base_date == valuation_date)
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
            
        cf_date = row['Date_Obj']
        cf_year_month = (cf_date.year, cf_date.month)
        
        # Special rule: If cash flow occurs in or before valuation month, use original value
        if cf_year_month <= val_year_month:
            # Cash flow has already occurred, use original value (no interest)
            total_pv += amount
        else:
            # Cash flow occurs after valuation month, discount to valuation date
            if cf_date == valuation_date:
                total_pv += amount
                continue
            
            # Discount from cf_date to valuation_date
            factor = Decimal('1.0')
            
            if is_current_curve:
                # Current curve: term_month 从1开始（从评估日期开始的第一期、第二期...）
                rd = relativedelta(cf_date, valuation_date)
                months_diff = rd.years * 12 + rd.months
                
                if months_diff > 0:
                    # term_month 从1开始：第1期、第2期...第months_diff期
                    for t in range(1, months_diff + 1):
                        r = get_monthly_rate(rates_map, t, max_term)
                        factor /= (Decimal('1.0') + r)
            else:
                # Locked curve: term_month = (现金流日期 - 签单日期) 的月数差
                def get_month_idx(d):
                    rd = relativedelta(d, curve_base_date)
                    return rd.years * 12 + rd.months
                
                idx_cf = get_month_idx(cf_date)
                idx_val = get_month_idx(valuation_date)
                
                start_step = max(1, idx_val + 1)
                end_step = idx_cf
                
                for t in range(start_step, end_step + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            
            total_pv += amount * factor
        
    return total_pv

# --- Main Logic ---

def main():
    # 1. Fetch Data
    try:
        policy_row = get_real_policy_data(TARGET_POLICY_NO, certi_no=TARGET_CERTI_NO)
    except Exception as e:
        logger.error(f"Failed to load policy: {e}")
        return None

    uw_date = pd.to_datetime(policy_row["under_write_date"]).date()
    val_date = date(uw_date.year, 12, 31) # EOP
    
    # 2. Assumptions & Rates
    assump_obj = get_real_assumptions(policy_row["class_code"], val_date.strftime("%Y%m"))
    
    rate_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
    rate_current_df = get_discount_factors("current", val_date.strftime("%Y%m"))
    
    print("\n" + "="*80)
    print("POLICY RAW DATA (DB) — 核对关键信息")
    print("="*80)
    policy_display_cols = [
        "policy_no",
        "risk_code",
        "class_code",
        "under_write_date",
        "start_date",
        "warranty_end_date",
        "end_date",
        "premium",
        "iacf_amount",
    ]
    policy_subset = policy_row[policy_display_cols].to_frame().T
    print(policy_subset.to_string(index=False))

    print("\n" + "="*80)
    print("ACTUARIAL ASSUMPTIONS — 精算假设核对")
    print("="*80)
    print(
        f"Loss Ratio={assump_obj.loss_ratio}, "
        f"Claim Expense Ratio={assump_obj.claim_expense_ratio}, "
        f"Maintenance Expense Ratio={assump_obj.maintenance_expense_ratio}, "
        f"RA Ratio={assump_obj.ra_ratio}, "
        f"Acq Expense Ratio={assump_obj.acquisition_expense_ratio}"
    )

    def print_rate_curve(df: pd.DataFrame, title: str):
        print("\n" + "-"*80)
        print(title)
        print("-"*80)
        if df.empty:
            print("Curve is empty!")
        else:
            print(
                df.to_string(
                    columns=["term_month", "forward_disrate_value"],
                    index=False
                )
            )
            print(f"—— 共 {len(df)} 个期限 ——")

    print_rate_curve(rate_locked_df, f"LOCKED CURVE ({uw_date.strftime('%Y%m')})")
    print_rate_curve(rate_current_df, f"CURRENT CURVE ({val_date.strftime('%Y%m')})")

    # 3. Project Cash Flows
    projector = CashFlowProjector()
    full_cf_df = projector.project_policy_flows(policy_row, assump_obj)
    full_cf_df['Date_Obj'] = pd.to_datetime(full_cf_df['YYYYMM'], format='%Y%m').dt.date
    
    # Split Contexts
    # "Ini" Context: Valuation Date = UW Date
    # "Eop" Context: Valuation Date = End of Year
    # "Future" relative to Ini: All flows after UW Date
    # "Future" relative to Eop: All flows after EOP Date
    
    # But the requested fields are simpler:
    # "预期当期 (Current Period)": Flows in Year 0 (Sign Year)
    # "预期未来 (Future Period)": Flows in Year 1+
    
    cf_current_period = full_cf_df[full_cf_df['Year'] == uw_date.year]
    cf_future_period = full_cf_df[full_cf_df['Year'] > uw_date.year]
    
    # Print CF Preview
    print("\n" + "="*50)
    print("CASH FLOW PREVIEW (First 12 Months)")
    print(full_cf_df.head(12).to_string(columns=['YYYYMM', 'Premium', 'IACF', 'Claims', 'Expenses']))
    
    # 4. Calculate PVs for each valuation month
    # Each valuation month should have both Rec (initial recognition) and Rep (end of period) metrics
    
    def calc_all(cf_subset, val_d, curve_base_d, rates, label_suffix):
        """Helper to calc Pre, Acq, Cla, Mtn, Rad for a specific subset and curve"""
        pre = calculate_pv_exact(cf_subset, 'Premium', rates, val_d, curve_base_d)
        acq = calculate_pv_exact(cf_subset, 'IACF', rates, val_d, curve_base_d)
        cla = calculate_pv_exact(cf_subset, 'Claims', rates, val_d, curve_base_d)
        mtn = calculate_pv_exact(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        
        # RAD Calculation: (PV_Claims + PV_Maint) * RA_Ratio
        # Note: RAD is usually based on Outflows only.
        rad = (cla + mtn) * assump_obj.ra_ratio
        
        return {
            f"_Pre_Amt": pre,
            f"_Acq_Amt": acq,
            f"_Cla_Amt": cla,
            f"_Mtn_Amt": mtn,
            f"_Rad_Amt": rad
        }

    # Define valuation months: 
    # 1. 签单月（初始确认）
    # 2. 后续每年年初（1月1日，用于生成年初预期的PV数据）
    # 3. 从签单年开始的各年年底（12月31日，用于生成期末预期的PV数据）
    val_months = [
        (uw_date, "初始确认评估月"),
    ]
    # 添加签单年年底
    if uw_date.year <= 2024:
        val_months.append((date(uw_date.year, 12, 31), f"{uw_date.year}年年底"))
    # 添加后续每年年初和年底到2024年
    for year in range(uw_date.year + 1, 2025):  # 2025不包含，所以到2024年
        val_months.append((date(year, 1, 1), f"{year}年年初"))  # 年初，用于生成年初预期的PV数据
        val_months.append((date(year, 12, 31), f"{year}年年底"))  # 年底，用于生成期末预期的PV数据

    if TARGET_VAL_MONTH_FILTER:
        normalized_targets = {m.replace("-", "") for m in TARGET_VAL_MONTH_FILTER}
        filtered_val_months = [
            (month_date, label)
            for (month_date, label) in val_months
            if month_date.strftime("%Y%m") in normalized_targets
        ]
        if not filtered_val_months:
            raise ValueError(f"指定的评估月份 {TARGET_VAL_MONTH_FILTER} 在生成列表中不存在。")
        val_months = filtered_val_months
    
    all_results = {}
    # Create PV source data collection to store all calculated PV metrics
    pv_source_collection = PVSourceDataCollection(policy_no=TARGET_POLICY_NO)
    
    # 存储每年年初的现金流（基于上年年底的精算假设）
    # key: year (int), value: DataFrame
    bop_cf_by_year = {}
    
    last_current_curve = None

    for val_month_date, val_month_label in val_months:
        val_month_str = val_month_date.strftime("%Y-%m")
        # Calculate last day of the month
        _, last_day = calendar.monthrange(val_month_date.year, val_month_date.month)
        val_month_end = date(val_month_date.year, val_month_date.month, last_day)
        
        # Get rate curves for this valuation month
        val_month_yyyymm = val_month_date.strftime("%Y%m")
        rate_val_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
        
        # 尝试获取当前评估月的利率曲线，如果不存在则报错
        try:
            rate_val_current_df = get_discount_factors("current", val_month_yyyymm)
        except RuntimeError as e:
            raise RuntimeError(f"评估月 {val_month_yyyymm} 缺少 current 曲线，无法继续生成PV原材料。") from e
        
        # 判断是否为签单年度
        is_new_business = (val_month_date.year == uw_date.year)
        
        # 重要：Nb字段只在签单年度有值，非签单年度应该为0
        # 但为了保持数据结构一致性，我们仍然会生成这些字段，只是值设为0
        
        # 获取精算假设
        # 对于年初（1月1日），使用上年年底的精算假设
        # 对于其他评估月，使用当月的精算假设
        if val_month_date.month == 1 and val_month_date.day == 1:
            # 年初评估使用当前年初的评估月份
            assump_month_str = val_month_yyyymm
        else:
            # 年末等其他评估点使用对应月份
            assump_month_str = val_month_yyyymm
        
        try:
            val_assump_obj = get_real_assumptions(policy_row["class_code"], assump_month_str)
        except RuntimeError as e:
            logger.warning(f"⚠️  警告: 评估月 {assump_month_str} 的精算假设数据不存在，使用默认假设: {e}")
            val_assump_obj = assump_obj  # 使用初始假设作为fallback
        
        # 判断是否为年初（1月1日）
        is_bop = (val_month_date.month == 1 and val_month_date.day == 1)
        
        # 生成现金流
        if is_bop and not is_new_business:
            # 年初：生成基于上年年底精算假设的现金流，并保存
            projector_bop = CashFlowProjector()
            bop_cf_df = projector_bop.project_policy_flows(policy_row, val_assump_obj)
            bop_cf_df['Date_Obj'] = pd.to_datetime(bop_cf_df['YYYYMM'], format='%Y%m').dt.date
            bop_cf_by_year[val_month_date.year] = bop_cf_df
            cf_for_calc = bop_cf_df
        else:
            # 其他评估月：生成基于当月精算假设的现金流（从下月开始）
            projector_eop = CashFlowProjector()
            eop_cf_df = projector_eop.project_policy_flows(policy_row, val_assump_obj)
            eop_cf_df['Date_Obj'] = pd.to_datetime(eop_cf_df['YYYYMM'], format='%Y%m').dt.date
            # 对于期末预期，只使用从下月开始的所有现金流
            next_month_start = date(val_month_date.year, val_month_date.month, 1)
            if val_month_date.month == 12:
                next_month_start = date(val_month_date.year + 1, 1, 1)
            else:
                next_month_start = date(val_month_date.year, val_month_date.month + 1, 1)
            eop_cf_df = eop_cf_df[eop_cf_df['Date_Obj'] >= next_month_start]
            cf_for_calc = eop_cf_df
        
        # 对于新增合同，使用初始现金流
        if is_new_business:
            cf_for_calc = full_cf_df
        
        # Split cash flows: current period (same year as val_month) vs future
        cf_val_current = cf_for_calc[cf_for_calc['Year'] == val_month_date.year]
        cf_val_future = cf_for_calc[cf_for_calc['Year'] > val_month_date.year]
        
        results = {}
        
        # --- NB Initial Recognition (Rec) - only for new business year ---
        # 重要：Nb字段只在签单年度有值，非签单年度应该为0
        if is_new_business:
            # 签单年度：计算新增合同的PV值
            # Ini_Cca (Current Period Flows, discounted to Initial Recognition)
            res_ini_cca = calc_all(cf_val_current, uw_date, uw_date, rate_val_locked_df, "")
            for k, v in res_ini_cca.items():
                results[f"Pvfl_Nb_Ini_Cca_Rec_Lkd{k}"] = v
                results[f"Pvfl_Nb_Ini_Cca_Rec_Wlk{k}"] = v  # Weighted = Locked for single policy
            
            # Ini_Cfa (Future Period Flows, discounted to Initial Recognition)
            res_ini_cfa = calc_all(cf_val_future, uw_date, uw_date, rate_val_locked_df, "")
            for k, v in res_ini_cfa.items():
                results[f"Pvfl_Nb_Ini_Cfa_Rec_Lkd{k}"] = v
                results[f"Pvfl_Nb_Ini_Cfa_Rec_Wlk{k}"] = v
            
            # --- NB Rep (End of Period) - based on val_month_end ---
            # Ini_Cca_Rep (Current Period Flows, rolled to val_month_end using locked curve)
            # Special rule: If CF occurs in or before valuation month, use original value (no interest)
            def calc_all_current_period_rep(cf_subset, val_d, curve_base_d, rates):
                """Helper for Cca_Rep: special logic for current period flows"""
                pre = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Premium', rates, val_d, curve_base_d)
                acq = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'IACF', rates, val_d, curve_base_d)
                cla = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Claims', rates, val_d, curve_base_d)
                mtn = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Expenses', rates, val_d, curve_base_d)
                rad = (cla + mtn) * assump_obj.ra_ratio
                return {
                    f"_Pre_Amt": pre,
                    f"_Acq_Amt": acq,
                    f"_Cla_Amt": cla,
                    f"_Mtn_Amt": mtn,
                    f"_Rad_Amt": rad
                }
            
            res_ini_cca_rep = calc_all_current_period_rep(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
            for k, v in res_ini_cca_rep.items():
                results[f"Pvfl_Nb_Ini_Cca_Rep_Wlk{k}"] = v
            
            # Ini_Cfa_Rep (Future Period Flows, rolled to val_month_end using locked curve)
            res_ini_cfa_rep = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked_df, "")
            for k, v in res_ini_cfa_rep.items():
                results[f"Pvfl_Nb_Ini_Cfa_Rep_Wlk{k}"] = v
            
            # Eop_Cfa_Rep (Future Period Flows, rolled to val_month_end)
            # Wlk (using locked curve from UW date)
            for k, v in res_ini_cfa_rep.items():
                results[f"Pvfl_Nb_Eop_Cfa_Rep_Wlk{k}"] = v
            
            # Eop_Cca_Rep (Current Period Flows, rolled to val_month_end) - 新增：预期当期
            # 用于IFIE计算，需要包含预期当期的期末现值
            res_eop_cca_rep = calc_all_current_period_rep(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
            for k, v in res_eop_cca_rep.items():
                results[f"Pvfl_Nb_Eop_Cca_Rep_Wlk{k}"] = v
            
            # Cur (using current curve from val_month)
            res_eop_cfa_cur = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current_df, "")
            for k, v in res_eop_cfa_cur.items():
                results[f"Pvfl_Nb_Eop_Cfa_Rep_Cur{k}"] = v
            
            # Eop_Cca_Rep_Cur (Current Period Flows, using current curve) - 新增：预期当期（期末利率）
            res_eop_cca_cur = calc_all_current_period_rep(cf_val_current, val_month_end, val_month_end, rate_val_current_df)
            for k, v in res_eop_cca_cur.items():
                results[f"Pvfl_Nb_Eop_Cca_Rep_Cur{k}"] = v
        else:
            # 非签单年度：新增合同的PV值应该为0（因为没有新增合同）
            # 但为了保持数据结构一致性，我们仍然会生成这些字段，只是值设为0
            nb_field_suffixes = [
                "_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"
            ]
            nb_field_prefixes = [
                "Pvfl_Nb_Ini_Cca_Rec_Lkd",
                "Pvfl_Nb_Ini_Cca_Rec_Wlk",
                "Pvfl_Nb_Ini_Cfa_Rec_Lkd",
                "Pvfl_Nb_Ini_Cfa_Rec_Wlk",
                "Pvfl_Nb_Ini_Cca_Rep_Wlk",
                "Pvfl_Nb_Ini_Cfa_Rep_Wlk",
                "Pvfl_Nb_Eop_Cfa_Rep_Wlk",
                "Pvfl_Nb_Eop_Cca_Rep_Wlk",
                "Pvfl_Nb_Eop_Cfa_Rep_Cur",
                "Pvfl_Nb_Eop_Cca_Rep_Cur",
            ]
            for prefix in nb_field_prefixes:
                for suffix in nb_field_suffixes:
                    field_name = f"{prefix}{suffix}"
                    results[field_name] = DECIMAL_ZERO
        
        # --- IF Fields (有效合同PV数据) ---
        # 判断是否为签单年度：签单年 = 评估年 → 新业务，签单年 < 评估年 → 有效合同
        is_new_business = (val_month_date.year == uw_date.year)
        
        if is_new_business:
            # 签单年度：有效合同的PV数据为0（因为此时是新增合同）
            if_required_fields = [
                "Pvfl_If_Bop_Cca_Rep_Wlk_Pre_Amt",
                "Pvfl_If_Bop_Cca_Rep_Wlk_Acq_Amt",
                "Pvfl_If_Bop_Cca_Rep_Wlk_Cla_Amt",
                "Pvfl_If_Bop_Cca_Rep_Wlk_Mtn_Amt",
                "Pvfl_If_Bop_Cca_Rep_Wlk_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Wlk_Pre_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Wlk_Acq_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Wlk_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Wlk_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Wlk_Rad_Amt",
                "Pvfl_If_Bop_Cca_Beg_Lcu_Pre_Amt",
                "Pvfl_If_Bop_Cca_Beg_Lcu_Acq_Amt",
                "Pvfl_If_Bop_Cca_Beg_Lcu_Cla_Amt",
                "Pvfl_If_Bop_Cca_Beg_Lcu_Mtn_Amt",
                "Pvfl_If_Bop_Cca_Beg_Lcu_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Pre_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Acq_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt",
                "Pvfl_If_Bop_Cca_Beg_Wlk_Pre_Amt",
                "Pvfl_If_Bop_Cca_Beg_Wlk_Acq_Amt",
                "Pvfl_If_Bop_Cca_Beg_Wlk_Cla_Amt",
                "Pvfl_If_Bop_Cca_Beg_Wlk_Mtn_Amt",
                "Pvfl_If_Bop_Cca_Beg_Wlk_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Wlk_Pre_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Wlk_Acq_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Wlk_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Wlk_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Wlk_Rad_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Wlk_Pre_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Wlk_Acq_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Wlk_Cla_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Wlk_Mtn_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Wlk_Rad_Amt",
                "Pvfl_If_Eop_Cca_Rep_Wlk_Pre_Amt",
                "Pvfl_If_Eop_Cca_Rep_Wlk_Acq_Amt",
                "Pvfl_If_Eop_Cca_Rep_Wlk_Cla_Amt",
                "Pvfl_If_Eop_Cca_Rep_Wlk_Mtn_Amt",
                "Pvfl_If_Eop_Cca_Rep_Wlk_Rad_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Pre_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Acq_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt",
                "Pvfl_If_Eop_Cca_Rep_Cur_Pre_Amt",
                "Pvfl_If_Eop_Cca_Rep_Cur_Acq_Amt",
                "Pvfl_If_Eop_Cca_Rep_Cur_Cla_Amt",
                "Pvfl_If_Eop_Cca_Rep_Cur_Mtn_Amt",
                "Pvfl_If_Eop_Cca_Rep_Cur_Rad_Amt",
            ]
            for field in if_required_fields:
                if field not in results:
                    results[field] = DECIMAL_ZERO
        else:
            # 非签单年度（第二年及以后）：计算有效合同的PV数据
            # 年初（BOP）：评估年1月1日
            bop_date = date(val_month_date.year, 1, 1)
            
            # 获取年初现金流（基于上年年底的精算假设）
            if val_month_date.year in bop_cf_by_year:
                cf_bop = bop_cf_by_year[val_month_date.year]
            else:
                # 如果没有年初现金流，使用当前现金流（fallback）
                cf_bop = cf_for_calc
            
            # 年初预期当期现金流（BOP_Cca）：评估年当年发生的现金流
            # 关键逻辑：已过去月份取原值，未来月份折现到评估月底
            cf_bop_current = cf_bop[cf_bop['Year'] == val_month_date.year]
            
            # 计算年初预期当期（BOP_Cca）
            # 已过去月份（1月到评估月）：取原值（不计息）
            # 未来月份（评估月+1月到12月）：折现到评估月底
            def calc_bop_cca_rep(cf_subset, val_d, curve_base_d, rates):
                """计算年初预期当期：已过去月份取原值，未来月份折现"""
                if cf_subset.empty:
                    return {
                        f"_Pre_Amt": DECIMAL_ZERO,
                        f"_Acq_Amt": DECIMAL_ZERO,
                        f"_Cla_Amt": DECIMAL_ZERO,
                        f"_Mtn_Amt": DECIMAL_ZERO,
                        f"_Rad_Amt": DECIMAL_ZERO
                    }
                
                # 分离已过去和未来的现金流
                # 注意：val_d是评估月底，已过去月份是指Date_Obj < val_d的月份
                cf_past = cf_subset[cf_subset['Date_Obj'] < val_d].copy()
                cf_future = cf_subset[cf_subset['Date_Obj'] >= val_d].copy()
                
                # 已过去月份：取原值（不计息）
                past_pre = Decimal(str(cf_past['Premium'].sum())) if not cf_past.empty and 'Premium' in cf_past.columns else DECIMAL_ZERO
                past_acq = Decimal(str(cf_past['IACF'].sum())) if not cf_past.empty and 'IACF' in cf_past.columns else DECIMAL_ZERO
                past_cla = Decimal(str(cf_past['Claims'].sum())) if not cf_past.empty and 'Claims' in cf_past.columns else DECIMAL_ZERO
                past_mtn = Decimal(str(cf_past['Expenses'].sum())) if not cf_past.empty and 'Expenses' in cf_past.columns else DECIMAL_ZERO
                
                # 未来月份：折现到评估月底
                future_pre = calculate_pv_exact(cf_future, 'Premium', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                future_acq = calculate_pv_exact(cf_future, 'IACF', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                future_cla = calculate_pv_exact(cf_future, 'Claims', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                future_mtn = calculate_pv_exact(cf_future, 'Expenses', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                
                # 合计
                pre = past_pre + future_pre
                acq = past_acq + future_acq
                cla = past_cla + future_cla
                mtn = past_mtn + future_mtn
                
                # 使用评估月的精算假设计算RA
                rad = (cla + mtn) * val_assump_obj.ra_ratio
                
                return {
                    f"_Pre_Amt": pre,
                    f"_Acq_Amt": acq,
                    f"_Cla_Amt": cla,
                    f"_Mtn_Amt": mtn,
                    f"_Rad_Amt": rad
                }
            
            res_bop_cca = calc_bop_cca_rep(cf_bop_current, val_month_end, uw_date, rate_val_locked_df)
            for k, v in res_bop_cca.items():
                results[f"Pvfl_If_Bop_Cca_Rep_Wlk{k}"] = v
            
            # 年初预期未来现金流（BOP_Cfa）：评估年之后发生的现金流，折现到评估月底
            # 注意：折现时间点是评估月底，不是年初
            cf_bop_future = cf_bop[cf_bop['Year'] > val_month_date.year]
            res_bop_cfa = calc_all(cf_bop_future, val_month_end, uw_date, rate_val_locked_df, "")
            for k, v in res_bop_cfa.items():
                results[f"Pvfl_If_Bop_Cfa_Rep_Wlk{k}"] = v
            
            # --- 新增：年初现值（Beg）字段计算 ---
            # 折现到年初时点（1月1日），使用上年年末的锁定利率曲线（Lcu）
            # 仅针对有效合同年初预期（If_Bop），且仅在年初（is_bop）时计算
            # 注意：这里已经在 is_bop 且 not is_new_business 的分支中，所以不需要再次判断
            # 获取上年年末的锁定利率曲线（上年12月31日）
            # 注意：Lcu使用的是上年年末的锁定利率曲线
            # 锁定利率曲线在签单日确定后保持不变，所以使用签单日的锁定利率曲线
            rate_prev_year_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
            
            # 年初时点（1月1日）
            bop_date = date(val_month_date.year, 1, 1)
            
            # 计算年初预期当期（BOP_Cca）的年初现值（Beg_Lcu）
            # 折现到年初时点（1月1日），使用上年年末锁定利率曲线
            # 1月现金流折现1个月，12月现金流折现12个月
            res_bop_cca_beg = calc_all(cf_bop_current, bop_date, uw_date, rate_prev_year_locked_df, "")
            # 修正RA计算：使用年初时的精算假设（val_assump_obj）
            cla_beg = res_bop_cca_beg.get("_Cla_Amt", DECIMAL_ZERO)
            mtn_beg = res_bop_cca_beg.get("_Mtn_Amt", DECIMAL_ZERO)
            rad_beg = (cla_beg + mtn_beg) * val_assump_obj.ra_ratio
            res_bop_cca_beg["_Rad_Amt"] = rad_beg
            for k, v in res_bop_cca_beg.items():
                results[f"Pvfl_If_Bop_Cca_Beg_Lcu{k}"] = v
            
            # 计算年初预期未来（BOP_Cfa）的年初现值（Beg_Lcu）
            # 折现到年初时点（1月1日），使用上年年末锁定利率曲线
            res_bop_cfa_beg = calc_all(cf_bop_future, bop_date, uw_date, rate_prev_year_locked_df, "")
            # 修正RA计算：使用年初时的精算假设（val_assump_obj）
            cla_beg_fut = res_bop_cfa_beg.get("_Cla_Amt", DECIMAL_ZERO)
            mtn_beg_fut = res_bop_cfa_beg.get("_Mtn_Amt", DECIMAL_ZERO)
            rad_beg_fut = (cla_beg_fut + mtn_beg_fut) * val_assump_obj.ra_ratio
            res_bop_cfa_beg["_Rad_Amt"] = rad_beg_fut
            for k, v in res_bop_cfa_beg.items():
                results[f"Pvfl_If_Bop_Cfa_Beg_Lcu{k}"] = v
            
            # --- 新增：年初现值（Beg_Wlk）字段计算 ---
            # 折现到年初时点（1月1日），使用签单日的锁定利率曲线（加权初始确认利率）
            # 注意：Wlk使用的是签单日的锁定利率曲线，锁定利率在签单日确定后保持不变
            # 计算年初预期当期（BOP_Cca）的年初现值（Beg_Wlk）
            res_bop_cca_beg_wlk = calc_all(cf_bop_current, bop_date, uw_date, rate_val_locked_df, "")
            # RA计算：使用相同维度的赔付+维持费用的值*精算假设中的ra率
            cla_beg_wlk = res_bop_cca_beg_wlk.get("_Cla_Amt", DECIMAL_ZERO)
            mtn_beg_wlk = res_bop_cca_beg_wlk.get("_Mtn_Amt", DECIMAL_ZERO)
            rad_beg_wlk = (cla_beg_wlk + mtn_beg_wlk) * val_assump_obj.ra_ratio
            res_bop_cca_beg_wlk["_Rad_Amt"] = rad_beg_wlk
            for k, v in res_bop_cca_beg_wlk.items():
                results[f"Pvfl_If_Bop_Cca_Beg_Wlk{k}"] = v
            
            # 计算年初预期未来（BOP_Cfa）的年初现值（Beg_Wlk）
            res_bop_cfa_beg_wlk = calc_all(cf_bop_future, bop_date, uw_date, rate_val_locked_df, "")
            # RA计算：使用相同维度的赔付+维持费用的值*精算假设中的ra率
            cla_beg_wlk_fut = res_bop_cfa_beg_wlk.get("_Cla_Amt", DECIMAL_ZERO)
            mtn_beg_wlk_fut = res_bop_cfa_beg_wlk.get("_Mtn_Amt", DECIMAL_ZERO)
            rad_beg_wlk_fut = (cla_beg_wlk_fut + mtn_beg_wlk_fut) * val_assump_obj.ra_ratio
            res_bop_cfa_beg_wlk["_Rad_Amt"] = rad_beg_wlk_fut
            for k, v in res_bop_cfa_beg_wlk.items():
                results[f"Pvfl_If_Bop_Cfa_Beg_Wlk{k}"] = v
            
            # 期末预期未来现金流（EOP_Cfa）：基于评估月精算假设，从下月开始的所有现金流，折现到评估月底
            # Wlk (using locked curve from UW date)
            res_eop_cfa_wlk = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked_df, "")
            for k, v in res_eop_cfa_wlk.items():
                results[f"Pvfl_If_Eop_Cfa_Rep_Wlk{k}"] = v
            
            # 期末预期当期现金流（EOP_Cca）：评估年当年发生的现金流，折现到评估月底 - 新增
            # 用于IFIE计算，需要包含预期当期的期末现值
            # 注意：这里需要区分已过去月份和未来月份
            if is_bop:
                # 年初时：使用年初现金流（cf_bop_current）
                res_eop_cca_wlk = calc_bop_cca_rep(cf_bop_current, val_month_end, uw_date, rate_val_locked_df)
            else:
                # 年末时：使用当前现金流（cf_val_current）
                res_eop_cca_wlk = calc_bop_cca_rep(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
            for k, v in res_eop_cca_wlk.items():
                results[f"Pvfl_If_Eop_Cca_Rep_Wlk{k}"] = v
            
            # Cur (using current curve from val_month)
            res_eop_cfa_cur_if = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current_df, "")
            for k, v in res_eop_cfa_cur_if.items():
                results[f"Pvfl_If_Eop_Cfa_Rep_Cur{k}"] = v
            
            # 期末预期当期现金流（EOP_Cca_Cur）：使用期末利率 - 新增
            if is_bop:
                res_eop_cca_cur_if = calc_bop_cca_rep(cf_bop_current, val_month_end, val_month_end, rate_val_current_df)
            else:
                res_eop_cca_cur_if = calc_bop_cca_rep(cf_val_current, val_month_end, val_month_end, rate_val_current_df)
            for k, v in res_eop_cca_cur_if.items():
                results[f"Pvfl_If_Eop_Cca_Rep_Cur{k}"] = v
        
        # Store results with valuation month prefix (for backward compatibility)
        for key, value in results.items():
            all_results[f"{val_month_str}_{key}"] = value
        
        # Create PVSourceData object for this valuation month
        pv_data = PVSourceData(
            policy_no=TARGET_POLICY_NO,
            valuation_month=val_month_yyyymm,
            valuation_date=val_month_end,
            under_write_date=uw_date,
            pv_fields=results.copy(),
            metadata={
                'valuation_month_label': val_month_label,
                'rate_locked_month': uw_date.strftime("%Y%m"),
                'rate_current_month': val_month_yyyymm,
            }
        )
        pv_source_collection.add_data(pv_data)
        
        # Print Results for this valuation month
        print("\n" + "="*80)
        print(f"RESULTS — {val_month_label} {val_month_str} (评估期末: {val_month_end.strftime('%Y-%m-%d')})")
        print("="*80)
        print(f"{'Field Name':<{FIELD_NAME_WIDTH}} | {'Value':>{VALUE_WIDTH}} | {DESC_HEADER}")
        print("-" * (FIELD_NAME_WIDTH + VALUE_WIDTH + len(DESC_HEADER) + 6))
        
        # Sort for readability
        for key in sorted(results.keys()):
            desc = describe_field(key)
            print(f"{key:<{FIELD_NAME_WIDTH}} | {results[key]:>{VALUE_WIDTH},.2f} | {desc}")
        
        print("="*80)
    
    # Save PV source data to file for reuse by other scripts
    import json
    generated_months = sorted(pv_source_collection.data_by_month.keys())
    certi_part = str(TARGET_CERTI_NO) if TARGET_CERTI_NO else "main"
    if certi_part == "main" and not TARGET_VAL_MONTH_FILTER:
        output_file = f"logs/pv_source_data_{TARGET_POLICY_NO}.json"
    else:
        month_part = "all"
        if generated_months:
            month_part = generated_months[0] if len(generated_months) == 1 else f"{generated_months[0]}_{generated_months[-1]}"
        output_file = f"logs/pv_source_data_{TARGET_POLICY_NO}_{certi_part}_{month_part}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(pv_source_collection.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"\n✅ PV原材料数据已保存至: {output_file}")
    print(f"   包含 {len(pv_source_collection.data_by_month)} 个评估月的数据")
    print(f"   评估月列表: {', '.join(sorted(pv_source_collection.data_by_month.keys()))}")
    
    return pv_source_collection, output_file

if __name__ == "__main__":
    main()