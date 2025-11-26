"""Data loader for Full Retrospective Approach (Step 1).

This module consolidates contract data (zh.t_pp_jl_contract) with
policy-level acquisition cash flow (IACF) data (qa.summary_iacf_cost).

The goal is to provide a single DataFrame that contains, per policy,
all attributes needed for downstream projection along with actual
acquisition costs sourced from the QA environment.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple
import pandas as pd
from sqlalchemy import text

from BBA_dev.data_access.db_utils import get_sa_engine


def _build_where_clause(
    run_date: Optional[str],
    val_method: Optional[str],
    unit_ids: Optional[Sequence[str]]
) -> Tuple[str, Dict[str, str]]:
    clauses = []
    params: Dict[str, str] = {}
    if run_date:
        params["run_date"] = run_date
        clauses.append("run_date = :run_date")
    if val_method:
        params["val_method"] = val_method
        clauses.append("val_method = :val_method")
    if unit_ids:
        placeholders = []
        for idx, unit_id in enumerate(unit_ids):
            key = f"unit_{idx}"
            params[key] = unit_id
            placeholders.append(f":{key}")
        clauses.append(f"unit_id IN ({', '.join(placeholders)})")

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)
    return where_sql, params


def load_full_data(
    run_date: Optional[str] = None,
    val_method: Optional[str] = None,
    unit_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Load policy + IACF data from QA database.

    Args:
        run_date: Optional run batch (e.g., '202412').
        val_method: Optional valuation method filter (e.g., '7' for BBA).
        unit_ids: Optional list of unit_ids for debugging.
        limit: Optional LIMIT for contract fetch.

    Returns:
        DataFrame containing contract-level data enriched with IACF amounts.
    """

    where_sql, params = _build_where_clause(run_date, val_method, unit_ids)
    limit_sql = f" LIMIT {int(limit)}" if limit else ""

    policy_query = f"""
        SELECT *
        FROM zh.t_pp_jl_contract
        {where_sql}
        {limit_sql}
    """

    # 修复：IACF查询需要同时按保单号和批单号分组，以正确匹配批单的IACF
    iacf_query = """
        SELECT "保单号" AS policy_no,
               "批单号" AS certi_no,
               SUM(COALESCE("合计费用", 0)) AS iacf_amount
        FROM zh.summary_iacf_cost
        GROUP BY "保单号", "批单号"
    """

    engine = get_sa_engine('qa')
    with engine.connect() as conn:
        policy_df = pd.read_sql_query(text(policy_query), conn, params=params or None)
        if policy_df.empty:
            print("⚠️ 未在 zh.t_pp_jl_contract 中查询到符合条件的数据。")
            return policy_df.assign(iacf_amount=0)

        iacf_df = pd.read_sql_query(text(iacf_query), conn)

    if iacf_df.empty:
        print("⚠️ qa.summary_iacf_cost 没有记录，默认 IACF=0。")
        policy_df['iacf_amount'] = 0
        return policy_df

    # 修复：合并时需要同时匹配policy_no和certi_no
    # 处理certi_no为NULL的情况（主单）
    # 将certi_no统一转换为字符串，NULL转换为空字符串用于匹配
    policy_df['certi_no_for_merge'] = policy_df['certi_no'].fillna('').astype(str)
    iacf_df['certi_no_for_merge'] = iacf_df['certi_no'].fillna('').astype(str)
    
    merged = policy_df.merge(
        iacf_df[['policy_no', 'certi_no_for_merge', 'iacf_amount']],
        how='left',
        left_on=['policy_no', 'certi_no_for_merge'],
        right_on=['policy_no', 'certi_no_for_merge']
    )
    merged = merged.drop(columns=['certi_no_for_merge'])
    merged['iacf_amount'] = merged['iacf_amount'].fillna(0)

    # 简单校验：确认未丢失合同记录
    if len(merged) != len(policy_df):
        raise RuntimeError("合并后合同数量变化，请检查 join 逻辑。")

    return merged


__all__ = ["load_full_data"]
