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


# %% 4 — COMPANY QUALITY. Settle this before caring what it is worth.
#
# The five questions: does it create value (ROIC vs WACC), is the growth real
# (FCF conversion), can it survive (leverage, coverage), am I being diluted,
# and what am I paying.
#
# ROIC vs WACC is the one that matters. A business earning 8% on capital that
# costs 9% destroys value every time it reinvests, and growth makes it worse.
# A low multiple on a negative spread is a value trap with a tidy ratio.

from financial_analysis import Fundamentals, evaluate  # noqa: E402

QUALITY_WACC = WACCInputs(
    risk_free=0.0415,
    equity_risk_premium=0.045,
    beta=1.05,
    cost_of_debt=0.055,
    tax_rate=0.21,
    debt_weight=0.15,
    basis="rf = 10Y Nov 2026. ERP 4.5%. Beta from factors.py.",
)

SNPS_FUNDAMENTALS = Fundamentals(
    ticker="SNPS",
    # --- income statement -------------------------------------------------
    revenue=8_700_000_000,
    revenue_prior=7_100_000_000,
    gross_profit=6_700_000_000,
    ebit=1_900_000_000,            # operating income
    net_income=1_400_000_000,
    interest_expense=450_000_000,
    tax_rate=0.17,                 # effective rate, not statutory
    # --- cash flow statement ---------------------------------------------
    cfo=2_300_000_000,
    capex=300_000_000,
    # --- balance sheet ----------------------------------------------------
    total_debt=10_000_000_000,
    cash=4_500_000_000,
    equity=19_000_000_000,
    # --- shares and price -------------------------------------------------
    shares_diluted=188_000_000,
    shares_diluted_prior=155_000_000,
    price=400.0,
    wacc=QUALITY_WACC.value(),
    basis={
        "revenue": "APPROXIMATE post-Ansys. REPLACE from the 10-K.",
        "cfo": "APPROXIMATE. REPLACE.",
        "total_debt": "APPROXIMATE Ansys financing. REPLACE.",
    },
)

print(evaluate(SNPS_FUNDAMENTALS))


# %% 4b — WATCHLIST QUALITY COMPARISON
#
# RKLB, SPCX, NVDA, AMD, LUNR, IONQ.
#
# WHAT IS FILLED IN AND WHAT IS NOT
# ---------------------------------
# Income-statement and cash-flow figures below are SOURCED from the quarters
# noted. BALANCE-SHEET fields are left at 0.0 because I do not have them, and
# inventing them would silently corrupt the ROIC line -- the single most
# important number in the scorecard.
#
# Left at 0.0, invested capital computes as zero and validate() says so
# explicitly rather than printing a confident wrong answer. Fill in
# total_debt, cash and equity from each 10-Q balance sheet and ROIC starts
# working. Three numbers per company.
#
# Watch what happens to IONQ. Its GAAP net income is positive and the
# scorecard still condemns it, which is the entire reason FCF conversion is
# in there.

WATCHLIST = {
    "NVDA": Fundamentals(
        ticker="NVDA",
        revenue=96_220_000_000,          # Q2 FY2027
        revenue_prior=46_740_000_000,    # implied by +106% YoY
        gross_profit=69_280_000_000,     # ~72% margin, ESTIMATE
        ebit=59_660_000_000,             # ~62% op margin, ESTIMATE
        net_income=50_000_000_000,       # ESTIMATE
        cfo=55_000_000_000,              # ESTIMATE
        capex=3_500_000_000,             # ESTIMATE
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=24_400_000_000,
        shares_diluted_prior=24_800_000_000,
        price=180.0,                     # FILL IN current
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q2 FY2027 release, SOURCED",
               "cfo": "ESTIMATE - VERIFY",
               "total_debt": "NOT FILLED IN"},
    ),
    "AMD": Fundamentals(
        ticker="AMD",
        revenue=13_400_000_000,          # Q3 2026, SOURCED
        revenue_prior=9_240_000_000,     # implied by +45% YoY
        gross_profit=7_370_000_000,      # ~55% margin, ESTIMATE
        ebit=2_900_000_000,              # ESTIMATE
        net_income=3_400_000_000,        # non-GAAP $2.09/sh x ~1.63B, ESTIMATE
        cfo=3_600_000_000,               # ESTIMATE
        capex=500_000_000,               # ESTIMATE
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=1_630_000_000,
        shares_diluted_prior=1_640_000_000,
        price=585.30,                    # 12 Nov 2026, SOURCED
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q3 2026 8-K, SOURCED",
               "cfo": "ESTIMATE - VERIFY",
               "total_debt": "NOT FILLED IN"},
    ),
    "SPCX": Fundamentals(
        ticker="SPCX",
        revenue=14_600_000_000,          # Q3 2026, SOURCED
        revenue_prior=5_590_000_000,     # implied by +161% YoY
        gross_profit=5_800_000_000,      # ESTIMATE
        ebit=4_800_000_000,              # ESTIMATE
        net_income=4_400_000_000,        # Q3 2026, SOURCED
        cfo=5_000_000_000,               # ESTIMATE
        capex=36_000_000_000,            # Q4 GUIDED $35-40B. ~250% of revenue.
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=13_700_000_000,   # ESTIMATE from ~$1.9T at ~$139
        shares_diluted_prior=13_500_000_000,
        price=139.0,
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q3 2026, SOURCED", "cfo": "ESTIMATE",
               "total_debt": "NOT FILLED IN"},
    ),
    "RKLB": Fundamentals(
        ticker="RKLB",
        revenue=267_800_000,             # Q3 2026, SOURCED
        revenue_prior=154_800_000,       # implied by +73% YoY
        gross_profit=87_000_000,         # ESTIMATE
        ebit=-70_000_000,                # ESTIMATE
        net_income=-79_700_000,          # Q3 2026, SOURCED
        cfo=-40_000_000,                 # ESTIMATE
        capex=30_000_000,                # ESTIMATE
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=510_000_000,
        shares_diluted_prior=490_000_000,
        price=54.97,                     # 9 Nov 2026 after hours, SOURCED
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q3 2026, SOURCED", "cfo": "ESTIMATE",
               "total_debt": "NOT FILLED IN"},
    ),
    "LUNR": Fundamentals(
        ticker="LUNR",
        revenue=269_000_000,             # Q3 2026, SOURCED
        revenue_prior=165_000_000,       # ESTIMATE
        gross_profit=69_000_000,         # Q3 2026, SOURCED (26% margin)
        ebit=5_000_000,                  # adj EBITDA +$8M, SOURCED-ish
        net_income=-4_020_000,           # Q3 2026, SOURCED
        cfo=66_000_000,                  # Q3 2026, SOURCED
        capex=33_000_000,                # Q3 2026, SOURCED. FCF = 66 - 33 = 33.
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=160_000_000,
        shares_diluted_prior=140_000_000,
        price=12.0,                      # FILL IN current
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q3 2026, SOURCED", "cfo": "CFO $66M SOURCED. But CFO credited working-capital timing and customer advances on a backlog that went 213M->1.9B. YTD FCF ~-$112M.",
               "total_debt": "NOT FILLED IN"},
    ),
    "IONQ": Fundamentals(
        ticker="IONQ",
        revenue=173_800_000,             # Q3 2026, SOURCED, +336% YoY
        revenue_prior=39_900_000,        # implied by +336%
        gross_profit=70_000_000,         # ESTIMATE
        ebit=-433_000_000,               # Q3 2026 operating loss, SOURCED
        net_income=564_000_000,          # GAAP, SOURCED -- see below
        cfo=-190_000_000,                # 9mo -$570M / 3, ESTIMATE
        capex=25_000_000,                # ESTIMATE
        total_debt=0.0, cash=0.0, equity=0.0,          # FILL IN
        shares_diluted=397_000_000,      # ESTIMATE from $1.42 EPS
        shares_diluted_prior=300_000_000,
        price=60.0,                      # FILL IN current
        wacc=QUALITY_WACC.value(),
        basis={"revenue": "Q3 2026, SOURCED",
               "cfo": "9-month -$570M, SOURCED; quarterly ESTIMATE",
               "total_debt": "NOT FILLED IN"},
    ),
}

# --- the comparison -------------------------------------------------------
print("WATCHLIST — what the income statement says\n")
hdr = (
    f"{'':<7}{'revenue $m':>13}{'growth':>9}{'op mgn':>9}"
    f"{'FCF $m':>13}{'FCF/NI':>9}"
)
print(hdr)
print("-" * len(hdr))
for tk, f in WATCHLIST.items():
    conv = f.fcf_conversion
    # None means net income was negative, so the ratio is meaningless rather
    # than bad. LUNR is the case that matters: positive FCF with a small loss
    # is a GOOD sign this particular check cannot express.
    conv_s = "n/a" if conv is None else f"{conv:.2f}"
    print(
        f"{tk:<7}{f.revenue / 1e6:>13,.0f}{f.revenue_growth:>9.0%}"
        f"{f.operating_margin:>9.1%}{f.fcf / 1e6:>13,.0f}{conv_s:>9}"
    )

print("\n\nFull scorecard for each:\n")
for tk in WATCHLIST:
    print(evaluate(WATCHLIST[tk]))
    print()


# %% 5 — Intrinsic value (DCF). Replace the numbers from the 10-K.
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


# %% 6 — Multiple convergence. Three inputs, no terminal assumption.
# Start here, not with the DCF. Both inputs are observable.
for target in (18, 22, 26):
    print(
        multiple_convergence(
            "SNPS", eps_growth=0.22, current_multiple=22.5, target_multiple=target
        )
    )


# %% 7 — Add a company of my own
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


# %% 8 — Print the research brief for a name I'm studying
print(brief("TICKER"))
