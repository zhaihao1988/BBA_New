"""Actuarial assumption and discount factor loader for FRA engine (Step 2).

This module abstracts access to two critical data sources:
1. Actuarial assumptions (loss ratio, maintenance, claim expense, RA) keyed
   by product/risk code and vintage (valuation month/year).
2. Discount rate curves (locked-in vs current) leveraging existing
   database loaders.

The current implementation provides a mock lookup table so that the rest of
`bba_dev` can be developed without waiting for the real SQL integration.
Once the actual assumption tables are ready, replace the lookup logic inside
``ActuarialAssumptionManager._fetch_from_source``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Optional

import pandas as pd

from BBA_group.data_access import loader as db_loader


@dataclass(frozen=True)
class ActuarialAssumptions:
    """Container for the key ratios used in projection/calibration."""

    loss_ratio: Decimal
    claim_expense_ratio: Decimal
    maintenance_expense_ratio: Decimal
    ra_ratio: Decimal


class ActuarialAssumptionManager:
    """Mocked manager that simulates DB-backed assumption lookup.

    Args:
        default_val_method: Default valuation method code used for DB filters
            once SQL queries are implemented.
    """

    def __init__(self, default_val_method: str = '7') -> None:
        self.default_val_method = default_val_method
        self._cache: Dict[tuple, ActuarialAssumptions] = {}

    def get_assumptions(self, risk_code: str, vintage_date: date | str) -> ActuarialAssumptions:
        """Return assumptions for given risk_code + valuation month.

        The current implementation uses a deterministic fallback table so that
        downstream modules can be unit-tested. Replace `_fetch_from_source`
        with actual SQL later.
        """

        if isinstance(vintage_date, date):
            vintage_key = vintage_date.strftime('%Y%m')
        else:
            vintage_key = str(vintage_date).replace('-', '')[:6]

        cache_key = (risk_code, vintage_key)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._fetch_from_source(risk_code, vintage_key)
        return self._cache[cache_key]

    def _fetch_from_source(self, risk_code: str, vintage_key: str) -> ActuarialAssumptions:
        """Mock implementation returning deterministic ratios."""

        # Basic mocked lookup table; replace with SQL results later.
        ratio_table = {
            '040012': (Decimal('0.55'), Decimal('0.05'), Decimal('0.12'), Decimal('0.03')),
            '040013': (Decimal('0.60'), Decimal('0.06'), Decimal('0.10'), Decimal('0.035')),
        }
        default_ratios = (Decimal('0.50'), Decimal('0.05'), Decimal('0.11'), Decimal('0.03'))
        lr, cer, mer, ra = ratio_table.get(risk_code, default_ratios)
        return ActuarialAssumptions(lr, cer, mer, ra)


def get_discount_factors(curve_type: str, valuation_month: str) -> pd.DataFrame:
    """Load discount curve based on curve_type and valuation month.

    Args:
        curve_type: 'locked' or 'current'. Currently both map to the same
            measure_platform curve, but the explicit argument keeps the API
            forward-compatible once we introduce separate sources.
        valuation_month: YYYYMM string representing either initial recognition
            month (for locked curves) or current reporting month.
    """

    if len(valuation_month) != 6 or not valuation_month.isdigit():
        raise ValueError(f"valuation_month 必须是6位YYYYMM格式, 当前为 {valuation_month}")

    df = db_loader.get_rates(valuation_month)
    if df.empty:
        raise RuntimeError(f"未能获取 {valuation_month} 的利率曲线数据")

    df = df.copy()
    df['curve_type'] = curve_type
    return df


__all__ = [
    'ActuarialAssumptions',
    'ActuarialAssumptionManager',
    'get_discount_factors',
]
