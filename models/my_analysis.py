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
    Fundamentals,
    WACCInputs,
    brief,
    evaluate,
    load_book,
    main,
    multiple_convergence,
    report,
    report_candidate,
    reverse_dcf,
)

# Underscore-prefixed names are skipped by `import *`, so this one is explicit.
# It writes a starter portfolio.json if none exists. Needed here because the
# generated file only calls it under `if __name__ == "__main__"`, which does
# not fire when the module is imported.
from financial_analysis import _ensure_portfolio

PORTFOLIO = _ensure_portfolio()


# %% 0 — IMPORT FROM FIDELITY.  Run this cell first, after a fresh export.
#
# Fidelity: Positions > Download. Put the path below.
# Nothing is uploaded anywhere. portfolio.json is gitignored.
#
# Use a RAW string (the r before the quote) so Windows backslashes are not
# read as escape characters -- r"C:\Users\..." works, "C:\Users\..." does not.

FIDELITY_CSV = r"C:\Users\HomePC\Downloads\Portfolio_Positions_Nov-17-2026.csv"

# theme and sleeve are judgments no export contains, so set them here once.
# A ticker missing from this map imports as UNCLASSIFIED and the scenario
# engine will refuse to run until it is classified -- an unclassified holding
# is an unmeasured risk.
MY_THEMES = {
    "GOOGL": ("ai_platform", "core"),
    "SNPS": ("eda", "core"),
    "NOW": ("ai_platform", "core"),
    "SPCX": ("space", "core"),
    "AMD": ("ai_hardware", "satellite"),
    "CORT": ("non_correlated", "core"),
}

import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

from financial_analysis import read_positions, merge_into_portfolio  # noqa: E402

_csv = _Path(FIDELITY_CSV)
if not _csv.exists():
    print(f"not found: {_csv}")
    print("Update FIDELITY_CSV above with the real path, then re-run this cell.")
else:
    _holdings, _cash, _notes = read_positions(_csv, "fidelity")
    print(f"Read {len(_holdings)} holdings and ${_cash:,.2f} of cash\n")
    for _h in sorted(_holdings, key=lambda h: -h.market_value):
        _pl = _h.market_value - _h.cost_basis
        print(f"  {_h.ticker:<7}{_h.shares:>11,.3f} sh  ${_h.market_value:>10,.2f}"
              f"   cost ${_h.cost_basis:>9,.2f}   {_pl:>+10,.2f}"
              f"  {_pl / _h.cost_basis if _h.cost_basis else 0:>+7.1%}")
    for _n in _notes:
        print(f"  note: {_n}")

    for _n in merge_into_portfolio(_holdings, _cash, PORTFOLIO):
        print(f"  ! {_n}")

    # Restore the judgments the export cannot carry.
    _d = _json.loads(PORTFOLIO.read_text())
    for _row in _d["positions"]:
        if _row["ticker"] in MY_THEMES:
            _row["theme"], _row["sleeve"] = MY_THEMES[_row["ticker"]]
    PORTFOLIO.write_text(_json.dumps(_d, indent=2) + "\n")

    _tc = sum(h.cost_basis for h in _holdings)
    _tm = sum(h.market_value for h in _holdings)
    print(f"\n  cost ${_tc:,.2f}   market ${_tm:,.2f}   "
          f"unrealized {_tm - _tc:+,.2f} ({_tm / _tc - 1:+.1%})")
    print(f"  wrote {PORTFOLIO}")


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

from financial_analysis import ESTIMATES, years_to_recover  # noqa: E402

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
print(f"{'':<7}{'exp. return':>13}{'worst case':>12}{'ret/risk':>10}"
      f"{'recover':>10}  worst scenario")
print("-" * 88)
for _tk, _ret, _worst, _wname, _held in _rows:
    _h = " *" if _held else "  "
    _r = f"{_ret:>12.1%}" if _ret is not None else "         n/a"
    _rr = f"{abs(_ret / _worst):>9.2f}" if _ret is not None and _worst < 0 else "        -"
    _yr = years_to_recover(_ret, _worst) if _ret is not None else None
    _ys = f"{_yr:>8.1f}y" if _yr is not None else "       -"
    print(f"{_tk + _h:<7}{_r}{_worst:>12.1%}{_rr}{_ys}  {_wname[:34]}")
print("\n  * = currently held")
print("  n/a = no earnings, so multiple convergence does not apply")
print("""
  READ 'recover' BEFORE 'ret/risk'. ret/risk divides an ANNUAL rate by a
  ONE-TIME loss, so it is not dimensionless and no textbook threshold
  applies to it -- there is no "strong" value, only a rank order inside
  this one scenario set. It also contains no risk-free rate, so unlike a
  Sharpe ratio it never asks whether the risk is paid for at all.

  'recover' puts both numbers in the same unit: years of compounding to
  climb back out of the worst case. Against a ten-year horizon, FIVE is
  the line -- past it, one bad event eats half the runway.

  The two metrics do not even agree on order. Where they conflict, the
  years column is the one that means something.""")
print("\n  Every estimate carries a basis string. Read them before trusting the")
print("  ranking:  for tk, e in ESTIMATES.items(): print(tk, e.basis)")


# %% 3c — FULL RANKING: return per unit of downside, and valuation sensitivity
#
# Two tables. The first ranks every name on expected return against its own
# worst case. The second shows what each earns if its multiple lands at
# various points in ten years -- which is the honest form of intrinsic value
# for most of these, because a DCF needs balance-sheet figures that are not
# available for twenty companies and inventing them would be worse than
# leaving the number uncomputed.
#
# Note how often market_beta is the dominant factor. For most of these names
# the biggest single risk is not the thesis -- it is simply owning equities.

_allp = {**BOOK, **CANDIDATES}
_rk = []
for _tk, _prof in _allp.items():
    _e = ESTIMATES.get(_tk)
    _res = sorted(
        ((scenarios.run_scenario(s, {_tk: _prof}, {_tk: 1.0}).portfolio_return, s.name)
         for s in scenarios.SCENARIOS.values()),
        key=lambda x: x[0],
    )
    _dom = max(_prof.as_map().items(), key=lambda kv: abs(kv[1]))
    _rk.append({
        "tk": _tk, "ret": _e.total_return if _e and _e.applicable else None,
        "worst": _res[0][0], "second": _res[1][0], "wsc": _res[0][1],
        "dom": _dom, "held": _tk in BOOK,
    })

for _r in _rk:
    _r["yrs"] = (years_to_recover(_r["ret"], _r["worst"])
                 if _r["ret"] is not None else None)

# Sorted by RECOVERY TIME, not by ret/risk. See the note in cell 3b: the
# ratio divides an annual rate by a one-time loss and the two orderings
# genuinely differ. A name with None never recovers, so it sorts last.
_rated = sorted((r for r in _rk if r["ret"] is not None),
                key=lambda r: (r["yrs"] is None, r["yrs"] or 0.0))
_unrated = sorted((r for r in _rk if r["ret"] is None), key=lambda r: -r["worst"])

print("=" * 92)
print("RANKED BY YEARS TO RECOVER THE WORST CASE  (names with earnings)")
print("=" * 100)
print(f"{'':<3}{'':<7}{'exp ret':>9}{'worst':>8}{'2nd worst':>11}{'ret/risk':>10}"
      f"{'recover':>10}  dominant factor")
print("-" * 100)
for _i, _r in enumerate(_rated, 1):
    _h = "*" if _r["held"] else " "
    _d = f"{_r['dom'][0]} {_r['dom'][1]:+.2f}"
    _y = _r["yrs"]
    _ys = f"{_y:>8.1f}y" if _y is not None else "   never"
    _mark = "  <<<" if _y is not None and _y > 5.0 else ""
    print(f"{_i:<3}{_r['tk'] + _h:<7}{_r['ret']:>9.1%}{_r['worst']:>8.1%}"
          f"{_r['second']:>11.1%}{abs(_r['ret'] / _r['worst']):>10.2f}{_ys}  {_d}{_mark}")
print("\n  <<< = over 5 years to recover: one bad event costs half a 10-year horizon.")

print("\n" + "=" * 92)
print("NO EARNINGS — downside only, least bad first. No return is computable.")
print("=" * 92)
for _i, _r in enumerate(_unrated, 1):
    _h = "*" if _r["held"] else " "
    _d = f"{_r['dom'][0]} {_r['dom'][1]:+.2f}"
    print(f"{_i:<3}{_r['tk'] + _h:<7}{'n/a':>9}{_r['worst']:>8.1%}"
          f"{_r['second']:>11.1%}{'-':>10}  {_d}")
print("\n  * = currently held")

print("\n\n" + "=" * 88)
print("VALUATION SENSITIVITY — annualized return if the multiple lands at X")
print("=" * 88)
print(f"{'':<7}{'EPS gr':>8}{'now':>7}  {'-40%':>8}{'-25%':>8}{'flat':>8}{'+15%':>8}   assumed")
print("-" * 88)
for _r in _rated:
    _e = ESTIMATES[_r["tk"]]
    _cm = _e.current_multiple
    _cells = [
        multiple_convergence(_r["tk"], _e.eps_growth, _cm, _cm * m).total_return
        + _e.dividend_yield
        for m in (0.60, 0.75, 1.00, 1.15)
    ]
    print(f"{_r['tk']:<7}{_e.eps_growth:>8.0%}{_cm:>7.1f}"
          + "".join(f"{x:>8.1%}" for x in _cells)
          + f"   {_e.target_multiple:.0f}x")
print("\n  Dividend included. Both inputs observable: check EPS growth against")
print("  guidance and the multiple against a decade of history.")


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


# %% 7b — SCAFFOLD A NEW TICKER.  Name it; the facts get fetched.
#
# This is as far as automation honestly goes. It fills in every field that is
# a FACT -- revenue, earnings, cash flow, balance sheet, share count, straight
# from the company's own SEC XBRL filings -- and marks every field that is a
# JUDGMENT with REPLACE.
#
# The split is not arbitrary. A filing says what a company earned. It cannot
# say whether the moat holds for ten years, whose budget the revenue comes out
# of, or what multiple it deserves. Those are the inputs that drive the output,
# and a tool that guessed at them would hand you confident numbers with
# nothing behind them.
#
# Needs network. If it fails, run fetch_main(["--check"]) to see which
# endpoint is unreachable.

NEW_TICKER = "CORT"   # any US-listed ticker; the CIK is looked up

from financial_analysis import scaffold, fetch_main  # noqa: E402

print(scaffold(NEW_TICKER))

# Copy the output into cell 7, fill in every REPLACE, then run it.
# A ticker with no CIK on file prints the EDGAR lookup link instead.
#
# Just the raw figures, without the scaffolding:
#   fetch_main(["--facts", NEW_TICKER])


# %% 7c — CORT.  Facts sourced 17 Nov 2026; judgments marked and defended.
#
# CORT is ALREADY in the engine -- CANDIDATES["CORT"] and ESTIMATES["CORT"]
# were written when you put it on the watchlist. So this cell does NOT
# redefine them. What was missing is the two blocks below: the quality
# scorecard and the intrinsic value.
#
# PERIOD CONVENTION: trailing twelve months, Q4 2025 through Q3 2026.
# Not an annualized quarter. CORT's quarters are too uneven to annualize --
# revenue ran 202 -> 165 -> 256 -> 340 -- so multiplying any one of them by
# four would be wrong by 30% in either direction.

# make the cell runnable on its own, without cell 2
if "book" not in globals():
    book, contribution, _ = load_book(PORTFOLIO)

# WACC first, because both blocks below use it. Beta 0.75 matches
# market_beta in CANDIDATES["CORT"]; debt_weight 0 because there is no debt --
# $9.0M of finance leases against a $9.2B market cap rounds to nothing.
# This is CORT's own cost of capital, not the generic QUALITY_WACC from cell 4,
# so this cell runs on its own with Ctrl+Enter.

CORT_WACC = WACCInputs(
    risk_free=0.0415,
    equity_risk_premium=0.045,
    beta=0.75,
    cost_of_debt=0.050,
    tax_rate=0.14,
    debt_weight=0.00,
    basis="rf = 10Y Nov 2026. ERP 4.5% Damodaran. Beta 0.75 = market_beta "
          "from the factor profile: reimbursed, non-discretionary demand.",
)

CORT_FUNDAMENTALS = Fundamentals(
    ticker="CORT",
    # --- income statement, TTM Q4'25-Q3'26 ----------------------------------
    revenue=963_647_000,        # 202.1 + 164.9 + 256.1 + 340.5
    revenue_prior=741_172_000,  # 181.9 + 157.2 + 194.4 + 207.6  -> +30.0%
    gross_profit=949_550_000,   # 98.5% margin. A pill, not a device.
    ebit=110_910_000,           # 4.5 - 49.6 + 41.3 + 114.7
    net_income=162_005_000,     # 24.3 - 31.2 + 42.1 + 126.8
    interest_expense=0.0,       # SOURCED: no interest expense in any quarter
    tax_rate=0.14,              # JUDGMENT -- see note below
    # --- cash flow, same TTM window -----------------------------------------
    cfo=198_110_000,            # 38.4 - 16.8 + 33.5 + 142.9
    capex=3_488_000,            # 0.05 + 0.2 + 2.5 + 0.7.  Capital-light.
    # --- balance sheet, 30 Sep 2026 -----------------------------------------
    total_debt=8_991_000,       # finance-lease obligations. NO borrowings.
    cash=662_307_000,           # 98.7 cash + 272.0 short-term + 291.6 long-term
    equity=833_740_000,
    goodwill=0.0,               # SOURCED: never made an acquisition
    # --- shares and price ----------------------------------------------------
    shares_diluted=125_523_000,        # $126.778M NI / $1.01 reported dil. EPS
    shares_diluted_prior=122_925_000,  # $19.668M / $0.16  -> +2.1% dilution
    price=72.94,                       # 13 Nov 2026 close. REPLACE with live.
    wacc=CORT_WACC.value(),
    basis={
        "revenue": "TTM Q4'25-Q3'26, SOURCED from quarterly filings",
        "cfo": "TTM, SOURCED. capex $3.5M on $964M of revenue.",
        "total_debt": "30 Sep 2026, SOURCED: finance leases only, no debt",
        "cash": "JUDGMENT: includes $291.6M of LONG-TERM investments as "
                "cash-like. They are marketable securities, not operating "
                "assets. Excluding them lifts invested capital to $472M and "
                "cuts ROIC from ~53% to ~20% -- still far above WACC, so the "
                "conclusion does not turn on this choice.",
        "tax_rate": "JUDGMENT: 14%, the blended effective rate for 2023-24 "
                    "(13.5%). The TTM figure is a net tax BENEFIT of $37.3M, "
                    "driven by stock-comp windfalls, and using it would "
                    "produce a NOPAT above pre-tax income. Not sustainable.",
    },
)

print(evaluate(CORT_FUNDAMENTALS))

# --- intrinsic value --------------------------------------------------------
CORT_DCF = DCFAssumptions(
    ticker="CORT",
    base_fcf=194_622_000,       # CFO 198.1 - capex 3.5
    shares_diluted=125_523_000,
    net_debt=-653_316_000,      # 9.0 debt - 662.3 cash. NEGATIVE = net cash.
    initial_growth=0.20,        # JUDGMENT. The whole answer sits here.
    terminal_growth=0.03,
    years=10,
    wacc=CORT_WACC,
    basis={
        "base_fcf": "TTM CFO less capex, SOURCED",
        "initial_growth": "JUDGMENT, 20%. FY2026 revenue is guided to "
                          "$1.1-1.2B against 2025's $761M (+48%), and Lifyorli "
                          "added $91.4M in its second full quarter. 20% fading "
                          "to 3% is well BELOW the current ramp and "
                          "deliberately EXCLUDES the 17 Dec 2026 Cushing's "
                          "PDUFA, which management frames as a $3-5B revenue "
                          "case. If you want that in, raise this -- but then "
                          "you are underwriting a binary event 30 days out.",
        "terminal_growth": "~nominal GDP",
    },
)

print(report(CORT_DCF, price=72.94))

# --- READING THE OUTPUT: two numbers above will mislead you -----------------
#
# 1. "Operating margin 11.5% [WEAK]" is an artefact of the window, not the
#    business. Q1 2026 carried $145.4M of SG&A against $164.9M of revenue and
#    posted a $49.6M operating LOSS, which drags the TTM figure down. Q3 2026
#    on its own: $114.7M of EBIT on $340.5M of revenue = 33.7%. Before you
#    accept 11.5%, find out what that Q1 charge was -- if it recurs the 11.5%
#    is the truth and the 33.7% is the artefact. I have not established which.
#
# 2. "P/E 56.5x" here vs "current_multiple=20.0" in ESTIMATES["CORT"] is not a
#    contradiction, it is two bases. 56.5x is TTM: $9.16B over $162.0M of
#    trailing net income, which includes the Q1 loss. 20x is the run rate:
#    Q3's $126.8M annualized is ~$507M, and $9.16B over that is 18x. Cell 3b
#    ranks CORT on the run rate; this cell scores it on the trailing year.
#    Neither is wrong. Quote the basis whenever you quote the number.
#
# 3. The reverse DCF is the line that matters: the price requires +18.5% and
#    the cell assumes +20.0%. That is 1.5 points of cushion on a 10-year
#    forecast -- i.e. CORT is priced roughly FAIRLY for the two drugs it
#    already sells. You are not being handed a discount for the 17 Dec PDUFA;
#    you are being asked to pay full price for the base business and take the
#    binary event for free. Whether that is a good trade depends on the odds
#    you put on approval, which is a judgment no cell in this file makes.


# %% 7d — GEV (GE Vernova).  Facts 18 Nov 2026. Read the warnings first.
#
# Exposures and the return estimate are already in the engine -- see
# CANDIDATES["GEV"] and ESTIMATES["GEV"]. This cell adds the scorecard and the
# valuation, and the valuation is the interesting part because IT DOES NOT
# RESOLVE.
#
# PERIOD: trailing twelve months, Q4 2025 through Q3 2026.
#
# TWO REPORTED FIGURES ARE TRAPS, and both would make GEV look cheap:
#
#   TTM GAAP net income is $10.37B. About $7.1B of that is non-recurring:
#   a ~$4.5B pre-tax remeasurement gain on buying the remaining 50% of
#   Prolec GE in Q1 2026, and a $2.57B tax benefit in Q4 2025. GAAP EPS in
#   Q1 was $17.44 against $1.98 adjusted. Using TTM GAAP gives a P/E of
#   20.8x on a company that is not earning anything like that.
#
#   TTM free cash flow is $17.1B. All of FY2025 was $3.7B. A 4.6x jump on
#   17% revenue growth is not an earnings story -- current liabilities
#   exceed current assets by $11.8B, so customers are pre-paying for a
#   $197B order book. That cash is real and it is spendable. It is not
#   profit, and it stops the quarter order growth stops.
#
# net_income below is therefore DERIVED, not reported. Operating income plus
# net interest, taxed at 25%. Say so to anyone you show this to.

GEV_WACC = WACCInputs(
    risk_free=0.0415,
    equity_risk_premium=0.045,
    beta=1.30,
    cost_of_debt=0.050,
    tax_rate=0.25,
    debt_weight=0.015,          # $2.83B debt against a $215B market cap
    basis="rf = 10Y Nov 2026. ERP 4.5% Damodaran. Beta 1.30 = market_beta "
          "from the factor profile: capital goods, cyclical order book.",
)

GEV_FUNDAMENTALS = Fundamentals(
    ticker="GEV",
    # --- income statement, TTM Q4'25-Q3'26, $ thousands ---------------------
    revenue=44_041_000_000,        # 10,956 + 9,339 + 11,104 + 12,642
    revenue_prior=37_679_000_000,  # 10,558 + 8,041 + 9,111 + 9,969 -> +16.9%
    gross_profit=9_570_000_000,
    ebit=2_829_000_000,            # 601 + 179 + 655 + 1,394. SOURCED.
    net_income=2_542_000_000,      # DERIVED, not reported -- see header
    interest_expense=120_000_000,  # ESTIMATE on $2.83B of notes
    tax_rate=0.25,                 # JUDGMENT: Q3'26 actual 27.7%, FY24 12.6%
    # --- cash flow, same window ---------------------------------------------
    cfo=19_217_000_000,            # SOURCED. See trap #2 before using it.
    capex=2_101_000_000,           # SOURCED
    # --- balance sheet, 30 Sep 2026 -----------------------------------------
    total_debt=2_826_000_000,
    cash=16_764_000_000,           # net CASH of $13.94B
    equity=11_382_000_000,
    goodwill=9_609_000_000,        # was $4.44B. Prolec consolidation.
    shares_diluted=268_400_000,    # $1,291M NI / $4.81 reported diluted EPS
    shares_diluted_prior=275_600_000,  # $452M / $1.64 -> count FELL 2.6%
    price=803.13,                  # 13 Nov 2026. REPLACE with live.
    wacc=GEV_WACC.value(),
    basis={
        "revenue": "TTM Q4'25-Q3'26, SOURCED from quarterly filings",
        "net_income": "DERIVED: EBIT $2,829M + net interest ~$560M, taxed at "
                      "25%. TTM GAAP is $10,368M and ~$7.1B of that is the "
                      "Prolec remeasurement gain plus a Q4'25 tax benefit. "
                      "Reporting GAAP here would give a 20.8x P/E on earnings "
                      "the company did not earn.",
        "cfo": "SOURCED $19,217M. NOT owner earnings. FY2025 CFO was $4,988M. "
               "The difference is progress payments on a $197B backlog after a "
               "quarter of $29.3B of orders (+96% organic). Verify against the "
               "10-Q cash flow statement: look for 'contract liabilities' and "
               "'progress collections'. I could not reach the filing.",
        "total_debt": "30 Sep 2026, SOURCED",
        "equity": "SOURCED $11,382M. NOTE: goodwill $9,609M plus intangibles "
                  "$4,343M exceeds it, so TANGIBLE equity is NEGATIVE ~$2.6B "
                  "against $62.5B of current liabilities.",
    },
)

print(evaluate(GEV_FUNDAMENTALS))

# --- VALUATION: deliberately not a single number ----------------------------
# A DCF needs one base_fcf and that is exactly the number in dispute. So run
# the reverse DCF across every defensible definition and look at the spread.
# This is the honest output for GEV: a range, and the range is enormous.

GEV_FCF_CASES = {
    "reported TTM FCF":        19_217_000_000 - 2_101_000_000,   # $17.1B
    "FY2026 guided FCF (mid)": 16_500_000_000,
    "FY2025 actual FCF":        4_988_000_000 - 1_277_000_000,   # $3.7B
    "NOPAT + D&A - capex":      2_829_000_000 * 0.75 + 1_428_000_000
                                - 2_101_000_000,                 # $1.4B
}

print("=" * 76)
print("GEV REVERSE DCF — what the price requires, by FCF definition")
print("=" * 76)
print(f"{'basis':<26}{'base FCF':>12}{'implied 10y growth':>22}")
print("-" * 76)
for _label, _fcf in GEV_FCF_CASES.items():
    _a = DCFAssumptions(
        ticker="GEV", base_fcf=_fcf, shares_diluted=268_400_000,
        net_debt=2_826_000_000 - 16_764_000_000,
        initial_growth=0.15, terminal_growth=0.03, years=10, wacc=GEV_WACC,
        basis={"base_fcf": _label, "initial_growth": "placeholder; the reverse "
               "DCF solves for this, so the value here is not used"},
    )
    try:
        _g = reverse_dcf(_a, 803.13)
        print(f"{_label:<26}{_fcf/1e9:>11,.1f}B{_g:>21.1%}")
    except ValueError as _e:
        print(f"{_label:<26}{_fcf/1e9:>11,.1f}B   not solvable in range")
print("-" * 76)
print("""
  The spread is ~66 percentage points on one input. That is not a model
  failure, it IS the GE Vernova question: how much of $17.1B of operating
  cash flow is profit and how much is customers pre-paying for turbines?

  You cannot answer it from a screener. Open the 10-Q, find the cash flow
  statement, and read the working-capital lines. If contract liabilities
  and progress collections account for most of the increase, the bottom two
  rows are the real ones and the stock requires 36-64% growth for a decade.
  If they do not, the top two are real and it is cheap.

  Until you have read that statement you do not have a view on GEV, you
  have a hope. The multiple convergence in cell 3b is the better tool here
  because it needs no FCF at all -- only EPS growth and a multiple.
""")


# %% 8 — Print the research brief for a name I'm studying
print(brief("TICKER"))
