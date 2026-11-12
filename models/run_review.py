"""
Spyder entry point — run this file with F5, or run cells with Ctrl+Enter.
=========================================================================

WHY THIS FILE EXISTS
--------------------
`mandate` is a package and uses relative imports (`from . import risk`). That
is correct for a package and it is exactly what breaks under Spyder's F5,
because runfile() executes a script as `__main__` with no package context and
relative imports have nothing to be relative to.

This launcher sits ABOVE the package, puts its parent on sys.path, and imports
absolutely. F5 works. So does `python run_review.py`.

SPYDER WORKFLOW
---------------
The `#%%` markers below split this into cells. Ctrl+Enter runs the cell under
the cursor and leaves every object in the namespace, so you can open `book`,
`corr.matrix` or `results` in the Variable Explorer and poke at them. That is
the point of running this here rather than from a terminal: the report is the
summary, the objects are the actual work.

Cells are ordered so each one builds on the last. Run them top to bottom the
first time.

DEPENDENCIES
------------
numpy, pandas, scipy. TensorFlow is NOT used and should not be — there is no
supervised learning problem here. A neural net fitted to a few years of returns
would produce a confident number with no information in it, which is strictly
worse than the honest arithmetic below.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402

from mandate import risk, scenarios  # noqa: E402
from mandate.factors import BOOK, CANDIDATES, validate_all  # noqa: E402
from mandate.policy import audit  # noqa: E402
from mandate.review import load_book, main  # noqa: E402
from mandate.rubric import brief  # noqa: E402

PORTFOLIO = HERE / "mandate" / "portfolio.json"
PRICES = HERE / "closes.csv"       # optional; see cell 5


# %% 1 — Full report, exactly as the CLI prints it
if __name__ == "__main__":
    main([])


# %% 2 — Load the book as objects you can inspect
book, contribution, using_basis = load_book(PORTFOLIO)

print(f"Equity   ${book.equity_value:,.2f}")
print(f"Cash     ${book.cash:,.2f}")
print(f"Total    ${book.total_value:,.2f}")
print(f"Weights  {book.weights()}")
print(f"Themes   {book.theme_weights()}")
print(f"Funding  {book.funding_plan()}")
if using_basis:
    print("\nNOTE: market_value is null in portfolio.json, so these are")
    print("COST-BASIS weights. Edit the file with real broker values.")


# %% 3 — Policy audit as a DataFrame (sortable in the Variable Explorer)
findings = audit(book, contribution)
findings_df = pd.DataFrame(
    [
        {
            "severity": f.severity.value,
            "section": f.section,
            "message": f.message,
            "remedy": f.remedy,
        }
        for f in findings
    ]
)
print(findings_df[["severity", "section", "message"]].to_string(index=False))


# %% 4 — Factor concentration, and what each candidate would do to it
fc_now = risk.factor_concentration(BOOK, book.weights())

rows = {"current": fc_now.loadings}
for ticker, profile in CANDIDATES.items():
    merged = {**BOOK, ticker: profile}
    hypothetical = dict(book.weights())
    # Add the candidate at the equal-cost-basis target, then renormalize.
    target = 5_000.0
    scale = book.equity_value / (book.equity_value + target)
    hypothetical = {t: w * scale for t, w in hypothetical.items()}
    hypothetical[ticker] = target / (book.equity_value + target)
    rows[ticker] = risk.factor_concentration(merged, hypothetical).loadings

factor_table = pd.DataFrame(rows).fillna(0.0).round(2)
factor_table["worst_delta"] = (
    factor_table.drop(columns="current").sub(factor_table["current"], axis=0).max(axis=1)
)
print(factor_table.sort_values("worst_delta", ascending=False).to_string())


# %% 5 — Correlation (needs price history)
#
# Build closes.csv however you like — yfinance, your broker's export, Alpha
# Vantage. Required shape: a date index, one adjusted-close column per ticker.
#
#     import yfinance as yf
#     px = yf.download(["GOOGL","SNPS","NOW"], period="3y")["Close"]
#     px.to_csv(HERE / "closes.csv")
#
# Three years of daily data is the practical minimum. Correlation estimated on
# a single quiet year tells you how things behaved while nothing happened.

if PRICES.exists():
    prices = pd.read_csv(PRICES, index_col=0, parse_dates=True)
    corr = risk.correlation(prices, book.weights())
    print(corr.matrix.round(2).to_string())
    print(f"\nPortfolio vol        {corr.portfolio_vol:.1%}")
    print(f"Diversification      {corr.diversification_ratio:.2f}")
    print(f"Effective BETS       {corr.effective_bets:.2f}")
    print(f"Effective POSITIONS  {risk.concentration(book.weights()).effective_positions:.2f}")
    print(f"\n{corr.verdict()}")
    print(
        "\nThe gap between effective BETS and effective POSITIONS is the"
        "\nnumber that matters. Positions counts tickers; bets counts"
        "\nindependent sources of loss. In a thematic book the second is"
        "\nalways smaller, usually by more than feels believable."
    )
else:
    print(f"No price file at {PRICES}. See the comment above to build one.")
    print("Correlation skipped — not estimated.")


# %% 6 — Scenarios as a DataFrame
results = scenarios.run_all(BOOK, book.weights())
scenario_df = pd.DataFrame(
    [
        {
            "scenario": r.scenario.name,
            "equity_return": round(r.portfolio_return, 4),
            "dollars": round(book.equity_value * r.portfolio_return, 0),
            "analogue": r.scenario.analogue,
        }
        for r in results
    ]
)
print(scenario_df[["scenario", "equity_return", "dollars"]].to_string(index=False))

worst = results[0]
attribution = pd.Series(worst.factor_attribution()).round(4)
print(f"\nWorst: {worst.scenario.name}")
print(attribution.to_string())


# %% 7 — Per-position scenario grid (rows = positions, cols = scenarios)
grid = pd.DataFrame(
    {r.scenario.key: {p.ticker: p.total_return for p in r.positions} for r in results}
).round(3)
print(grid.to_string())


# %% 8 — Print a research brief to hand to an agent
print(brief("AMD"))


# %% 9 — Sanity-check the assumption layer
problems = validate_all(BOOK) + validate_all(CANDIDATES)
print("\n".join(problems) if problems else "All factor profiles carry a written basis.")
