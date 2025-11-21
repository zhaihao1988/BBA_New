import pandas as pd
import sys
import os
from decimal import Decimal

# 使用相对导入
from bba_model.data_access.db_utils import get_db_connection


def get_policy_data(policy_no):
    """
    从数据库读取保单基础数据
    
    Args:
        policy_no: 保单号
        
    Returns:
        DataFrame: 包含保单信息的 DataFrame，字段包括：
            - sum_premium_no_tax: 签单保费（不含税）
            - under_write_date: 签单日期
            - start_date: 起保日期
            - end_date: 终保日期
            - class_code: 险类代码（用于匹配精算假设）
            - risk_code: 险种代码（备用）
            - stat_date: 统计日期
    """
    conn = get_db_connection()
    try:
        data_query = f"""
            SELECT 
                sum_premium_no_tax, 
                under_write_date, 
                start_date, 
                end_date, 
                class_code,  -- 关键：用于匹配精算假设
                risk_code,   -- 备用
                stat_date
            FROM bi_to_cas25.pi_policy_data_info_mon 
            WHERE policy_no = '{policy_no}' 
            ORDER BY stat_date DESC LIMIT 1
        """
        df_data = pd.read_sql_query(data_query, conn)
        if df_data.empty:
            print(f"⚠️  警告: 未找到保单号 {policy_no} 的数据")
        return df_data
    except Exception as e:
        print(f"❌ 读取保单数据失败: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def get_rates(val_month_str):
    """
    从数据库读取指定评估月份的利率曲线
    
    Args:
        val_month_str: 评估月份，格式 'YYYYMM'，例如 '202512'
        
    Returns:
        DataFrame: 包含利率曲线的 DataFrame，字段包括：
            - term_month: 期限（月）
            - forward_disrate_value: 月化远期折现率
    """
    conn = get_db_connection()
    try:
        rates_query = f"""
            SELECT term_month, forward_disrate_value 
            FROM measure_platform.conf_measure_month_disrate
            WHERE val_month = '{val_month_str}'
            ORDER BY term_month
        """
        rates_df = pd.read_sql_query(rates_query, conn)
        if rates_df.empty:
            print(f"⚠️  警告: 未找到 {val_month_str} 的利率曲线数据")
        return rates_df
    except Exception as e:
        print(f"❌ 读取利率曲线失败: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def get_assumptions(class_code, val_month_str, val_method='7', use_db_acquisition_expense=True):
    """
    从数据库读取精算假设
    
    Args:
        class_code: 险类代码（用于匹配精算假设表）
        val_month_str: 评估月份，格式 'YYYYMM'，例如 '202512'
        val_method: 计量方法，默认为 '7'（表示 BBA 方法）
        use_db_acquisition_expense: 是否从数据库读取获取费用率，默认为 True
        
    Returns:
        dict: 包含精算假设的字典，字段包括：
            - loss_ratio: 赔付率
            - indirect_claims_expense_ratio: 间接理赔费用率（ULAE Ratio）
            - maintenance_expense_ratio: 维持费用率
            - ra_ratio: 非金融风险调整因子
            - acquisition_expense_ratio: 获取费用率（如果 use_db_acquisition_expense=True 则从数据库读取）
            
    注意：
        - 如果 use_db_acquisition_expense=False，则 acquisition_expense_ratio 需从代码 Config/Parameter 读取
        - val_method='7' 表示 BBA 计量方法
    """
    conn = get_db_connection()
    try:
        # 构建查询字段
        select_fields = [
            'loss_ratio',
            'indirect_claims_expense_ratio',
            'maintenance_expense_ratio',
            'ra as ra_ratio'  # 非金融风险调整因子
        ]
        
        if use_db_acquisition_expense:
            select_fields.append('acquisition_expense_ratio')
        
        assumptions_query = f"""
            SELECT 
                {', '.join(select_fields)}
            FROM measure_platform.conf_measure_actuarial_assumption
            WHERE class_code = '{class_code}' 
              AND val_month = '{val_month_str}'
              AND val_method = '{val_method}'
            LIMIT 1
        """
        df_assumptions = pd.read_sql_query(assumptions_query, conn)
        
        if df_assumptions.empty:
            print(f"⚠️  警告: 未找到险类 {class_code} 在 {val_month_str} 的精算假设数据")
            print(f"   查询条件: class_code={class_code}, val_month={val_month_str}, val_method={val_method}")
            print(f"   将使用默认值或抛出异常")
            return None
        
        # 转换为字典并确保 Decimal 类型
        assumptions = {
            'loss_ratio': Decimal(str(df_assumptions.iloc[0]['loss_ratio'])),
            'indirect_claims_expense_ratio': Decimal(str(df_assumptions.iloc[0]['indirect_claims_expense_ratio'])),
            'maintenance_expense_ratio': Decimal(str(df_assumptions.iloc[0]['maintenance_expense_ratio'])),
            'ra_ratio': Decimal(str(df_assumptions.iloc[0]['ra_ratio']))
        }
        
        # 如果从数据库读取获取费用率
        if use_db_acquisition_expense:
            assumptions['acquisition_expense_ratio'] = Decimal(str(df_assumptions.iloc[0]['acquisition_expense_ratio']))
        
        return assumptions
        
    except Exception as e:
        print(f"❌ 读取精算假设失败: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()

