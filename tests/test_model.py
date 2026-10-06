import json
import numpy as np
import pandas as pd
import pytest

from credit import (Financials, load_grid, score, factor_score, bucket_score_to_notch, with_implicit_support,
                    load_curves, spread_bps, base_rate, price_loan, comparable_range, NOTCHES)


def case():
    return json.load(open("data/base_case.json"))


def fin():
    c = case()
    return Financials(**{k: c[k] for k in ("revenue", "ebitda", "interest_expense", "tax_paid", "total_debt")})


def test_ratios_by_hand():
    r = fin().ratios
    assert r["ebitda_margin"] == pytest.approx(120 / 1200)
    assert r["debt_to_ebitda"] == pytest.approx(480 / 120)
    assert r["ffo_to_debt"] == pytest.approx((120 - 22 - 18) / 480)


def test_factor_score_hits_integers_at_thresholds():
    t = [25, 15, 9, 5, 3, 1.5, 0.75]
    for k, v in enumerate(t):
        assert factor_score(v, t, True) == pytest.approx(k + 1)
    assert factor_score(12, t, True) == pytest.approx(2.5)      # halfway between AA (15) and A (9)
    assert factor_score(100, t, True) == 1.0 and factor_score(0.1, t, True) == 7.0


def test_lower_is_better_direction():
    t = [0.5, 1.0, 1.75, 2.75, 4.0, 5.5, 7.5]
    assert factor_score(0.2, t, False) == 1.0
    assert factor_score(4.0, t, False) == pytest.approx(5.0)
    assert factor_score(6.0, t, False) > factor_score(3.0, t, False)


def test_score_to_notch():
    assert bucket_score_to_notch(1.0) == "AAA"
    assert bucket_score_to_notch(2.0) == "AA"
    assert bucket_score_to_notch(4.33) == "BBB-"
    assert bucket_score_to_notch(4.67) == "BB+"
    assert bucket_score_to_notch(7.0) == "CCC"


def test_weights_sum_to_one_and_score_is_weighted_average():
    g = load_grid()
    res = score(fin(), g)
    assert res["score"] == pytest.approx((res["table"]["weight"] * res["table"]["score"]).sum())


def test_implicit_support_never_exceeds_group():
    assert with_implicit_support("BB+", "A-", 2) == ("BBB", 2)
    assert with_implicit_support("BBB", "BBB+", 3) == ("BBB+", 1)     # capped at the group rating
    assert with_implicit_support("A", "BBB", 3) == ("A", 0)           # stronger than the group: no lift


def test_spread_monotone_in_rating_and_tenor():
    c = load_curves()
    s = [spread_bps(r, 5, c) for r in NOTCHES[:17]]
    assert all(np.diff(s) > 0)
    assert spread_bps("BBB", 10, c) > spread_bps("BBB", 2, c)
    assert spread_bps("BBB", 5, c) == pytest.approx(170)             # grid point reproduced exactly
    assert spread_bps("BBB", 4, c) == pytest.approx(np.exp(np.interp(np.log(4), np.log([3, 5]), np.log([135, 170]))))


def test_rate_build_up_adds_up():
    p = price_loan("BBB", "EUR", 5, secured=True)
    assert p["base_rate"] == pytest.approx(0.0255)
    assert p["all_in_rate"] == pytest.approx(p["base_rate"] + (p["spread_bps"] + p["adjustment_bps"]) / 1e4)
    assert p["adjustment_bps"] == -25


def test_comparable_range_filters_and_orders():
    bonds = pd.read_csv("data/comparable_bonds.csv")
    r = comparable_range(bonds, "BBB", 5)
    assert r["n"] == len(r["set"]) > 0
    assert set(r["set"]["rating"]) <= {"BBB+", "BBB", "BBB-"}
    assert (r["set"]["maturity_years"].between(3, 7)).all()
    assert r["q1"] <= r["median"] <= r["q3"]
