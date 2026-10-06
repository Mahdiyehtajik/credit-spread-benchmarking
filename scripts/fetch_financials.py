"""
Build a case file for a listed borrower from its last annual statements.

    pip install yfinance
    python scripts/fetch_financials.py SAP.DE > data/sap.json

Only the five scorecard inputs are pulled. Group rating, tenor, security and
currency are judgement calls and are left for you to fill in.
"""
import json, sys
import yfinance as yf

ticker = sys.argv[1]
t = yf.Ticker(ticker)
fin, bs = t.financials, t.balance_sheet
col = fin.columns[0]
def g(df, *names):
    for n in names:
        if n in df.index and df.loc[n, col] == df.loc[n, col]:
            return float(df.loc[n, col])
    return None
fx = 1e6
case = {
    "_note": f"{ticker}, fiscal year {col.year}, from yfinance; statement currency in millions",
    "borrower": t.info.get("longName", ticker), "lender": "<fill in>", "currency": "EUR",
    "principal": 50.0, "tenor_years": 5,
    "revenue": g(fin, "Total Revenue") / fx,
    "ebitda": g(fin, "EBITDA", "Normalized EBITDA") / fx,
    "interest_expense": abs(g(fin, "Interest Expense") or 0) / fx,
    "tax_paid": (g(fin, "Tax Provision") or 0) / fx,
    "total_debt": g(bs, "Total Debt") / fx,
    "group_rating": "<fill in>", "implicit_support_notches": 2, "secured": False, "subordinated": False,
}
print(json.dumps(case, indent=2))
