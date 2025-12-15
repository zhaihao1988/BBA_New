import re
import os
import sys
import pandas as pd
from decimal import Decimal

def parse_decimal(text):
    if not text:
        return Decimal('0')
    if isinstance(text, (int, float)):
        return Decimal(str(text))
    # 移除逗号和括号（负数）
    clean_text = str(text).replace(',', '').strip()
    if '(' in clean_text and ')' in clean_text:
        clean_text = '-' + clean_text.replace('(', '').replace(')', '')
    return Decimal(clean_text)

def format_decimal(val):
    if val > -Decimal('0.005') and val < Decimal('0.005'): return '0.00'
    return f"{val:,.2f}"

def convert_yearly_results_to_data_by_year(yearly_results):
    """
    将yearly_results转换为data_by_year格式
    """
    data_by_year = {}
    for result in yearly_results:
        year = result.get('year')
        if year:
            data_by_year[year] = {}
            # 复制所有字段，将值转换为Decimal
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
    """
    Generates rows for the table AND explanation text for each year.
    """
    years = sorted(data_by_year.keys())
    all_rows = []
    explanations_by_year = {}
    
    # Initialize Opening Balance for the first year
    opening_balance = {'pv': Decimal('0'), 'ra': Decimal('0'), 'csm': Decimal('0')}
    
    for year in years:
        data = data_by_year[year]
        year_rows = []
        year_explanations = [] # List of dicts: {title, content}
        
        # Helper to safely get decimal
        def get_d(key):
            return data.get(key, Decimal('0'))

        # Helper to add row
        def add_row(cat_id, cat_name, pv=Decimal('0'), ra=Decimal('0'), csm=Decimal('0'), indent=0, is_header=False):
            year_rows.append({
                'year': year,
                'category_id': cat_id,
                'category_name': cat_name,
                'pv': pv,
                'ra': ra,
                'csm': csm,
                'indent': indent,
                'is_header': is_header
            })

        # --- 1. Opening Balance ---
        add_row('1', '年初的保险合同负债(1)', opening_balance['pv'], opening_balance['ra'], opening_balance['csm'])
        add_row('2', '年初的保险合同资产(2)', Decimal('0'), Decimal('0'), Decimal('0'))
        
        net_opening = {
            'pv': opening_balance['pv'],
            'ra': opening_balance['ra'],
            'csm': opening_balance['csm']
        }
        add_row('3', '年初的保险合同净负债(3)=(1)+(2)', net_opening['pv'], net_opening['ra'], net_opening['csm'])

        year_explanations.append({
            "title": "1. 年初余额",
            "content": f"""
            <ul>
                <li><b>BEL (未来现金流量现值)</b>: {format_decimal(net_opening['pv'])}</li>
                <li><b>RA (非金融风险调整)</b>: {format_decimal(net_opening['ra'])}</li>
                <li><b>CSM (合同服务边际)</b>: {format_decimal(net_opening['csm'])}</li>
                <li><b>合计</b>: {format_decimal(net_opening['pv'] + net_opening['ra'] + net_opening['csm'])}</li>
            </ul>
            """
        })

        # --- 2. Current Service ---
        # CSM Amortization
        # 修复：保险合同收入_摊销的CSM存储的已经是负数（csm_amort_amount），表示减少CSM余额，不需要再取反
        csm_amort_val = get_d('保险合同收入_摊销的CSM')
        csm_amort = csm_amort_val  # 直接使用，已经是负数（减少CSM）
        add_row('4', '合同服务边际的摊销(4)', Decimal('0'), Decimal('0'), csm_amort, indent=1)

        # RA Release
        # 只使用含亏损（总额），不再加亏损分摊（避免重复计算）
        ra_release_gross = get_d('保险合同收入_预期释放的非金融风险调整_含亏损')
        ra_change = -ra_release_gross
        add_row('5', '非金融风险调整的变动(5)', Decimal('0'), ra_change, Decimal('0'), indent=1)
        
        year_explanations.append({
            "title": "5. 非金融风险调整的变动 (RA)",
            "content": f"""
            <ul>
                <li><b>数值</b>: {format_decimal(ra_change)}</li>
                <li><b>公式</b>: -预期释放RA_含亏损</li>
                <li><b>计算</b>: -{format_decimal(ra_release_gross)} = {format_decimal(ra_change)}</li>
                <li><b>说明</b>: RA随着服务提供而释放，导致负债减少。使用含亏损总额，不重复加亏损分摊。</li>
            </ul>
            """
        })

        # Experience Adjustments
        # 直接使用含亏损总额，不再减去亏损分摊
        expected_claims_exp = get_d('保险合同收入_预期赔付与费用_含亏损')
        
        # [Revert Fix] 实际赔付与费用：
        # Log Closing (未到期责任负债) 只包含 LRC (Future CF)，不包含 LIC (Incurred)。
        # 因此，Roll-forward 应该体现 Expected Release (减少 LRC)，而不应该加回 Actual Incurred (增加 LIC)。
        # 所以 Actual 设为 0。
        actual_claims_exp = Decimal('0')
        
        exp_adj_log = get_d('保险合同收入_经验调整')
        
        curr_service_pv_val = actual_claims_exp - expected_claims_exp + exp_adj_log
        add_row('6', '当期经验调整(6)', curr_service_pv_val, Decimal('0'), Decimal('0'), indent=1)

        year_explanations.append({
            "title": "6. 当期经验调整 (BEL)",
            "content": f"""
            <ul>
                <li><b>数值</b>: {format_decimal(curr_service_pv_val)}</li>
                <li><b>公式</b>: 实际赔付与费用 - 预期赔付与费用 + 保费经验调整</li>
                <li><b>计算</b>: {format_decimal(actual_claims_exp)} - {format_decimal(expected_claims_exp)} + {format_decimal(exp_adj_log)}</li>
                <li><b>说明</b>: 反映了实际现金流与预期现金流的差异，以及预期现金流的释放。</li>
            </ul>
            """
        })

        # Sum Current Service
        curr_service_sum = {
            'pv': curr_service_pv_val,
            'ra': ra_change,
            'csm': csm_amort
        }
        add_row('7', '与当期服务相关的变动(7)=(4)+(5)+(6)', curr_service_sum['pv'], curr_service_sum['ra'], curr_service_sum['csm'])

        # --- 3. Future Service (New Business & Estimate Changes) ---
        # New Business
        # 判断是否为初始确认年：如果init_data有数据且是第一个年份，使用初始确认数据
        first_year = min(data_by_year.keys()) if data_by_year else year
        if year == first_year and init_data.get('nb_init_prem', Decimal('0')) != Decimal('0'):
            # 使用初始确认数据（从日志开头提取）
            nb_bel = (init_data.get('nb_init_claims', Decimal('0')) + 
                      init_data.get('nb_init_maint', Decimal('0')) + 
                      init_data.get('nb_init_iacf', Decimal('0'))) - init_data.get('nb_init_prem', Decimal('0'))
            nb_ra = init_data.get('nb_init_ra', Decimal('0'))
            # 修复：使用初始确认的CSM值（盈利合同有CSM，亏损合同CSM=0但有LC）
            nb_csm = init_data.get('nb_init_csm', Decimal('0'))
            
            nb_explanation = f"""
            <ul>
                <li><b>BEL</b>: {format_decimal(nb_bel)} = (预期赔付 {format_decimal(init_data.get('nb_init_claims'))} + 预期维费 {format_decimal(init_data.get('nb_init_maint'))} + 预期获取费用 {format_decimal(init_data.get('nb_init_iacf'))}) - 预期保费 {format_decimal(init_data.get('nb_init_prem'))}</li>
                <li><b>RA</b>: {format_decimal(nb_ra)}</li>
                <li><b>CSM</b>: {format_decimal(nb_csm)}</li>
            </ul>
            """
        else:
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
            
            nb_explanation = f"""
            <ul>
                <li><b>BEL</b>: {format_decimal(nb_bel)}</li>
                <li><b>RA</b>: {format_decimal(nb_ra)}</li>
                <li><b>CSM</b>: {format_decimal(nb_csm)}</li>
            </ul>
            """

        add_row('8', '当期初始确认的保险合同影响(8)', nb_bel, nb_ra, nb_csm, indent=1)
        
        if year == 2022 or (nb_bel if nb_bel > 0 else -nb_bel) + (nb_ra if nb_ra > 0 else -nb_ra) + (nb_csm if nb_csm > 0 else -nb_csm) > 0:
            year_explanations.append({
                "title": "8. 当期初始确认的保险合同影响",
                "content": nb_explanation
            })

        # CSM Adjusting
        csm_adj_pv = get_d('未到期_调整CSM的预期现金流变动')
        csm_adj_ra = get_d('未到期_调整CSM的非金融风险调整变动')
        csm_adj_csm = get_d('未到期_调整CSM的估计变更')
        add_row('9', '调整合同服务边际的估计变更(9)', csm_adj_pv, csm_adj_ra, csm_adj_csm, indent=1)

        # Non-CSM Adjusting
        non_csm_pv = get_d('亏损合同损益_不调整CSM的预期现金流变动')
        non_csm_ra = get_d('亏损合同损益_不调整CSM的非金融风险调整变动')
        add_row('10', '不调整合同服务边际的估计变更(10)', non_csm_pv, non_csm_ra, Decimal('0'), indent=1)
        
        add_row('11', '其他与未来服务相关变动(11)', Decimal('0'), Decimal('0'), Decimal('0'), indent=1)

        # Sum Future Service
        future_service_sum = {
            'pv': nb_bel + csm_adj_pv + non_csm_pv,
            'ra': nb_ra + csm_adj_ra + non_csm_ra,
            'csm': nb_csm + csm_adj_csm
        }
        add_row('12', '与未来服务相关的变动(12)=(8)+(9)+(10)+(11)', future_service_sum['pv'], future_service_sum['ra'], future_service_sum['csm'])

        # --- 4. Past Service ---
        add_row('13', '已发生赔款负债相关履约现金流量变动(13)', Decimal('0'), Decimal('0'), Decimal('0'), indent=1)
        add_row('14', '其他与过去服务相关的变动(14)', Decimal('0'), Decimal('0'), Decimal('0'), indent=1)
        add_row('15', '与过去服务相关的变动(15)=(13)+(14)', Decimal('0'), Decimal('0'), Decimal('0'))

        # --- 5. Insurance Service Result ---
        ins_service_result = {
            'pv': curr_service_sum['pv'] + future_service_sum['pv'],
            'ra': curr_service_sum['ra'] + future_service_sum['ra'],
            'csm': curr_service_sum['csm'] + future_service_sum['csm']
        }
        add_row('16', '保险服务业绩(16)=(7)+(12)+(15)', ins_service_result['pv'], ins_service_result['ra'], ins_service_result['csm'])

        # --- 6. IFIE (Finance) ---
        # 从非亏损+亏损计算IFIE_P&L合计值（包含亏损和非亏损）
        ifie_pl_cf_non_lc = get_d('IFIE_P&L_未到期_预期现金流_非亏损')
        ifie_pl_cf_lc = get_d('IFIE_P&L_未到期_预期现金流_亏损')
        ifie_pv = ifie_pl_cf_non_lc + ifie_pl_cf_lc
        
        ifie_pl_ra_non_lc = get_d('IFIE_P&L_未到期_非金融风险调整_非亏损')
        ifie_pl_ra_lc = get_d('IFIE_P&L_未到期_非金融风险调整_亏损')
        ifie_ra = ifie_pl_ra_non_lc + ifie_pl_ra_lc
        
        # CSM计息在日志/CSV中为P&L费用（负数），报表需显示为正数（增加负债）
        ifie_csm_log = get_d('IFIE_P&L_未到期_CSM')
        ifie_csm = -ifie_csm_log  # 取反为正数
        add_row('17', '保险合同金融变动额(17)', ifie_pv, ifie_ra, ifie_csm)
        
        year_explanations.append({
            "title": "17. 保险合同金融变动额 (IFIE_P&L)",
            "content": f"""
            <ul>
                <li><b>BEL</b>: {format_decimal(ifie_pv)} = {format_decimal(ifie_pl_cf_non_lc)} (非亏损) + {format_decimal(ifie_pl_cf_lc)} (亏损)</li>
                <li><b>RA</b>: {format_decimal(ifie_ra)} = {format_decimal(ifie_pl_ra_non_lc)} (非亏损) + {format_decimal(ifie_pl_ra_lc)} (亏损)</li>
                <li><b>CSM</b>: {format_decimal(ifie_csm)}</li>
            </ul>
            """
        })

        add_row('18', '其他损益变动(18)', Decimal('0'), Decimal('0'), Decimal('0'))

        # OCI
        # 直接使用日志中已计算的IFIE_OCI合计值（包含亏损和非亏损）
        # 从非亏损+亏损计算，因为日志中已有这两个值
        ifie_oci_pv_non_lc = get_d('IFIE_OCI_未到期_预期现金流_非亏损')
        ifie_oci_pv_lc = get_d('IFIE_OCI_未到期_预期现金流_亏损')
        ifie_oci_pv = ifie_oci_pv_non_lc + ifie_oci_pv_lc
        
        ifie_oci_ra_non_lc = get_d('IFIE_OCI_未到期_非金融风险调整_非亏损')
        ifie_oci_ra_lc = get_d('IFIE_OCI_未到期_非金融风险调整_亏损')
        ifie_oci_ra = ifie_oci_ra_non_lc + ifie_oci_ra_lc
        
        add_row('19', '其他综合收益其他变动(19)', ifie_oci_pv, ifie_oci_ra, Decimal('0'))
        
        year_explanations.append({
            "title": "19. 其他综合收益 (OCI)",
            "content": f"""
            <ul>
                <li><b>BEL</b>: {format_decimal(ifie_oci_pv)} = IFIE_OCI_预期现金流（包含亏损和非亏损）</li>
                <li><b>RA</b>: {format_decimal(ifie_oci_ra)} = IFIE_OCI_非金融风险调整（包含亏损和非亏损）</li>
            </ul>
            """
        })

        # Total Comprehensive Income
        total_ci = {
            'pv': ins_service_result['pv'] + ifie_pv + ifie_oci_pv,
            'ra': ins_service_result['ra'] + ifie_ra + ifie_oci_ra,
            'csm': ins_service_result['csm'] + ifie_csm
        }
        add_row('20', '相关综合收益变动合计(20)=(16)+(17)+(18)+(19)', total_ci['pv'], total_ci['ra'], total_ci['csm'])

        # --- 7. Cash Flows ---
        cf_prem = get_d('现金流_收到的保费')
        add_row('21', '收到的保费(21)', cf_prem, Decimal('0'), Decimal('0'), indent=1)

        cf_acq = -get_d('现金流_支付的获取费用') 
        add_row('22', '支付的保险获取现金流量(22)', cf_acq, Decimal('0'), Decimal('0'), indent=1)

        add_row('23', '支付的赔款及其他相关费用(含投资成分)(23)', Decimal('0'), Decimal('0'), Decimal('0'), indent=1)
        add_row('24', '其他现金流量(24)', Decimal('0'), Decimal('0'), Decimal('0'), indent=1)

        cf_total = cf_prem + cf_acq
        add_row('25', '现金流量合计(25)=(21)+(22)+(23)+(24)', cf_total, Decimal('0'), Decimal('0'))
        
        year_explanations.append({
            "title": "21 & 22. 现金流",
            "content": f"""
            <ul>
                <li><b>(21) 收到的保费</b>: {format_decimal(cf_prem)}</li>
                <li><b>(22) 支付的获取费用</b>: {format_decimal(cf_acq)} (流出为负)</li>
                <li><b>(25) 现金流量合计</b>: {format_decimal(cf_total)}</li>
            </ul>
            """
        })

        # --- 8. Other & Closing ---
        
        # Calculate target closing (from logs)
        log_closing_bel = get_d('未到期责任负债_预期现金流_非亏损') + get_d('未到期责任负债_预期现金流_亏损')
        log_closing_ra = get_d('未到期责任负债_非金融风险调整_非亏损') + get_d('未到期责任负债_非金融风险调整_亏损')
        log_closing_csm = get_d('未到期责任负债_CSM')
        
        # Calculate tentative closing (from roll-forward)
        tentative_closing_pv = net_opening['pv'] + total_ci['pv'] + cf_total
        tentative_closing_ra = net_opening['ra'] + total_ci['ra']
        
        # Calculate Other Changes (should be zero ideally)
        # 移除作为 Plug 的逻辑，只保留真正的其他变动（如果有）
        other_change_pv = Decimal('0')
        other_change_ra = Decimal('0')
        
        add_row('26', '其他变动(26)', other_change_pv, other_change_ra, Decimal('0')) 
        
        calc_closing = {
            'pv': net_opening['pv'] + total_ci['pv'] + cf_total + other_change_pv,
            'ra': net_opening['ra'] + total_ci['ra'] + other_change_ra,
            'csm': net_opening['csm'] + total_ci['csm']
        }

        add_row('27', '年末的保险合同净负债(27)=(3)+(20)+(25)+(26)', calc_closing['pv'], calc_closing['ra'], calc_closing['csm'])
        add_row('28', '年末的保险合同资产(28)', Decimal('0'), Decimal('0'), Decimal('0'))
        add_row('29', '年末的保险合同负债(29)', calc_closing['pv'], calc_closing['ra'], calc_closing['csm'])

        # Verification Section
        diff_pv = calc_closing['pv'] - log_closing_bel
        diff_ra = calc_closing['ra'] - log_closing_ra
        diff_csm = calc_closing['csm'] - log_closing_csm
        
        def get_verify_status(diff):
            if diff > -Decimal('0.01') and diff < Decimal('0.01'):
                return "<span style='color:green'>无差异</span>"
            return f"<span style='color:red'>差异: {format_decimal(diff)}</span>"

        year_explanations.append({
            "title": "期末余额验算 (计算值 vs 日志值)",
            "content": f"""
            <table style="width:100%; border-collapse: collapse; margin-top: 5px; border: 1px solid #eee;">
                <tr style="background-color: #f8f9fa;">
                    <th style="text-align: left; padding: 8px;">项目</th>
                    <th style="text-align: right; padding: 8px;">计算期末</th>
                    <th style="text-align: right; padding: 8px;">日志期末</th>
                    <th style="text-align: right; padding: 8px;">差异</th>
                </tr>
                <tr>
                    <td style="padding: 8px;">BEL</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(calc_closing['pv'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_closing_bel)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_pv)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">RA</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(calc_closing['ra'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_closing_ra)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_ra)}</td>
                </tr>
                <tr>
                    <td style="padding: 8px;">CSM</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(calc_closing['csm'])}</td>
                    <td style="text-align: right; padding: 8px;">{format_decimal(log_closing_csm)}</td>
                    <td style="text-align: right; padding: 8px;">{get_verify_status(diff_csm)}</td>
                </tr>
            </table>
            <p style="font-size: 0.9em; color: #666; margin-top: 5px;">注：计算期末 = 期初 + 综合收益变动 + 现金流 + 其他变动</p>
            """
        })

        all_rows.extend(year_rows)
        explanations_by_year[year] = year_explanations
        
        # Update opening for next year
        opening_balance = calc_closing

    return all_rows, explanations_by_year

def render_html_template(rows, explanations_by_year, policy_no=None, certi_no=None):
    df = pd.DataFrame(rows)
    years = df['year'].unique()
    
    # 确定年份范围
    year_range = f"{min(years)}-{max(years)}" if len(years) > 1 else str(years[0])
    
    # 构建保单信息显示
    policy_info = policy_no if policy_no else "未知保单"
    if certi_no:
        policy_info += f" (批单号: {certi_no})"
    
    tabs_html = ""
    content_html = ""
    
    for idx, year in enumerate(years):
        active_class = " active" if idx == 0 else ""
        tabs_html += f'<button class="tab-btn{active_class}" onclick="openTab(event, \'y{year}\')">{year} 年度</button>\n'
        
        # Build Table
        year_df = df[df['year'] == year]
        
        table_rows = ""
        for _, row in year_df.iterrows():
            total = row['pv'] + row['ra'] + row['csm']
            
            def fmt(val):
                if val > -Decimal('0.005') and val < Decimal('0.005'): return '<span class="zero">0.00</span>'
                s = "{:,.2f}".format(val)
                if val < 0:
                    return f'<span class="negative">({s.replace("-", "")})</span>'
                return s
            
            csm_class = " col-csm"
            row_class = ""
            
            # Add borders for key summary lines
            if any(x in row['category_name'] for x in ['年初的保险合同负债(1)', '合同服务边际的摊销(4)', '当期初始确认', '已发生赔款', '保险服务业绩', '现金流量合计', '年末的保险合同净负债']):
                 row_class = "border-top-heavy"
            if '年末的保险合同净负债' in row['category_name']:
                row_class += " border-double-bottom"

            indent_class = f" indent-{row['indent']}" if row['indent'] > 0 else ""
            
            pv_cell = fmt(row['pv'])
            ra_cell = fmt(row['ra'])
            csm_cell = fmt(row['csm'])
            total_cell = fmt(total)

            table_rows += f"""
                <tr class="{row_class}">
                    <td class="{indent_class}">{row['category_name']}</td>
                    <td class="num">{pv_cell}</td>
                    <td class="num">{ra_cell}</td>
                    <td class="num{csm_class}">{csm_cell}</td>
                    <td class="num">{total_cell}</td>
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
                        <th colspan="4">{year}年度 (单位: 元)</th>
                    </tr>
                    <tr>
                        <th>未来现金流量<br>的现值</th>
                        <th>非金融风险<br>调整</th>
                        <th class="header-csm">合同服务<br>边际(a)</th>
                        <th>合计</th>
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
    <title>IFRS 17 合同负债余额调节表 (详细版)</title>
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

        /* Tabs */
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

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
        }}

        /* Table */
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
        
        .border-top-heavy {{
            border-top: 2px solid #6c757d;
        }}
        
        .border-double-bottom {{
            border-bottom: 3px double #6c757d;
        }}

        .num {{ font-family: Consolas, monospace; }}
        .zero {{ color: #adb5bd; }} 
        .negative {{ color: #d9534f; }}

        .col-csm {{
            background-color: #fffbeb;
        }}
        .header-csm {{
            color: #d68b00;
        }}

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
    <h1>IFRS 17 合同负债余额调节表</h1>
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

def main(yearly_results=None, init_context=None, output_html_path=None, policy_no=None, certi_no=None):
    """
    生成IFRS 17报表
    
    Args:
        yearly_results: 年度计算结果列表（从context提取），优先使用
        init_context: 初始确认后的context（用于提取初始确认数据）
        output_html_path: 输出HTML文件路径，如果为None则根据policy_no和certi_no自动生成
        policy_no: 保单号
        certi_no: 批单号（可选）
    """
    if yearly_results is None or len(yearly_results) == 0:
        print("Error: 需要提供yearly_results数据")
        return
    
    # 从yearly_results中提取保单号和批单号（如果未提供）
    if policy_no is None and yearly_results:
        policy_no = yearly_results[0].get('policy_no')
    if certi_no is None and yearly_results:
        certi_no = yearly_results[0].get('certi_no') or None
    
    # 提取初始确认数据
    if init_context:
        def to_decimal(val):
            if val is None:
                return Decimal('0')
            if isinstance(val, Decimal):
                return val
            return Decimal(str(val))
        
        init_data = {
            'nb_init_prem': to_decimal(getattr(init_context, 'actual_premium', None)),
            'nb_init_iacf': to_decimal(getattr(init_context, 'actual_iacf_incurred', None)),
            'nb_init_claims': to_decimal(getattr(init_context, 'init_fut_claim', None)),
            'nb_init_maint': to_decimal(getattr(init_context, 'init_fut_maint', None)),
            'nb_init_ra': to_decimal(getattr(init_context, 'init_ra', None)),
            'nb_init_csm': to_decimal(getattr(init_context, 'nb_initial_csm', None)),
            'nb_init_lc': to_decimal(getattr(init_context, 'nb_initial_lc', None)),
        }
    else:
        # 如果没有init_context，尝试从第一个年度结果推导（如果可能）
        init_data = {
            'nb_init_prem': Decimal('0'),
            'nb_init_iacf': Decimal('0'),
            'nb_init_claims': Decimal('0'),
            'nb_init_maint': Decimal('0'),
            'nb_init_ra': Decimal('0'),
            'nb_init_csm': Decimal('0'),
            'nb_init_lc': Decimal('0'),
        }
    
    # 转换yearly_results为data_by_year格式
    data_by_year = convert_yearly_results_to_data_by_year(yearly_results)
    
    if not data_by_year:
        print("Error: No data found in yearly_results.")
        return
    
    # 确定输出路径
    if output_html_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        logs_dir = os.path.join(project_root, 'logs')
        certi_part = f"_{certi_no}" if certi_no else ""
        output_html_path = os.path.join(logs_dir, f"ifrs17_104_report_{policy_no}{certi_part}.html")
        
    rows, explanations = generate_report_data(init_data, data_by_year)
    html = render_html_template(rows, explanations, policy_no=policy_no, certi_no=certi_no)
    
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Successfully generated report: {output_html_path}")
    return output_html_path

if __name__ == "__main__":
    # 支持命令行参数：python generate_ifrs17_report.py <policy_no> [certi_no]
    policy_no = sys.argv[1] if len(sys.argv) > 1 else None
    certi_no = sys.argv[2] if len(sys.argv) > 2 else None
    main(policy_no=policy_no, certi_no=certi_no)
