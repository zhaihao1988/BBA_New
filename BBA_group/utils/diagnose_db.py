import psycopg2
import pandas as pd

# 使用修正后的数据库连接配置
DB_CONFIG = {
    'host': '10.128.21.148',
    'port': '5431',
    'dbname': 'cas25_test',
    'user': 'readonly_cas25_test',
    'password': 'readonly_cas25_test'
}

def diagnose_database_connection():
    """
    连接到数据库并执行一系列诊断查询，以解决 "relation does not exist" 的问题。
    """
    conn = None
    try:
        # --- 1. 建立数据库连接 ---
        print("="*50)
        print(f"正在尝试以用户 '{DB_CONFIG['user']}' 连接到数据库 '{DB_CONFIG['dbname']}'...")
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("数据库连接成功！")
        print("="*50)

        # --- 2. 查询并打印 search_path ---
        print("\n正在查询当前用户的搜索路径 (search_path)...")
        cursor.execute("SHOW search_path;")
        search_path = cursor.fetchone()[0]
        print(f"当前的 search_path 为: {search_path}")
        print("说明: 这是数据库在没有指定schema时查找表的顺序。")
        print("如果 'bi_to_cas25' 和 'measure_platform' 不在这里面，就必须在查询时显式指定。")
        print("="*50)

        # --- 3. 查询用户可见的所有表 ---
        # 这是最关键的一步，它会告诉我们这个用户到底能看见哪些表。
        visible_tables_query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        ORDER BY table_schema, table_name;
        """
        print("\n正在查询用户可见的所有 schemas 和 tables...")
        
        try:
            df_tables = pd.read_sql_query(visible_tables_query, conn)
            
            if df_tables.empty:
                print("错误：此用户看不到任何表！请检查用户权限。")
            else:
                print("查询成功！该用户可见的表和其所属的schema列表如下：")
                # 筛选我们关心的schema
                target_schemas = ['bi_to_cas25', 'measure_platform']
                found_our_tables = False
                
                with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
                    print(df_tables)

                print("\n--- 诊断结果分析 ---")
                # 检查我们需要的表是否存在
                pi_table_found = ((df_tables['table_schema'] == 'bi_to_cas25') & 
                                  (df_tables['table_name'] == 'pi_policy_data_info_mon')).any()
                conf_table_found = ((df_tables['table_schema'] == 'measure_platform') & 
                                    (df_tables['table_name'] == 'conf_measure_month_disrate')).any()

                if pi_table_found:
                    print("✅ 成功找到目标表: bi_to_cas25.pi_policy_data_info_mon")
                else:
                    print("❌ 未找到目标表: bi_to_cas25.pi_policy_data_info_mon")

                if conf_table_found:
                    print("✅ 成功找到目标表: measure_platform.conf_measure_month_disrate")
                else:
                    print("❌ 未找到目标表: measure_platform.conf_measure_month_disrate")
                
                if not pi_table_found or not conf_table_found:
                     print("\n结论：用户权限不足或表确实不存在于此数据库中。请数据库管理员(DBA)为用户 'readonly_cas25_test' 授予对这些表的 SELECT 权限，或确认表名拼写无误。")
                else:
                    print("\n结论：用户权限看起来是足够的，表也存在。如果之前的脚本仍然失败，问题可能更复杂，例如网络策略或数据库的行级安全策略。")


        except Exception as e:
            print(f"查询可见表时出错: {e}")
        
        print("="*50)

    except psycopg2.OperationalError as e:
        print(f"数据库连接失败: {e}")
        print("请检查主机、端口、数据库名和网络连接。")
    except Exception as error:
        print(f"处理过程中发生未知错误: {error}")
    finally:
        if conn is not None:
            conn.close()
            print("\n数据库连接已关闭。")

if __name__ == '__main__':
    diagnose_database_connection()
