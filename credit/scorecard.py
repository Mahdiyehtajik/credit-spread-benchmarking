"""
Ratio-based credit scorecard: financial statements -> synthetic rating.

The approach follows the shape of a rating-agency industrial scorecard: a handful
of ratios, each mapped to a rating bucket by threshold, combined with weights
into one numeric score and translated back to a notched rating.

Rating scale used throughout
----------------------------
21 notches, AAA = 1 ... CCC = 19, CC = 20, C = 21. Each letter bucket (AAA, AA,
A, BBB, BB, B, CCC) spans three notches (+, flat, -), except AAA which is one.
The bucket score is a continuous number in [1, 7] where the integers are the
flat ratings: 1 = AAA, 2 = AA, 3 = A, 4 = BBB, 5 = BB, 6 = B, 7 = CCC. A score
of 4.33 is one third of the way from BBB to BB and rounds to BBB-; 4.67 rounds
to BB+.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

NOTCHES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
           "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C"]
BUCKETS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]


@dataclass(frozen=True)
class Financials:
    revenue: float            # EUR millions
    ebitda: float
    interest_expense: float
    tax_paid: float
    total_debt: float

    @property
    def ratios(self) -> dict[str, float]:
        ffo = self.ebitda - self.interest_expense - self.tax_paid   # funds from operations, simplified
        return {
            "ebitda_margin": self.ebitda / self.revenue,
            "debt_to_ebitda": self.total_debt / self.ebitda,
            "ebitda_to_interest": self.ebitda / self.interest_expense if self.interest_expense > 0 else math.inf,
            "ffo_to_debt": ffo / self.total_debt if self.total_debt > 0 else math.inf,
            "revenue_eur_m": self.revenue,
        }


def load_grid(path: str | Path = "data/scorecard_grid.json") -> dict:
    grid = json.load(open(path))
    w = sum(f["weight"] for f in grid["factors"].values())
    if abs(w - 1.0) > 1e-9:
        raise ValueError(f"factor weights sum to {w}, not 1")
    return grid


def factor_score(x: float, thresholds: list[float], higher_is_better: bool) -> float:
    """
    Map one ratio to a continuous bucket score in [1, 7].

    thresholds[k] is the ratio at which the factor sits squarely in bucket k+1
    (index 0 = AAA, 1 = AA, ...). Between two thresholds the score is
    interpolated linearly; outside the grid it is clipped to 1 or 7.
    """
    t = np.asarray(thresholds, dtype=float)
    if not higher_is_better:
        t = -t
        x = -x
    if x >= t[0]:
        return 1.0
    if x <= t[-1]:
        return 7.0
    # t is strictly decreasing from here; find the bracketing boundaries
    k = int(np.searchsorted(-t, -x, side="right")) - 1       # t[k] >= x > t[k+1]
    lo, hi = t[k + 1], t[k]
    frac = (hi - x) / (hi - lo)                              # 0 at boundary k, 1 at boundary k+1
    return (k + 1) + frac


def bucket_score_to_notch(score: float) -> str:
    """1.0 -> AAA, 1.67 -> AA+, 2.0 -> AA, 2.33 -> AA-, 2.67 -> A+, 3.0 -> A ... 7.0 -> CCC."""
    score = float(np.clip(score, 1.0, 7.0))
    idx = 2 + int(np.floor((score - 2.0) * 3 + 0.5))        # AA is index 2; round half up
    return NOTCHES[min(max(idx, 0), len(NOTCHES) - 1)]


def notch_index(rating: str) -> int:
    return NOTCHES.index(rating)


def shift_notches(rating: str, n: int) -> str:
    """Move a rating n notches (negative = better / towards AAA)."""
    return NOTCHES[min(max(notch_index(rating) + n, 0), len(NOTCHES) - 1)]


def score(fin: Financials, grid: dict | None = None) -> dict:
    """
    Run the scorecard. Returns the per-factor table, the weighted score and the
    stand-alone (unsupported) rating.
    """
    grid = grid or load_grid()
    rows = []
    for name, spec in grid["factors"].items():
        x = fin.ratios[name]
        s = factor_score(x, spec["thresholds"], spec["higher_is_better"])
        rows.append({"factor": name, "value": x, "weight": spec["weight"],
                     "score": s, "notch": bucket_score_to_notch(s),
                     "weighted": spec["weight"] * s})
    table = pd.DataFrame(rows).set_index("factor")
    total = float(table["weighted"].sum())
    return {"table": table, "score": total, "standalone_rating": bucket_score_to_notch(total)}


def with_implicit_support(standalone: str, group_rating: str, max_notches: int) -> tuple[str, int]:
    """
    Group-support notching (OECD TPG Chapter X, para 10.76 ff.): a subsidiary's
    rating can be lifted towards the group rating by up to `max_notches`, but
    never above the group's own rating.
    """
    gap = notch_index(standalone) - notch_index(group_rating)      # > 0 means subsidiary is weaker
    lift = int(np.clip(gap, 0, max_notches))
    return shift_notches(standalone, -lift), lift
