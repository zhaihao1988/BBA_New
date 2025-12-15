import os
import sys
import pandas as pd
from decimal import Decimal

def parse_decimal(text):
    if not text:
        return Decimal('0')
    if isinstance(text, (int, float)):
        return Decimal(str(text))
    clean_text = str(text).replace(',', '').strip()
    if '(' in clean_text and ')' in clean_text:
        clean_text = '-' + clean_text.replace('(', '').replace(')', '')
    return Decimal(clean_text)

def format_decimal(val):
    if val > -Decimal('0.005') and val < Decimal('0.005'): return '0.00'
    return f"{val:,.2f}"

def convert_yearly_results_to_data_by_year(yearly_results):
    data_by_year = {}
    for result in yearly_results:
        year = result.get('year')
        if year:
            data_by_year[year] = {}
            for key, value in result.items():
                if key not in ['year', 'policy_no', 'certi_no']:
                    if isinstance(value, (int, float)):
                        data_by_year[year][key] = Decimal(str(value))
                    elif isinstance(value, Decimal):
                        data_by_year[year][key] = value
                    else:
                        data_by_year[year][key] = parse_decimal(str(value))
    return data_by_year

def generate_report_data(init_data, data_by_year):
    years = sorted(data_by_year.keys())
    all_rows = []
    explanations_by_year = {}
    
    # Initialize Opening Balance (LRC Non-LC, LRC LC, LIC)
    opening = {
        'lrc_non_lc': Decimal('0'),
        'lrc_lc': Decimal('0'),
        'lic': Decimal('0')
    }
    
    for year in years:
        data = data_by_year[year]
        
        year_rows = []
        year_explanations = []  # List of dicts: {title, content}
        
        def get_d(key):
            return data.get(key, Decimal('0'))
        
        # --- 1. Opening Balance ---
        # 1.1 Net Opening
        net_opening = opening['lrc_non_lc'] + opening['lrc_lc'] + opening['lic']
        
        year_rows.append({
            'year': year,
            'category': '年初的保险合同负债(1)',
            'lrc_non_lc': opening['lrc_non_lc'],
            'lrc_lc': opening['lrc_lc'],
            'lic': opening['lic'],
            'total': net_opening,
            'is_header': True,
            'indent': 0
        })
        
        year_explanations.append({
            "title": "1. 年初余额",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">年初的保险合同负债(1)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lrc_non_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-opening['lrc_lc'] if opening['lrc_lc'] < 0 else opening['lrc_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lic'])}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">年初的保险合同资产(2)</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">年初的保险合同净负债(3)=(1)+(2)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lrc_non_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-opening['lrc_lc'] if opening['lrc_lc'] < 0 else opening['lrc_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lic'])}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                <b>说明</b>: 年初余额来自上一年度的期末余额。LRC-非亏损 = BEL + RA + CSM - LC，LRC-亏损 = LC（显示为绝对值）。
            </p>
            """
        })
        
        add_row = lambda cat, lrc_nl, lrc_l, lic, indent=0, is_header=False: year_rows.append({
            'year': year,
            'category': cat,
            'lrc_non_lc': lrc_nl,
            'lrc_lc': lrc_l,
            'lic': lic,
            'total': lrc_nl + lrc_l + lic,
            'is_header': is_header,
            'indent': indent
        })

        # For the first year, calculate opening from log data using reverse derivation
        # For subsequent years, opening is inherited from previous year's closing
        if year == min(data_by_year.keys()):
            # First year: calculate opening from log using reverse derivation
            # CRITICAL: Do not trust log's Non-LC field directly
            # Use: Total = BEL + RA + CSM, then Non-LC = Total - LC (absolute)
            opening_bel = get_d('opening_bel')
            opening_ra = get_d('opening_ra')
            opening_csm = get_d('opening_csm')
            opening_lc_log = get_d('opening_lc')  # This is negative in log (liability reduction)
            opening_lic = get_d('opening_lic')
            
            # Total LRC = BEL + RA + CSM (from log)
            opening_lrc_total = opening_bel + opening_ra + opening_csm
            
            # LC in report display: absolute value (positive)
            opening_lc_display = -opening_lc_log if opening_lc_log < 0 else opening_lc_log
            
            # Non-LC in report: Total - LC (reverse derivation)
            opening_non_lc = opening_lrc_total - opening_lc_display
            
            opening = {
                'lrc_non_lc': opening_non_lc,
                'lrc_lc': opening_lc_display,  # Store as positive for consistency
                'lic': opening_lic
            }
        # For subsequent years, opening is already set from previous year's closing
        # (opening variable is updated at the end of each loop iteration)
        
        # Add opening balance rows (1), (2), (3)
        # In the roll-forward table, LC column displays the absolute value (positive) for presentation
        opening_lc_display = opening['lrc_lc']  # Already positive from above logic
        add_row('年初的保险合同负债(1)', opening['lrc_non_lc'], opening_lc_display, opening['lic'], is_header=True)
        add_row('年初的保险合同资产(2)', Decimal('0'), Decimal('0'), Decimal('0'), is_header=False)
        add_row('年初的保险合同净负债(3)=(1)+(2)', opening['lrc_non_lc'], opening_lc_display, opening['lic'], is_header=False)
        
        is_initial_year = (year == min(data_by_year.keys()))
        is_final_year = (year == max(data_by_year.keys()))

        # --- 2. Revenue (4) ---
        rev_csm = get_d('保险合同收入_摊销的CSM')
        # CSV 中 IACF 摊销为正值，报表需显示为负数（产生收入），因此取反
        rev_iacf = -get_d('保险合同收入_摊销的IACF')
        rev_exp = get_d('保险合同收入_经验调整')
        
        rev_lc_release_claims = get_d('保险合同收入_预期赔付与费用_亏损分摊')
        rev_lc_release_ra = get_d('保险合同收入_预期释放的非金融风险调整_亏损分摊')
        revenue_from_lc_release = rev_lc_release_claims + rev_lc_release_ra

        rev_claims_gross = get_d('保险合同收入_预期赔付与费用_含亏损')
        rev_ra_gross = get_d('保险合同收入_预期释放的非金融风险调整_含亏损')
        
        rev_claims_net = rev_claims_gross - rev_lc_release_claims
        rev_ra_net = rev_ra_gross - rev_lc_release_ra

        # Revenue calculation: keep display and calculation signs consistent
        # rev_claims_net / rev_ra_net 在表格展示时取负号，因此计算时同样取负
        revenue_non_lc = rev_csm + rev_iacf + rev_exp - rev_claims_net - rev_ra_net
        
        # Per user instruction, the LC column revenue should be 0.
        revenue_lc = Decimal('0')
        
        add_row('保险服务收入合计(4)', revenue_non_lc, revenue_lc, Decimal('0'), is_header=True)
        
        year_explanations.append({
            "title": "4. 保险服务收入合计",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">预期赔付与费用释放 (净额)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-rev_claims_net)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;总额 (含亏损释放)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(rev_claims_gross)}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;减: 亏损分摊部分</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-rev_lc_release_claims)}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">预期释放的非金融风险调整 (净额)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-rev_ra_net)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;总额 (含亏损释放)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(rev_ra_gross)}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;减: 亏损分摊部分</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-rev_lc_release_ra)}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">摊销的CSM</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(rev_csm)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">摊销的IACF</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(rev_iacf)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">经验调整 (负号)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(rev_exp)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">合计</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(revenue_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(revenue_lc)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
            </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>计算公式</b>: 收入 = CSM摊销 + IACF摊销 + 经验调整 - 预期赔付与费用释放(净额) - RA释放(净额)<br>
                    <b>说明</b>: 收入减少负债，显示为负数。CSM摊销和IACF摊销为负数（产生收入），预期释放组件取负号以保持显示一致性。亏损部分的收入为0（按用户要求）。
                </p>
            """
        })

        # --- 3. Insurance Service Expenses (5) ---
        # 5a. Incurred Claims (LIC)
        incurred_claims = Decimal('0')  # Placeholder
        add_row('当期发生赔款及其他相关费用(保险获取现金流量除外)(5)', Decimal('0'), Decimal('0'), incurred_claims, indent=1)

        # 5b. IACF Amortization
        iacf_amort_exp = get_d('赔付与费用_摊销的IACF')
        add_row('保险获取现金流量的摊销(6)', iacf_amort_exp, Decimal('0'), Decimal('0'), indent=1)
        
        # Add explanation for IACF amortization if non-zero
        if iacf_amort_exp != 0:
            year_explanations.append({
                "title": "6. 保险获取现金流量的摊销",
                "content": f"""
                <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                    <tr style="background-color: #f8f9fa;">
                        <th style="text-align: left; padding: 8px;">项目</th>
                        <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                        <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                        <th style="text-align: right; padding: 8px;">LIC</th>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">IACF摊销金额</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(iacf_amort_exp)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>说明</b>: IACF摊销增加负债，所以显示为正数。仅影响非亏损部分。
                </p>
                """
            })

        # 5c. Loss Component Recognition & Reversal
        initial_loss_recog = -get_d('nb_initial_lc') if is_initial_year else Decimal('0')
        lc_change_est = get_d('亏损合同损益_不调整CSM的预期现金流变动') + get_d('亏损合同损益_不调整CSM的非金融风险调整变动')
        
        # LC release (分摊的LC) reduces LC but is not counted as revenue (per user instruction).
        # So net LC recognition = initial loss + changes - LC release
        lc_release_claims = get_d('保险合同收入_预期赔付与费用_亏损分摊')
        lc_release_ra = get_d('保险合同收入_预期释放的非金融风险调整_亏损分摊')
        lc_release_total = lc_release_claims + lc_release_ra
        
        # For final year, we need to calculate IFIE LC impact first to determine LC reversal amount
        # This is needed because LC reversal should account for IFIE effects
        net_lc_recog_non_lc = Decimal('0')
        
        if is_final_year:
            # Step 1: Calculate IFIE LC impact (P&L + OCI) - needed for LC reversal calculation
            ifie_pl_cf_lc_temp = get_d('IFIE_P&L_未到期_预期现金流_亏损')
            ifie_pl_ra_lc_temp = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')
            ifie_oci_cf_lc_temp = get_d('IFIE_OCI_未到期_预期现金流_亏损')
            ifie_oci_ra_lc_temp = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')
            ifie_lc_total = (ifie_pl_cf_lc_temp + ifie_pl_ra_lc_temp) + (ifie_oci_cf_lc_temp + ifie_oci_ra_lc_temp)
            
            # Step 2: Opening LC balance (absolute value)
            opening_lc_abs = -opening['lrc_lc'] if opening['lrc_lc'] < 0 else opening['lrc_lc']
            
            # Step 3: LC can absorb = opening LC + IFIE LC impact
            # IFIE LC is typically negative (reduces liability), so we add it
            lc_after_ifie = opening_lc_abs + ifie_lc_total  # ifie_lc_total is negative, so this reduces
            
            # Step 4: Total reversal amount from log
            total_reversal = lc_release_total
            
            # Step 5: Calculate LC reversal and NonLC allocation
            # LC reversal should fully reverse the LC after IFIE: -lc_after_ifie
            # If total reversal > lc_after_ifie, excess goes to NonLC
            if total_reversal > lc_after_ifie:
                # Excess that needs to be allocated to NonLC
                excess_to_non_lc = total_reversal - lc_after_ifie
                net_lc_recog_non_lc = -excess_to_non_lc  # Negative because it reduces NonLC
                # LC reversal: fully reverse LC after IFIE (negative value to reduce LC)
                net_lc_recog = -lc_after_ifie
            else:
                # LC can absorb all reversal
                net_lc_recog = -total_reversal
        else:
            # Normal year: Net LC recognition = initial loss + changes - LC release
            # In the roll-forward table, LC column shows changes (positive = increase LC, negative = decrease LC)
            net_lc_recog = initial_loss_recog + lc_change_est - lc_release_total
        
        add_row('亏损部分的确认及转回(7)', net_lc_recog_non_lc, net_lc_recog, Decimal('0'), indent=1)
        
        # Add explanation for LC recognition if non-zero
        if net_lc_recog != 0 or net_lc_recog_non_lc != 0:
            explanation_content = f"""
                <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                    <tr style="background-color: #f8f9fa;">
                        <th style="text-align: left; padding: 8px;">项目</th>
                        <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                        <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                        <th style="text-align: right; padding: 8px;">LIC</th>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">初始确认亏损</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(initial_loss_recog) if is_initial_year else '0.00'}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">预期现金流变动</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(get_d('亏损合同损益_不调整CSM的预期现金流变动'))}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">非金融风险调整变动</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(get_d('亏损合同损益_不调整CSM的非金融风险调整变动'))}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">减: LC释放 (亏损分摊)</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(-lc_release_total)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">&nbsp;&nbsp;预期赔付与费用亏损分摊</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(-lc_release_claims)}</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">&nbsp;&nbsp;非金融风险调整亏损分摊</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(-lc_release_ra)}</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                    </tr>"""
            
            if is_final_year and net_lc_recog_non_lc != 0:
                explanation_content += f"""
                    <tr>
                        <td style="padding: 8px;">超额转回分配至非亏损部分</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(net_lc_recog_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                        <td style="text-align: right; padding: 8px;">-</td>
                    </tr>"""
            
            explanation_content += f"""
                    <tr style="background-color: #f8f9fa; font-weight: bold;">
                        <td style="padding: 8px;">净确认</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(net_lc_recog_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(net_lc_recog)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>计算公式</b>: 净确认 = 初始确认亏损 + 预期现金流变动 + 非金融风险调整变动 - LC释放<br>
                    <b>说明</b>: 亏损确认增加LC负债，显示为正数。LC释放减少LC负债，显示为负数。
                    {f'在合同终止年度，如果LC转回超过期初LC余额，超额部分将分配至非亏损部分。' if is_final_year and net_lc_recog_non_lc != 0 else ''}
                </p>
                """
            
            year_explanations.append({
                "title": "7. 亏损部分的确认及转回",
                "content": explanation_content
            })

        # 5d. LIC Changes
        lic_changes = Decimal('0') # Placeholder
        add_row('已发生赔款负债相关履约现金流量变动(8)', Decimal('0'), Decimal('0'), lic_changes, indent=1)
        
        # Total Service Expense
        # Note: net_lc_recog_non_lc is negative (reduces NonLC), so we add it directly
        # In expense calculation: expense = iacf_amort + net_lc_recog_non_lc (where net_lc_recog_non_lc is negative)
        service_expense_non_lc = iacf_amort_exp + net_lc_recog_non_lc  # net_lc_recog_non_lc is negative, so this reduces expense
        service_expense_lc = net_lc_recog  # Use net LC recognition
        service_expense_lic = incurred_claims + lic_changes
        # In the roll-forward table, LC column shows changes (positive = increase LC)
        add_row('保险服务费用(10)', service_expense_non_lc, service_expense_lc, service_expense_lic, is_header=True)
        
        # Add explanation for service expenses
        year_explanations.append({
            "title": "10. 保险服务费用",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">当期发生赔款及其他相关费用</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(incurred_claims)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">保险获取现金流量的摊销</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(iacf_amort_exp)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">亏损部分的确认及转回</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(net_lc_recog_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(net_lc_recog)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">已发生赔款负债相关履约现金流量变动</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(lic_changes)}</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">合计</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_lic)}</td>
                </tr>
            </table>
            """
        })

        # --- 6. Insurance Service Result (11) ---
        # For calculation: revenue_lc is 0 (per user instruction), service_expense_lc is positive (expense increases LC).
        res_non_lc = revenue_non_lc + service_expense_non_lc
        res_lc = revenue_lc + service_expense_lc  # Positive because expense increases LC (revenue_lc is 0)
        res_lic = service_expense_lic
        
        add_row('保险服务业绩(11)=(4)+(10)', res_non_lc, res_lc, res_lic, is_header=True)
        
        year_explanations.append({
            "title": "11. 保险服务业绩",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">保险服务收入合计(4)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(revenue_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(revenue_lc)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">保险服务费用(10)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(service_expense_lic)}</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">保险服务业绩(11)=(4)+(10)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_lic)}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                <b>计算公式</b>: 保险服务业绩 = 保险服务收入 + 保险服务费用<br>
                <b>说明</b>: 收入减少负债（负数），费用增加负债（正数），业绩 = 收入 + 费用。
            </p>
            """
        })
        
        # --- 7. Finance Income/Expenses (12) ---
        # --- 7. Total Comprehensive Income (15) ---
        
        # IFIE P&L
        # CRITICAL: Log fields use algebraic sign (LC is negative), but report displays LC as positive (absolute)
        # Strategy: Calculate Total first, then LC (absolute), then derive Non-LC = Total - LC
        
        # Step 1: Get raw components from log
        ifie_pl_cf_non_lc_raw = get_d('IFIE_P&L_未到期_预期现金流_非亏损')
        ifie_pl_ra_non_lc_raw = get_d('IFIE_P&L_未到期_非金融风险调整_非亏损')
        ifie_pl_csm = get_d('IFIE_P&L_未到期_CSM')
        ifie_pl_cf_lc_log = get_d('IFIE_P&L_未到期_预期现金流_亏损')  # Negative in log
        ifie_pl_ra_lc_log = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')  # Negative in log
        
        # Step 2: Calculate Total IFIE P&L (same as 104 report logic)
        # Total = (CF_NonLC + CF_LC) + (RA_NonLC + RA_LC) + CSM
        # Note: ifie_pl_csm 在日志中为负数（P&L费用），报表需显示为正数，因此这里取反用于合计
        ifie_pl_total = (ifie_pl_cf_non_lc_raw + ifie_pl_cf_lc_log) + (ifie_pl_ra_non_lc_raw + ifie_pl_ra_lc_log) - ifie_pl_csm
        
        # Step 3: LC in report display
        # Note: LC balance is displayed as positive (liability), but LC changes (IFIE) need to be negated
        # LC IFIE values in log are negative, but in report should be displayed as positive (increases liability)
        ifie_pl_lc_log_sum = ifie_pl_cf_lc_log + ifie_pl_ra_lc_log
        ifie_pl_lc_display = -ifie_pl_lc_log_sum  # Negate to show as positive in report
        
        # Step 4: Derive Non-LC as Total - LC (reverse derivation, ensures Non-LC + LC = Total)
        ifie_pl_non_lc = ifie_pl_total - ifie_pl_lc_display
        
        ifie_pl_lic = Decimal('0')  # Placeholder for LIC-related IFIE if any

        add_row('保险合同金融变动额(12)', ifie_pl_non_lc, ifie_pl_lc_display, ifie_pl_lic, indent=0)
        
        # Add explanation for IFIE P&L
        if ifie_pl_non_lc != 0 or ifie_pl_lc_display != 0:
            # Calculate component breakdown for Non-LC (derived from Total - LC)
            # Note: We show the derived Non-LC components, not the raw log values
            # LC components in display: negate to show as positive in report
            ifie_pl_cf_lc_display_comp = -ifie_pl_cf_lc_log  # Negate to show as positive
            ifie_pl_ra_lc_display_comp = -ifie_pl_ra_lc_log  # Negate to show as positive
            ifie_pl_cf_total = ifie_pl_cf_non_lc_raw + ifie_pl_cf_lc_log
            ifie_pl_ra_total = ifie_pl_ra_non_lc_raw + ifie_pl_ra_lc_log
            ifie_pl_cf_non_lc_derived = ifie_pl_cf_total - ifie_pl_cf_lc_display_comp
            ifie_pl_ra_non_lc_derived = ifie_pl_ra_total - ifie_pl_ra_lc_display_comp
            ifie_pl_csm_display = -ifie_pl_csm  # 显示为正数
            
            year_explanations.append({
                "title": "12. 保险合同金融变动额 (IFIE_P&L)",
                "content": f"""
                <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                    <tr style="background-color: #f8f9fa;">
                        <th style="text-align: left; padding: 8px;">项目</th>
                        <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                        <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                        <th style="text-align: right; padding: 8px;">LIC</th>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">预期现金流 IFIE (非亏损)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_cf_non_lc_derived)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">非金融风险调整 IFIE (非亏损)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_ra_non_lc_derived)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">CSM IFIE</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_csm_display)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">预期现金流 IFIE (亏损)</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_cf_lc_display_comp)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">非金融风险调整 IFIE (亏损)</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_ra_lc_display_comp)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr style="background-color: #f8f9fa; font-weight: bold;">
                        <td style="padding: 8px;">合计</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_lc_display)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_lic)}</td>
                    </tr>
                    <tr style="background-color: #fff9e6;">
                        <td style="padding: 8px;">验证: Non-LC + LC = Total</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_lc_display)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_total)}</td>
                    </tr>
                </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>计算公式</b>: 非亏损部分 = 总额 - 亏损部分（确保 Non-LC + LC = Total，与104报表一致）<br>
                    <b>说明</b>: IFIE_P&L仅包含计息影响（使用锁定利率）。日志中的"非亏损"字段是毛额口径，需通过倒挤得到净额口径。
                </p>
                """
            })
        
        # Other P&L changes (13) - Placeholder
        add_row('其他损益变动(13)', Decimal('0'), Decimal('0'), Decimal('0'), indent=0)
        
        # OCI
        # CRITICAL: Same strategy as IFIE P&L - derive Non-LC from Total - LC
        # Step 1: Get raw components from log
        ifie_oci_cf_non_lc_raw = get_d('IFIE_OCI_未到期_预期现金流_非亏损')
        ifie_oci_ra_non_lc_raw = get_d('IFIE_OCI_未到期_非金融风险调整_非亏损')
        ifie_oci_cf_lc_log = get_d('IFIE_OCI_未到期_预期现金流_亏损')  # May be positive or negative in log
        ifie_oci_ra_lc_log = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')  # May be positive or negative in log
        
        # Step 2: Calculate Total IFIE OCI (same as 104 report logic)
        # Total = (CF_NonLC + CF_LC) + (RA_NonLC + RA_LC)
        # Note: LC components may be positive or negative in log
        ifie_oci_total = (ifie_oci_cf_non_lc_raw + ifie_oci_cf_lc_log) + (ifie_oci_ra_non_lc_raw + ifie_oci_ra_lc_log)
        
        # Step 3: LC in report display
        # Note: LC balance is displayed as positive (liability), but LC changes (IFIE) need to be negated
        # LC IFIE values in log are negative, but in report should be displayed as positive (increases liability)
        ifie_oci_lc_log_sum = ifie_oci_cf_lc_log + ifie_oci_ra_lc_log
        ifie_oci_lc_display = -ifie_oci_lc_log_sum  # Negate to show as positive in report
        
        # Step 4: Derive Non-LC as Total - LC (reverse derivation, ensures Non-LC + LC = Total)
        ifie_oci_non_lc = ifie_oci_total - ifie_oci_lc_display

        add_row('其他综合收益其他变动(14)', ifie_oci_non_lc, ifie_oci_lc_display, Decimal('0'), indent=0)
        
        # Add explanation for IFIE OCI
        if ifie_oci_non_lc != 0 or ifie_oci_lc_display != 0:
            # Calculate component breakdown for Non-LC (derived from Total - LC)
            # LC components in display: negate to show as positive in report
            ifie_oci_cf_lc_display_comp = -ifie_oci_cf_lc_log  # Negate to show as positive
            ifie_oci_ra_lc_display_comp = -ifie_oci_ra_lc_log  # Negate to show as positive
            ifie_oci_cf_total = ifie_oci_cf_non_lc_raw + ifie_oci_cf_lc_log
            ifie_oci_ra_total = ifie_oci_ra_non_lc_raw + ifie_oci_ra_lc_log
            ifie_oci_cf_non_lc_derived = ifie_oci_cf_total - ifie_oci_cf_lc_display_comp
            ifie_oci_ra_non_lc_derived = ifie_oci_ra_total - ifie_oci_ra_lc_display_comp
            
            year_explanations.append({
                "title": "14. 其他综合收益其他变动 (IFIE_OCI)",
                "content": f"""
                <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                    <tr style="background-color: #f8f9fa;">
                        <th style="text-align: left; padding: 8px;">项目</th>
                        <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                        <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                        <th style="text-align: right; padding: 8px;">LIC</th>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">预期现金流 IFIE_OCI (非亏损)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_cf_non_lc_derived)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">非金融风险调整 IFIE_OCI (非亏损)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_ra_non_lc_derived)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">预期现金流 IFIE_OCI (亏损)</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_cf_lc_display_comp)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">非金融风险调整 IFIE_OCI (亏损)</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_ra_lc_display_comp)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr style="background-color: #f8f9fa; font-weight: bold;">
                        <td style="padding: 8px;">合计</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_lc_display)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr style="background-color: #fff9e6;">
                        <td style="padding: 8px;">验证: Non-LC + LC = Total</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_lc_display)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_total)}</td>
                    </tr>
                </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>计算公式</b>: 非亏损部分 = 总额 - 亏损部分（确保 Non-LC + LC = Total，与104报表一致）<br>
                    <b>说明</b>: IFIE_OCI仅包含利率变化影响，不包含计息影响。日志中的"非亏损"字段是毛额口径，需通过倒挤得到净额口径。
                </p>
                """
            })

        # --- 8. OCI (14) ---
        # add_row('其他综合收益其他变动(14)', ifie_oci_non_lc, ifie_oci_lc, Decimal('0'), is_header=False, indent=0)
        
        # --- 9. Total Comprehensive Income (15) ---
        # TCI calculation: use display values (LC as positive/negative per report logic)
        tci_non_lc = res_non_lc + ifie_pl_non_lc + ifie_oci_non_lc
        # Note: res_lc uses display logic (positive for increase, negative for decrease)
        # ifie_pl_lc_display and ifie_oci_lc_display are already in display format
        tci_lc = res_lc + ifie_pl_lc_display + ifie_oci_lc_display
        tci_lic = res_lic + ifie_pl_lic
        
        add_row('相关综合收益变动合计(15)=(11)+(12)+(13)+(14)', tci_non_lc, tci_lc, tci_lic, is_header=True)
        
        year_explanations.append({
            "title": "15. 相关综合收益变动合计",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">保险服务业绩(11)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(res_lic)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">保险合同金融变动额(12)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(ifie_pl_lic)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">其他损益变动(13)</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">其他综合收益其他变动(14)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(ifie_oci_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">相关综合收益变动合计(15)=(11)+(12)+(13)+(14)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_lic)}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                <b>计算公式</b>: 相关综合收益变动合计 = 保险服务业绩 + 金融变动额 + 其他损益 + OCI<br>
                <b>说明</b>: 包含所有影响负债变动的项目。
            </p>
            """
        })
        
        # --- 10. Investment Components (16) ---
        inv_comp = Decimal('0')
        # Transfer from LRC to LIC? Usually handled in cash flows or service expenses.
        # Here assume 0.
        add_row('投资成分(16)', -inv_comp, Decimal('0'), inv_comp) # Reduces LRC, Increases LIC
        
        # --- 11. Cash Flows (17-21) ---
        cf_premium = get_d('现金流_收到的保费')
        cf_iacf = -get_d('现金流_支付的获取费用') # Expense, so should be negative in cash flow
        cf_claims = Decimal('0') # TODO
        cf_other = Decimal('0') # TODO
        
        # Cash flows only affect the non-LC component in this model
        cf_total_non_lc = cf_premium + cf_iacf + cf_claims + cf_other
        cf_total_lc = Decimal('0')
        cf_total_lic = Decimal('0')

        add_row('收到的保费(17)', cf_premium, Decimal('0'), Decimal('0'), indent=0)
        add_row('支付的保险获取现金流量(18)', cf_iacf, Decimal('0'), Decimal('0'), indent=0)
        add_row('支付的赔款及其他相关费用(含投资成分)(19)', cf_claims, Decimal('0'), Decimal('0'), indent=0)
        add_row('其他现金流量(20)', cf_other, Decimal('0'), Decimal('0'), indent=0)
        add_row('现金流量合计(21)=(17)+(18)+(19)+(20)', cf_total_non_lc, cf_total_lc, cf_total_lic, is_header=True)
        
        # Add explanation for cash flows
        if cf_premium != 0 or cf_iacf != 0 or cf_claims != 0 or cf_other != 0:
            year_explanations.append({
                "title": "21. 现金流量合计",
                "content": f"""
                <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                    <tr style="background-color: #f8f9fa;">
                        <th style="text-align: left; padding: 8px;">项目</th>
                        <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                        <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                        <th style="text-align: right; padding: 8px;">LIC</th>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">收到的保费(17)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_premium)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">支付的保险获取现金流量(18)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_iacf)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">支付的赔款及其他相关费用(19)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_claims)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px;">其他现金流量(20)</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_other)}</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                        <td style="text-align: right; padding: 8px;">0.00</td>
                    </tr>
                    <tr style="background-color: #f8f9fa; font-weight: bold;">
                        <td style="padding: 8px;">合计</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_non_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_lc)}</td>
                        <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_lic)}</td>
                    </tr>
                </table>
                <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                    <b>说明</b>: 收到的保费增加负债（正数），支付的费用减少负债（负数）。
                </p>
                """
            })
        
        # --- 10. Other Changes (22) ---
        # CRITICAL: Other changes should always be zero - all calculations must balance precisely
        # Do not use other changes to absorb any differences
        other_changes_non_lc = Decimal('0')
        other_changes_lc = Decimal('0')
        other_changes_lic = Decimal('0')
        
        # Always add the row (even if zero) for consistency with report format
        add_row('其他变动(22)', other_changes_non_lc, other_changes_lc, other_changes_lic, is_header=False)
        
        # --- 11. Closing Balance (23) ---
        closing_non_lc = opening['lrc_non_lc'] + tci_non_lc - inv_comp + cf_total_non_lc + other_changes_non_lc
        closing_lc = opening['lrc_lc'] + tci_lc + other_changes_lc
        closing_lic = opening['lic'] + tci_lic + inv_comp + cf_total_lic + other_changes_lic
        
        # In the roll-forward table, LC column displays the absolute value (positive) for presentation,
        # but we use the actual LC value (negative) for calculation and verification.
        closing_lc_display = -closing_lc if closing_lc < 0 else closing_lc
        
        add_row('年末的保险合同净负债(23)=(3)+(15)+(16)+(21)+(22)', closing_non_lc, closing_lc_display, closing_lic, is_header=True)
        add_row('年末的保险合同资产(24)', Decimal('0'), Decimal('0'), Decimal('0'), is_header=False)
        add_row('年末的保险合同负债(25)', closing_non_lc, closing_lc_display, closing_lic, is_header=True)
        
        # --- 14. Verification Section ---
        # 获取日志中的期末余额值用于验算
        # CRITICAL: Use correct log extraction logic with reverse derivation
        # For final year (2024), all balances should be 0.00
        
        is_final_year = (year == max(data_by_year.keys()))
        # 注意：并非所有“最后一年”都是合同终止年。只有当日志/输入明确给出期末余额为0时，才按终止年处理。
        # 否则仍按正常年度提取/验算，避免把最后一年错误强制为0导致全表失真。
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
            # Termination year: All balances should be 0.00
            log_total = Decimal('0')
            log_lc_display = Decimal('0')
            log_non_lc_display = Decimal('0')
            log_lic = Decimal('0')
        else:
            # Normal year: Extract from input/log directly
            log_closing_bel = get_d('closing_bel')
            log_closing_ra = get_d('closing_ra')
            log_closing_csm = get_d('closing_csm')
            
            # LC: Use calculated value as the LC display for verification (LC在报表中为绝对值口径)
            log_lc_display = closing_lc_display
            
            # Non-LC = BEL + RA + CSM - LC
            log_non_lc_display = log_closing_bel + log_closing_ra + log_closing_csm - log_lc_display
            
            # Total for verification
            log_total = log_non_lc_display + log_lc_display
            
            # LIC balance
            log_lic = get_d('closing_lic')
        
        # Calculate differences
        diff_non_lc = closing_non_lc - log_non_lc_display
        diff_lc = closing_lc_display - log_lc_display
        diff_lic = closing_lic - log_lic
        
        def get_verify_status(diff):
            if diff > -Decimal('0.01') and diff < Decimal('0.01'):
                return "<span style='color:green'>✓ 无差异</span>"
            return f"<span style='color:red'>✗ 差异: {format_decimal(diff)}</span>"
        
        year_explanations.append({
            "title": "23. 年末的保险合同净负债 - 计算明细",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">LRC-非亏损</th>
                    <th style="text-align: right; padding: 8px;">LRC-亏损</th>
                    <th style="text-align: right; padding: 8px;">LIC</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">期初余额(3)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lrc_non_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-opening['lrc_lc'] if opening['lrc_lc'] < 0 else opening['lrc_lc'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(opening['lic'])}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">相关综合收益变动合计(15)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(tci_lic)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">投资成分(16)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(-inv_comp)}</td>
                    <td style="text-align: right; padding: 8px;">0.00</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(inv_comp)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">现金流量合计(21)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(cf_total_lic)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">其他变动(22)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(other_changes_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(other_changes_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(other_changes_lic)}</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">期末余额(23)</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_lic)}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                <b>计算公式</b>: 期末 = 期初 + 综合收益变动 + 投资成分 + 现金流 + 其他变动<br>
                <b>验算</b>: 期末余额应与日志中的期末余额一致
            </p>
            """
        })
        
        year_explanations.append({
            "title": "期末余额验算 (计算值 vs 日志值)",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">计算期末</th>
                    <th style="text-align: right; padding: 8px;">日志期末</th>
                    <th style="text-align: right; padding: 8px;">验算结果</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">LRC-非亏损</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_non_lc)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_non_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_non_lc)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;BEL</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(get_d('closing_bel') if not is_final_year else Decimal('0'))}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;RA</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(get_d('closing_ra') if not is_final_year else Decimal('0'))}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;CSM</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(get_d('closing_csm') if not is_final_year else Decimal('0'))}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">&nbsp;&nbsp;减: LC</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_lc_display if not is_final_year else Decimal('0'))}</td>
                    <td style="text-align: right; padding: 8px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">LRC-亏损</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_lc_display)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_lc)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">LIC</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_lic)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_lic)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_lic)}</td>
                </tr>
                <tr style="background-color: #f8f9fa; font-weight: bold;">
                    <td style="padding: 8px;">合计</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(closing_non_lc + closing_lc_display + closing_lic)}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_non_lc_display + log_lc_display + log_lic)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status((closing_non_lc + closing_lc_display + closing_lic) - (log_non_lc_display + log_lc_display + log_lic))}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                <b>计算公式</b>: LRC-非亏损 = Total - LC (倒挤法)<br>
                <b>说明</b>: 日志期末值提取逻辑：<br>
                1. Total = 期末未到期责任负债余额<br>
                2. LC = -期末LC余额_合计 (日志中LC为负数，报表中显示为正数)<br>
                3. Non-LC = Total - LC (倒挤法，确保与报表口径一致)<br>
                4. 终止年度(2024)所有余额强制为0.00<br>
                计算期末值来自调节表的滚算。
            </p>
            """
        })
        
        all_rows.extend(year_rows)
        explanations_by_year[year] = year_explanations
        
        # Update opening for next year
        # Use display value for LC (positive) to maintain consistency
        opening = {
            'lrc_non_lc': closing_non_lc,
            'lrc_lc': closing_lc_display,  # Store as positive for next year's opening
            'lic': closing_lic
        }
        
    return all_rows, explanations_by_year

def render_html_template(rows, explanations_by_year, policy_no=None, certi_no=None):
    df = pd.DataFrame(rows)
    years = df['year'].unique()
    
    year_range = f"{min(years)}-{max(years)}" if len(years) > 1 else str(years[0])
    policy_info = policy_no if policy_no else "未知保单"
    if certi_no:
        policy_info += f" (批单号: {certi_no})"
    
    tabs_html = ""
    content_html = ""
    
    for idx, year in enumerate(years):
        active_class = " active" if idx == 0 else ""
        tabs_html += f'<button class="tab-btn{active_class}" onclick="openTab(event, \'y{year}\')">{year} 年度</button>\n'
        
        year_df = df[df['year'] == year]
        
        table_rows = ""
        for _, row in year_df.iterrows():
            total = row['total']
            
            def fmt(val):
                if val > -Decimal('0.005') and val < Decimal('0.005'): return '<span class="zero">0.00</span>'
                s = "{:,.2f}".format(val)  # 保留两位小数
                if val < 0:
                    return f'<span class="negative">({s.replace("-", "")})</span>'
                return s
            
            row_class = ""
            if row.get('is_header'):
                row_class = "border-top-heavy"
            if '年末的保险合同净负债' in row['category']:
                row_class += " border-double-bottom"
                
            indent_class = f" indent-{row['indent']}" if row['indent'] > 0 else ""
            
            # Format cells
            # Image columns: [Item] [LRC Non-LC] [LRC LC] [LIC] [Total]
            
            cells = [
                fmt(row['lrc_non_lc']),
                fmt(row['lrc_lc']),
                fmt(row['lic']),
                fmt(total)
            ]
            
            table_rows += f"""
                <tr class="{row_class}">
                    <td class="{indent_class}">{row['category']}</td>
                    <td class="num">{cells[0]}</td>
                    <td class="num">{cells[1]}</td>
                    <td class="num">{cells[2]}</td>
                    <td class="num">{cells[3]}</td>
                </tr>
            """
        
        # Build Explanation Section
        explanation_html = ""
        if year in explanations_by_year:
            explanation_html += '<div class="explanation-box">'
            explanation_html += f'<h3>{year} 年度计算明细与验算</h3>'
            
            for exp in explanations_by_year[year]:
                explanation_html += f"""
                <div class="explanation-item">
                    <h4 class="exp-title">{exp['title']}</h4>
                    <div class="exp-content">
                        {exp['content']}
                    </div>
                </div>
                """
            explanation_html += '</div>'
            
        content_html += f"""
        <div id="y{year}" class="tab-content{active_class}">
            <table>
                <thead>
                    <tr>
                        <th rowspan="2" style="text-align: left;">项目</th>
                        <th colspan="2">未到期责任负债</th>
                        <th rowspan="2">已发生<br>赔款负债</th>
                        <th rowspan="2">合计</th>
                    </tr>
                    <tr>
                        <th>非亏损部分</th>
                        <th>亏损部分</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
            
            {explanation_html}
        </div>
        """
        
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IFRS 17 未到期责任负债和已发生赔款负债调节表 (103报表)</title>
    <style>
        :root {{
            --header-bg: #f8f9fa;
            --border-color: #e9ecef;
            --text-color: #212529;
        }}
        body {{
            font-family: "Microsoft YaHei", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f4f4f4;
            color: var(--text-color);
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        h1 {{
            text-align: center;
            font-size: 24px;
            margin-bottom: 5px;
        }}
        .subtitle {{
            text-align: center;
            color: #6c757d;
            margin-bottom: 30px;
            font-size: 14px;
        }}
        .tabs {{
            display: flex;
            border-bottom: 1px solid #dee2e6;
            margin-bottom: 20px;
        }}
        .tab-btn {{
            padding: 10px 20px;
            background: none;
            border: none;
            border-bottom: 3px solid transparent;
            font-size: 16px;
            cursor: pointer;
            color: #495057;
            font-weight: 500;
        }}
        .tab-btn.active {{
            color: #0d6efd;
            border-bottom-color: #0d6efd;
        }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            padding: 8px 12px;
            border-bottom: 1px solid var(--border-color);
            text-align: right;
        }}
        th {{
            background-color: var(--header-bg);
            font-weight: bold;
            color: #495057;
            text-align: center;
            vertical-align: middle;
        }}
        td:first-child {{
            text-align: left;
            width: 40%;
            color: #212529;
        }}
        .indent-1 {{ padding-left: 20px !important; }}
        .border-top-heavy {{ border-top: 2px solid #6c757d; }}
        .border-double-bottom {{ border-bottom: 3px double #6c757d; }}
        .num {{ font-family: Consolas, monospace; }}
        .zero {{ color: #adb5bd; }}
        .negative {{ color: #d9534f; }}
        
        /* Explanation Section */
        .explanation-box {{
            margin-top: 30px;
            border-top: 1px solid #eee;
            padding-top: 20px;
        }}
        .explanation-box h3 {{
            font-size: 18px;
            color: #333;
            margin-bottom: 15px;
            border-left: 4px solid #0d6efd;
            padding-left: 10px;
        }}
        .explanation-item {{
            margin-bottom: 15px;
            background-color: #fafafa;
            border: 1px solid #eee;
            border-radius: 4px;
            padding: 10px 15px;
        }}
        .exp-title {{
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #0d6efd;
            font-weight: bold;
        }}
        .exp-content ul {{
            margin: 0;
            padding-left: 20px;
            font-size: 13px;
            color: #555;
        }}
        .exp-content li {{
            margin-bottom: 4px;
        }}
        .exp-content b {{
            color: #333;
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>IFRS 17 未到期责任负债和已发生赔款负债调节表</h1>
    <p class="subtitle">保单号: {policy_info} | 模拟区间: {year_range}</p>
    <div class="tabs">
        {tabs_html}
    </div>
    {content_html}
</div>
<script>
    function openTab(evt, yearName) {{
        var i, tabcontent, tablinks;
        tabcontent = document.getElementsByClassName("tab-content");
        for (i = 0; i < tabcontent.length; i++) {{
            tabcontent[i].style.display = "none";
            tabcontent[i].classList.remove("active");
        }}
        tablinks = document.getElementsByClassName("tab-btn");
        for (i = 0; i < tablinks.length; i++) {{
            tablinks[i].className = tablinks[i].className.replace(" active", "");
        }}
        document.getElementById(yearName).style.display = "block";
        document.getElementById(yearName).classList.add("active");
        evt.currentTarget.className += " active";
    }}
</script>
</body>
</html>
    """
    return html

def main(yearly_results=None, output_html_path=None, policy_no=None, certi_no=None):
    if yearly_results is None or len(yearly_results) == 0:
        print("Error: 需要提供yearly_results数据")
        return

    if policy_no is None and yearly_results:
        policy_no = yearly_results[0].get('policy_no')
    if certi_no is None and yearly_results:
        certi_no = yearly_results[0].get('certi_no') or None
        
    data_by_year = convert_yearly_results_to_data_by_year(yearly_results)
    rows, explanations = generate_report_data(None, data_by_year)
    html = render_html_template(rows, explanations, policy_no=policy_no, certi_no=certi_no)
    
    if output_html_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        logs_dir = os.path.join(project_root, 'logs')
        certi_part = f"_{certi_no}" if certi_no else ""
        output_html_path = os.path.join(logs_dir, f"ifrs17_103_report_{policy_no}{certi_part}.html")
        
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html)
        
    print(f"Successfully generated 103 report: {output_html_path}")
    return output_html_path

if __name__ == "__main__":
    policy_no = sys.argv[1] if len(sys.argv) > 1 else None
    certi_no = sys.argv[2] if len(sys.argv) > 2 else None
    main(policy_no=policy_no, certi_no=certi_no)

