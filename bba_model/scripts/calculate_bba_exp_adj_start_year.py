import psycopg2
import pandas as pd
from decimal import Decimal, getcontext
from datetime import datetime

# --- 配置 ---
getcontext().prec = 38
POLICY_NO = '1440003000004501220210000004'
DB_CONFIG = {
    'host': '10.128.21.148',
    'port': '5431',
    'dbname': 'cas25_test',
    'user': 'readonly_cas25_test',
    'password': 'readonly_cas25_test'
}

def calculate_experience_adjustment():
    conn = None
    try:
        print("="*80)
        print(f"BBA计量展示：经验调整-保费现金流")
        print(f"保单号: {POLICY_NO}")
        print("="*80)

        conn = psycopg2.connect(**DB_CONFIG)
        
        # 1. 确定起期年份
        print("\n[Step 1] 确定保单起期年份...")
        date_query = f"SELECT start_date FROM bi_to_cas25.pi_policy_data_info_mon WHERE policy_no = '{POLICY_NO}' LIMIT 1"
        df_date = pd.read_sql_query(date_query, conn)
        if df_date.empty or pd.isna(df_date.iloc[0]['start_date']):
            print("错误：无法找到保单起期。")
            return
        
        start_date = df_date.iloc[0]['start_date']
        year = start_date.year
        print(f"✅ 保单起期: {start_date.date()} -> 计量年度: {year}年 (属于新增合同)")

        # 2. 获取该年度数据 (实际保费)
        print(f"\n[Step 2] 获取保单保费数据...")
        # 尝试获取起期当年的数据，如果不存在，则使用最新可用的数据快照（因为保费通常是固定的）
        # 优先找 2024-12 (已知存在) 或按时间倒序的第一条
        data_query = f"""
            SELECT sum_premium_no_tax, under_write_date, stat_date
            FROM bi_to_cas25.pi_policy_data_info_mon 
            WHERE policy_no = '{POLICY_NO}' 
            ORDER BY stat_date DESC LIMIT 1
        """
        df_data = pd.read_sql_query(data_query, conn)
        
        if df_data.empty:
            print(f"错误：未找到该保单的任何数据记录。")
            return
            
        record_stat_date = df_data.iloc[0]['stat_date']
        actual_premium = Decimal(df_data.iloc[0]['sum_premium_no_tax'] or 0)
        
        if record_stat_date.year != year:
            print(f"⚠️ 提示: 未找到起期当年({year})的统计数据。")
            print(f"   使用最新可用数据 (统计日期: {record_stat_date.date()}) 中的保费金额作为替代。")
            print(f"   假设: 签单保费金额在合同全生命周期内保持不变。")
        
        print(f"✅ 数据库记录的保费(不含税): {actual_premium:,.2f}")
        print("   -> 将被映射为: 【当年新增合同当年实际保费现金流】 (CF_NEWC_ACT_PREM)")

        # 3. 定义变量 (使用新命名规范)
        print(f"\n[Step 3] 定义公式变量 (根据您提供的趸交场景设定预期值)...")
        print(f"   场景假设: 2020年起期，趸交保费，预期当期收到 {actual_premium:,.2f}，预期未来为 0。")
        
        # === 变量映射 ===
        # 新增合同相关
        CF_NEWC_ACT_PREM      = actual_premium    # 实际当期收到保费 (数据库获取)
        PV_NEWC_INIT_CUR_PREM = actual_premium    # 2020年预期当期收到的保费 (假设 = 实际)
        PV_NEWC_INIT_FUT_PREM = Decimal('0')      # 2020年初始预期未来收到保费 (趸交，未来为0)
        PV_NEWC_EOP_FUT_PREM  = Decimal('0')      # 2020年期末预期未来收到保费 (趸交，未来为0)
        
        # 有效合同 (BPIF) 相关 -> 对于起期当年的新增合同，这些项通常为0
        CF_BPIF_ACT_PREM      = Decimal('0')
        PV_BPIF_BOP_CUR_PREM  = Decimal('0')
        PV_BPIF_BOP_FUT_PREM  = Decimal('0')
        PV_BPIF_EOP_FUT_PREM  = Decimal('0')
        
        # 过责合同 (LAPS) 相关
        CF_LAPS_ACT_PREM      = Decimal('0')
        CF_LAPS_BOP_ACT_PREM  = Decimal('0')
        PV_LAPS_BOP_FUT_PREM  = Decimal('0')
        PV_LAPS_EOP_FUT_PREM  = Decimal('0')
        
        # 经验调整占比
        EXP_ADJ_RATIO         = Decimal('1.0')  # 假设100%计入经验调整以便演示
        
        print(f"   CF_NEWC_ACT_PREM      (实际当期收到保费)              = {CF_NEWC_ACT_PREM:,.2f}")
        print(f"   PV_NEWC_INIT_CUR_PREM (2020年预期当期收到的保费)      = {PV_NEWC_INIT_CUR_PREM:,.2f}")
        print(f"   PV_NEWC_INIT_FUT_PREM (2020年初始预期未来收到保费)    = {PV_NEWC_INIT_FUT_PREM:,.2f}")
        print(f"   PV_NEWC_EOP_FUT_PREM  (2020年期末预期未来收到保费)    = {PV_NEWC_EOP_FUT_PREM:,.2f}")
        print(f"   ... 其他项均为 0")

        # 4. 执行计算
        print(f"\n[Step 4] 执行计算公式...")
        
        # (1) 过责合同调整项 (Lapsed Adjustment)
        # 公式: (过责期末未来PV + 过责年初实际CF) - (过责年初未来PV + 过责当年实际CF)
        lapsed_adj = (PV_LAPS_EOP_FUT_PREM + CF_LAPS_BOP_ACT_PREM) - (PV_LAPS_BOP_FUT_PREM + CF_LAPS_ACT_PREM)
        print(f"   1. 过责合同调整项 = {lapsed_adj}")

        # (2) 主体偏差 (Main Difference)
        # 公式逻辑: (期末视角总额) - (期初/初始视角总额) - 过责调整
        # 期末视角 = (有效期末未来PV + 新增期末未来PV) + (有效当年实际 + 新增当年实际)
        end_view = (PV_BPIF_EOP_FUT_PREM + PV_NEWC_EOP_FUT_PREM) + (CF_BPIF_ACT_PREM + CF_NEWC_ACT_PREM)
        
        # 期初视角 = (有效年初未来PV + 新增初始未来PV) + (有效年初当期PV + 新增初始当期PV)
        start_view = (PV_BPIF_BOP_FUT_PREM + PV_NEWC_INIT_FUT_PREM) + (PV_BPIF_BOP_CUR_PREM + PV_NEWC_INIT_CUR_PREM)
        
        main_diff = end_view - start_view - lapsed_adj
        
        print(f"   2. 期末视角总额 (未来PV+实际CF) = {end_view:,.2f}")
        print(f"   3. 期初视角总额 (未来PV+当期PV) = {start_view:,.2f}")
        print(f"   4. 主体偏差 = {end_view:,.2f} - {start_view:,.2f} - {lapsed_adj} = {main_diff:,.2f}")

        # (3) 最终结果
        # 公式: 主体偏差 * 占比 + 过责调整
        final_result = (main_diff * EXP_ADJ_RATIO) + lapsed_adj
        
        print("\n" + "-"*30)
        print(f"【计算结果】 经验调整-保费现金流: {final_result:,.2f}")
        print("-"*30)
        
        print("\n结果解读:")
        if final_result > 0:
            print("正值 (+): 说明实际收到的保费(或期末对未来的预期) 高于 初始确认时的预期。")
            print("         这通常意味着公司“多收了钱”，是个好消息。")
        elif final_result < 0:
            print("负值 (-): 说明实际收到的保费(或期末对未来的预期) 低于 初始确认时的预期。")
        else:
            print("零值 (0): 说明实际与预期完全一致。")

    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    calculate_experience_adjustment()

