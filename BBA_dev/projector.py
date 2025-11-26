"""
Cash flow projection engine for Full Retrospective Approach (Step 3).

This module focuses on single-policy projection with special logic for
extended warranty business:
- Insurer's effective risk period starts after the manufacturer's warranty
  (`warranty_end_date`), so expected claims/expenses are zero before that date.
- Premium amortisation for monthly earned premium uses the number of months in
  the risk period (warranty_end_date -> end_date).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, List, Mapping, Optional

import pandas as pd


def _to_date(value: Optional[object]) -> Optional[date]:
    """Convert pandas Timestamp/str/date to date."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, str):
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    raise ValueError(f"无法识别的日期类型: {type(value)}")


def _months_between(start: date, end: date) -> int:
    """Compute whole months between two dates (exclusive of start month)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _month_range(start: date, end: date) -> Iterable[date]:
    """Generate first day of months from start to end inclusive."""
    start_month = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    for ts in pd.date_range(start=start_month, end=end_month, freq="MS"):
        yield ts.date()


@dataclass
class CashFlowProjector:
    """Project policy-level cash flows under FRA rules."""

    def project_policy_flows(
        self,
        policy_row: Mapping[str, object],
        assumptions: object,
    ) -> pd.DataFrame:
        """
        Build monthly cash flow series for a single policy.

        Args:
            policy_row: Mapping/Series containing premium, dates, iacf, etc.
            assumptions: object with attributes loss_ratio, claimant expense
                ratio, maintenance_expense_ratio.

        Returns:
            DataFrame with columns [Year, Month, YYYYMM, Premium, IACF,
            Claims, Expenses]
        """

        premium = Decimal(str(policy_row.get("sum_premium_no_tax", 0) or policy_row.get("premium", 0) or 0))
        iacf_amount = Decimal(str(policy_row.get("iacf_amount", 0) or 0))

        start_date = _to_date(policy_row.get("start_date"))
        end_date = _to_date(policy_row.get("end_date"))
        uw_date = _to_date(policy_row.get("under_write_date"))
        warranty_end = _to_date(policy_row.get("warranty_end_date")) or start_date

        if not all([start_date, end_date, uw_date]):
            raise ValueError("缺少必要的起期/止期/签单日期信息。")

        # timeline start ensures we capture pre-risk months (e.g., manufacturing warranty)
        timeline_start = min(filter(None, [start_date, uw_date]))

        # Determine risk period: only after warranty_end_date
        risk_start = warranty_end or start_date
        risk_end = end_date
        risk_start_month = date(risk_start.year, risk_start.month, 1)
        risk_end_month = date(risk_end.year, risk_end.month, 1)
        coverage_months = _months_between(risk_start_month, risk_end_month) + 1
        monthly_earned = (
            (premium / Decimal(coverage_months)) if coverage_months > 0 else Decimal("0")
        )

        loss_ratio = Decimal(str(getattr(assumptions, "loss_ratio")))
        claim_exp_ratio = Decimal(str(getattr(assumptions, "claim_expense_ratio", 0)))
        maint_ratio = Decimal(str(getattr(assumptions, "maintenance_expense_ratio", 0)))

        records: List[dict] = []
        for month_date in _month_range(timeline_start, end_date):
            yyyymm = f"{month_date.year}{month_date.month:02d}"
            premium_inflow = Decimal("0")
            iacf_outflow = Decimal("0")

            if month_date.year == uw_date.year and month_date.month == uw_date.month:
                premium_inflow = premium
                iacf_outflow = iacf_amount

            in_risk_period = (month_date >= risk_start_month) and (month_date <= risk_end_month)
            if in_risk_period and monthly_earned > 0:
                claims = monthly_earned * loss_ratio * (Decimal("1") + claim_exp_ratio)
                expenses = monthly_earned * maint_ratio
            else:
                claims = Decimal("0")
                expenses = Decimal("0")

            records.append(
                {
                    "Year": month_date.year,
                    "Month": month_date.month,
                    "YYYYMM": yyyymm,
                    "Premium": float(premium_inflow),
                    "IACF": float(iacf_outflow),
                    "Claims": float(claims),
                    "Expenses": float(expenses),
                }
            )

        return pd.DataFrame(records)


if __name__ == "__main__":
    # Sample test based on user-provided extended warranty scenario
    from types import SimpleNamespace

    sample_policy = pd.Series(
        {
            "premium": 24000,
            "iacf_amount": 0,
            "under_write_date": "2023-01-01",
            "start_date": "2023-01-01",
            "warranty_end_date": "2023-12-31",
            "end_date": "2025-12-31",
        }
    )
    sample_assump = SimpleNamespace(
        loss_ratio=Decimal("0.5"),
        claim_expense_ratio=Decimal("0.0"),
        maintenance_expense_ratio=Decimal("0.0"),
    )

    projector = CashFlowProjector()
    df = projector.project_policy_flows(sample_policy, sample_assump)
    print(df)

