import pandas as pd
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import text

from BBA_dev.data_access.db_utils import get_sa_engine


def get_policy_data(policy_no, certi_no=None, val_method='7', run_date='202412'):
    """
    从数据库读取保单基础数据（从zh.t_pp_jl_contract表）
    
    Args:
        policy_no: 保单号
        certi_no: 批单号（可选，默认为None，查询主单）
        val_method: 计量方法（默认'7'，表示BBA方法）
        run_date: 运行批次（默认'202412'）
        
    Returns:
        DataFrame: 包含保单信息的 DataFrame，字段包括：
            - sum_premium_no_tax: 签单保费（不含税，映射自premium_cny）
            - under_write_date: 签单日期
            - start_date: 起保日期
            - end_date: 终保日期
            - warranty_end_date: 保修结束日期
            - class_code: 险类代码（用于匹配精算假设）
            - risk_code: 险种代码（备用）
            - run_date: 运行批次
    """
    engine = get_sa_engine('qa')  # 改为qa数据库
    try:
        # 构建查询条件
        where_conditions = [
            f"policy_no = '{policy_no}'",
            f"val_method = '{val_method}'",
            f"run_date = '{run_date}'"
        ]
        
        if certi_no is None:
            where_conditions.append("certi_no IS NULL")
        else:
            where_conditions.append(f"certi_no = '{certi_no}'")
        
        where_clause = " AND ".join(where_conditions)
        
        data_query = f"""
            SELECT 
                premium_cny AS sum_premium_no_tax,  -- 保费字段映射
                under_write_date, 
                start_date, 
                end_date, 
                warranty_end_date,  -- 保修结束日期
                class_code,  -- 关键：用于匹配精算假设
                risk_code,   -- 备用
                run_date      -- 运行批次（替代stat_date）
            FROM zh.t_pp_jl_contract 
            WHERE {where_clause}
            LIMIT 1
        """
        with engine.connect() as conn:
            df_data = pd.read_sql_query(text(data_query), conn)
        if df_data.empty:
            print(f"⚠️  警告: 未找到保单号 {policy_no} 的数据（查询条件: certi_no={certi_no}, val_method={val_method}, run_date={run_date}）")
        return df_data
    except Exception as e:
        print(f"❌ 读取保单数据失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
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
    engine = get_sa_engine('test')
    try:
        rates_query = f"""
            SELECT term_month, forward_disrate_value 
            FROM measure_platform.conf_measure_month_disrate
            WHERE val_month = '{val_month_str}'
            ORDER BY term_month
        """
        with engine.connect() as conn:
            rates_df = pd.read_sql_query(text(rates_query), conn)
        if rates_df.empty:
            print(f"⚠️  警告: 未找到 {val_month_str} 的利率曲线数据")
        return rates_df
    except Exception as e:
        print(f"❌ 读取利率曲线失败: {e}")
        return pd.DataFrame()
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
    engine = get_sa_engine('test')
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
        with engine.connect() as conn:
            df_assumptions = pd.read_sql_query(text(assumptions_query), conn)
        
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


def get_contracts(run_date: str, val_method: str = '7', status: str | None = '1'):
    """
    从 QA 数据库 zh.t_pp_jl_contract 读取指定 run_date/val_method 的合同明细

    Args:
        run_date: 运行批次 (YYYYMM)
        val_method: 计量方法，默认为 '7'
        status: 是否限定 is_status 字段，默认只取 '1'（有效）

    Returns:
        DataFrame: 包含合同明细的 DataFrame
    """
    engine = get_sa_engine('qa')
    try:
        filters = ["run_date = %s", "val_method = %s"]
        params = [run_date, val_method]
        if status:
            filters.append("is_status = %s")
            params.append(status)

        data_query = f"""
            SELECT
                policy_no,
                certi_no,
                business_type,
                present_flag,
                class_code,
                risk_code,
                com_code,
                business_nature,
                planrevise_flag,
                under_write_date,
                stat_date,
                premium,
                currency,
                premium_cny,
                appli_type_stat,
                unit_id,
                min_unit_id,
                insrisk_flag,
                portfolio,
                portfolio_id,
                group_id,
                val_method,
                profit_loss,
                ini_confirm,
                record_date,
                pay_rate_gd,
                invest_prop,
                invest_date,
                start_date,
                end_date,
                car_kind_code,
                use_nature_code,
                policy_period,
                revise_flag,
                run_date,
                coverage_segment,
                warranty_period,
                valid_date,
                plan_date,
                certi_write_date,
                warranty_end_date
            FROM zh.t_pp_jl_contract
            WHERE {' AND '.join(filters)}
        """
        with engine.connect() as conn:
            df = pd.read_sql_query(text(data_query), conn, params=dict(zip([f"p{i}" for i in range(len(params))], params)))
        if df.empty:
            print(f"⚠️  警告: run_date={run_date}, val_method={val_method} 未检索到合同数据")
        return df
    except Exception as exc:
        print(f"❌ 读取 zh.t_pp_jl_contract 失败: {exc}")
        return pd.DataFrame()
def get_all_policy_numbers(run_date: str = '202412', val_method: str = '7') -> list[str]:
    """
    获取指定批次下所有需要计算的保单号列表。

    仅查询 policy_no 字段以减少 IO。
    """
    engine = get_sa_engine('qa')
    try:
        query = """
            SELECT policy_no
            FROM zh.t_pp_jl_contract
            WHERE run_date = :run_date
              AND val_method = :val_method
        """
        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), conn, params={"run_date": run_date, "val_method": val_method})
        if df.empty:
            print(f"⚠️  警告: run_date={run_date}, val_method={val_method} 未检索到保单号")
            return []
        return df['policy_no'].dropna().astype(str).tolist()
    except Exception as exc:
        print(f"❌ 获取保单号列表失败: {exc}")
        return []


def get_all_policy_entries(run_date: str = '202412', val_method: str = '7') -> List[Tuple[str, Optional[str]]]:
    """
    获取保单号与批单号组合，供批处理使用。
    """
    engine = get_sa_engine('qa')
    try:
        query = """
            SELECT policy_no, certi_no
            FROM zh.t_pp_jl_contract
            WHERE run_date = :run_date
              AND val_method = :val_method
        """
        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), conn, params={"run_date": run_date, "val_method": val_method})
        if df.empty:
            print(f"⚠️  警告: run_date={run_date}, val_method={val_method} 未检索到保单/批单组合")
            return []
        entries: List[Tuple[str, Optional[str]]] = []
        for _, row in df.iterrows():
            policy_no = str(row['policy_no'])
            certi_value = row.get('certi_no')
            certi_no = str(certi_value) if certi_value and not pd.isna(certi_value) else None
            entries.append((policy_no, certi_no))
        return entries
    except Exception as exc:
        print(f"❌ 获取保单/批单组合失败: {exc}")
        return []

