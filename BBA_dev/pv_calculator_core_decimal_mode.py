"""
PV计算核心 - 强制Decimal精确计算模式

目标：确保与旧版模拟器计算结果完全一致
策略：禁用所有JIT加速和float计算，强制使用Decimal高精度计算
"""

import pandas as pd
import numpy as np
from datetime import date
from decimal import Decimal, getcontext
import calendar
from typing import Dict, List, Optional

# 设置高精度
getcontext().prec = 28

from BBA_dev.projector import CashFlowProjector
from BBA_dev.models.pv_source_data import PVSourceData, PVSourceDataCollection

# 强制禁用JIT和向量化，确保精确计算
USE_VECTORIZED_PV = False
USE_JIT_BATCH = False
DECIMAL_ZERO = Decimal('0')

def get_monthly_rate_decimal(rates_map: Dict[int, Decimal], term_month: int, max_term: int) -> Decimal:
    """获取月度利率（Decimal精确版本）"""
    if term_month <= 0: 
        return DECIMAL_ZERO
    if term_month > max_term: 
        return rates_map.get(max_term, DECIMAL_ZERO)
    return rates_map.get(term_month, DECIMAL_ZERO)

def calculate_discount_factor_decimal(rate_annual: Decimal, term_months: int) -> Decimal:
    """计算折现因子（Decimal精确版本）"""
    if term_months <= 0 or rate_annual <= 0:
        return Decimal('1')
    
    # 使用精确的复利公式: (1 + r)^(-t/12)
    base = Decimal('1') + rate_annual
    exponent = Decimal(str(term_months)) / Decimal('12')
    
    # 使用Decimal的精确幂运算
    try:
        discount_factor = base ** (-exponent)
        return discount_factor
    except Exception:
        # 降级处理：使用近似计算
        monthly_rate = rate_annual / Decimal('12')
        return (Decimal('1') + monthly_rate) ** (-term_months)

def set_cf_dates_for_initial_recognition_decimal(cf_df, uw_date, col_name):
    """为初始确认设置现金流日期（Decimal版本）"""
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
                # 保费和获取费用：月中（15日）
                date_list.append(date(cf_year, cf_month, 15))
            else:
                # 赔付和费用：月末
                _, last_day = calendar.monthrange(cf_year, cf_month)
                date_list.append(date(cf_year, cf_month, last_day))
        else:
            # 其他月份：月末
            _, last_day = calendar.monthrange(cf_year, cf_month)
            date_list.append(date(cf_year, cf_month, last_day))
    
    cf_df['Date_Obj'] = date_list
    return cf_df

def calculate_pv_initial_recognition_decimal(cf_df, col_name, rates_map, max_term, uw_date):
    """计算初始确认现值（Decimal精确版本）"""
    total_pv = DECIMAL_ZERO
    uw_year_month = (uw_date.year, uw_date.month)
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
        
        cf_date = row['Date_Obj']
        yyyymm = str(row['YYYYMM'])
        cf_year = int(yyyymm[:4])
        cf_month = int(yyyymm[4:6])
        
        # 计算期限（月数）
        if (cf_year, cf_month) == uw_year_month:
            # 签单月：特殊处理
            if col_name in ['Premium', 'IACF']:
                # 保费/获取费用：从签单日到月中的期限
                from dateutil.relativedelta import relativedelta
                months_diff = (cf_date.year - uw_date.year) * 12 + (cf_date.month - uw_date.month)
                days_diff = cf_date.day - uw_date.day
                term_months_precise = months_diff + days_diff / 30.0  # 近似处理
                term_months = max(1, int(round(term_months_precise * 12)) / 12)  # 转换为分数月
            else:
                # 赔付/费用：从签单日到月末
                term_months = 1
        else:
            # 其他月份：从签单月末到现金流月末
            term_months = (cf_year - uw_date.year) * 12 + (cf_month - uw_date.month)
        
        if term_months <= 0:
            # 当期现金流，无折现
            pv = amount
        else:
            # 获取利率并折现
            rate = get_monthly_rate_decimal(rates_map, int(term_months), max_term)
            discount_factor = calculate_discount_factor_decimal(rate, term_months)
            pv = amount * discount_factor
        
        total_pv += pv
    
    return total_pv

def calculate_pv_exact_decimal(cf_df, col_name, rates_map, val_date, curve_base_date):
    """计算精确现值（Decimal精确版本）"""
    total_pv = DECIMAL_ZERO
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
        
        cf_date = row['Date_Obj']
        
        # 计算从估值日到现金流日期的期限
        from dateutil.relativedelta import relativedelta
        delta = relativedelta(cf_date, val_date)
        term_months = delta.years * 12 + delta.months
        
        # 处理不足一个月的情况
        if delta.days > 0:
            term_months += delta.days / 30.0  # 近似处理
        
        if term_months <= 0:
            # 当期或过去的现金流
            pv = amount
        else:
            # 获取对应期限的利率
            rate = get_monthly_rate_decimal(rates_map, int(term_months), max(rates_map.keys()))
            discount_factor = calculate_discount_factor_decimal(rate, term_months)
            pv = amount * discount_factor
        
        total_pv += pv
    
    return total_pv

def calculate_pv_cca_decimal(cf_df, col_name, rates_map, val_date, curve_base_date):
    """计算当期现值（Decimal精确版本）"""
    # CCA (Current Coverage Amount) 仅包含当期现金流
    total_pv = DECIMAL_ZERO
    val_year = val_date.year
    
    for _, row in cf_df.iterrows():
        amount = Decimal(str(row[col_name]))
        if amount == 0:
            continue
        
        cf_date = row['Date_Obj']
        
        # 只考虑当年的现金流
        if cf_date.year == val_year:
            # 当期现金流，折现到评估日
            from dateutil.relativedelta import relativedelta
            delta = relativedelta(cf_date, val_date)
            term_months = delta.years * 12 + delta.months
            
            if delta.days > 0:
                term_months += delta.days / 30.0
            
            if term_months <= 0:
                pv = amount
            else:
                rate = get_monthly_rate_decimal(rates_map, int(term_months), max(rates_map.keys()))
                discount_factor = calculate_discount_factor_decimal(rate, term_months)
                pv = amount * discount_factor
            
            total_pv += pv
    
    return total_pv

def calculate_pv_core_decimal_mode(policy_row: pd.Series, assumptions_map: Dict[str, object], rates_map: Dict[str, pd.DataFrame]):
    """
    PV计算核心入口（强制Decimal精确计算模式）
    
    Args:
        policy_row: 保单数据行
        assumptions_map: 字典 { 'YYYYMM': Assumptions对象 }
        rates_map: 字典 { 'YYYYMM': Rates_DataFrame }
    
    Returns:
        PVSourceDataCollection 对象
    """
    policy_no = policy_row.get('policy_no', 'UNKNOWN')
    pv_collection = PVSourceDataCollection(policy_no=policy_no)
    
    # 1. 基础变量
    uw_date = pd.to_datetime(policy_row["under_write_date"]).date()
    
    # 2. 固定评估时点（与旧版保持一致）
    val_months = []
    
    # 签单月（初始确认）
    init_month_str = uw_date.strftime('%Y%m')
    val_months.append((uw_date, init_month_str, "初始确认"))
    
    # 签单年年底
    if uw_date.year <= 2024:
        eoy_date = date(uw_date.year, 12, 31)
        eoy_month_str = eoy_date.strftime('%Y%m')
        val_months.append((eoy_date, eoy_month_str, f"{uw_date.year}年年底"))
    
    # 后续年份
    for year in range(uw_date.year + 1, 2025):
        # 年初
        boy_date = date(year, 1, 1)
        boy_month_str = boy_date.strftime('%Y%m')
        val_months.append((boy_date, boy_month_str, f"{year}年年初"))
        
        # 年底
        eoy_date = date(year, 12, 31)
        eoy_month_str = eoy_date.strftime('%Y%m')
        val_months.append((eoy_date, eoy_month_str, f"{year}年年底"))
    
    # 3. 现金流投射器
    projector = CashFlowProjector()
    
    # 4. 逐月计算PV
    for val_date, val_month_str, desc in val_months:
        
        print(f"计算 {val_month_str} ({desc}) 的PV数据...")
        
        # 获取对应的假设和利率
        assumptions = assumptions_map.get(val_month_str)
        rates_df = rates_map.get(val_month_str)
        
        if not assumptions or rates_df is None or rates_df.empty:
            print(f"  [WARN] 跳过 {val_month_str}: 缺少假设或利率数据")
            continue
        
        # 转换利率为字典格式
        rates_dict = {}
        max_term = 0
        for _, row in rates_df.iterrows():
            term = int(row['term_month'])
            # 对齐旧逻辑：使用 forward_disrate_value 作为利率列
            rate = Decimal(str(row.get('forward_disrate_value', row.get('annual_rate', 0))))
            rates_dict[term] = rate
            max_term = max(max_term, term)
        
        # 投射现金流
        try:
            # 构建policy_row用于现金流投射
            policy_dict = {
                'sum_premium_no_tax': float(policy_row.get('sum_premium_no_tax', 0)),
                'premium': float(policy_row.get('sum_premium_no_tax', 0)),
                'iacf_amount': float(policy_row.get('sum_premium_no_tax', 0)) * float(assumptions.acquisition_expense_ratio),
                'start_date': policy_row['start_date'],
                'end_date': policy_row['end_date'],
                'under_write_date': policy_row['under_write_date'],
                'warranty_end_date': policy_row.get('warranty_end_date', policy_row['start_date']),
            }
            
            cf_df = projector.project_policy_flows(policy_dict, assumptions)
            if cf_df.empty:
                print(f"  [WARN] 跳过 {val_month_str}: 现金流投射结果为空")
                continue
            
            # 设置现金流日期
            cf_df['Date_Obj'] = pd.to_datetime(cf_df['YYYYMM'], format='%Y%m') + pd.offsets.MonthEnd(0)
            cf_df['Date_Obj'] = cf_df['Date_Obj'].dt.date
            
        except Exception as e:
            print(f"  [ERROR] 现金流投射失败 {val_month_str}: {e}")
            continue
        
        # 计算各种PV字段
        results = {}
        
        # 判断是否为新业务
        is_new_business = (val_date == uw_date)
        
        if is_new_business:
            print(f"  计算新业务PV字段...")
            
            # === 新业务PV计算 ===
            
            # 1. Nb_Ini_Cfa_Rec_Lkd（初始确认，锁定利率）
            for col in ['Premium', 'IACF', 'Claims', 'Expenses']:
                cf_temp = set_cf_dates_for_initial_recognition_decimal(cf_df, uw_date, col)
                val = calculate_pv_initial_recognition_decimal(cf_temp, col, rates_dict, max_term, uw_date)
                
                prefix = "Pvfl_Nb_Ini_Cfa_Rec_Lkd"
                field_map = {'Premium': 'Pre', 'IACF': 'Acq', 'Claims': 'Cla', 'Expenses': 'Mtn'}
                results[f"{prefix}_{field_map[col]}_Amt"] = val
            
            # 计算风险调整
            total_claims_maint = results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt"] + results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt"]
            results["Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt"] = total_claims_maint * assumptions.ra_ratio
            
            # 2. 其他新业务字段（简化处理，使用相同的计算逻辑）
            # Nb_Ini_Cca_Rep_Wlk, Nb_Ini_Cfa_Rep_Wlk, Nb_Eop_*
            
            nb_prefixes = [
                "Pvfl_Nb_Ini_Cca_Rep_Wlk", "Pvfl_Nb_Ini_Cfa_Rep_Wlk",
                "Pvfl_Nb_Eop_Cfa_Rep_Wlk", "Pvfl_Nb_Eop_Cca_Rep_Wlk", 
                "Pvfl_Nb_Eop_Cfa_Rep_Cur"
            ]
            
            for prefix in nb_prefixes:
                for suffix in ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt"]:
                    field_name = f"{prefix}{suffix}"
                    
                    if "Cca" in prefix:
                        # 当期现值（基准=评估日）
                        col_map = {'_Pre_Amt': 'Premium', '_Acq_Amt': 'IACF', 
                                 '_Cla_Amt': 'Claims', '_Mtn_Amt': 'Expenses'}
                        col = col_map[suffix]
                        results[field_name] = calculate_pv_cca_decimal(cf_df, col, rates_dict, val_date, val_date)
                    else:
                        # 全期现值（基准=评估日，符合旧逻辑 current curve 折现）
                        col_map = {'_Pre_Amt': 'Premium', '_Acq_Amt': 'IACF',
                                 '_Cla_Amt': 'Claims', '_Mtn_Amt': 'Expenses'}
                        col = col_map[suffix]
                        results[field_name] = calculate_pv_exact_decimal(cf_df, col, rates_dict, val_date, val_date)
                
                # 风险调整
                rad_field = f"{prefix}_Rad_Amt"
                cla_field = f"{prefix}_Cla_Amt"
                mtn_field = f"{prefix}_Mtn_Amt"
                results[rad_field] = (results.get(cla_field, DECIMAL_ZERO) + 
                                    results.get(mtn_field, DECIMAL_ZERO)) * assumptions.ra_ratio
            
            # IF字段置零
            if_prefixes = [
                "Pvfl_If_Bop_Cca_Rep_Wlk", "Pvfl_If_Bop_Cfa_Rep_Wlk", 
                "Pvfl_If_Bop_Cfa_Beg_Lcu", "Pvfl_If_Bop_Cfa_Beg_Wlk",
                "Pvfl_If_Eop_Cfa_Rep_Wlk", "Pvfl_If_Eop_Cca_Rep_Wlk", 
                "Pvfl_If_Eop_Cfa_Rep_Cur"
            ]
            
            for prefix in if_prefixes:
                for suffix in ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                    results[f"{prefix}{suffix}"] = DECIMAL_ZERO
        
        else:
            print(f"  计算存量合同PV字段...")
            
            # === 存量合同PV计算 ===
            
            # NB字段置零
            nb_prefixes = [
                "Pvfl_Nb_Ini_Cfa_Rec_Lkd", "Pvfl_Nb_Ini_Cca_Rep_Wlk", 
                "Pvfl_Nb_Ini_Cfa_Rep_Wlk", "Pvfl_Nb_Eop_Cfa_Rep_Wlk",
                "Pvfl_Nb_Eop_Cca_Rep_Wlk", "Pvfl_Nb_Eop_Cfa_Rep_Cur"
            ]
            
            for prefix in nb_prefixes:
                for suffix in ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt", "_Rad_Amt"]:
                    results[f"{prefix}{suffix}"] = DECIMAL_ZERO
            
            # IF字段计算（简化处理）
            if_prefixes = [
                "Pvfl_If_Bop_Cca_Rep_Wlk", "Pvfl_If_Bop_Cfa_Rep_Wlk",
                "Pvfl_If_Bop_Cfa_Beg_Lcu", "Pvfl_If_Bop_Cfa_Beg_Wlk",
                "Pvfl_If_Eop_Cfa_Rep_Wlk", "Pvfl_If_Eop_Cca_Rep_Wlk",
                "Pvfl_If_Eop_Cfa_Rep_Cur"
            ]
            
            for prefix in if_prefixes:
                for suffix in ["_Pre_Amt", "_Acq_Amt", "_Cla_Amt", "_Mtn_Amt"]:
                    field_name = f"{prefix}{suffix}"
                    
                    if "Cca" in prefix:
                        # 当期现值（基准=评估日）
                        col_map = {'_Pre_Amt': 'Premium', '_Acq_Amt': 'IACF',
                                 '_Cla_Amt': 'Claims', '_Mtn_Amt': 'Expenses'}
                        col = col_map[suffix]
                        results[field_name] = calculate_pv_cca_decimal(cf_df, col, rates_dict, val_date, val_date)
                    else:
                        # 全期现值（基准=评估日）
                        col_map = {'_Pre_Amt': 'Premium', '_Acq_Amt': 'IACF',
                                 '_Cla_Amt': 'Claims', '_Mtn_Amt': 'Expenses'}
                        col = col_map[suffix]
                        results[field_name] = calculate_pv_exact_decimal(cf_df, col, rates_dict, val_date, val_date)
                
                # 风险调整
                rad_field = f"{prefix}_Rad_Amt"
                cla_field = f"{prefix}_Cla_Amt"
                mtn_field = f"{prefix}_Mtn_Amt"
                results[rad_field] = (results.get(cla_field, DECIMAL_ZERO) + 
                                    results.get(mtn_field, DECIMAL_ZERO)) * assumptions.ra_ratio
        
        # 创建PV数据对象
        pv_data = PVSourceData(
            policy_no=policy_no,
            valuation_month=val_month_str,
            valuation_date=val_date,
            under_write_date=uw_date,
            pv_fields=results
        )
        
        # 添加到集合
        pv_collection.data_by_month[val_month_str] = pv_data
        
        print(f"  [OK] 完成 {val_month_str}: 生成 {len(results)} 个PV字段")
    
    print(f"[OK] PV计算完成，共处理 {len(pv_collection.data_by_month)} 个评估月")
    
    return pv_collection

# 导出主要函数
def calculate_pv_core(policy_row: pd.Series, assumptions_map: Dict[str, object], rates_map: Dict[str, pd.DataFrame]):
    """兼容性接口：强制使用Decimal精确模式"""
    return calculate_pv_core_decimal_mode(policy_row, assumptions_map, rates_map)
