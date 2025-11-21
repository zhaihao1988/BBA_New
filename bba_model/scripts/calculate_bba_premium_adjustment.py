import psycopg2
import pandas as pd
from decimal import Decimal, getcontext
from datetime import datetime

# 设置Decimal的精度
getcontext().prec = 38

# --- 数据库连接信息 ---
DB_CONFIG = {
    'host': '10.128.21.148',
    'port': '5431',
    'dbname': 'cas25_test',
    'user': 'readonly_cas25_test',
    'password': 'readonly_cas25_test'
}

def calculate_premium_experience_adjustment():
    """
    BBA项目第一步：计算“经验调整-保费现金流”。
    该函数将连接数据库，获取所需数据，并搭建一个带有占位符的完整计算框架。
    """
    conn = None
    try:
        # --- 1. 建立数据库连接 ---
        print("="*80)
        print("正在连接到 PostgreSQL 数据库...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("数据库连接成功。")
        print("="*80)

        # --- 2. 查询指定的保单数据 ---
        policy_query = """
        SELECT policy_no, under_write_date, start_date, end_date, sum_premium_no_tax, currency
        FROM "bi_to_cas25"."pi_policy_data_info_mon"
        WHERE
            policy_no = '1440003000004501220210000004'
            AND certi_no IS NULL
            AND stat_date >= '2024-12-01'
            AND stat_date < '2025-01-01'
        LIMIT 1;
        """
        print("\n正在查询保单 '1440003000004501220210000004' 在 2024-12 的数据...")
        policy_df = pd.read_sql_query(policy_query, conn)
        
        if policy_df.empty:
            print("错误：未找到指定的保单数据。计算无法继续。")
            return

        policy_data = policy_df.iloc[0]
        print("✅ 成功获取保单数据：")
        print(policy_data)
        print("="*80)

        # --- 3. 根据保单签单日，查询对应的利率曲线 ---
        under_write_date = policy_data['under_write_date']
        if pd.isna(under_write_date):
            print("错误：保单签单日期为空，无法确定利率曲线。")
            return
            
        rate_period = under_write_date.strftime('%Y-%m')
        print(f"\n根据签单日 {under_write_date.date()}，需要查询 '{rate_period}' 的利率曲线...")

        disrate_query = f"""
        SELECT term_month, forward_disrate_value
        FROM "measure_platform"."conf_measure_month_disrate"
        WHERE val_month = '{rate_period}'
        ORDER BY term_month;
        """
        disrate_df = pd.read_sql_query(disrate_query, conn)

        if disrate_df.empty:
            print(f"⚠️ 警告：未找到 '{rate_period}' 的利率数据。后续折现计算将无法进行。")
        else:
            print(f"✅ 成功获取 '{rate_period}' 的月度远期利率数据：")
            print(disrate_df)
        print("="*80)

        # --- 4. 搭建计算框架并定义占位符 ---
        print("\n核心说明：开始搭建“经验调整-保费现金流”计算框架。")
        print("以下计算所需变量均为精算模型输出的聚合值，无法从单张保单快照中获取。")
        print("因此，所有变量均使用 0 作为占位符，以演示计算逻辑。")
        print("---"*30)

        # 使用最终确认的命名规范定义所有变量
        PV_BPIF_EOP_FUT_PREM = Decimal('0') # 【有效合同-期末预期-预期未来-预期保费-期末现值】
        PV_NEWC_EOP_FUT_PREM = Decimal('0') # 【新增合同-期末预期-预期未来-预期保费-期末现值】
        CF_BPIF_ACT_PREM = Decimal('0')     # 【年初有效合同当年实际保费现金流】
        CF_NEWC_ACT_PREM = Decimal('0')     # 【当年新增合同当年实际保费现金流】
        PV_BPIF_BOP_FUT_PREM = Decimal('0') # 【有效合同-年初预期-预期未来-预期保费-期末现值】
        PV_NEWC_INIT_FUT_PREM = Decimal('0')# 【新增合同-初始确认-预期未来-预期保费-期末现值】
        PV_BPIF_BOP_CUR_PREM = Decimal('0') # 【有效合同-年初预期-预期当年-预期保费-期末现值】
        PV_NEWC_INIT_CUR_PREM = Decimal('0')# 【新增合同-初始确认-预期当期-预期保费-期末现值】
        PV_LAPS_EOP_FUT_PREM = Decimal('0') # 【过责合同-期末预期-预期未来-保费现金流-期末现值】
        CF_LAPS_BOP_ACT_PREM = Decimal('0') # 【过责合同-年初预期-当年实际保费现金流】
        PV_LAPS_BOP_FUT_PREM = Decimal('0') # 【过责合同-年初预期-预期未来-保费现金流-期末现值】
        CF_LAPS_ACT_PREM = Decimal('0')     # 【过责合同-当年实际保费现金流】
        exp_adj_ratio_prem = Decimal('0.0') # 【保费现金流与过去或当前服务相关的经验调整占比】

        print("计算使用的占位符变量:")
        print(f"{'PV_BPIF_EOP_FUT_PREM':<25} = {PV_BPIF_EOP_FUT_PREM}")
        print(f"{'CF_BPIF_ACT_PREM':<25} = {CF_BPIF_ACT_PREM}")
        print(f" ... (其他变量均为0)")
        print(f"{'exp_adj_ratio_prem':<25} = {exp_adj_ratio_prem} (关键占比参数)")
        print("="*80)

        # --- 5. 执行计算并详细打印过程 ---
        print("\n详细计算过程：")
        
        # 步骤 5.1: 计算“过责合同”相关的调整项
        print("\nStep 5.1: 计算'过责合同'调整项 (total_lapsed_adjustment)")
        lapsed_part_1 = PV_LAPS_EOP_FUT_PREM + CF_LAPS_BOP_ACT_PREM
        lapsed_part_2 = PV_LAPS_BOP_FUT_PREM + CF_LAPS_ACT_PREM
        total_lapsed_adjustment = lapsed_part_1 - lapsed_part_2
        print(f"  ({PV_LAPS_EOP_FUT_PREM} + {CF_LAPS_BOP_ACT_PREM}) - ({PV_LAPS_BOP_FUT_PREM} + {CF_LAPS_ACT_PREM}) = {total_lapsed_adjustment}")

        # 步骤 5.2: 计算大括号内的主要内容
        print("\nStep 5.2: 计算公式主体部分 (main_bracket_content)")
        main_bracket_content = (
            PV_BPIF_EOP_FUT_PREM + PV_NEWC_EOP_FUT_PREM +
            CF_BPIF_ACT_PREM + CF_NEWC_ACT_PREM -
            PV_BPIF_BOP_FUT_PREM - PV_NEWC_INIT_FUT_PREM -
            PV_BPIF_BOP_CUR_PREM - PV_NEWC_INIT_CUR_PREM -
            total_lapsed_adjustment
        )
        print(f"  计算逻辑：(期末未来PV + 当年实际CF) - (期初/初始未来PV + 期初/初始当期PV) - 过责调整")
        print(f"  ( ({PV_BPIF_EOP_FUT_PREM} + {PV_NEWC_EOP_FUT_PREM}) + ({CF_BPIF_ACT_PREM} + {CF_NEWC_ACT_PREM}) ) - ( ({PV_BPIF_BOP_FUT_PREM} + {PV_NEWC_INIT_FUT_PREM}) + ({PV_BPIF_BOP_CUR_PREM} + {PV_NEWC_INIT_CUR_PREM}) ) - {total_lapsed_adjustment} = {main_bracket_content}")

        # 步骤 5.3: 计算最终的经验调整
        print("\nStep 5.3: 计算最终的'经验调整-保费现金流'")
        final_experience_adjustment = (
            main_bracket_content * exp_adj_ratio_prem + total_lapsed_adjustment
        )
        print(f"  计算逻辑: main_bracket_content * 经验调整占比 + total_lapsed_adjustment")
        print(f"  {main_bracket_content} * {exp_adj_ratio_prem} + {total_lapsed_adjustment} = {final_experience_adjustment}")
        print("="*80)
        
        print("\n--- 最终计算结果 ---")
        print(f"基于占位符数据的“经验调整-保费现金流”为: {final_experience_adjustment}")
        print("---"*30)

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"\n❌ 处理过程中发生错误: {error}")
    finally:
        if conn is not None:
            conn.close()
            print("\n数据库连接已关闭。")

if __name__ == '__main__':
    # 在运行此脚本前，请确保已在虚拟环境中安装所需库:
    # pip install psycopg2-binary pandas
    calculate_premium_experience_adjustment()
