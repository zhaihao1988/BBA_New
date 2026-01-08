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
from BBA_group.projector import CashFlowProjector
from BBA_group.assumptions import get_discount_factors
from BBA_group.data_loader import load_full_data
from BBA_group.data_access.loader import get_assumptions as fetch_assumptions_from_db
from BBA_group.data_access.group_loader import load_policies_by_group
from BBA_group.models.pv_source_data import PVSourceData, PVSourceDataCollection
from BBA_group.models.group_cohort_state import GroupCohortState
from BBA_group.models.group_policy_state import GroupPolicyState
# from BBA_group.logic.group_rates_manager import build_group_rate_curve # Removed: explicit single policy usage

# 向量化计算开关（当前已移除向量化模块，强制关闭）
USE_VECTORIZED_PV = False
calculate_pv_exact_fast = None
calculate_pv_cca_fast = None

# Setup Logging
logger = logging.getLogger("pv_validator")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Configuration - 从config读取保单号
from BBA_group.config import POLICY_NO
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
    "Lkd": "锁定利率", # Renamed/Unified from Wlk/Lkd
    "Lcu": "上年末锁定利率",
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
    """
    total_pv = Decimal('0')
    
    # Pre-process rates into a fast lookup map
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    # 判断是 current curve 还是 locked curve
    # 如果 curve_base_date == valuation_date，说明是 current curve
    is_current_curve = (curve_base_date == valuation_date)
    
    val_date_for_calc = valuation_date
    if valuation_date.day == 1:
        val_date_for_calc = valuation_date - relativedelta(days=1)
    
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
            # Current curve
            rd = relativedelta(cf_date, val_date_for_calc)
            months_diff = rd.years * 12 + rd.months
            
            if months_diff > 0:
                for t in range(1, months_diff + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            elif months_diff < 0:
                for t in range(1, abs(months_diff) + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
        else:
            # Locked curve
            def get_month_idx(d):
                rd = relativedelta(d, curve_base_date)
                return rd.years * 12 + rd.months
            
            idx_cf = get_month_idx(cf_date)
            idx_val = get_month_idx(val_date_for_calc)
            
            if cf_date > valuation_date:
                # Discounting: Future -> Present
                if idx_cf == idx_val:
                    term = idx_cf + 1
                    r = get_monthly_rate(rates_map, term, max_term)
                    factor /= (Decimal('1.0') + r)
                else:
                    start_step = max(1, idx_val + 2)  # +1 for period adjustment
                    end_step = idx_cf + 1  # +1 for period adjustment
                    
                    for t in range(start_step, end_step + 1):
                        r = get_monthly_rate(rates_map, t, max_term)
                        factor /= (Decimal('1.0') + r)
            elif cf_date < valuation_date:
                # Accumulation: Past -> Present
                start_step = max(1, idx_cf + 1)
                end_step = idx_val
                
                for t in range(start_step, end_step + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
        
        total_pv += amount * factor
        
    return total_pv

def calculate_pv_initial_recognition(
    cf_df: pd.DataFrame, 
    col_name: str, 
    rates_df: pd.DataFrame, 
    valuation_date: date,  # 签单月月中（15日）
    curve_base_date: date,  # 签单日期
    uw_date: date,  # 签单日期，用于判断签单月
    start_date: date  # 保险起期，用于倒签单判断
) -> Decimal:
    """
    初始确认现值计算（折现至签单月月中）
    """
    total_pv = Decimal('0')
    
    # Pre-process rates into a fast lookup map
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
            
        cf_date = row['Date_Obj']
        # 保费/IACF 全程不折现
        if col_name in ['Premium', 'IACF']:
            factor = Decimal('1.0')
            total_pv += amount * factor
            continue

        # 赔付/维费：签单月半期，之后整月；签单月之前视为已发生（原值）
        rd = relativedelta(cf_date, uw_date)
        months_from_uw = rd.years * 12 + rd.months

        if months_from_uw < 0:
            factor = Decimal('1.0')
        else:
            r1 = get_monthly_rate(rates_map, 1, max_term)
            factor = Decimal('1.0') / (Decimal('1.0') + r1 / Decimal('2'))
            if months_from_uw >= 1:
                # 后续整月：期数从2开始
                for t in range(2, months_from_uw + 2):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
        
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
    Calculate PV for "Current Period - End of Period" metrics with special rule.
    """
    total_pv = Decimal('0')
    
    val_year_month = (valuation_date.year, valuation_date.month)
    rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
    max_term = rates_df['term_month'].max() if not rates_df.empty else 0
    
    is_current_curve = (curve_base_date == valuation_date)
    
    val_date_for_calc = valuation_date
    if valuation_date.day == 1:
        val_date_for_calc = valuation_date - relativedelta(days=1)
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
            
        cf_date = row['Date_Obj']
        cf_year_month = (cf_date.year, cf_date.month)
        
        if cf_year_month <= val_year_month:
            total_pv += amount
        else:
            if cf_date == valuation_date:
                total_pv += amount
                continue
            
            factor = Decimal('1.0')
            
            if is_current_curve:
                rd = relativedelta(cf_date, val_date_for_calc)
                months_diff = rd.years * 12 + rd.months
                
                if months_diff > 0:
                    for t in range(1, months_diff + 1):
                        r = get_monthly_rate(rates_map, t, max_term)
                        factor /= (Decimal('1.0') + r)
            else:
                def get_month_idx(d):
                    rd = relativedelta(d, curve_base_date)
                    return rd.years * 12 + rd.months
                
                idx_cf = get_month_idx(cf_date)
                idx_val = get_month_idx(val_date_for_calc)
                
                if idx_cf < 0:
                    factor = Decimal('1.0')
                else:
                    if idx_cf == idx_val:
                        term = idx_cf + 1
                        r = get_monthly_rate(rates_map, term, max_term)
                        factor /= (Decimal('1.0') + r)
                    else:
                        start_step = max(1, idx_val + 2)
                        end_step = idx_cf + 1
                        
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
    start_date = pd.to_datetime(policy_row["start_date"]).date()  # 保险起期
    val_date = date(uw_date.year, 12, 31) # EOP
    
    # 获取 group_id（如果存在）
    group_id = policy_row.get("group_id")
    if pd.isna(group_id) or group_id is None:
        group_id = None
        # Note: We are using single policy locked curve regardless of group_id for Lkd fields.
    
    # 检测批减单（签单保费为负值）
    original_premium = Decimal(str(policy_row.get("premium", 0) or policy_row.get("sum_premium_no_tax", 0) or 0))
    original_iacf = Decimal(str(policy_row.get("iacf_amount", 0) or 0))
    is_reversal_policy = (original_premium < 0)
    
    if is_reversal_policy:
        print("\n" + "="*80)
        print("⚠️  检测到批减单（签单保费为负值）")
        print("="*80)
        print(f"签单保费(原始口径): {original_premium:,.2f}")
        print(f"获取费用(原始口径): {original_iacf:,.2f}")
        print("PV计算将按原始符号生成PV原材料（不取反）...")
        print("="*80 + "\n")
    
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
    
    full_cf_df_preview = projector.project_policy_flows(policy_row, assump_obj)
    full_cf_df_preview['Date_Obj'] = (pd.to_datetime(full_cf_df_preview['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
    
    print("\n" + "="*50)
    print("CASH FLOW PREVIEW (First 12 Months - Based on EOP Assumptions)")
    print(full_cf_df_preview.head(12).to_string(columns=['YYYYMM', 'Premium', 'IACF', 'Claims', 'Expenses']))
    
    def get_assumptions_for_date(target_date):
        month_str = target_date.strftime("%Y%m")
        try:
            return get_real_assumptions(policy_row["class_code"], month_str)
        except RuntimeError as e:
            logger.warning(f"⚠️ 警告: {month_str} 精算假设缺失，使用默认假设")
            return assump_obj

    def calc_all(cf_subset, val_d, curve_base_d, rates, label_suffix):
        if USE_VECTORIZED_PV:
            pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            pre = calculate_pv_exact(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_exact(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_exact(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_exact(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        rad = (cla + mtn) * assump_obj.ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    def calculate_pv_beg_lcu(
        cf_df: pd.DataFrame,
        col_name: str,
        rates_df: pd.DataFrame,
        bop_date: date
    ) -> Decimal:
        total_pv = Decimal('0')
        rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
        max_term = rates_df['term_month'].max() if not rates_df.empty else 0
        
        bop_date_for_calc = bop_date
        if bop_date.day == 1:
            bop_date_for_calc = bop_date - relativedelta(days=1)
        
        for _, row in cf_df.iterrows():
            amount = Decimal(str(row[col_name]))
            if amount == 0:
                continue
                
            cf_date = row['Date_Obj']
            
            if cf_date == bop_date:
                total_pv += amount
                continue
            
            rd = relativedelta(cf_date, bop_date_for_calc)
            months_diff = rd.years * 12 + rd.months
            
            factor = Decimal('1.0')
            
            if months_diff > 0:
                for t in range(1, months_diff + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            elif months_diff < 0:
                for t in range(1, abs(months_diff) + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
            
            total_pv += amount * factor
        
        return total_pv
    
    def calc_all_beg_lcu(cf_subset, bop_date, prev_year_end_month, rates_df):
        if cf_subset.empty:
            return {
                "_Pre_Amt": DECIMAL_ZERO,
                "_Acq_Amt": DECIMAL_ZERO,
                "_Cla_Amt": DECIMAL_ZERO,
                "_Mtn_Amt": DECIMAL_ZERO,
                "_Rad_Amt": DECIMAL_ZERO
            }
        
        pre = calculate_pv_beg_lcu(cf_subset, 'Premium', rates_df, bop_date)
        acq = calculate_pv_beg_lcu(cf_subset, 'IACF', rates_df, bop_date)
        cla = calculate_pv_beg_lcu(cf_subset, 'Claims', rates_df, bop_date)
        mtn = calculate_pv_beg_lcu(cf_subset, 'Expenses', rates_df, bop_date)
        rad = (cla + mtn) * assump_obj.ra_ratio
        
        return {
            "_Pre_Amt": pre,
            "_Acq_Amt": acq,
            "_Cla_Amt": cla,
            "_Mtn_Amt": mtn,
            "_Rad_Amt": rad
        }
    
    def calc_all_cca(cf_subset, val_d, curve_base_d, rates):
        if USE_VECTORIZED_PV:
            pre = calculate_pv_cca_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_cca_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_cca_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_cca_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            pre = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        rad = (cla + mtn) * assump_obj.ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    # 评估月份列表：
    # - 初始确认评估月：使用签单日期所在月份
    # - 此后每个年度仅在年末（12月31日）进行评估，不再生成年初评估月
    val_months = [(uw_date, "初始确认评估月")]
    
    if uw_date.year <= 2024:
        val_months.append((date(uw_date.year, 12, 31), f"{uw_date.year}年年底"))
    
    for year in range(uw_date.year + 1, 2025):
        # 仅需年末评估月，不需要年初评估月
        val_months.append((date(year, 12, 31), f"{year}年年底"))
    
    if TARGET_VAL_MONTH_FILTER:
        normalized_targets = {m.replace("-", "") for m in TARGET_VAL_MONTH_FILTER}
        val_months = [(m, l) for (m, l) in val_months if m.strftime("%Y%m") in normalized_targets]
        if not val_months: raise ValueError(f"Specified months not found.")

    pv_source_collection = PVSourceDataCollection(policy_no=TARGET_POLICY_NO)
    bop_cf_by_year = {} 
    all_results = {} 
    
    for val_month_date, val_month_label in val_months:
            val_month_yyyymm = val_month_date.strftime("%Y%m")
            val_month_str = val_month_yyyymm
            _, last_day_val = calendar.monthrange(val_month_date.year, val_month_date.month)
            val_month_end = date(val_month_date.year, val_month_date.month, last_day_val)
            
            is_new_business = (val_month_date.year == uw_date.year)
            is_bop = (val_month_date.month == 1 and val_month_date.day == 1)
            
            assump_uw = get_assumptions_for_date(uw_date)
            prev_year_end = date(val_month_date.year - 1, 12, 31)
            assump_prev_ye = get_assumptions_for_date(prev_year_end)
            assump_val = get_assumptions_for_date(val_month_date)
            
            cf_uw = projector.project_policy_flows(policy_row, assump_uw)
            def set_cf_dates_for_initial_recognition(cf_df, uw_date, col_name):
                cf_df = cf_df.copy()
                uw_year_month = (uw_date.year, uw_date.month)
                is_premium_or_iacf = (col_name in ['Premium', 'IACF'])
                date_list = []
                for _, row in cf_df.iterrows():
                    yyyymm = row['YYYYMM']
                    cf_year = int(yyyymm[:4])
                    cf_month = int(yyyymm[4:6])
                    cf_year_month = (cf_year, cf_month)
                    
                    if cf_year_month == uw_year_month:
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
            
            cf_uw['Date_Obj'] = (pd.to_datetime(cf_uw['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            cf_prev_ye = projector.project_policy_flows(policy_row, assump_prev_ye)
            cf_prev_ye['Date_Obj'] = (pd.to_datetime(cf_prev_ye['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            if not is_new_business:
                bop_cf_by_year[val_month_date.year] = cf_prev_ye
            
            cf_val = projector.project_policy_flows(policy_row, assump_val)
            cf_val['Date_Obj'] = (pd.to_datetime(cf_val['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            rate_val_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
            rate_val_current_df = get_discount_factors("current", val_month_yyyymm)
            
            cf_for_calc = cf_val
            val_assump_obj = assump_val
            
            earliest_date_for_nb = min(uw_date, start_date) if is_new_business else start_date
            cf_uw_current = cf_uw[
                (cf_uw['Date_Obj'] >= earliest_date_for_nb) &
                (cf_uw['Date_Obj'] <= val_month_end)
            ]
            cf_uw_future = cf_uw[cf_uw['Date_Obj'] > val_month_end]
            
            if is_new_business:
                cash_flow_start_date = min(uw_date, start_date)
            else:
                cash_flow_start_date = date(val_month_date.year, 1, 1)
            
            if cf_val is not None and not cf_val.empty:
                cf_val_current = cf_val[
                    (cf_val['Date_Obj'] >= cash_flow_start_date) &
                    (cf_val['Date_Obj'] <= val_month_end)
                ]
                cf_val_future = cf_val[cf_val['Date_Obj'] > val_month_end]
            else:
                cf_val_current = cf_val
                cf_val_future = cf_val
            
            results = {}
        
            if is_new_business:
                uw_month_mid = date(uw_date.year, uw_date.month, 15)

                pre_rec = calculate_pv_initial_recognition(
                    set_cf_dates_for_initial_recognition(cf_uw, uw_date, 'Premium'), 
                    'Premium', rate_val_locked_df, uw_month_mid, uw_date, uw_date, start_date)
                acq_rec = calculate_pv_initial_recognition(
                    set_cf_dates_for_initial_recognition(cf_uw, uw_date, 'IACF'), 
                    'IACF', rate_val_locked_df, uw_month_mid, uw_date, uw_date, start_date)
                cla_rec = calculate_pv_initial_recognition(
                    set_cf_dates_for_initial_recognition(cf_uw, uw_date, 'Claims'), 
                    'Claims', rate_val_locked_df, uw_month_mid, uw_date, uw_date, start_date)
                mtn_rec = calculate_pv_initial_recognition(
                    set_cf_dates_for_initial_recognition(cf_uw, uw_date, 'Expenses'), 
                    'Expenses', rate_val_locked_df, uw_month_mid, uw_date, uw_date, start_date)
                rad_rec = (cla_rec + mtn_rec) * assump_uw.ra_ratio
                
                results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Pre_Amt"] = pre_rec
                results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Acq_Amt"] = acq_rec
                results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt"] = cla_rec
                results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt"] = mtn_rec
                results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt"] = rad_rec
                
                # Ini_Cca_Rep (renamed Wlk -> Lkd)
                res_ini_cca_rep = calc_all_cca(cf_uw_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_ini_cca_rep.items():
                    results[f"Pvfl_Nb_Ini_Cca_Rep_Lkd{k}"] = v
                
                # Ini_Cfa_Rep (renamed Wlk -> Lkd)
                res_ini_cfa_rep = calc_all(cf_uw_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_ini_cfa_rep.items():
                    results[f"Pvfl_Nb_Ini_Cfa_Rep_Lkd{k}"] = v
                
                # Eop_Cfa_Rep (renamed Wlk -> Lkd)
                res_eop_cfa_lkd = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_eop_cfa_lkd.items():
                    results[f"Pvfl_Nb_Eop_Cfa_Rep_Lkd{k}"] = v
                
                # Eop_Cca_Rep (renamed Wlk -> Lkd)
                res_eop_cca_lkd = calc_all_cca(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_eop_cca_lkd.items():
                    results[f"Pvfl_Nb_Eop_Cca_Rep_Lkd{k}"] = v
                
                res_eop_cfa_cur = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current_df, "")
                for k, v in res_eop_cfa_cur.items():
                    results[f"Pvfl_Nb_Eop_Cfa_Rep_Cur{k}"] = v
                
            else:
                nb_field_suffixes = [
                    "_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"
                ]
                nb_field_prefixes = [
                    "Pvfl_Nb_Ini_Cfa_Rec_Lkd",
                    "Pvfl_Nb_Ini_Cca_Rep_Lkd",
                    "Pvfl_Nb_Ini_Cfa_Rep_Lkd",
                    "Pvfl_Nb_Eop_Cfa_Rep_Lkd",
                    "Pvfl_Nb_Eop_Cca_Rep_Lkd",
                    "Pvfl_Nb_Eop_Cfa_Rep_Cur",
                ]
                for prefix in nb_field_prefixes:
                    for suffix in nb_field_suffixes:
                        field_name = f"{prefix}{suffix}"
                        results[field_name] = DECIMAL_ZERO
        
            if is_new_business:
                if_required_fields = [
                "Pvfl_If_Bop_Cca_Rep_Lkd_Pre_Amt",
                "Pvfl_If_Bop_Cca_Rep_Lkd_Acq_Amt",
                "Pvfl_If_Bop_Cca_Rep_Lkd_Cla_Amt",
                "Pvfl_If_Bop_Cca_Rep_Lkd_Mtn_Amt",
                "Pvfl_If_Bop_Cca_Rep_Lkd_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Lkd_Pre_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Lkd_Acq_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Lkd_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Lkd_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Rep_Lkd_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lkd_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lkd_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lkd_Rad_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Lkd_Pre_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Lkd_Acq_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Lkd_Cla_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Lkd_Mtn_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Lkd_Rad_Amt",
                "Pvfl_If_Eop_Cca_Rep_Lkd_Pre_Amt",
                "Pvfl_If_Eop_Cca_Rep_Lkd_Acq_Amt",
                "Pvfl_If_Eop_Cca_Rep_Lkd_Cla_Amt",
                "Pvfl_If_Eop_Cca_Rep_Lkd_Mtn_Amt",
                "Pvfl_If_Eop_Cca_Rep_Lkd_Rad_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Pre_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Acq_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Cla_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Mtn_Amt",
                "Pvfl_If_Eop_Cfa_Rep_Cur_Rad_Amt",
            ]
                for field in if_required_fields:
                    if field not in results:
                        results[field] = DECIMAL_ZERO
            else:
                bop_date = date(val_month_date.year, 1, 1)
                year_start = date(val_month_date.year, 1, 1) 
                
                if val_month_date.year in bop_cf_by_year:
                    cf_bop = bop_cf_by_year[val_month_date.year]
                else:
                    cf_bop = cf_prev_ye
                
                if not cf_bop.empty:
                    cf_bop_current = cf_bop[
                        (cf_bop['Date_Obj'] >= year_start) &
                        (cf_bop['Date_Obj'] <= val_month_end)
                    ]
                    cf_bop_future = cf_bop[cf_bop['Date_Obj'] > val_month_end]
                    cf_bop_beg = cf_bop[cf_bop['Date_Obj'] >= year_start]
                else:
                    cf_bop_current = cf_bop
                    cf_bop_future = cf_bop
                    cf_bop_beg = cf_bop
                
                def calc_bop_cca_rep(cf_subset, val_d, curve_base_d, rates):
                    if cf_subset.empty:
                        return {
                            f"_Pre_Amt": DECIMAL_ZERO,
                            f"_Acq_Amt": DECIMAL_ZERO,
                            f"_Cla_Amt": DECIMAL_ZERO,
                            f"_Mtn_Amt": DECIMAL_ZERO,
                            f"_Rad_Amt": DECIMAL_ZERO
                        }
                    
                    cf_past = cf_subset[cf_subset['Date_Obj'] < val_d].copy()
                    cf_future = cf_subset[cf_subset['Date_Obj'] >= val_d].copy()
                    
                    past_pre = Decimal(str(cf_past['Premium'].sum())) if not cf_past.empty and 'Premium' in cf_past.columns else DECIMAL_ZERO
                    past_acq = Decimal(str(cf_past['IACF'].sum())) if not cf_past.empty and 'IACF' in cf_past.columns else DECIMAL_ZERO
                    past_cla = Decimal(str(cf_past['Claims'].sum())) if not cf_past.empty and 'Claims' in cf_past.columns else DECIMAL_ZERO
                    past_mtn = Decimal(str(cf_past['Expenses'].sum())) if not cf_past.empty and 'Expenses' in cf_past.columns else DECIMAL_ZERO
                    
                    future_pre = calculate_pv_exact(cf_future, 'Premium', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                    future_acq = calculate_pv_exact(cf_future, 'IACF', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                    future_cla = calculate_pv_exact(cf_future, 'Claims', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                    future_mtn = calculate_pv_exact(cf_future, 'Expenses', rates, val_d, curve_base_d) if not cf_future.empty else DECIMAL_ZERO
                    
                    pre = past_pre + future_pre
                    acq = past_acq + future_acq
                    cla = past_cla + future_cla
                    mtn = past_mtn + future_mtn
                    
                    rad = (cla + mtn) * val_assump_obj.ra_ratio
                    
                    return {
                        f"_Pre_Amt": pre,
                        f"_Acq_Amt": acq,
                        f"_Cla_Amt": cla,
                        f"_Mtn_Amt": mtn,
                        f"_Rad_Amt": rad
                    }
                
                # Pvfl_If_Bop_Cca_Rep_Lkd (Renamed)
                res_bop_cca = calc_bop_cca_rep(cf_bop_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_bop_cca.items():
                    results[f"Pvfl_If_Bop_Cca_Rep_Lkd{k}"] = v
                
                # Pvfl_If_Bop_Cfa_Rep_Lkd (Renamed)
                res_bop_cfa = calc_all(cf_bop_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_bop_cfa.items():
                    results[f"Pvfl_If_Bop_Cfa_Rep_Lkd{k}"] = v
                
                bop_date = date(val_month_date.year, 1, 1)
                val_date_for_beg_pv = date(val_month_date.year - 1, 12, 31)
                
                prev_year_end_month = date(val_month_date.year - 1, 12, 31).strftime("%Y%m")
                rate_prev_year_locked_df = get_discount_factors("locked", prev_year_end_month)
                
                res_bop_cfa_beg = calc_all_beg_lcu(cf_bop_beg, val_date_for_beg_pv, prev_year_end_month, rate_prev_year_locked_df)
                cla_beg_fut = res_bop_cfa_beg.get("_Cla_Amt", DECIMAL_ZERO)
                mtn_beg_fut = res_bop_cfa_beg.get("_Mtn_Amt", DECIMAL_ZERO)
                rad_beg_fut = (cla_beg_fut + mtn_beg_fut) * val_assump_obj.ra_ratio
                res_bop_cfa_beg["_Rad_Amt"] = rad_beg_fut
                for k, v in res_bop_cfa_beg.items():
                    if k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                        results[f"Pvfl_If_Bop_Cfa_Beg_Lcu{k}"] = v
                
                # Pvfl_If_Bop_Cfa_Beg_Lkd (Renamed Wlk -> Lkd)
                # 使用签单日锁定利率
                res_bop_cfa_beg_lkd = calc_all(cf_bop_beg, val_date_for_beg_pv, uw_date, rate_val_locked_df, "")
                cla_beg_lkd_fut = res_bop_cfa_beg_lkd.get("_Cla_Amt", DECIMAL_ZERO)
                mtn_beg_lkd_fut = res_bop_cfa_beg_lkd.get("_Mtn_Amt", DECIMAL_ZERO)
                rad_beg_lkd_fut = (cla_beg_lkd_fut + mtn_beg_lkd_fut) * val_assump_obj.ra_ratio
                res_bop_cfa_beg_lkd["_Rad_Amt"] = rad_beg_lkd_fut
                for k, v in res_bop_cfa_beg_lkd.items():
                    if k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                        results[f"Pvfl_If_Bop_Cfa_Beg_Lkd{k}"] = v
                
                # Pvfl_If_Eop_Cfa_Rep_Lkd (Renamed)
                res_eop_cfa_lkd = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_eop_cfa_lkd.items():
                    results[f"Pvfl_If_Eop_Cfa_Rep_Lkd{k}"] = v
                
                # Pvfl_If_Eop_Cca_Rep_Lkd (Renamed)
                if is_bop:
                    res_eop_cca_lkd = calc_bop_cca_rep(cf_bop_current, val_month_end, uw_date, rate_val_locked_df)
                else:
                    res_eop_cca_lkd = calc_bop_cca_rep(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_eop_cca_lkd.items():
                    results[f"Pvfl_If_Eop_Cca_Rep_Lkd{k}"] = v
                
                res_eop_cfa_cur_if = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current_df, "")
                for k, v in res_eop_cfa_cur_if.items():
                    results[f"Pvfl_If_Eop_Cfa_Rep_Cur{k}"] = v

            # --- 统一字段命名：将所有 Wlk 段位规范为 Lkd，并做去重 ---
            # 规则：
            # - 仅替换字段名中的段位 "_Wlk_" 为 "_Lkd_"
            # - 如果规范化后 new_key 已存在，则以原 Wlk 字段的数值为准进行覆盖
            normalized_results = {}
            for key, value in results.items():
                new_key = key.replace("_Wlk_", "_Lkd_")
                # 使用来自原 Wlk 字段的值覆盖已有键，确保加权锁定利率口径一致
                normalized_results[new_key] = value

            for key, value in normalized_results.items():
                all_results[f"{val_month_str}_{key}"] = value
            
            pv_data = PVSourceData(
                policy_no=TARGET_POLICY_NO,
                valuation_month=val_month_yyyymm,
                valuation_date=val_month_end,
                under_write_date=uw_date,
                pv_fields=normalized_results.copy(),
                metadata={
                    'valuation_month_label': val_month_label,
                    'rate_locked_month': uw_date.strftime("%Y%m"),
                    'rate_current_month': val_month_yyyymm,
                    'is_reversal_policy': is_reversal_policy,
                }
            )
            pv_source_collection.add_data(pv_data)
            
            print("\n" + "="*80)
            print(f"RESULTS — {val_month_label} {val_month_str} (评估期末: {val_month_end.strftime('%Y-%m-%d')})")
            print("="*80)
            print(f"{'Field Name':<{FIELD_NAME_WIDTH}} | {'Value':>{VALUE_WIDTH}} | {DESC_HEADER}")
            print("-" * (FIELD_NAME_WIDTH + VALUE_WIDTH + len(DESC_HEADER) + 6))
            
            for key in sorted(normalized_results.keys()):
                desc = describe_field(key)
                print(f"{key:<{FIELD_NAME_WIDTH}} | {normalized_results[key]:>{VALUE_WIDTH},.2f} | {desc}")
            
            print("="*80)
    
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