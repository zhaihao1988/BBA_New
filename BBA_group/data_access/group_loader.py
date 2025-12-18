"""
组维度数据加载器 (Group Data Loader)

按group_id分组加载保单数据
"""

from typing import Optional, List, Dict
import pandas as pd
from BBA_group.data_access.db_utils import get_sa_engine
from sqlalchemy import text


def load_policies_by_group(
    group_id: str,
    run_date: Optional[str] = None,
    val_method: Optional[str] = '7',
    status: Optional[str] = None
) -> pd.DataFrame:
    """
    按group_id加载组内所有保单数据
    
    Args:
        group_id: 合同分组编码
        run_date: 运行批次（可选）
        val_method: 评估方法（默认'7'）
        status: 状态筛选（可选）
        
    Returns:
        pd.DataFrame: 组内所有保单的数据
    """
    engine = get_sa_engine('qa')
    try:
        filters = []
        params = {}
        
        filters.append("group_id = :group_id")
        params['group_id'] = group_id
        
        if run_date:
            filters.append("run_date = :run_date")
            params['run_date'] = run_date
        
        if val_method:
            filters.append("val_method = :val_method")
            params['val_method'] = val_method
        
        if status:
            filters.append("is_status = :status")
            params['status'] = status
        
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
                is_status,
                warranty_end_date
            FROM zh.t_pp_jl_contract
            WHERE {' AND '.join(filters)}
            ORDER BY under_write_date, policy_no, certi_no
        """
        
        with engine.connect() as conn:
            df = pd.read_sql_query(
                text(data_query),
                conn,
                params=params
            )
        
        if df.empty:
            print(f"⚠️  警告: group_id={group_id}, run_date={run_date}, val_method={val_method} 未检索到合同数据")
        
        return df
    except Exception as exc:
        print(f"❌ 读取 zh.t_pp_jl_contract 失败 (group_id={group_id}): {exc}")
        return pd.DataFrame()


def get_group_policy_data(
    group_id: str,
    policy_no: str,
    certi_no: Optional[str] = None,
    val_method: str = '7',
    run_date: str = '202412'
) -> pd.DataFrame:
    """
    获取组内指定保单的数据
    
    Args:
        group_id: 合同分组编码
        policy_no: 保单号
        certi_no: 批单号（可选）
        val_method: 评估方法
        run_date: 运行批次
        
    Returns:
        pd.DataFrame: 保单数据
    """
    engine = get_sa_engine('qa')
    try:
        filters = []
        params = {}
        
        filters.append("group_id = :group_id")
        params['group_id'] = group_id
        
        filters.append("policy_no = :policy_no")
        params['policy_no'] = policy_no
        
        filters.append("val_method = :val_method")
        params['val_method'] = val_method
        
        filters.append("run_date = :run_date")
        params['run_date'] = run_date
        
        if certi_no is None:
            filters.append("(certi_no IS NULL OR certi_no = '' OR COALESCE(certi_no::text, '') = '')")
        else:
            filters.append("certi_no = :certi_no")
            params['certi_no'] = certi_no
        
        data_query = f"""
            SELECT 
                premium_cny AS sum_premium_no_tax,
                under_write_date, 
                start_date, 
                end_date, 
                warranty_end_date,
                class_code,
                risk_code,
                run_date,
                group_id,
                portfolio_id
            FROM zh.t_pp_jl_contract 
            WHERE {' AND '.join(filters)}
            LIMIT 1
        """
        
        with engine.connect() as conn:
            df_data = pd.read_sql_query(text(data_query), conn, params=params)
        
        if df_data.empty:
            print(f"⚠️  警告: 未找到保单号 {policy_no} 的数据（group_id={group_id}, certi_no={certi_no}, val_method={val_method}, run_date={run_date}）")
        
        return df_data
    except Exception as e:
        print(f"❌ 读取保单数据失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def load_group_full_data(
    group_id: str,
    run_date: Optional[str] = None,
    val_method: Optional[str] = '7'
) -> pd.DataFrame:
    """
    加载组内所有保单的完整数据（包含IACF）
    
    Args:
        group_id: 合同分组编码
        run_date: 运行批次（可选）
        val_method: 评估方法（默认'7'）
        
    Returns:
        pd.DataFrame: 组内所有保单的完整数据
    """
    # 先加载保单数据
    policy_df = load_policies_by_group(group_id, run_date, val_method)
    
    if policy_df.empty:
        return policy_df.assign(iacf_amount=0)
    
    # 加载IACF数据
    engine = get_sa_engine('qa')
    try:
        iacf_query = """
            SELECT "保单号" AS policy_no,
                   "批单号" AS certi_no,
                   SUM(COALESCE("合计费用", 0)) AS iacf_amount
            FROM zh.summary_iacf_cost
            GROUP BY "保单号", "批单号"
        """
        
        with engine.connect() as conn:
            iacf_df = pd.read_sql_query(text(iacf_query), conn)
        
        if iacf_df.empty:
            print("⚠️ qa.summary_iacf_cost 没有记录，默认 IACF=0。")
            policy_df['iacf_amount'] = 0
            return policy_df
        
        # 合并IACF数据
        policy_df['certi_no_for_merge'] = policy_df['certi_no'].fillna('').astype(str)
        iacf_df['certi_no_for_merge'] = iacf_df['certi_no'].fillna('').astype(str)
        
        merged_df = policy_df.merge(
            iacf_df,
            on=['policy_no', 'certi_no_for_merge'],
            how='left'
        )
        merged_df['iacf_amount'] = merged_df['iacf_amount'].fillna(0)
        merged_df = merged_df.drop(columns=['certi_no_for_merge'])
        
        return merged_df
    except Exception as exc:
        print(f"❌ 加载IACF数据失败: {exc}")
        policy_df['iacf_amount'] = 0
        return policy_df

