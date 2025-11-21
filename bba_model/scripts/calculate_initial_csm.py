import psycopg2
import pandas as pd
from decimal import Decimal, getcontext
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- 配置 ---
getcontext().prec = 38
POLICY_NO_TO_CALCULATE = '1440003000004501220210000004'
DB_CONFIG = {
    'host': '10.128.21.148',
    'port': '5431',
    'dbname': 'cas25_test',
    'user': 'readonly_cas25_test',
    'password': 'readonly_cas25_test'
}

def get_discount_factor(term_months, rates_df):
    """根据月度远期利率计算指定月数的折现因子。"""
    if rates_df.empty or term_months == 0:
        return Decimal('1.0')
    
    # 确保利率是Decimal类型
    rates_df['forward_disrate_value'] = rates_df['forward_disrate_value'].apply(Decimal)
    
    # 筛选出需要的月份范围
    relevant_rates = rates_df[rates_df['term_month'] <= term_months]
    
    if len(relevant_rates) < term_months:
        # 如果利率曲线不完整，无法计算
        return None 

    # 连乘计算折现因子: 1 / ((1+r1)*(1+r2)*...*(1+rn))
    discount_factor = Decimal('1.0')
    for rate in relevant_rates['forward_disrate_value']:
        discount_factor /= (Decimal('1.0') + rate)
        
    return discount_factor

def calculate_initial_csm_for_policy():
    """
    为指定保单计算其起期当年的初始计量（CSM）。
    """
    conn = None
    try:
        print("="*80)
        print("任务：为指定保单计算起期当年的初始计量 (CSM)")
        print(f"目标保单号: {POLICY_NO_TO_CALCULATE}")
        print("="*80)

        # --- 1. 连接数据库 ---
        conn = psycopg2.connect(**DB_CONFIG)
        print("\nStep 1: 数据库连接成功。")

        # --- 2. 动态确定计量年度 ---
        print("\nStep 2: 查找保单起期以确定计量年度...")
        pre_query = f"""
        SELECT start_date 
        FROM "bi_to_cas25"."pi_policy_data_info_mon"
        WHERE policy_no = '{POLICY_NO_TO_CALCULATE}'
        LIMIT 1;
        """
        start_date_df = pd.read_sql_query(pre_query, conn)
        if start_date_df.empty or pd.isna(start_date_df.iloc[0]['start_date']):
            print(f"❌ 错误：无法找到保单 '{POLICY_NO_TO_CALCULATE}' 的起期。")
            return
            
        start_date = start_date_df.iloc[0]['start_date']
        measurement_year = start_date.year
        print(f"✅ 找到保单起期: {start_date.date()}，因此计量年度为: {measurement_year}")

        # --- 3. 获取该年度年底的数据快照 ---
        stat_period_start = f"{measurement_year}-12-01"
        stat_period_end = f"{measurement_year + 1}-01-01"
        print(f"\nStep 3: 获取 {measurement_year} 年底 (统计月份 {measurement_year}-12) 的数据快照...")
        
        policy_query = f"""
        SELECT *
        FROM "bi_to_cas25"."pi_policy_data_info_mon"
        WHERE
            policy_no = '{POLICY_NO_TO_CALCULATE}'
            AND certi_no IS NULL
            AND stat_date >= '{stat_period_start}'
            AND stat_date < '{stat_period_end}'
        LIMIT 1;
        """
        policy_df = pd.read_sql_query(policy_query, conn)
        
        if policy_df.empty:
            print(f"❌ 错误：未找到保单在 {measurement_year}-12 的数据快照。")
            return

        policy_data = policy_df.iloc[0]
        print("✅ 成功获取保单数据快照：")
        print(policy_data[['policy_no', 'under_write_date', 'start_date', 'end_date', 'sum_premium_no_tax']])
        
        # --- 4. 获取签单年月的利率曲线 ---
        under_write_date = policy_data['under_write_date']
        if pd.isna(under_write_date):
            print("❌ 错误：保单签单日期为空，无法获取利率曲线。")
            return
            
        rate_period = under_write_date.strftime('%Y-%m')
        print(f"\nStep 4: 根据签单年月 '{rate_period}' 获取月度远期利率曲线...")
        
        disrate_query = f"""
        SELECT term_month, forward_disrate_value
        FROM "measure_platform"."conf_measure_month_disrate"
        WHERE val_month = '{rate_period}'
        ORDER BY term_month;
        """
        disrate_df = pd.read_sql_query(disrate_query, conn)

        if disrate_df.empty:
            print(f"⚠️ 警告：未找到 '{rate_period}' 的利率数据。折现将按无利率(折现因子=1)进行。")
        else:
            print(f"✅ 成功获取 '{rate_period}' 的利率数据。")

        # --- 5. 构建履约现金流并计算CSM ---
        print("\nStep 5: 构建履约现金流 (FCF) 并计算初始CSM...")
        
        # 定义初始确认日 = 签单日
        initial_recognition_date = under_write_date.to_pydatetime()
        print(f"  - 初始确认日 (折现基准点): {initial_recognition_date.date()}")
        
        fulfillment_cash_flows = []

        # 5.1 保费现金流
        premium_amount = Decimal(policy_data['sum_premium_no_tax'] or '0.0')
        premium_date = initial_recognition_date
        fulfillment_cash_flows.append({
            "type": "Premium Inflow",
            "date": premium_date,
            "amount": premium_amount
        })
        print(f"  - 假设1 (保费): 在签单日收到保费流入 {premium_amount:.2f}")

        # 5.2 预期赔付和费用 (占位符)
        print("  - 假设2 (赔付/费用): 源数据不含未来预期，因此预期赔付和费用现金流设为 0。")
        
        # --- 计算过程 ---
        total_pv_fcf = Decimal('0.0')
        print("\n  --- 详细折现计算 ---")
        for cf in fulfillment_cash_flows:
            # 计算现金流发生日距离初始确认日的月数
            r_delta = relativedelta(cf['date'], initial_recognition_date)
            term_months = r_delta.years * 12 + r_delta.months

            # 获取该月数对应的折现因子
            df = get_discount_factor(term_months, disrate_df)
            if df is None:
                print(f"    ❌ 错误: 利率曲线不完整，无法计算 {term_months} 个月后的现金流现值。")
                continue

            # 计算PV (注意：保费是流入，所以计算PV时应为正；赔付费用是流出，为负)
            pv_amount = cf['amount'] * df
            total_pv_fcf += pv_amount
            
            print(f"    - 类型: {cf['type']:<15} | 日期: {cf['date'].date()} | 金额: {cf['amount']:>12.2f} | "
                  f"月数: {term_months:<2} | 折现因子: {df:.10f} | PV: {pv_amount:>12.2f}")

        # --- 计算最终CSM ---
        # CSM = - (PV of Inflows - PV of Outflows)
        # 因为我们的赔付费用是0, 所以 CSM = - PV of Premium Inflows
        initial_csm = -total_pv_fcf
        
        print("="*80)
        print("\n--- 最终计算结果 ---")
        print(f"履约现金流(FCF)现值总和: {total_pv_fcf:.4f}")
        print(f"初始合同服务边际 (CSM) = - (FCF现值总和) = {initial_csm:.4f}")
        print("="*80)

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"\n❌ 处理过程中发生严重错误: {error}")
    finally:
        if conn is not None:
            conn.close()
            print("\n数据库连接已关闭。")

if __name__ == '__main__':
    calculate_initial_csm_for_policy()
