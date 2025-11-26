import psycopg2
import pandas as pd
from decimal import Decimal, getcontext
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
import sys

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from BBA_dev.utils.pv_source_loader import load_pv_source_data

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
        
        # --- 4. 加载PV原材料数据（强制要求） ---
        policy_no = policy_data['policy_no']
        under_write_date = policy_data['under_write_date']
        if pd.isna(under_write_date):
            print("❌ 错误：保单签单日期为空，无法确定评估月。")
            return
        
        uw_month_str = under_write_date.strftime('%Y%m')
        print(f"\nStep 4: 加载PV原材料数据（评估月: {uw_month_str}）...")
        
        pv_source_data = load_pv_source_data(policy_no)
        if pv_source_data is None:
            raise ValueError(
                f"❌ 错误: PV原材料数据不可用！\n"
                f"   保单号: {policy_no}\n"
                f"   请先运行 pv_calculator.py 生成PV原材料数据文件: logs/pv_source_data_{policy_no}.json\n"
                f"   系统要求必须使用PV原材料数据，不允许使用旧的计算方式。"
            )
        
        pv_data = pv_source_data.get_data(uw_month_str)
        if pv_data is None:
            raise ValueError(
                f"❌ 错误: 找不到评估月 {uw_month_str} 的PV原材料数据！\n"
                f"   签单日期: {under_write_date.date()}\n"
                f"   请确保 pv_calculator.py 已计算该评估月的PV数据。"
            )
        
        print(f"✅ 成功加载PV原材料数据（评估月: {uw_month_str}）")

        # --- 5. 从PV原材料数据读取现值并计算CSM ---
        print("\nStep 5: 从PV原材料数据读取现值并计算初始CSM...")
        
        # 定义初始确认日 = 签单日
        initial_recognition_date = under_write_date.to_pydatetime()
        print(f"  - 初始确认日: {initial_recognition_date.date()}")
        
        # 5.1 保费现值（从PV原材料数据读取）
        # 保费发生在T=0，现值 = Written Premium
        premium_amount = Decimal(policy_data['sum_premium_no_tax'] or '0.0')
        pv_premium = premium_amount  # 保费在签单日发生，现值=原值
        print(f"  - 保费现值 (Pvfl_Nb_Ini_Cca_Rec_Lkd_Pre_Amt): {pv_premium:,.2f}")
        
        # 5.2 IACF现值（从PV原材料数据读取）
        pv_iacf = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt')
        print(f"  - IACF现值 (Pvfl_Nb_Ini_Cca_Rec_Lkd_Acq_Amt): {pv_iacf:,.2f}")
        
        # 5.3 赔付现值（从PV原材料数据读取）
        # 预期当期 + 预期未来
        pv_claims_current = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Cla_Amt')
        pv_claims_future = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Cla_Amt')
        pv_claims = pv_claims_current + pv_claims_future
        print(f"  - 赔付现值 (当期: {pv_claims_current:,.2f} + 未来: {pv_claims_future:,.2f}): {pv_claims:,.2f}")
        
        # 5.4 维费现值（从PV原材料数据读取）
        # 预期当期 + 预期未来
        pv_maint_current = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Mtn_Amt')
        pv_maint_future = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Mtn_Amt')
        pv_maint = pv_maint_current + pv_maint_future
        print(f"  - 维费现值 (当期: {pv_maint_current:,.2f} + 未来: {pv_maint_future:,.2f}): {pv_maint:,.2f}")
        
        # 5.5 RA现值（从PV原材料数据读取）
        # 预期当期 + 预期未来
        pv_ra_current = pv_data.get_field('Pvfl_Nb_Ini_Cca_Rec_Lkd_Rad_Amt')
        pv_ra_future = pv_data.get_field('Pvfl_Nb_Ini_Cfa_Rec_Lkd_Rad_Amt')
        pv_ra = pv_ra_current + pv_ra_future
        print(f"  - RA现值 (当期: {pv_ra_current:,.2f} + 未来: {pv_ra_future:,.2f}): {pv_ra:,.2f}")
        
        # --- 计算最终CSM ---
        # CSM = PV_Inflows - PV_Outflows - RA
        # PV_Inflows = Premium
        # PV_Outflows = IACF + Claims + Maint
        pv_inflows = pv_premium
        pv_outflows = pv_iacf + pv_claims + pv_maint
        net_inflow = pv_inflows - pv_outflows
        margin = net_inflow - pv_ra
        
        if margin >= 0:
            initial_csm = margin
            initial_lc = Decimal('0')
            csm_status = "Profitable (CSM)"
        else:
            initial_csm = Decimal('0')
            initial_lc = -margin
            csm_status = "Onerous (Loss Component)"
        
        print("\n  --- 详细计算过程 ---")
        print(f"    PV流入 (保费): {pv_inflows:>15,.2f}")
        print(f"    PV流出 (IACF+赔付+维费): {pv_outflows:>15,.2f}")
        print(f"    净流入: {net_inflow:>15,.2f}")
        print(f"    RA: {pv_ra:>15,.2f}")
        print(f"    边际: {margin:>15,.2f} ({csm_status})")
        
        print("="*80)
        print("\n--- 最终计算结果 ---")
        print(f"初始合同服务边际 (CSM): {initial_csm:,.2f}")
        print(f"初始亏损合同 (LC): {initial_lc:,.2f}")
        print(f"判定结果: {csm_status}")
        print("\n注意: 所有现值均从PV原材料数据读取，确保数据完整性和准确性。")
        print("="*80)

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"\n❌ 处理过程中发生严重错误: {error}")
    finally:
        if conn is not None:
            conn.close()
            print("\n数据库连接已关闭。")

if __name__ == '__main__':
    calculate_initial_csm_for_policy()
