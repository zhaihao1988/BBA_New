import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from decimal import Decimal

import pandas as pd

# 将项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from BBA_group.scripts.generate_ifrs17_reports_from_batch_csv import (
    _fill_nan_numeric_to_zero,
    _auto_fix_sign,
    _derive_fields_for_103,
    _normalize_certi_no,
    _coerce_year,
    _build_yearly_results,
    GroupKey,
    SIGN_FIX_COLUMNS,
)

# 直接复用 103/104 报表的核心计算逻辑，避免在本脚本中重复实现一套“第二口径”
from BBA_group.utils.generate_ifrs17_103_report import (
    convert_yearly_results_to_data_by_year,
    generate_report_data,
)
from BBA_group.utils import generate_ifrs17_104_report as gen104


@dataclass
class ValidationResult:
    """验算结果"""
    policy_no: str
    certi_no: Optional[str]
    year: int
    passed_103: bool
    passed_104: bool
    diff_103: Dict[str, Decimal]  # {'non_lc': ..., 'lc': ..., 'lic': ...}
    diff_104: Dict[str, Decimal]  # {'pv': ..., 'ra': ..., 'csm': ...}
    error: Optional[str] = None


def parse_decimal(val):
    """将值转换为Decimal"""
    if val is None:
        return Decimal('0')
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    if isinstance(val, Decimal):
        return val
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return Decimal('0')
    return Decimal(s)


def _validate_103_year(data: Dict, year: int, years: List[int], opening: Optional[Dict] = None) -> Tuple[Dict, Dict[str, Decimal], bool]:
    """
    验算103报表的单个年度
    
    Returns:
        (updated_opening, diff_dict, passed)
        - updated_opening: 更新后的期初余额（用于下一年）
        - diff_dict: 差异字典 {'non_lc': ..., 'lc': ..., 'lic': ...}
        - passed: 是否通过验算
    """
    from decimal import Decimal
    
    def get_d(key):
        return parse_decimal(data.get(key, 0))
    
    is_initial_year = (year == min(years))
    is_final_year = (year == max(years))
    
    # 计算期初余额（第一年从日志提取，后续年份使用上一年期末）
    if is_initial_year or opening is None:
        opening_bel = get_d('opening_bel')
        opening_ra = get_d('opening_ra')
        opening_csm = get_d('opening_csm')
        opening_lc_log = get_d('opening_lc')
        opening_lic = get_d('opening_lic')
        
        opening_lrc_total = opening_bel + opening_ra + opening_csm
        opening_lc_display = -opening_lc_log if opening_lc_log < 0 else opening_lc_log
        opening_non_lc = opening_lrc_total - opening_lc_display
        
        opening = {
            'lrc_non_lc': opening_non_lc,
            'lrc_lc': opening_lc_display,
            'lic': opening_lic
        }
    
    # --- 计算收入 ---
    rev_csm = get_d('保险合同收入_摊销的CSM')
    rev_iacf = -get_d('保险合同收入_摊销的IACF')
    rev_exp = get_d('保险合同收入_经验调整')
    
    rev_lc_release_claims = get_d('保险合同收入_预期赔付与费用_亏损分摊')
    rev_lc_release_ra = get_d('保险合同收入_预期释放的非金融风险调整_亏损分摊')
    
    rev_claims_gross = get_d('保险合同收入_预期赔付与费用_含亏损')
    rev_ra_gross = get_d('保险合同收入_预期释放的非金融风险调整_含亏损')
    
    rev_claims_net = rev_claims_gross - rev_lc_release_claims
    rev_ra_net = rev_ra_gross - rev_lc_release_ra
    
    revenue_non_lc = rev_csm + rev_iacf + rev_exp - rev_claims_net - rev_ra_net
    revenue_lc = Decimal('0')
    
    # --- 计算费用 ---
    iacf_amort_exp = get_d('赔付与费用_摊销的IACF')
    
    initial_loss_recog = -get_d('nb_initial_lc') if is_initial_year else Decimal('0')
    lc_change_est = get_d('亏损合同损益_不调整CSM的预期现金流变动') + get_d('亏损合同损益_不调整CSM的非金融风险调整变动')
    
    lc_release_claims = get_d('保险合同收入_预期赔付与费用_亏损分摊')
    lc_release_ra = get_d('保险合同收入_预期释放的非金融风险调整_亏损分摊')
    lc_release_total = lc_release_claims + lc_release_ra
    
    net_lc_recog_non_lc = Decimal('0')
    
    if is_final_year:
        ifie_pl_cf_lc_temp = get_d('IFIE_P&L_未到期_预期现金流_亏损')
        ifie_pl_ra_lc_temp = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')
        ifie_oci_cf_lc_temp = get_d('IFIE_OCI_未到期_预期现金流_亏损')
        ifie_oci_ra_lc_temp = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')
        ifie_lc_total = (ifie_pl_cf_lc_temp + ifie_pl_ra_lc_temp) + (ifie_oci_cf_lc_temp + ifie_oci_ra_lc_temp)
        
        opening_lc_abs = -opening['lrc_lc'] if opening['lrc_lc'] < 0 else opening['lrc_lc']
        lc_after_ifie = opening_lc_abs + ifie_lc_total
        total_reversal = lc_release_total
        
        if total_reversal > lc_after_ifie:
            excess_to_non_lc = total_reversal - lc_after_ifie
            net_lc_recog_non_lc = -excess_to_non_lc
            net_lc_recog = -lc_after_ifie
        else:
            net_lc_recog = -total_reversal
    else:
        net_lc_recog = initial_loss_recog + lc_change_est - lc_release_total
    
    service_expense_non_lc = iacf_amort_exp + net_lc_recog_non_lc
    service_expense_lc = net_lc_recog
    service_expense_lic = Decimal('0')
    
    # --- 计算业绩 ---
    res_non_lc = revenue_non_lc + service_expense_non_lc
    res_lc = revenue_lc + service_expense_lc
    res_lic = service_expense_lic
    
    # --- 计算IFIE P&L ---
    ifie_pl_cf_non_lc_raw = get_d('IFIE_P&L_未到期_预期现金流_非亏损')
    ifie_pl_ra_non_lc_raw = get_d('IFIE_P&L_未到期_非金融风险调整_非亏损')
    ifie_pl_csm = get_d('IFIE_P&L_未到期_CSM')
    ifie_pl_cf_lc_log = get_d('IFIE_P&L_未到期_预期现金流_亏损')
    ifie_pl_ra_lc_log = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')
    
    ifie_pl_total = (ifie_pl_cf_non_lc_raw + ifie_pl_cf_lc_log) + (ifie_pl_ra_non_lc_raw + ifie_pl_ra_lc_log) - ifie_pl_csm
    ifie_pl_lc_log_sum = ifie_pl_cf_lc_log + ifie_pl_ra_lc_log
    ifie_pl_lc_display = -ifie_pl_lc_log_sum
    ifie_pl_non_lc = ifie_pl_total - ifie_pl_lc_display
    ifie_pl_lic = Decimal('0')
    
    # --- 计算IFIE OCI ---
    ifie_oci_cf_non_lc_raw = get_d('IFIE_OCI_未到期_预期现金流_非亏损')
    ifie_oci_ra_non_lc_raw = get_d('IFIE_OCI_未到期_非金融风险调整_非亏损')
    ifie_oci_cf_lc_log = get_d('IFIE_OCI_未到期_预期现金流_亏损')
    ifie_oci_ra_lc_log = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')
    
    ifie_oci_total = (ifie_oci_cf_non_lc_raw + ifie_oci_cf_lc_log) + (ifie_oci_ra_non_lc_raw + ifie_oci_ra_lc_log)
    ifie_oci_lc_log_sum = ifie_oci_cf_lc_log + ifie_oci_ra_lc_log
    ifie_oci_lc_display = -ifie_oci_lc_log_sum
    ifie_oci_non_lc = ifie_oci_total - ifie_oci_lc_display
    
    # --- 计算综合收益变动合计 ---
    tci_non_lc = res_non_lc + ifie_pl_non_lc + ifie_oci_non_lc
    tci_lc = res_lc + ifie_pl_lc_display + ifie_oci_lc_display
    tci_lic = res_lic + ifie_pl_lic
    
    # --- 计算现金流 ---
    cf_premium = get_d('现金流_收到的保费')
    cf_iacf = -get_d('现金流_支付的获取费用')
    cf_claims = Decimal('0')
    cf_other = Decimal('0')
    cf_total_non_lc = cf_premium + cf_iacf + cf_claims + cf_other
    cf_total_lc = Decimal('0')
    cf_total_lic = Decimal('0')
    
    # --- 其他变动 ---
    other_changes_non_lc = Decimal('0')
    other_changes_lc = Decimal('0')
    other_changes_lic = Decimal('0')
    
    # --- 计算期末余额 ---
    inv_comp = Decimal('0')
    closing_non_lc = opening['lrc_non_lc'] + tci_non_lc - inv_comp + cf_total_non_lc + other_changes_non_lc
    closing_lc = opening['lrc_lc'] + tci_lc + other_changes_lc
    closing_lic = opening['lic'] + tci_lic + inv_comp + cf_total_lic + other_changes_lic
    closing_lc_display = -closing_lc if closing_lc < 0 else closing_lc
    
    # --- 验算：比较计算值与日志值 ---
    is_termination_year = False
    if is_final_year:
        try:
            closing_sum = (
                get_d('closing_bel')
                + get_d('closing_ra')
                + get_d('closing_csm')
                + get_d('closing_lic')
            )
            is_termination_year = (closing_sum > -Decimal('0.01') and closing_sum < Decimal('0.01'))
        except Exception:
            is_termination_year = False
    
    if is_termination_year:
        log_non_lc_display = Decimal('0')
        log_lc_display = Decimal('0')
        log_lic = Decimal('0')
    else:
        log_closing_bel = get_d('closing_bel')
        log_closing_ra = get_d('closing_ra')
        log_closing_csm = get_d('closing_csm')
        log_lc_display = closing_lc_display
        log_non_lc_display = log_closing_bel + log_closing_ra + log_closing_csm - log_lc_display
        log_lic = get_d('closing_lic')
    
    diff_non_lc = closing_non_lc - log_non_lc_display
    diff_lc = closing_lc_display - log_lc_display
    diff_lic = closing_lic - log_lic
    
    diff_dict = {
        'non_lc': diff_non_lc,
        'lc': diff_lc,
        'lic': diff_lic
    }
    
    # 判断是否通过（差异绝对值 < 0.01）
    passed = (
        abs(diff_non_lc) < Decimal('0.01') and
        abs(diff_lc) < Decimal('0.01') and
        abs(diff_lic) < Decimal('0.01')
    )
    
    # 更新期初余额用于下一年
    updated_opening = {
        'lrc_non_lc': closing_non_lc,
        'lrc_lc': closing_lc_display,
        'lic': closing_lic
    }
    
    return updated_opening, diff_dict, passed


def _validate_104_year(data: Dict, year: int, years: List[int], opening_balance: Optional[Dict] = None) -> Tuple[Dict, Dict[str, Decimal], bool]:
    """
    验算104报表的单个年度
    
    Returns:
        (updated_opening, diff_dict, passed)
        - updated_opening: 更新后的期初余额（用于下一年）
        - diff_dict: 差异字典 {'pv': ..., 'ra': ..., 'csm': ...}
        - passed: 是否通过验算
    """
    from decimal import Decimal
    
    def get_d(key):
        return parse_decimal(data.get(key, 0))
    
    is_initial_year = (year == min(years))
    
    # 期初余额（第一年从日志提取，后续年份使用上一年期末）
    if is_initial_year or opening_balance is None:
        opening_balance = {
            'pv': get_d('opening_bel'),
            'ra': get_d('opening_ra'),
            'csm': get_d('opening_csm')
        }
    
    net_opening = opening_balance.copy()
    
    # --- 当期服务相关变动 ---
    csm_amort = get_d('保险合同收入_摊销的CSM')
    ra_release_gross = get_d('保险合同收入_预期释放的非金融风险调整_含亏损')
    ra_change = -ra_release_gross
    
    expected_claims_exp = get_d('保险合同收入_预期赔付与费用_含亏损')
    actual_claims_exp = Decimal('0')
    exp_adj_log = get_d('保险合同收入_经验调整')
    curr_service_pv_val = actual_claims_exp - expected_claims_exp + exp_adj_log
    
    curr_service_sum = {
        'pv': curr_service_pv_val,
        'ra': ra_change,
        'csm': csm_amort
    }
    
    # --- 未来服务相关变动 ---
    # 第一年也应该使用新增合同数据（与104报表生成逻辑一致）
    nb_claims_profit = get_d('新增合同预期现金流_赔付与费用现金流_盈利合同')
    nb_iacf_profit = get_d('新增合同预期现金流_IACF_盈利合同')
    nb_prem_profit = get_d('新增合同预期现金流_保费现金流_盈利合同')
    
    nb_claims_loss = get_d('新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损')
    loss_nb_cf = get_d('亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损')
    nb_iacf_loss = get_d('新增合同预期现金流_IACF_亏损合同')
    nb_prem_loss = get_d('新增合同预期现金流_保费现金流_亏损合同')
    
    nb_bel = (nb_claims_profit + nb_iacf_profit - nb_prem_profit) + \
             (nb_claims_loss + loss_nb_cf + nb_iacf_loss - nb_prem_loss)
    
    nb_ra = get_d('新增合同非金融风险调整_盈利合同') + \
            get_d('新增合同非金融风险调整_亏损合同_非亏损') + \
            get_d('亏损合同损益_新增合同非金融风险调整_亏损')
    
    nb_csm = get_d('新增合同CSM_盈利合同')
    
    csm_adj_pv = get_d('未到期_调整CSM的预期现金流变动')
    csm_adj_ra = get_d('未到期_调整CSM的非金融风险调整变动')
    csm_adj_csm = get_d('未到期_调整CSM的估计变更')
    
    non_csm_pv = get_d('亏损合同损益_不调整CSM的预期现金流变动')
    non_csm_ra = get_d('亏损合同损益_不调整CSM的非金融风险调整变动')
    
    future_service_sum = {
        'pv': nb_bel + csm_adj_pv + non_csm_pv,
        'ra': nb_ra + csm_adj_ra + non_csm_ra,
        'csm': nb_csm + csm_adj_csm
    }
    
    # --- 保险服务业绩 ---
    ins_service_result = {
        'pv': curr_service_sum['pv'] + future_service_sum['pv'],
        'ra': curr_service_sum['ra'] + future_service_sum['ra'],
        'csm': curr_service_sum['csm'] + future_service_sum['csm']
    }
    
    # --- IFIE P&L ---
    ifie_pl_cf_non_lc = get_d('IFIE_P&L_未到期_预期现金流_非亏损')
    ifie_pl_cf_lc = get_d('IFIE_P&L_未到期_预期现金流_亏损')
    ifie_pv = ifie_pl_cf_non_lc + ifie_pl_cf_lc
    
    ifie_pl_ra_non_lc = get_d('IFIE_P&L_未到期_非金融风险调整_非亏损')
    ifie_pl_ra_lc = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')
    ifie_ra = ifie_pl_ra_non_lc + ifie_pl_ra_lc
    
    ifie_csm_log = get_d('IFIE_P&L_未到期_CSM')
    ifie_csm = -ifie_csm_log
    
    # --- IFIE OCI ---
    ifie_oci_pv_non_lc = get_d('IFIE_OCI_未到期_预期现金流_非亏损')
    ifie_oci_pv_lc = get_d('IFIE_OCI_未到期_预期现金流_亏损')
    ifie_oci_pv = ifie_oci_pv_non_lc + ifie_oci_pv_lc
    
    ifie_oci_ra_non_lc = get_d('IFIE_OCI_未到期_非金融风险调整_非亏损')
    ifie_oci_ra_lc = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')
    ifie_oci_ra = ifie_oci_ra_non_lc + ifie_oci_ra_lc
    
    # --- 相关综合收益变动合计 ---
    total_ci = {
        'pv': ins_service_result['pv'] + ifie_pv + ifie_oci_pv,
        'ra': ins_service_result['ra'] + ifie_ra + ifie_oci_ra,
        'csm': ins_service_result['csm'] + ifie_csm
    }
    
    # --- 现金流 ---
    cf_prem = get_d('现金流_收到的保费')
    cf_acq = -get_d('现金流_支付的获取费用')
    cf_total = cf_prem + cf_acq
    
    # --- 其他变动 ---
    other_change_pv = Decimal('0')
    other_change_ra = Decimal('0')
    
    # --- 计算期末余额 ---
    calc_closing = {
        'pv': net_opening['pv'] + total_ci['pv'] + cf_total + other_change_pv,
        'ra': net_opening['ra'] + total_ci['ra'] + other_change_ra,
        'csm': net_opening['csm'] + total_ci['csm']
    }
    
    # --- 验算：比较计算值与日志值 ---
    log_closing_bel = get_d('未到期责任负债_预期现金流_非亏损') + get_d('未到期责任负债_预期现金流_亏损')
    log_closing_ra = get_d('未到期责任负债_非金融风险调整_非亏损') + get_d('未到期责任负债_非金融风险调整_亏损')
    log_closing_csm = get_d('未到期责任负债_CSM')
    
    diff_pv = calc_closing['pv'] - log_closing_bel
    diff_ra = calc_closing['ra'] - log_closing_ra
    diff_csm = calc_closing['csm'] - log_closing_csm
    
    diff_dict = {
        'pv': diff_pv,
        'ra': diff_ra,
        'csm': diff_csm
    }
    
    # 判断是否通过（差异绝对值 < 0.01）
    passed = (
        abs(diff_pv) < Decimal('0.01') and
        abs(diff_ra) < Decimal('0.01') and
        abs(diff_csm) < Decimal('0.01')
    )
    
    # 更新期初余额用于下一年
    updated_opening = calc_closing.copy()
    
    return updated_opening, diff_dict, passed


def _validate_one_policy(
    key: GroupKey,
    yearly_results: List[Dict],
    validate_103: bool,
    validate_104: bool,
) -> ValidationResult:
    """对单个保批单组合进行验算"""
    try:
        years = sorted([r['year'] for r in yearly_results])
        
        # 103报表验算
        passed_103 = True
        diff_103 = {'non_lc': Decimal('0'), 'lc': Decimal('0'), 'lic': Decimal('0')}
        if validate_103:
            # 使用 103 报表自身的 generate_report_data 作为“权威口径”
            data_by_year = convert_yearly_results_to_data_by_year(yearly_results)
            report_rows, _ = generate_report_data(init_data=None, data_by_year=data_by_year)

            # 按年度取出“年末的保险合同负债(25)”这一行，作为 103 报表的计算期末余额
            closing_rows_by_year: Dict[int, Dict] = {}
            for row in report_rows:
                if row.get("category") == "年末的保险合同负债(25)":
                    closing_rows_by_year[row["year"]] = row

            all_passed_103 = True

            for year in years:
                row = closing_rows_by_year.get(year)
                if not row:
                    # 找不到对应年度的期末行，视为未通过
                    all_passed_103 = False
                    continue

                # 103 报表计算得到的期末 LRC/LIC（计算口径）
                closing_non_lc = parse_decimal(row.get("lrc_non_lc"))
                closing_lc_display = parse_decimal(row.get("lrc_lc"))
                closing_lic = parse_decimal(row.get("lic"))

                # 同一年度在 CSV/yearly_results 中的原始日志值
                year_data = next((r for r in yearly_results if r["year"] == year), {})

                def get_d(key: str) -> Decimal:
                    return parse_decimal(year_data.get(key, 0))

                # 终止年度判断逻辑，与 103 报表内部保持一致
                years_list = [r["year"] for r in yearly_results]
                is_final_year = (year == max(years_list)) if years_list else False
                is_termination_year = False
                if is_final_year:
                    try:
                        closing_sum = (
                            get_d("closing_bel")
                            + get_d("closing_ra")
                            + get_d("closing_csm")
                            + get_d("closing_lic")
                        )
                        is_termination_year = (closing_sum > -Decimal("0.01") and closing_sum < Decimal("0.01"))
                    except Exception:
                        is_termination_year = False

                if is_termination_year:
                    # 终止年度：日志期末应为 0
                    log_non_lc_display = Decimal("0")
                    log_lc_display = Decimal("0")
                    log_lic = Decimal("0")
                else:
                    # 正常年度：从 CSV 日志提取 BEL/RA/CSM，再用“总额-LC”倒挤非亏损部分
                    log_closing_bel = get_d("closing_bel")
                    log_closing_ra = get_d("closing_ra")
                    log_closing_csm = get_d("closing_csm")
                    # LC 在报表中以绝对值呈现，验证时直接使用 103 报表计算得到的 closing_lc_display
                    log_lc_display = closing_lc_display
                    log_non_lc_display = log_closing_bel + log_closing_ra + log_closing_csm - log_lc_display
                    log_lic = get_d("closing_lic")

                diff_non_lc = closing_non_lc - log_non_lc_display
                diff_lc = closing_lc_display - log_lc_display
                diff_lic = closing_lic - log_lic

                # 判断年度是否通过（与 103 报表内部的 0.01 阈值一致）
                passed_year = (
                    abs(diff_non_lc) < Decimal("0.01")
                    and abs(diff_lc) < Decimal("0.01")
                    and abs(diff_lic) < Decimal("0.01")
                )

                if not passed_year:
                    all_passed_103 = False
                    # 记录最大绝对差异
                    if abs(diff_non_lc) > abs(diff_103["non_lc"]):
                        diff_103["non_lc"] = diff_non_lc
                    if abs(diff_lc) > abs(diff_103["lc"]):
                        diff_103["lc"] = diff_lc
                    if abs(diff_lic) > abs(diff_103["lic"]):
                        diff_103["lic"] = diff_lic

            passed_103 = all_passed_103
        
        # 104报表验算
        passed_104 = True
        diff_104 = {'pv': Decimal('0'), 'ra': Decimal('0'), 'csm': Decimal('0')}
        if validate_104:
            # 使用 104 报表自身的 generate_report_data 作为“权威口径”
            data_by_year_104 = gen104.convert_yearly_results_to_data_by_year(yearly_results)
            # 注意：generate_report_data 期望 init_data 至少是一个 dict，这里传空 dict 即可
            report_rows_104, _ = gen104.generate_report_data(init_data={}, data_by_year=data_by_year_104)

            # 按年度取出“年末的保险合同净负债(27)”这一行，作为 104 报表的计算期末余额
            closing_rows_by_year_104: Dict[int, Dict] = {}
            for row in report_rows_104:
                if row.get("category_id") == "27":
                    closing_rows_by_year_104[row["year"]] = row

            all_passed_104 = True

            for year in years:
                row = closing_rows_by_year_104.get(year)
                if not row:
                    # 找不到对应年度的期末行，视为未通过
                    all_passed_104 = False
                    continue

                # 104 报表计算得到的期末 BEL/RA/CSM（计算口径）
                closing_pv = parse_decimal(row.get("pv"))
                closing_ra = parse_decimal(row.get("ra"))
                closing_csm = parse_decimal(row.get("csm"))

                # 同一年度在 CSV/yearly_results 中的原始日志值
                year_data = next((r for r in yearly_results if r["year"] == year), {})

                def get_d_104(key: str) -> Decimal:
                    return parse_decimal(year_data.get(key, 0))

                log_closing_bel = get_d_104('未到期责任负债_预期现金流_非亏损') + get_d_104('未到期责任负债_预期现金流_亏损')
                log_closing_ra = get_d_104('未到期责任负债_非金融风险调整_非亏损') + get_d_104('未到期责任负债_非金融风险调整_亏损')
                log_closing_csm = get_d_104('未到期责任负债_CSM')

                diff_pv = closing_pv - log_closing_bel
                diff_ra = closing_ra - log_closing_ra
                diff_csm = closing_csm - log_closing_csm

                passed_year = (
                    abs(diff_pv) < Decimal('0.01') and
                    abs(diff_ra) < Decimal('0.01') and
                    abs(diff_csm) < Decimal('0.01')
                )

                if not passed_year:
                    all_passed_104 = False
                    # 记录当前保单组合在全部年度中的最大绝对差异
                    if abs(diff_pv) > abs(diff_104['pv']):
                        diff_104['pv'] = diff_pv
                    if abs(diff_ra) > abs(diff_104['ra']):
                        diff_104['ra'] = diff_ra
                    if abs(diff_csm) > abs(diff_104['csm']):
                        diff_104['csm'] = diff_csm

            passed_104 = all_passed_104
        
        # 选择第一个年度作为代表（用于输出）
        first_year = years[0] if years else None
        
        return ValidationResult(
            policy_no=key.policy_no,
            certi_no=key.certi_no,
            year=first_year,
            passed_103=passed_103,
            passed_104=passed_104,
            diff_103=diff_103,
            diff_104=diff_104,
            error=None
        )
    except Exception as e:
        return ValidationResult(
            policy_no=key.policy_no,
            certi_no=key.certi_no,
            year=None,
            passed_103=False,
            passed_104=False,
            diff_103={'non_lc': Decimal('0'), 'lc': Decimal('0'), 'lic': Decimal('0')},
            diff_104={'pv': Decimal('0'), 'ra': Decimal('0'), 'csm': Decimal('0')},
            error=str(e)
        )


def main():
    parser = argparse.ArgumentParser(
        description="基于跑批CSV批量验算IFRS17 103/104报表，找出校验不通过的保单号"
    )
    parser.add_argument(
        "--input",
        default=os.path.join(PROJECT_ROOT, "logs", "bba_batch_results_assumption_202412.csv"),
        help="输入CSV路径（默认：logs/bba_batch_results_assumption_202412.csv）",
    )
    parser.add_argument("--workers", type=int, default=4, help="并行进程数（Windows下建议 1-4）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前N个保单组合（调试用）")
    parser.add_argument("--policy", type=str, default=None, help="只处理指定policy_no（调试用）")
    parser.add_argument("--certi", type=str, default=None, help="只处理指定certi_no（调试用，可为空表示无批单）")
    parser.add_argument(
        "--sign_mode",
        choices=["auto", "none", "force_negative"],
        default="auto",
        help="CSM/IFIE_CSM符号校准策略（默认auto）",
    )
    parser.add_argument("--only_103", action="store_true", help="只验算103")
    parser.add_argument("--only_104", action="store_true", help="只验算104")
    parser.add_argument(
        "--output_csv",
        default=None,
        help="输出详细验算结果到CSV（可选）",
    )

    args = parser.parse_args()

    input_csv = args.input
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"找不到输入文件: {input_csv}")

    validate_103 = True
    validate_104 = True
    if args.only_103 and not args.only_104:
        validate_104 = False
    if args.only_104 and not args.only_103:
        validate_103 = False

    # 读CSV
    df = pd.read_csv(input_csv, dtype={"policy_no": "string"}, low_memory=False)
    if "certi_no" not in df.columns:
        df["certi_no"] = None
    if "year" not in df.columns:
        raise ValueError("CSV缺少 year 列")

    # 规范化 key/year
    df["policy_no"] = df["policy_no"].astype(str).str.strip()
    df["certi_no"] = df["certi_no"].apply(_normalize_certi_no)
    df["year"] = df["year"].apply(_coerce_year)
    df = df[df["policy_no"].notna() & (df["policy_no"] != "")]
    df = df[df["year"].notna()]
    df["year"] = df["year"].astype(int)

    # 过滤调试条件
    if args.policy:
        df = df[df["policy_no"] == args.policy.strip()]
    if args.certi is not None:
        certi_filter = _normalize_certi_no(args.certi)
        df = df[df["certi_no"].fillna("").astype(str) == (certi_filter or "")]

    if len(df) == 0:
        print("⚠️ 过滤后无数据，结束。")
        return

    df = _fill_nan_numeric_to_zero(df)
    df, sign_applied = _auto_fix_sign(df, mode=args.sign_mode)

    # 明细模式（逐保单/批单）
    df = _derive_fields_for_103(df)

    # 分组（policy_no + certi_no）
    group_keys = []
    for (policy_no, certi_no), _ in df.groupby(["policy_no", "certi_no"], dropna=False):
        group_keys.append(GroupKey(policy_no=str(policy_no), certi_no=_normalize_certi_no(certi_no)))

    group_keys = sorted(group_keys, key=lambda k: (k.policy_no, k.certi_no or ""))
    if args.limit and args.limit > 0:
        group_keys = group_keys[: args.limit]

    print(f"输入: {input_csv}")
    print(f"将验算保单组合数: {len(group_keys)}")
    if args.sign_mode != "none":
        applied_cols = [k for k, v in sign_applied.items() if v]
        print(f"符号校准({args.sign_mode})已应用列: {applied_cols if applied_cols else '无'}")

    # 逐组验算
    total = len(group_keys)
    done = 0
    failed_validation = []
    all_results = []

    def get_group_df(k: GroupKey) -> pd.DataFrame:
        if k.certi_no:
            return df[(df["policy_no"] == k.policy_no) & (df["certi_no"] == k.certi_no)]
        return df[(df["policy_no"] == k.policy_no) & (df["certi_no"].isna())]

    # workers=1 时走串行，避免Windows多进程开销/环境问题
    if args.workers <= 1:
        for k in group_keys:
            gdf = get_group_df(k)
            yearly_results = _build_yearly_results(gdf, k)
            result = _validate_one_policy(k, yearly_results, validate_103, validate_104)
            all_results.append(result)
            done += 1
            
            if not result.passed_103 or not result.passed_104:
                failed_validation.append(result)
                status_103 = "[X]" if not result.passed_103 else "[OK]"
                status_104 = "[X]" if not result.passed_104 else "[OK]"
                print(f"{status_103}103 {status_104}104 {k.policy_no} {k.certi_no or ''}")
                if result.error:
                    print(f"   错误: {result.error}")
            
            if done % 50 == 0 or done == total:
                print(f"进度: {done}/{total}，不通过: {len(failed_validation)}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {}
            for k in group_keys:
                gdf = get_group_df(k)
                yearly_results = _build_yearly_results(gdf, k)
                fut = ex.submit(_validate_one_policy, k, yearly_results, validate_103, validate_104)
                futures[fut] = k

            for fut in as_completed(futures):
                k = futures[fut]
                result = fut.result()
                all_results.append(result)
                done += 1
                
                if not result.passed_103 or not result.passed_104:
                    failed_validation.append(result)
                    status_103 = "[X]" if not result.passed_103 else "[OK]"
                    status_104 = "[X]" if not result.passed_104 else "[OK]"
                    print(f"{status_103}103 {status_104}104 {k.policy_no} {k.certi_no or ''}")
                    if result.error:
                        print(f"   错误: {result.error}")
                
                if done % 50 == 0 or done == total:
                    print(f"进度: {done}/{total}，不通过: {len(failed_validation)}")

    # 输出汇总
    print("=" * 80)
    print(f"✅ 验算完成：{done}/{total}")
    print(f"❌ 不通过：{len(failed_validation)}")
    
    if failed_validation:
        print("\n不通过的保单号列表：")
        failed_policies = set()
        for r in failed_validation:
            policy_key = f"{r.policy_no}" + (f"_{r.certi_no}" if r.certi_no else "")
            failed_policies.add(policy_key)
            if not r.passed_103:
                print(f"  {policy_key} - 103报表不通过")
                print(f"    差异: non_lc={r.diff_103['non_lc']:.2f}, lc={r.diff_103['lc']:.2f}, lic={r.diff_103['lic']:.2f}")
            if not r.passed_104:
                print(f"  {policy_key} - 104报表不通过")
                print(f"    差异: pv={r.diff_104['pv']:.2f}, ra={r.diff_104['ra']:.2f}, csm={r.diff_104['csm']:.2f}")
            if r.error:
                print(f"    错误: {r.error}")
        
        print(f"\n不通过的保单号（去重后）: {len(failed_policies)} 个")
        for p in sorted(failed_policies):
            print(f"  {p}")
    else:
        print("\n✅ 所有保单验算通过！")

    # 输出详细结果到CSV（如果指定）
    if args.output_csv:
        output_rows = []
        for r in all_results:
            output_rows.append({
                'policy_no': r.policy_no,
                'certi_no': r.certi_no or '',
                'year': r.year or '',
                'passed_103': r.passed_103,
                'passed_104': r.passed_104,
                'diff_103_non_lc': float(r.diff_103['non_lc']),
                'diff_103_lc': float(r.diff_103['lc']),
                'diff_103_lic': float(r.diff_103['lic']),
                'diff_104_pv': float(r.diff_104['pv']),
                'diff_104_ra': float(r.diff_104['ra']),
                'diff_104_csm': float(r.diff_104['csm']),
                'error': r.error or '',
            })
        output_df = pd.DataFrame(output_rows)
        output_df.to_csv(args.output_csv, index=False, encoding='utf-8-sig')
        print(f"\n详细结果已保存到: {args.output_csv}")


if __name__ == "__main__":
    main()

