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


# %% 3b — RETURN vs RISK, every name ranked
#
# This is the table the workbench was missing. Expected return comes from
# multiple convergence (EPS growth +/- annualized multiple change + yield);
# worst case is the deepest loss across all 10 scenarios for a position held
# on its own. ret/risk is expected return divided by that loss -- a crude
# return-per-unit-of-downside, NOT a Sharpe ratio, because the denominator is
# a scenario rather than a volatility.
#
# "n/a" means the company has no earnings, so there is no P/E to converge.
# That is reported rather than papered over with price-to-sales, which would
# smuggle in a margin assumption without stating it.

from financial_analysis import ESTIMATES  # noqa: E402

_all = {**BOOK, **CANDIDATES}
_rows = []
for _tk, _prof in _all.items():
    _est = ESTIMATES.get(_tk)
    _worst, _wname = min(
        (
            (scenarios.run_scenario(s, {_tk: _prof}, {_tk: 1.0}).portfolio_return, s.name)
            for s in scenarios.SCENARIOS.values()
        ),
        key=lambda x: x[0],
    )
    _ret = _est.total_return if _est and _est.applicable else None
    _rows.append((_tk, _ret, _worst, _wname, _tk in BOOK))

_rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
print(f"{'':<7}{'exp. return':>13}{'worst case':>12}{'ret/risk':>10}  worst scenario")
print("-" * 78)
for _tk, _ret, _worst, _wname, _held in _rows:
    _h = " *" if _held else "  "
    _r = f"{_ret:>12.1%}" if _ret is not None else "         n/a"
    _rr = f"{abs(_ret / _worst):>9.2f}" if _ret is not None and _worst < 0 else "        -"
    print(f"{_tk + _h:<7}{_r}{_worst:>12.1%}{_rr}  {_wname[:34]}")
print("\n  * = currently held")
print("  n/a = no earnings, so multiple convergence does not apply")
print("\n  Every estimate carries a basis string. Read them before trusting the")
print("  ranking:  for tk, e in ESTIMATES.items(): print(tk, e.basis)")


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
    # --- income statement (annualized from Q3 FY2026, first full Ansys qtr) --
    revenue=9_920_000_000,         # Q3 FY26 revenue $2.48B x 4
    revenue_prior=6_990_000_000,   # implied by +42% YoY
    gross_profit=7_600_000_000,    # ESTIMATE
    ebit=3_470_000_000,            # ESTIMATE at ~35% op margin
    net_income=2_400_000_000,      # ESTIMATE
    interest_expense=450_000_000,  # ESTIMATE on $10B of notes
    tax_rate=0.17,                 # effective
    # --- cash flow -----------------------------------------------------------
    cfo=2_800_000_000,             # ESTIMATE
    capex=300_000_000,             # ESTIMATE; EDA is capital-light
    # --- balance sheet: SOURCED from the 10-Q, 31 July 2026 ------------------
    total_debt=10_040_000_000,     # SOURCED: $1.02B short + $9.02B long
    cash=3_610_000_000,            # SOURCED
    equity=31_150_000_000,         # SOURCED
    goodwill=26_800_000_000,       # SOURCED; ~$23.5B of it arrived with Ansys
    # --- shares and price ----------------------------------------------------
    shares_diluted=188_000_000,    # ESTIMATE post-Ansys issuance
    shares_diluted_prior=155_000_000,
    price=400.0,                   # FILL IN current
    wacc=QUALITY_WACC.value(),
    basis={
        "revenue": "Q3 FY2026 $2.48B annualized, SOURCED",
        "cfo": "ESTIMATE - VERIFY from the cash flow statement",
        "total_debt": "10-Q 31 July 2026, SOURCED",
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


# %% 7 — ADD A COMPANY: one block, all three levels of analysis
#
# This replaces editing three separate cells. Fill in ONE block per company
# and analyze() runs the whole stack:
#
#   1. FACTOR EXPOSURES  -> what it does to your portfolio's risk
#   2. FUNDAMENTALS      -> quality scorecard, ROIC vs WACC
#   3. DCF ASSUMPTIONS   -> reverse DCF, intrinsic value, sensitivity
#
# Any of the three can be left as None and that section is skipped. Start with
# exposures only, add the rest as you pull figures from the filings.


def analyze(ticker, exposures=None, fundamentals=None, dcf=None, price=None):
    """Full stack on one company. Skips whatever you have not supplied."""
    if exposures is not None:
        CANDIDATES[ticker] = exposures
        problems = exposures.validate()
        if problems:
            print(f"!! {ticker} factor profile is incomplete:")
            for pr in problems:
                print(f"   {pr}")
            print()
        else:
            report_candidate(book, ticker, contribution)
            print()

    if fundamentals is not None:
        print(evaluate(fundamentals))
        print()

    if dcf is not None:
        if price is None:
            print("DCF skipped: pass price= so upside can be computed.")
        else:
            print(report(dcf, price=price))
            print()


# ===========================================================================
# TEMPLATE — copy this whole block, change MYTICKER, fill in the numbers
# ===========================================================================

MYTICKER = "PLTR"          # <- the ticker
MYPRICE = 0.0              # <- current price. REQUIRED for the DCF.

# --- 1. factor exposures. Thirteen factor names to choose from: -------------
#   ai_capex  semi_rd  china_policy  rates_duration  enterprise_it  ad_cycle
#   regulatory  gov_appropriation  saas_disintermediation
#   digital_services_tax  consumer_spending  commodity_cycle
#   market_volatility  market_beta   <- market_beta is REQUIRED
#
# Beta is an ELASTICITY: 1.0 = full pass-through, negative = position GAINS.
# The third argument is a required basis string, not a comment.

MY_EXPOSURES = ExposureSet(
    ticker=MYTICKER,
    thesis="What it does, who pays, latest hard numbers with their date.",
    exposures=[
        Exposure("enterprise_it", 0.00, "REPLACE: why this number."),
        Exposure("rates_duration", 0.00, "REPLACE: why this number."),
        Exposure("market_beta", 1.00, "REPLACE: why this number."),
    ],
)

# --- 2. fundamentals for the quality scorecard ------------------------------
# Income statement and cash flow from the latest 10-Q or 10-K. Balance sheet
# matters most: without total_debt, cash and equity, ROIC cannot be computed.
# goodwill is optional but IMPORTANT for an acquisitive company -- it splits
# "was the deal worth it" from "is the business good".

MY_FUNDAMENTALS = Fundamentals(
    ticker=MYTICKER,
    revenue=0.0,              # income stmt
    revenue_prior=0.0,        # same quarter a year ago
    gross_profit=0.0,
    ebit=0.0,                 # operating income
    net_income=0.0,
    interest_expense=0.0,
    tax_rate=0.21,            # effective rate
    cfo=0.0,                  # cash flow stmt, operating activities
    capex=0.0,                # purchases of PP&E
    total_debt=0.0,           # balance sheet, short + long
    cash=0.0,                 # cash + short-term investments
    equity=0.0,               # total stockholders' equity
    goodwill=0.0,             # balance sheet; 0 is fine if not acquisitive
    shares_diluted=0.0,
    shares_diluted_prior=0.0,
    price=MYPRICE,
    wacc=QUALITY_WACC.value(),
    basis={"revenue": "SOURCE", "cfo": "SOURCE", "total_debt": "SOURCE"},
)

# --- 3. DCF assumptions for intrinsic value ---------------------------------
# Refuses to run on negative free cash flow, by design: a DCF on a pre-profit
# company values the terminal assumption and nothing else. For those names use
# multiple_convergence() in cell 6 instead.

MY_WACC = WACCInputs(
    risk_free=0.0415,            # 10Y Treasury
    equity_risk_premium=0.045,
    beta=1.00,                   # match market_beta above
    cost_of_debt=0.050,
    tax_rate=0.21,
    debt_weight=0.00,            # debt / (debt + market cap)
    basis="REPLACE: where these came from.",
)

MY_DCF = DCFAssumptions(
    ticker=MYTICKER,
    base_fcf=0.0,                # trailing twelve-month FCF = CFO - capex
    shares_diluted=0.0,
    net_debt=0.0,                # NEGATIVE means net cash
    initial_growth=0.00,         # your year-1 FCF growth view
    terminal_growth=0.03,        # the code rejects anything above ~4%
    years=10,
    wacc=MY_WACC,
    basis={"base_fcf": "SOURCE", "initial_growth": "my estimate",
           "terminal_growth": "~nominal GDP"},
)

# --- run it -----------------------------------------------------------------
# Uncomment once the numbers are real. Passing zeros produces nonsense, which
# is why it ships commented out.
#
# analyze(MYTICKER, MY_EXPOSURES, MY_FUNDAMENTALS, MY_DCF, MYPRICE)
#
# Or run just one level while you are still gathering figures:
#
# analyze(MYTICKER, MY_EXPOSURES)                                  # risk only
# analyze(MYTICKER, None, MY_FUNDAMENTALS)                         # quality only
# analyze(MYTICKER, None, None, MY_DCF, MYPRICE)                   # value only


# %% 8 — Print the research brief for a name I'm studying
print(brief("TICKER"))
