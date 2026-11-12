"""
My analysis — personal workbench. Edit this freely; it is yours.
================================================================

SETUP (once)
------------
1. Rename the big generated file to have NO SPACES:

       Financial Analysis.py   ->   financial_analysis.py

   Python cannot import a module whose name contains a space, so
   `from Financial Analysis import *` is a syntax error with no workaround.

2. Put this file in the SAME folder.

3. Open THIS file in Spyder and press F5.

WHY A SEPARATE FILE
-------------------
`financial_analysis.py` is generated. Re-download it and anything you wrote
inside is gone. This file is never generated and never overwritten, so your
work survives every update. Keep your assumptions, your companies and your
valuations here.

HOW TO USE IT
-------------
F5 runs everything top to bottom. Ctrl+Enter runs just the cell your cursor is
in, which is what you want most of the time: change one number, re-run one
cell, see what moved.
"""

from __future__ import annotations

from pathlib import Path

# Everything from the generated file. The `if __name__ == "__main__"` guard
# inside it means importing does NOT trigger a full report -- you get the
# functions and the data, and you decide what to run.
from financial_analysis import *  # noqa: F401,F403
from financial_analysis import (
    CANDIDATES,
    BOOK,
    DCFAssumptions,
    Exposure,
    ExposureSet,
    WACCInputs,
    brief,
    load_book,
    main,
    multiple_convergence,
    report,
    report_candidate,
)

# Underscore-prefixed names are skipped by `import *`, so this one is explicit.
# It writes a starter portfolio.json if none exists. Needed here because the
# generated file only calls it under `if __name__ == "__main__"`, which does
# not fire when the module is imported.
from financial_analysis import _ensure_portfolio

PORTFOLIO = _ensure_portfolio()


# %% 1 — Full portfolio review
main(["--portfolio", str(PORTFOLIO)])


# %% 2 — Test candidates against my book
# Any ticker in CANDIDATES. Prints only the candidate section, not the
# whole report, which is what you want when comparing several.

book, contribution, _ = load_book(PORTFOLIO)

for ticker in ["CME", "RKLB", "LUNR"]:
    report_candidate(book, ticker, contribution)


# %% 3 — Side-by-side: what each candidate does to my worst case
import pandas as pd  # noqa: E402

from financial_analysis import risk, scenarios  # noqa: E402

TARGET = 5_000.0
weights = book.weights()
rows = {"current": risk.factor_concentration(BOOK, weights).loadings}
worst = {"current": scenarios.run_all(BOOK, weights)[0].portfolio_return}

for ticker, profile in CANDIDATES.items():
    merged = {**BOOK, ticker: profile}
    scale = book.equity_value / (book.equity_value + TARGET)
    hypothetical = {t: w * scale for t, w in weights.items()}
    hypothetical[ticker] = TARGET / (book.equity_value + TARGET)
    rows[ticker] = risk.factor_concentration(merged, hypothetical).loadings
    worst[ticker] = scenarios.run_all(merged, hypothetical)[0].portfolio_return

table = pd.DataFrame(rows).fillna(0.0).round(2)
table.loc[">> WORST SCENARIO"] = pd.Series(worst).round(3)
print(table.to_string())
print("\nSorted by worst case, best first:")
for t, v in sorted(worst.items(), key=lambda kv: -kv[1]):
    print(f"  {t:<10} {v:>7.1%}{'   <- current book' if t == 'current' else ''}")


# %% 4 — Intrinsic value (DCF). Replace the numbers from the 10-K.
GOOGL_WACC = WACCInputs(
    risk_free=0.0415,
    equity_risk_premium=0.045,
    beta=1.00,
    cost_of_debt=0.045,
    tax_rate=0.21,
    debt_weight=0.05,
    basis="rf = 10Y Treasury Nov 2026. ERP 4.5% Damodaran. Beta from factors.",
)

GOOGL_DCF = DCFAssumptions(
    ticker="GOOGL",
    base_fcf=72_000_000_000,        # cash flow stmt: CFO minus capex
    shares_diluted=12_100_000_000,  # income stmt: diluted shares
    net_debt=-80_000_000_000,       # NEGATIVE means net cash
    initial_growth=0.12,
    terminal_growth=0.03,           # ~nominal GDP; the code rejects >4%
    years=10,
    wacc=GOOGL_WACC,
    basis={
        "base_fcf": "REPLACE from the 10-K",
        "initial_growth": "my estimate",
        "terminal_growth": "~nominal GDP",
    },
)

print(report(GOOGL_DCF, price=290.0))


# %% 5 — Multiple convergence. Three inputs, no terminal assumption.
# Start here, not with the DCF. Both inputs are observable.
for target in (18, 22, 26):
    print(
        multiple_convergence(
            "SNPS", eps_growth=0.22, current_multiple=22.5, target_multiple=target
        )
    )


# %% 6 — Add a company of my own
# Factor names: ai_capex, semi_rd, china_policy, rates_duration, enterprise_it,
# ad_cycle, regulatory, gov_appropriation, saas_disintermediation,
# digital_services_tax, consumer_spending, market_volatility, market_beta
#
# market_beta is REQUIRED. Every exposure needs a non-empty basis string.
# Beta is an elasticity: 1.0 = full pass-through, negative = position GAINS.

CANDIDATES["TICKER"] = ExposureSet(
    ticker="TICKER",
    thesis="What it does, who pays, latest hard numbers with their date.",
    exposures=[
        Exposure("consumer_spending", 0.00, "Why this number."),
        Exposure("regulatory", 0.00, "Why this number."),
        Exposure("rates_duration", 0.00, "Why this number."),
        Exposure("market_beta", 1.00, "Why this number."),
    ],
)

# report_candidate(book, "TICKER", contribution)


# %% 7 — Print the research brief for a name I'm studying
print(brief("TICKER"))
