"""
Run the full benchmarking on a case file and write every output to outputs/.

    python run.py                      # illustrative case in data/base_case.json
    python run.py data/my_borrower.json
"""
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from credit import (Financials, load_grid, score, with_implicit_support, load_curves, load_base_rates,
                    rating_grid, price_loan, comparable_range, write_workbook, verify_against_python)

case = json.load(open(Path(sys.argv[1] if len(sys.argv) > 1 else "data/base_case.json")))
grid = load_grid()
curves = load_curves()
out = Path("outputs"); out.mkdir(exist_ok=True)

# ---- 1. Scorecard -> stand-alone rating -> supported rating
fin = Financials(**{k: case[k] for k in ("revenue", "ebitda", "interest_expense", "tax_paid", "total_debt")})
res = score(fin, grid)
sup, lift = with_implicit_support(res["standalone_rating"], case["group_rating"], case["implicit_support_notches"])
print(f"Borrower: {case['borrower']}  (lender {case['lender']}, {case['currency']} {case['principal']:,.0f}m, {case['tenor_years']}y)\n")
print(res["table"].round(3).to_string())
print(f"\nWeighted score        {res['score']:.2f}")
print(f"Stand-alone rating    {res['standalone_rating']}")
print(f"Group rating          {case['group_rating']}  -> implicit support lift {lift} notch(es)")
print(f"Supported rating      {sup}")
res["table"].round(4).to_csv(out / "scorecard.csv")

# ---- 2. Spread curves: notch x tenor
g = rating_grid(curves=curves)
g.round(1).to_csv(out / "spread_grid.csv")
fig, ax = plt.subplots(figsize=(8, 4.5))
for rt, color in zip(["AAA", "AA", "A", "BBB", "BB", "B", "CCC+"], plt.cm.viridis(np.linspace(0, 0.95, 7))):
    ax.plot(g.columns, g.loc[rt], marker="o", label=rt, color=color)
ax.set_xlabel("tenor (years)"); ax.set_ylabel("spread (bps)"); ax.set_yscale("log")
ax.set_title("Credit spread curves by rating (illustrative)"); ax.legend(ncol=4, fontsize=8)
fig.tight_layout(); fig.savefig(out / "spread_curves.png", dpi=150)

# ---- 3. Curve-based rate build-up
px = price_loan(sup, case["currency"], case["tenor_years"], case["secured"], case["subordinated"], curves)
print(f"\nBase rate ({case['currency']} {case['tenor_years']}y)   {px['base_rate']:.3%}")
print(f"Credit spread ({sup})  {px['spread_bps']:.0f} bps")
print(f"Adjustments            {px['adjustment_bps']:+.0f} bps")
print(f"All-in rate            {px['all_in_rate']:.3%}")

# ---- 4. Market check: interquartile range of comparable bonds
bonds = pd.read_csv("data/comparable_bonds.csv")
cmp = comparable_range(bonds, sup, case["tenor_years"])
cmp["set"].to_csv(out / "comparables_selected.csv", index=False)
inside = cmp["q1"] <= px["spread_bps"] <= cmp["q3"]
print(f"\nComparable bonds (rating +/-1 notch, tenor +/-2y): n = {cmp['n']}")
print(f"Interquartile range    {cmp['q1']:.0f} - {cmp['q3']:.0f} bps (median {cmp['median']:.0f})")
print(f"Curve-based spread {'inside' if inside else 'OUTSIDE'} the arm's-length range")
fig, ax = plt.subplots(figsize=(8, 4.5))
sel = cmp["set"]
ax.scatter(bonds["maturity_years"], bonds["spread_bps"], color="#bfbfbf", s=25, label="all bonds")
ax.scatter(sel["maturity_years"], sel["spread_bps"], color="#2e75b6", s=35, label="comparable set")
ax.axhspan(cmp["q1"], cmp["q3"], color="#2e75b6", alpha=0.12, label="interquartile range")
ax.scatter([case["tenor_years"]], [px["spread_bps"]], color="#c55a11", s=90, marker="D", zorder=5, label=f"tested loan ({sup})")
ax.set_xlabel("maturity (years)"); ax.set_ylabel("spread (bps)")
ax.set_title("Arm's-length range from comparable bonds"); ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(out / "comparables.png", dpi=150)

# ---- 5. Sensitivity: rate across one-notch moves and tenors
sens = pd.DataFrame({t: [price_loan(r, case["currency"], t, case["secured"], case["subordinated"], curves)["all_in_rate"]
                         for r in [with_implicit_support(res["standalone_rating"], case["group_rating"], n)[0] for n in range(0, 4)]]
                     for t in (3, 5, 7, 10)},
                    index=[f"lift {n}" for n in range(0, 4)])
sens.to_csv(out / "sensitivity_lift_x_tenor.csv")
print("\nAll-in rate: implicit-support lift (rows) x tenor (cols)\n", (sens * 100).round(2).to_string())

# ---- 6. Excel with live formulas
summary = {"borrower": case["borrower"], "standalone_rating": res["standalone_rating"], "supported_rating": sup,
           "base_rate": px["base_rate"], "spread_bps": px["spread_bps"], "all_in_rate": px["all_in_rate"],
           "comparable_n": cmp["n"], "iqr_bps": [cmp["q1"], cmp["q3"]], "inside_range": bool(inside)}
json.dump(summary, open(out / "summary.json", "w"), indent=2)
xlsx = write_workbook(case, grid, out / "credit_benchmark.xlsx", curves)
chk = verify_against_python(xlsx, case, grid)
print(f"\nWrote {xlsx}" + ("  (formulas verified against Python)" if chk["checked"] else ""))
