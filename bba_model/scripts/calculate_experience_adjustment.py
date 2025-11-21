import psycopg2
import pandas as pd
from decimal import Decimal

# 数据库连接配置（已移动到 bba_model/data_access/db_utils.py）
# 这里直接使用配置，或从 db_utils 导入
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
try:
    from bba_model.data_access.db_utils import DB_CONFIG
except ImportError:
    # 备用配置
    DB_CONFIG = {
        'host': '10.128.21.148',
        'port': '5431',
        'dbname': 'cas25_test',
        'user': 'readonly_cas25_test',
        'password': 'readonly_cas25_test'
    }

def get_data_and_calculate():
    """
    连接数据库，获取指定保单和利率数据，并搭建计算框架。
    """
    conn = None
    try:
        # --- 1. 建立数据库连接 ---
        print("="*50)
        print("正在连接到 PostgreSQL 数据库...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("数据库连接成功。")
        print("="*50)

        # --- 2. 查询指定的保单数据 ---
        policy_query = """
        SELECT *
        FROM "bi_to_cas25"."pi_policy_data_info_mon"
        WHERE
            policy_no = '1440003000004501220210000004'
            AND certi_no IS NULL
            AND stat_date >= '2024-12-01'
            AND stat_date < '2025-01-01'
        LIMIT 1;
        """
        print("\n正在查询保单数据...")
        policy_df = pd.read_sql_query(policy_query, conn)
        
        if policy_df.empty:
            print("错误：未找到指定的保单数据。请检查查询条件。")
            return

        policy_data = policy_df.iloc[0]
        print("成功获取保单数据：")
        print(policy_data)
        print("="*50)

        # --- 3. 查询利率数据 ---
        # 我们将使用统计月份 '2024-12' 作为利率的期间
        disrate_query = """
        SELECT term_month, compute_disrate_value, forward_disrate_value, disrate_value
        FROM "measure_platform"."conf_measure_month_disrate"
        WHERE val_month = '2024-12';
        """
        print("\n正在查询 2024年12月 的利率数据...")
        disrate_df = pd.read_sql_query(disrate_query, conn)

        if disrate_df.empty:
            print("警告：未找到 2024年12月 的利率数据，后续计算中的折现将无法进行。")
        else:
            print("成功获取利率数据：")
            print(disrate_df.head())
        print("="*50)

        # --- 4. 搭建计算框架 ---
        print("\n开始进行“经验调整-保费现金流”计算...")
        print("---"*20)
        print("重要提示：")
        print("您提供的公式非常复杂，依赖于大量当前数据源无法提供的数据（如预期现金流、年初有效合同状态等）。")
        print("因此，以下计算将使用占位符（设置为0）来构建计算框架。")
        print("您需要将这些占位符替换为实际的精算模型输出值才能得到准确结果。")
        print("---"*20)

        # --- 5. 采纳新的命名规范并定义占位符 ---
        # 请根据您的精算模型结果填充这些值
        
        # 核心变量 - 均设置为0作为占位符
        PV_BPIF_EOP_FUT_PREM = Decimal('0') # 【有效合同-期末预期-预期未来-预期保费-期末现值】
        PV_NEWC_EOP_FUT_PREM = Decimal('0') # 【新增合同-期末预期-预期未来-预期保费-期末现值】
        CF_BPIF_ACT_PREM = Decimal('0')     # 【年初有效合同当年实际保费现金流】
        CF_NEWC_ACT_PREM = Decimal('0')     # 【当年新增合同当年实际保费现金流】
        PV_BPIF_BOP_FUT_PREM = Decimal('0') # 【有效合同-年初预期-预期未来-预期保费-期末现值】
        PV_NEWC_INIT_FUT_PREM = Decimal('0')# 【新增合同-初始确认-预期未来-预期保费-期末现值】
        PV_BPIF_BOP_CUR_PREM = Decimal('0') # 【有效合同-年初预期-预期当年-预期保费-期末现值】
        PV_NEWC_INIT_CUR_PREM = Decimal('0')# 【新增合同-初始确认-预期当期-预期保费-期末现值】
        
        # “过责合同”相关变量
        PV_LAPS_EOP_FUT_PREM = Decimal('0') # 【过责合同-期末预期-预期未来-保费现金流-期末现值】
        CF_LAPS_BOP_ACT_PREM = Decimal('0') # 【过责合同-年初预期-当年实际保费现金流】
        PV_LAPS_BOP_FUT_PREM = Decimal('0') # 【过责合同-年初预期-预期未来-保费现金流-期末现值】
        CF_LAPS_ACT_PREM = Decimal('0')     # 【过责合同-当年实际保费现金流】

        # 经验调整占比
        exp_adj_ratio_prem = Decimal('0.0') # 【保费现金流与过去或当前服务相关的经验调整占比】 - 关键参数

        print("\n计算过程使用的变量（占位符）：")
        print(f"{'PV_BPIF_EOP_FUT_PREM':<25}: {PV_BPIF_EOP_FUT_PREM}")
        print(f"{'CF_BPIF_ACT_PREM':<25}: {CF_BPIF_ACT_PREM}")
        print(f"{'exp_adj_ratio_prem':<25}: {exp_adj_ratio_prem} (关键占比参数)")
        # ... 可以打印更多变量 ...
        print("-" * 50)
        
        # --- 6. 直接使用您提供的完整公式进行计算 ---
        
        # 计算公式中的“过责合同”部分
        lapsed_part_1 = PV_LAPS_EOP_FUT_PREM + CF_LAPS_BOP_ACT_PREM
        lapsed_part_2 = PV_LAPS_BOP_FUT_PREM + CF_LAPS_ACT_PREM
        total_lapsed_adjustment = lapsed_part_1 - lapsed_part_2

        # 计算主体部分（大括号内的内容）
        main_bracket_content = (
            PV_BPIF_EOP_FUT_PREM + PV_NEWC_EOP_FUT_PREM +
            CF_BPIF_ACT_PREM + CF_NEWC_ACT_PREM -
            PV_BPIF_BOP_FUT_PREM - PV_NEWC_INIT_FUT_PREM -
            PV_BPIF_BOP_CUR_PREM - PV_NEWC_INIT_CUR_PREM -
            total_lapsed_adjustment
        )

        # 最终的经验调整计算
        final_experience_adjustment = (
            main_bracket_content * exp_adj_ratio_prem + total_lapsed_adjustment
        )
        
        print("\n--- 计算结果 ---")
        print(f"根据新的命名规范、公式框架和占位符数据：")
        print(f"总的经验调整-保费现金流 = {final_experience_adjustment}")
        print("---"*20)


    except (Exception, psycopg2.DatabaseError) as error:
        print(f"处理过程中发生错误: {error}")
    finally:
        # 关闭数据库连接
        if conn is not None:
            conn.close()
            print("\n数据库连接已关闭。")

if __name__ == '__main__':
    get_data_and_calculate()
