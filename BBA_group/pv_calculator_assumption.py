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
from BBA_group.projector_assumption import CashFlowProjector
from BBA_group.assumptions import get_discount_factors
from BBA_group.data_loader import load_full_data
from BBA_group.data_access.loader import get_assumptions as fetch_assumptions_from_db
from BBA_group.models.pv_source_data import PVSourceData, PVSourceDataCollection

# 向量化计算开关（默认开启以提升性能）
USE_VECTORIZED_PV = True
try:
    from BBA_group.pv_calculator_vectorized import calculate_pv_exact_fast, calculate_pv_cca_fast
    print("✓ 向量化PV计算模块已加载")
except ImportError as e:
    USE_VECTORIZED_PV = False
    print(f"⚠ 向量化PV计算模块加载失败，将使用原始方法: {e}")

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
    
    # [FIX] 评估日期调整：
    # 如果 valuation_date 是月初（1日），在计算月份差时将其视为上个月末（减1天）。
    # 这样可以保证 BOP（1月1日）的折现逻辑与上年 EOP（12月31日）完全一致，
    # 避免因 relativedelta 对整月的计算差异导致 PV 跳变。
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
            # Current curve: term_month 从1开始（从评估日期开始的第一期、第二期...）
            # 计算从评估日期到现金流日期的月数差
            # 使用调整后的 val_date_for_calc 计算 diff
            rd = relativedelta(cf_date, val_date_for_calc)
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
            # 使用调整后的 val_date_for_calc 计算 idx_val
            idx_val = get_month_idx(val_date_for_calc)
            
            if cf_date > valuation_date:
                # Discounting: Future -> Present
                if idx_cf == idx_val:
                    # 同月内的现金流（如1月1日到1月31日）
                    # 直接使用当月对应的term_month（签单月=1，之后逐月+1）
                    # 例如：签单9月，1月现金流idx_cf=4，使用term_month=5
                    term = idx_cf + 1
                    r = get_monthly_rate(rates_map, term, max_term)
                    factor /= (Decimal('1.0') + r)
                else:
                    # 跨月折现
                    # 期数需要+1：从 (idx_val + 1 + 1) 到 (idx_cf + 1)
                    # 例如：202205签单，202206评估，202207现金流
                    # idx_val=1, idx_cf=2 → 使用 term_month=3
                    # 202208现金流：idx_cf=3 → 使用 term_month=3,4累乘
                    start_step = max(1, idx_val + 2)  # +1 for period adjustment
                    end_step = idx_cf + 1  # +1 for period adjustment
                    
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
    
    特殊规则：
    - 签单月的保费和获取费用：在月中（15日），折现因子为1.0（不需要折现）
    - 签单月的赔付和维持费用：在月末，折现半个月
    - 其他月份的现金流：在月末
    
    折现逻辑：
    - 签单月保费/获取费用（月中）：折现因子 = 1.0（不折现）
    - 签单月赔付/维持费用（月末）：折现因子 = 1 / (1 + 第一个月利率/2)
    - 第二个月赔付/维持费用（月末）：折现因子 = 1 / ((1 + 第一个月利率/2) * (1 + 第二个月利率))
    - 第三个月赔付/维持费用（月末）：折现因子 = 1 / ((1 + 第一个月利率/2) * (1 + 第二个月利率) * (1 + 第三个月利率))
    - 保费/获取费用（非签单月）：第一个月折现半个月，后续月份折现整月
    
    Args:
        cf_df: Cash flow DataFrame with 'Date_Obj' column and 'YYYYMM' column.
        col_name: Value column to discount ('Premium', 'IACF', 'Claims', 'Expenses').
        rates_df: Rate curve (term_month -> forward_rate).
        valuation_date: 签单月月中（15日）
        curve_base_date: 签单日期（用于locked curve计算）
        uw_date: 签单日期（用于判断是否为签单月）
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
    
    # [FIX] 评估日期调整：
    # 如果 valuation_date 是月初（1日），在计算月份差时将其视为上个月末（减1天）。
    # 这样可以保证 BOP（1月1日）的折现逻辑与上年 EOP（12月31日）完全一致，
    # 避免因 relativedelta 对整月的计算差异导致 PV 跳变。
    val_date_for_calc = valuation_date
    if valuation_date.day == 1:
        val_date_for_calc = valuation_date - relativedelta(days=1)
    
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
                # 使用调整后的 val_date_for_calc 计算 diff
                rd = relativedelta(cf_date, val_date_for_calc)
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
                # 使用调整后的 val_date_for_calc 计算 idx_val
                idx_val = get_month_idx(val_date_for_calc)
                
                # 倒签单情况：如果现金流在签单日期之前，不需要折现计息，直接取原值
                if idx_cf < 0:
                    # 签单日期之前的现金流，直接取原值（不计息）
                    factor = Decimal('1.0')
                else:
                    # 签单日期之后的现金流，正常折现
                    if idx_cf == idx_val:
                        # 同月内的现金流
                        term = idx_cf + 1
                        r = get_monthly_rate(rates_map, term, max_term)
                        factor /= (Decimal('1.0') + r)
                    else:
                        # 跨月折现
                        # 期数需要+1：从 (idx_val + 1 + 1) 到 (idx_cf + 1)
                        start_step = max(1, idx_val + 2)  # +1 for period adjustment
                        end_step = idx_cf + 1  # +1 for period adjustment
                        
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
    
    # 检测批减单（签单保费为负值）
    original_premium = Decimal(str(policy_row.get("premium", 0) or policy_row.get("sum_premium_no_tax", 0) or 0))
    original_iacf = Decimal(str(policy_row.get("iacf_amount", 0) or 0))
    is_reversal_policy = (original_premium < 0)
    
    # 批减单：不在PV计算阶段取反，按原始符号进入PV原材料
    # 后续计量阶段同样按原始符号运行；仅在CSM/LC判定及所有LC触发条件处对批减单翻转符号判定
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
    
    # 使用配置表的获取费用率更新 policy_row 中的 iacf_amount
    # 确保后续现金流投射使用配置表的费率，而不是保单数据表中的值
    if hasattr(assump_obj, 'acquisition_expense_ratio') and assump_obj.acquisition_expense_ratio is not None:
        calculated_iacf = original_premium * assump_obj.acquisition_expense_ratio
        policy_row["iacf_amount"] = float(calculated_iacf)
    
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
    # 移除了在主循环外的全局full_cf_df生成，因为后续需要根据不同的精算假设（签单时、上年末、当前评估月）分别生成现金流
    
    # 保留projector实例用于循环内调用
    projector = CashFlowProjector()
    
    # 为了预览目的，生成一份基于期末假设的现金流
    full_cf_df_preview = projector.project_policy_flows(policy_row, assump_obj)
    # 将日期设置为月末（而不是月初），确保折现期数计算正确
    full_cf_df_preview['Date_Obj'] = (pd.to_datetime(full_cf_df_preview['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
    
    # Print CF Preview
    print("\n" + "="*50)
    print("CASH FLOW PREVIEW (First 12 Months - Based on EOP Assumptions)")
    print(full_cf_df_preview.head(12).to_string(columns=['YYYYMM', 'Premium', 'IACF', 'Claims', 'Expenses']))
    
    # 获取精算假设函数 (Helper)
    def get_assumptions_for_date(target_date):
        """根据日期获取精算假设"""
        month_str = target_date.strftime("%Y%m")
        try:
            return get_real_assumptions(policy_row["class_code"], month_str)
        except RuntimeError as e:
            logger.warning(f"⚠️ 警告: {month_str} 精算假设缺失，使用默认假设")
            return assump_obj # Fallback to initial assumptions

    # Define helpers
    def calc_all(cf_subset, val_d, curve_base_d, rates, label_suffix):
        """Helper to calc Pre, Acq, Cla, Mtn, Rad using EXACT discounting"""
        if USE_VECTORIZED_PV:
            # 使用向量化版本（5-10倍加速）
            pre = calculate_pv_exact_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_exact_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_exact_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_exact_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            # 原始版本（向量化模块不可用时）
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
        """
        计算Beg_Lcu字段的特殊折现逻辑
        
        为什么需要重写折现函数：
        1. 当前的calculate_pv_exact函数对于locked curve，使用(现金流日期 - 签单日期)的月数差来计算term_month
        2. 但对于Lcu字段，我们需要的是从1月1日开始，使用上年末利率曲线折现
        3. 这意味着折现逻辑需要从1月1日开始计算期数，而不是从签单日期开始
        4. 例如：2023年1月的现金流，应该使用202212利率曲线的第1期折现至2023年1月1日
        5. 如果使用calculate_pv_exact，它会从签单日期（如2022年5月）开始计算期数，导致期数错误
        
        Args:
            cf_df: 现金流DataFrame（从1月1日开始的所有现金流）
            col_name: 现金流列名（'Premium', 'IACF', 'Claims', 'Expenses'）
            rates_df: 上年末的锁定利率曲线（如202212）
            bop_date: 年初时点（1月1日，如2023年1月1日）
        
        Returns:
            现值
        
        折现逻辑：
        - 折现时点：1月1日（bop_date）
        - 利率曲线：上年末的锁定利率曲线（如202212）
        - 1月现金流：100 / (1 + 202212利率曲线第1期)
        - 2月现金流：100 / ((1 + 202212利率曲线第1期) * (1 + 202212利率曲线第2期))
        - 以此类推
        """
        total_pv = Decimal('0')
        
        # Pre-process rates into a fast lookup map
        rates_map = dict(zip(rates_df['term_month'], rates_df['forward_disrate_value'].apply(Decimal)))
        max_term = rates_df['term_month'].max() if not rates_df.empty else 0
        
        # [FIX] 评估日期调整：
        # 如果 bop_date 是月初（1日），在计算月份差时将其视为上个月末（减1天）。
        # 这样可以保证 BOP（1月1日）的折现逻辑与上年 EOP（12月31日）完全一致。
        bop_date_for_calc = bop_date
        if bop_date.day == 1:
            bop_date_for_calc = bop_date - relativedelta(days=1)
        
        for _, row in cf_df.iterrows():
            amount = Decimal(str(row[col_name]))
            if amount == 0:
                continue
                
            cf_date = row['Date_Obj']
            
            # 如果现金流日期就是折现时点，直接返回原值
            if cf_date == bop_date:
                total_pv += amount
                continue
            
            # 计算从折现时点到现金流日期的月数差
            # 使用调整后的 bop_date_for_calc 计算 diff
            rd = relativedelta(cf_date, bop_date_for_calc)
            months_diff = rd.years * 12 + rd.months
            
            # 计算折现因子
            factor = Decimal('1.0')
            
            if months_diff > 0:
                # 未来现金流：折现
                # 从第1期开始，到第months_diff期
                for t in range(1, months_diff + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor /= (Decimal('1.0') + r)
            elif months_diff < 0:
                # 过去现金流：累积（理论上不应该发生，因为cf_df应该只包含1月1日及之后的现金流）
                for t in range(1, abs(months_diff) + 1):
                    r = get_monthly_rate(rates_map, t, max_term)
                    factor *= (Decimal('1.0') + r)
            
            total_pv += amount * factor
        
        return total_pv
    
    def calc_all_beg_lcu(cf_subset, bop_date, prev_year_end_month, rates_df):
        """
        计算Beg_Lcu字段的特殊折现逻辑
        
        Args:
            cf_subset: 现金流DataFrame（从1月1日开始的所有现金流）
            bop_date: 年初时点（1月1日）
            prev_year_end_month: 上年末月份字符串（如"202212"），仅用于日志记录
            rates_df: 上年末的锁定利率曲线
        
        Returns:
            包含Pre, Acq, Cla, Mtn, Rad的字典
        """
        if cf_subset.empty:
            return {
                "_Pre_Amt": DECIMAL_ZERO,
                "_Acq_Amt": DECIMAL_ZERO,
                "_Cla_Amt": DECIMAL_ZERO,
                "_Mtn_Amt": DECIMAL_ZERO,
                "_Rad_Amt": DECIMAL_ZERO
            }
        
        # 使用专门的折现函数
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
        """Helper for Cca: Past/Current -> Original Value; Future -> Discounted"""
        if USE_VECTORIZED_PV:
            # 使用向量化版本（5-10倍加速）
            pre = calculate_pv_cca_fast(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_cca_fast(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_cca_fast(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_cca_fast(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        else:
            # 原始版本（向量化模块不可用时）
            pre = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Premium', rates, val_d, curve_base_d)
            acq = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'IACF', rates, val_d, curve_base_d)
            cla = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Claims', rates, val_d, curve_base_d)
            mtn = calculate_pv_current_period_no_interest_after_occurrence(cf_subset, 'Expenses', rates, val_d, curve_base_d)
        rad = (cla + mtn) * assump_obj.ra_ratio
        return {f"_Pre_Amt": pre, f"_Acq_Amt": acq, f"_Cla_Amt": cla, f"_Mtn_Amt": mtn, f"_Rad_Amt": rad}

    # Define valuation months
    # 注意：不生成签单年年初的数据，因为那时保单还不存在
    val_months = [(uw_date, "初始确认评估月")]
    
    # 签单年年底（如果签单年 <= 2024）
    if uw_date.year <= 2024:
        val_months.append((date(uw_date.year, 12, 31), f"{uw_date.year}年年底"))
    
    # 后续年份的年初和年底
    for year in range(uw_date.year + 1, 2025):
        val_months.append((date(year, 1, 1), f"{year}年年初"))
        val_months.append((date(year, 12, 31), f"{year}年年底"))
    
    if TARGET_VAL_MONTH_FILTER:
        normalized_targets = {m.replace("-", "") for m in TARGET_VAL_MONTH_FILTER}
        val_months = [(m, l) for (m, l) in val_months if m.strftime("%Y%m") in normalized_targets]
        if not val_months: raise ValueError(f"Specified months not found.")

    # Create PV source data collection
    pv_source_collection = PVSourceDataCollection(policy_no=TARGET_POLICY_NO)
    bop_cf_by_year = {} # Store BOP cashflows
    all_results = {} # Store all results across valuation months
    
    # 4. Calculate PVs for each valuation month
    for val_month_date, val_month_label in val_months:
            # 计算评估月相关日期
            val_month_yyyymm = val_month_date.strftime("%Y%m")
            val_month_str = val_month_yyyymm
            _, last_day_val = calendar.monthrange(val_month_date.year, val_month_date.month)
            val_month_end = date(val_month_date.year, val_month_date.month, last_day_val)
            
            # 判断是否为签单年度
            is_new_business = (val_month_date.year == uw_date.year)
            
            # 判断是否为年初（1月1日）
            is_bop = (val_month_date.month == 1 and val_month_date.day == 1)
            
            # 准备不同时点的精算假设
            # 1. 签单时假设 (用于初始确认)
            assump_uw = get_assumptions_for_date(uw_date)
            
            # 2. 上年末假设 (用于年初预期)
            # 如果当前是签单年，上年末假设可能不存在或不适用（通常用于后续年份）
            prev_year_end = date(val_month_date.year - 1, 12, 31)
            assump_prev_ye = get_assumptions_for_date(prev_year_end)
            
            # 3. 当前评估月假设 (用于期末预期)
            assump_val = get_assumptions_for_date(val_month_date)
            
            # 生成对应现金流
            # 1. 基于签单时假设的现金流 (用于Nb_Ini)
            cf_uw = projector.project_policy_flows(policy_row, assump_uw)
            # 设置现金流日期：
            # - 签单月的保费和获取费用：月中（15日）
            # - 签单月的赔付和维持费用：月末
            # - 其他月份：月末
            def set_cf_dates_for_initial_recognition(cf_df, uw_date, col_name):
                """
                为初始确认现值设置现金流日期
                根据现金流类型（Premium/IACF vs Claims/Expenses）设置不同的日期
                """
                cf_df = cf_df.copy()
                uw_year_month = (uw_date.year, uw_date.month)
                
                # 判断是否为保费或获取费用
                is_premium_or_iacf = (col_name in ['Premium', 'IACF'])
                
                # 创建日期列
                date_list = []
                for _, row in cf_df.iterrows():
                    yyyymm = row['YYYYMM']
                    cf_year = int(yyyymm[:4])
                    cf_month = int(yyyymm[4:6])
                    cf_year_month = (cf_year, cf_month)
                    
                    if cf_year_month == uw_year_month:
                        # 签单月
                        if is_premium_or_iacf:
                            # 保费和获取费用：月中（15日）
                            date_list.append(date(cf_year, cf_month, 15))
                        else:
                            # 赔付和维持费用：月末
                            _, last_day = calendar.monthrange(cf_year, cf_month)
                            date_list.append(date(cf_year, cf_month, last_day))
                    else:
                        # 其他月份：月末
                        _, last_day = calendar.monthrange(cf_year, cf_month)
                        date_list.append(date(cf_year, cf_month, last_day))
                
                cf_df['Date_Obj'] = date_list
                return cf_df
            
            # 其他用途的现金流仍使用月末日期
            cf_uw['Date_Obj'] = (pd.to_datetime(cf_uw['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            # 2. 基于上年末假设的现金流 (用于If_Bop)
            cf_prev_ye = projector.project_policy_flows(policy_row, assump_prev_ye)
            cf_prev_ye['Date_Obj'] = (pd.to_datetime(cf_prev_ye['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            # 保存年初现金流到bop_cf_by_year（基于上年末精算假设）
            # 注意：只在非签单年度保存，因为签单年度没有年初预期
            if not is_new_business:
                bop_cf_by_year[val_month_date.year] = cf_prev_ye
            
            # 3. 基于当前评估月假设的现金流 (用于Nb_Eop / If_Eop)
            cf_val = projector.project_policy_flows(policy_row, assump_val)
            cf_val['Date_Obj'] = (pd.to_datetime(cf_val['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)).dt.date
            
            # 获取折现率
            rate_val_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
            rate_val_current_df = get_discount_factors("current", val_month_yyyymm)
            rate_prev_year_locked_df = get_discount_factors("locked", uw_date.strftime("%Y%m"))
            
            # 保存当前现金流用于后续计算
            cf_for_calc = cf_val
            val_assump_obj = assump_val
            
            # Split cash flows for UW (underwriting) calculations
            # 修正：从签单日期和起期日期孰早开始，确保包含签单月的保费和获取费用
            # 对于 Pvfl_Nb_Ini_Cca_Rep_Wlk_* 字段，应包含从孰早日期至评估期末的现金流
            earliest_date_for_nb = min(uw_date, start_date) if is_new_business else start_date
            cf_uw_current = cf_uw[
                (cf_uw['Date_Obj'] >= earliest_date_for_nb) &
                (cf_uw['Date_Obj'] <= val_month_end)
            ]
            cf_uw_future = cf_uw[cf_uw['Date_Obj'] > val_month_end]
            
            # Split cash flows：预期当期=签单和起期孰早至评估期末，预期未来=评估期末之后
            # 修正：对于Nb字段，从签单日期和起期日期孰早开始，而不是仅从起期开始
            if is_new_business:
                # 新增合同：从签单日期和起期日期孰早开始
                cash_flow_start_date = min(uw_date, start_date)
            else:
                # 有效合同：从年初开始（保持原逻辑）
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
        
            # --- NB Initial Recognition (Rec) - only for new business year ---
            # 重要：Nb字段只在签单年度有值，非签单年度应该为0
            if is_new_business:
                # 计算签单月月中（作为初始确认现值 Rec 的折现时点）
                uw_month_mid = date(uw_date.year, uw_date.month, 15)

                # 签单年度：计算新增合同的PV值
                
                # 1. Nb_Ini_Rec (新增-初始-初始确认现值): 折现至 签单月月中 (uw_month_mid)
                # 注意：已删除 Cca 字段，只保留 Cfa 字段
                # Ini_Cfa (签单月及之后的所有现金流)
                # 使用新的初始确认折现函数（支持月中折现）
                # 为每种现金流类型分别设置日期（保费/IACF在月中，其他在月末）
                
                # 分别计算各个现金流类型，每种类型使用对应的日期设置
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
                
                # --- NB Rep (End of Period) - based on val_month_end ---
                # 2. Nb_Ini_Rep (新增-初始-期末现值): 折现至 评估期末 (val_month_end)
                
                # Ini_Cca_Rep (Current Period Flows, rolled to val_month_end using locked curve)
                # 使用 calc_all_cca (当期/过去不折现)
                res_ini_cca_rep = calc_all_cca(cf_uw_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_ini_cca_rep.items():
                    results[f"Pvfl_Nb_Ini_Cca_Rep_Wlk{k}"] = v
                
                # Ini_Cfa_Rep (Future Period Flows, rolled to val_month_end using locked curve)
                res_ini_cfa_rep = calc_all(cf_uw_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_ini_cfa_rep.items():
                    results[f"Pvfl_Nb_Ini_Cfa_Rep_Wlk{k}"] = v
                
                # 3. Nb_Eop_Rep (新增-期末-期末现值): 折现至 评估期末 (val_month_end)
                # 使用 cf_val (基于当前评估月假设的现金流)
                # 注意：cf_val_current 和 cf_val_future 已在前面基于保险起期重新定义

                # Eop_Cfa_Rep (Future Period Flows, rolled to val_month_end)
                # Wlk (using locked curve from UW date)
                res_eop_cfa_wlk = calc_all(cf_val_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_eop_cfa_wlk.items():
                    results[f"Pvfl_Nb_Eop_Cfa_Rep_Wlk{k}"] = v
                
                # Eop_Cca_Rep (Current Period Flows, rolled to val_month_end)
                # 使用 calc_all_cca
                res_eop_cca_wlk = calc_all_cca(cf_val_current, val_month_end, uw_date, rate_val_locked_df)
                for k, v in res_eop_cca_wlk.items():
                    results[f"Pvfl_Nb_Eop_Cca_Rep_Wlk{k}"] = v
                
                # Cur (using current curve from val_month)
                res_eop_cfa_cur = calc_all(cf_val_future, val_month_end, val_month_end, rate_val_current_df, "")
                for k, v in res_eop_cfa_cur.items():
                    results[f"Pvfl_Nb_Eop_Cfa_Rep_Cur{k}"] = v
                
                # 删除 Eop_Cca_Rep_Cur 字段（未使用，当期现金流不需要当期利率折现）
            else:
                # 非签单年度：新增合同的PV值应该为0（因为没有新增合同）
                # 但为了保持数据结构一致性，我们仍然会生成这些字段，只是值设为0
                nb_field_suffixes = [
                    "_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"
                ]
                # 注意：已删除 Pvfl_Nb_Ini_Cca_Rec_Lkd 字段
                nb_field_prefixes = [
                    "Pvfl_Nb_Ini_Cfa_Rec_Lkd",
                    "Pvfl_Nb_Ini_Cca_Rep_Wlk",
                    "Pvfl_Nb_Ini_Cfa_Rep_Wlk",
                    "Pvfl_Nb_Eop_Cfa_Rep_Wlk",
                    "Pvfl_Nb_Eop_Cca_Rep_Wlk",
                    "Pvfl_Nb_Eop_Cfa_Rep_Cur",
                ]
                for prefix in nb_field_prefixes:
                    for suffix in nb_field_suffixes:
                        field_name = f"{prefix}{suffix}"
                        results[field_name] = DECIMAL_ZERO
        
        # --- IF Fields (有效合同PV数据) ---
        # 判断是否为签单年度：签单年 = 评估年 → 新业务，签单年 < 评估年 → 有效合同
        
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
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Cla_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Mtn_Amt",
                "Pvfl_If_Bop_Cfa_Beg_Lcu_Rad_Amt",
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
            ]
                for field in if_required_fields:
                    if field not in results:
                        results[field] = DECIMAL_ZERO
            else:
                # 非签单年度（第二年及以后）：计算有效合同的PV数据
                # 年初（BOP）：评估年1月1日
                bop_date = date(val_month_date.year, 1, 1)
                year_start = date(val_month_date.year, 1, 1)  # 有效合同从年初开始
                
                # 获取年初现金流（基于上年年底的精算假设）
                # 修复：确保使用基于上年末精算假设的现金流，而不是当前评估月假设
                if val_month_date.year in bop_cf_by_year:
                    cf_bop = bop_cf_by_year[val_month_date.year]
                else:
                    # 如果没有年初现金流，使用上年末假设的现金流（cf_prev_ye）
                    # 注意：这里不应该fallback到当前现金流（cf_for_calc），因为年初预期必须基于上年末假设
                    # cf_prev_ye在循环开始时就已生成，基于上年末精算假设（assump_prev_ye）
                    cf_bop = cf_prev_ye
                
                # 年初预期当期现金流（BOP_Cca）：评估年度内的现金流
                if not cf_bop.empty:
                    cf_bop_current = cf_bop[
                        (cf_bop['Date_Obj'] >= year_start) &
                        (cf_bop['Date_Obj'] <= val_month_end)
                    ]
                    cf_bop_future = cf_bop[cf_bop['Date_Obj'] > val_month_end]
                    # Beg字段：必须包含从1月1日开始的所有现金流
                    cf_bop_beg = cf_bop[cf_bop['Date_Obj'] >= year_start]
                else:
                    cf_bop_current = cf_bop
                    cf_bop_future = cf_bop
                    cf_bop_beg = cf_bop
                
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
                
                # 年初预期未来现金流（BOP_Cfa）：评估期末之后发生的现金流，折现到评估月底
                res_bop_cfa = calc_all(cf_bop_future, val_month_end, uw_date, rate_val_locked_df, "")
                for k, v in res_bop_cfa.items():
                    results[f"Pvfl_If_Bop_Cfa_Rep_Wlk{k}"] = v
                
                # --- 新增：年初现值（Beg）字段计算 ---
                # 折现到年初时点（1月1日），使用上年年末的锁定利率曲线（Lcu）
                # 仅针对有效合同年初预期（If_Bop），且仅在年初（is_bop）时计算
                # 注意：这里已经在 is_bop 且 not is_new_business 的分支中，所以不需要再次判断
                
                # 年初时点（1月1日）
                bop_date = date(val_month_date.year, 1, 1)
                
                # [修正] 为了保证与上年期末现值的一致性，Beg PV 的折现基准日应设为上年期末（12月31日）
                # 原因：在月度离散模型中，T年末和T+1年初视为同一时刻。
                # 如果使用 1月1日 作为基准日，relativedelta 会导致 1月31日的现金流与 1月1日 只有 0 个月差（不折现），
                # 而 12月31日 到 1月31日 有 1 个月差（折现 1 期）。这导致了 PV 的跳变。
                val_date_for_beg_pv = date(val_month_date.year - 1, 12, 31)
                
                # 获取上年年末的锁定利率曲线（上年12月31日）
                # Lcu字段：使用上年年末的锁定利率曲线（如202212）
                prev_year_end_month = date(val_month_date.year - 1, 12, 31).strftime("%Y%m")
                rate_prev_year_locked_df = get_discount_factors("locked", prev_year_end_month)
                
                # 注意：已删除 Cca_Beg_Lcu 字段，因为 Cfa_Beg_Lcu 已经包含了1月现金流
                # 计算年初预期未来（BOP_Cfa）的年初现值（Beg_Lcu）
                # Beg字段：必须包含从1月1日开始的所有现金流
                # 折现到年初时点（实际使用上年末日期以保证一致性），使用上年年末锁定利率曲线
                # 对于Lcu字段，需要特殊处理折现逻辑：从1月1日开始，使用上年末利率曲线折现
                res_bop_cfa_beg = calc_all_beg_lcu(cf_bop_beg, val_date_for_beg_pv, prev_year_end_month, rate_prev_year_locked_df)
                # 修正RA计算：使用年初时的精算假设（val_assump_obj）
                cla_beg_fut = res_bop_cfa_beg.get("_Cla_Amt", DECIMAL_ZERO)
                mtn_beg_fut = res_bop_cfa_beg.get("_Mtn_Amt", DECIMAL_ZERO)
                rad_beg_fut = (cla_beg_fut + mtn_beg_fut) * val_assump_obj.ra_ratio
                res_bop_cfa_beg["_Rad_Amt"] = rad_beg_fut
                # 只保存赔付、维费、RA字段（删除保费和IACF）
                for k, v in res_bop_cfa_beg.items():
                    if k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                        results[f"Pvfl_If_Bop_Cfa_Beg_Lcu{k}"] = v
                
                # 计算年初预期未来（BOP_Cfa）的年初现值（Beg_Wlk）- 赔付、维费、RA
                # 折现到年初时点（实际使用上年末日期以保证一致性），使用签单日的锁定利率曲线（加权初始确认利率）
                # Beg字段：必须包含从1月1日开始的所有现金流
                # 这些字段用于IFIE_OCI计算（利率变化影响），必须保留！
                res_bop_cfa_beg_wlk = calc_all(cf_bop_beg, val_date_for_beg_pv, uw_date, rate_val_locked_df, "")
                # RA计算：使用相同维度的赔付+维持费用的值*精算假设中的ra率
                cla_beg_wlk_fut = res_bop_cfa_beg_wlk.get("_Cla_Amt", DECIMAL_ZERO)
                mtn_beg_wlk_fut = res_bop_cfa_beg_wlk.get("_Mtn_Amt", DECIMAL_ZERO)
                rad_beg_wlk_fut = (cla_beg_wlk_fut + mtn_beg_wlk_fut) * val_assump_obj.ra_ratio
                res_bop_cfa_beg_wlk["_Rad_Amt"] = rad_beg_wlk_fut
                # 只保存赔付、维费、RA字段（用于IFIE_OCI和LC分摊IFIE计算，删除保费和IACF）
                for k, v in res_bop_cfa_beg_wlk.items():
                    if k in ["_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
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
                
                # 删除 Eop_Cca_Rep_Cur 字段（未使用，当期现金流不需要当期利率折现）
            
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
                    'is_reversal_policy': is_reversal_policy,  # 批减单标记
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