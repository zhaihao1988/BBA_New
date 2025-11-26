
import psycopg2
import pandas as pd

# --- 数据库连接信息 ---
# 根据您提供的图片和说明进行配置
DB_CONFIG = {
    'host': '10.128.21.148',
    'port': '5431',
    'dbname': 'postgres',
    'user': 'readonly_cas25_test',
    'password': 'readonly_cas25_test'  # 密码和用户名相同
}

# --- SQL 查询语句 ---
# 筛选 risk_code 为 '040012' 或 '040013'，且统计日期为2024年12月的数据
SQL_QUERY = """
SELECT *
FROM bi_to_cas25.pi_policy_data_info_mon
WHERE
    risk_code IN ('040012', '040013')
    AND stat_date >= '2024-12-01'
    AND stat_date < '2025-01-01';
"""

def fetch_policy_data():
    """
    连接到 PostgreSQL 数据库，执行查询并获取数据。
    将查询结果保存为 CSV 文件。
    """
    conn = None
    try:
        # 建立数据库连接
        print("正在连接到 PostgreSQL 数据库...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("数据库连接成功。")

        # 执行查询并将结果读入 pandas DataFrame
        print("正在执行查询...")
        df = pd.read_sql_query(SQL_QUERY, conn)
        print("查询执行完毕。")

        if not df.empty:
            print(f"成功获取 {len(df)} 条记录。")
            
            # 将数据保存到 CSV 文件
            output_filename = 'policy_data_202412.csv'
            df.to_csv(output_filename, index=False, encoding='utf-8-sig')
            print(f"数据已成功保存到文件: {output_filename}")
            
            # 显示前5行数据作为预览
            print("\n数据预览 (前5行):")
            print(df.head())
        else:
            print("未找到满足条件的数据。")

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"连接数据库或查询数据时出错: {error}")
    finally:
        # 关闭数据库连接
        if conn is not None:
            conn.close()
            print("数据库连接已关闭。")

if __name__ == '__main__':
    # 在运行此脚本前，请确保已安装所需库:
    # pip install psycopg2-binary pandas
    fetch_policy_data()
