"""
Credit spread curves by rating and maturity, and the arm's-length rate build-up.

    all-in rate = base rate (currency, tenor)
                + credit spread (rating, tenor)
                + adjustments (security, subordination)

Spreads are interpolated in two directions:
* across maturity: linear in log(tenor), so a 4-year loan sits between the
  3- and 5-year points in a way that matches how term structures bend;
* across rating: log-linear between the letter buckets, one third of the
  bucket step per notch (BBB- sits one third of the way from BBB to BB).

Comparable bonds give a second, market-based view: filter the set to the
borrower's rating band and tenor window, then take the interquartile range of
their spreads. That range is the arm's-length range in the OECD sense; the
curve-based point estimate should fall inside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .scorecard import BUCKETS, NOTCHES, notch_index

SECURED_ADJ_BPS = -25        # senior secured: collateral reduces loss given default
SUBORDINATED_ADJ_BPS = +75   # subordinated: paid after senior creditors


def load_curves(path: str | Path = "data/spread_curves.csv") -> pd.DataFrame:
    c = pd.read_csv(path, index_col=0)
    c.columns = c.columns.astype(float)
    return c.loc[BUCKETS]


def load_base_rates(path: str | Path = "data/base_rates.json") -> dict[str, pd.Series]:
    raw = {k: v for k, v in json.load(open(path)).items() if not k.startswith("_")}
    return {ccy: pd.Series({float(t): r / 100 for t, r in pts.items()}).sort_index() for ccy, pts in raw.items()}


def _interp_tenor(series: pd.Series, tenor: float, log_space: bool = False) -> float:
    x = series.index.to_numpy(dtype=float)
    y = series.to_numpy(dtype=float)
    if tenor <= x[0]:
        return float(y[0])
    if tenor >= x[-1]:
        return float(y[-1])
    if log_space:
        return float(np.exp(np.interp(np.log(tenor), np.log(x), np.log(y))))
    return float(np.interp(np.log(tenor), np.log(x), y))


def base_rate(ccy: str, tenor: float, rates: dict[str, pd.Series] | None = None) -> float:
    rates = rates or load_base_rates()
    return _interp_tenor(rates[ccy], tenor)


def spread_bps(rating: str, tenor: float, curves: pd.DataFrame | None = None) -> float:
    """Credit spread in basis points for a notched rating and a tenor in years."""
    curves = curves if curves is not None else load_curves()
    i = notch_index(rating)
    pos = max(0.0, 1 + (i - 2) / 3)             # AAA -> 0 (row 0), AA+ -> 0.67, AA -> 1.0, AA- -> 1.33, A -> 2.0 ...
    pos = min(pos, len(BUCKETS) - 1)
    lo, hi = int(np.floor(pos)), int(np.ceil(pos))
    s_lo = _interp_tenor(curves.iloc[lo], tenor, log_space=True)
    if lo == hi:
        return s_lo
    s_hi = _interp_tenor(curves.iloc[hi], tenor, log_space=True)
    return float(np.exp(np.log(s_lo) + (pos - lo) * (np.log(s_hi) - np.log(s_lo))))


def rating_grid(tenors=(1, 2, 3, 5, 7, 10), curves: pd.DataFrame | None = None) -> pd.DataFrame:
    """Full notch x tenor spread table (bps), for plotting and the Excel sheet."""
    curves = curves if curves is not None else load_curves()
    rows = NOTCHES[:NOTCHES.index("CCC+") + 1]
    return pd.DataFrame({t: [spread_bps(r, t, curves) for r in rows] for t in tenors}, index=rows)


def price_loan(rating: str, ccy: str, tenor: float, secured: bool = False, subordinated: bool = False,
               curves: pd.DataFrame | None = None, rates: dict[str, pd.Series] | None = None) -> dict:
    base = base_rate(ccy, tenor, rates)
    sp = spread_bps(rating, tenor, curves)
    adj = (SECURED_ADJ_BPS if secured else 0) + (SUBORDINATED_ADJ_BPS if subordinated else 0)
    return {"base_rate": base, "spread_bps": sp, "adjustment_bps": adj,
            "all_in_rate": base + (sp + adj) / 1e4}


def comparable_range(bonds: pd.DataFrame, rating: str, tenor: float,
                     rating_band: int = 1, tenor_window: float = 2.0) -> dict:
    """
    Arm's-length range from comparable bonds: same currency assumed, rating
    within +/- `rating_band` notches, maturity within +/- `tenor_window` years.
    Returns the quartiles of the comparable spreads and the set itself.
    """
    i = notch_index(rating)
    idx = bonds["rating"].map(notch_index)
    sel = bonds[(idx.sub(i).abs() <= rating_band) & ((bonds["maturity_years"] - tenor).abs() <= tenor_window)].copy()
    q = sel["spread_bps"].quantile([0.25, 0.5, 0.75]) if len(sel) else pd.Series([np.nan] * 3, index=[0.25, 0.5, 0.75])
    return {"n": int(len(sel)), "q1": float(q[0.25]), "median": float(q[0.5]), "q3": float(q[0.75]), "set": sel}
