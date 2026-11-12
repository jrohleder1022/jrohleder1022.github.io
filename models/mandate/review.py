"""
Portfolio review — the entry point that ties the package together.
==================================================================

USAGE
-----
    python3.13 -m mandate.review
    python3.13 -m mandate.review --portfolio portfolio.json
    python3.13 -m mandate.review --prices closes.csv       # enables correlation
    python3.13 -m mandate.review --candidate AMD           # add a hypothetical
    python3.13 -m mandate.review --brief AMD               # print research brief

`--prices` expects a CSV with a date index and one column per ticker of
adjusted closes. Without it, correlation diagnostics are SKIPPED rather than
estimated from nothing — a correlation number invented from no data is worse
than no correlation number.

`--candidate TICKER` re-runs the whole review with that candidate added at the
equal-cost-basis target, so you can see what a position would do to the book
BEFORE buying it rather than after.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import risk, scenarios
from .factors import BOOK, CANDIDATES, validate_all
from .policy import Book, Position, Severity, TARGET_COST_BASIS, audit
from .rubric import brief

RULE = "=" * 78
THIN = "-" * 78


def load_book(path: Path) -> tuple[Book, float, bool]:
    """Load the portfolio file. Returns (book, annual_contribution, using_basis)."""
    data = json.loads(path.read_text())
    using_basis = False
    positions: list[Position] = []
    for row in data["positions"]:
        mv = row.get("market_value")
        if mv is None:
            mv = row["cost_basis"]
            using_basis = True
        positions.append(
            Position(
                ticker=row["ticker"],
                cost_basis=float(row["cost_basis"]),
                market_value=float(mv),
                theme=row["theme"],
                sleeve=row.get("sleeve", "core"),
            )
        )
    book = Book(
        positions=positions,
        cash=float(data.get("cash", 0.0)),
        cash_purpose=data.get("cash_purpose", ""),
        cash_decision_date=data.get("cash_decision_date", ""),
    )
    return book, float(data.get("annual_contribution", 2740.0)), using_basis


def section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def report_assumptions() -> int:
    """Validate the assumption layer before trusting anything built on it."""
    section("0. ASSUMPTION INTEGRITY")
    problems = validate_all(BOOK) + validate_all(CANDIDATES)
    if problems:
        print("The factor layer has problems. Downstream numbers are unreliable:\n")
        for p in problems:
            print(f"  ! {p}")
        return 1
    n_book = len(BOOK)
    n_cand = len(CANDIDATES)
    print(
        f"  OK  {n_book} held + {n_cand} candidate profiles; every exposure "
        "carries a written basis."
    )
    print(
        "      Reminder: these are sourced opinions, not measurements. Every\n"
        "      scenario number below is downstream of them."
    )
    return 0


def report_policy(book: Book, contribution: float, using_basis: bool) -> None:
    section("1. POLICY AUDIT")
    if using_basis:
        print(
            "  NOTE  market_value is unset, so weights below are COST-BASIS\n"
            "        weights. That flatters concentration: winners are\n"
            "        understated. Fill in real values for the true picture.\n"
        )
    findings = audit(book, contribution)
    breaches = sum(1 for f in findings if f.severity is Severity.BREACH)
    warnings = sum(1 for f in findings if f.severity is Severity.WARNING)
    for f in findings:
        print(f"  {f}")
    print(f"\n  {breaches} breach(es), {warnings} warning(s).")


def report_risk(book: Book, contribution: float, prices: pd.DataFrame | None) -> None:
    section("2. CONCENTRATION")
    weights = book.weights()
    conc = risk.concentration(weights)
    print(f"  Positions:            {conc.n_positions}")
    print(f"  Effective positions:  {conc.effective_positions:.2f}  (1 / HHI)")
    print(f"  Largest:              {conc.largest_ticker} at {conc.largest_weight:.1%}")
    print(f"  Top two combined:     {conc.top_two_share:.1%}")
    print(f"\n  {conc.verdict()}")

    section("3. FACTOR CONCENTRATION")
    fc = risk.factor_concentration(BOOK, weights)
    for factor, load in fc.loadings.items():
        bar = "#" * int(abs(load) * 40)
        print(f"  {factor:<16} {load:+.2f}  {bar}")
    print(f"\n  {fc.verdict()}")

    if prices is not None:
        section("4. CORRELATION")
        try:
            cr = risk.correlation(prices, weights)
            print(cr.matrix.round(2).to_string())
            print(f"\n  Portfolio volatility:   {cr.portfolio_vol:.1%} annualized")
            print(f"  Diversification ratio:  {cr.diversification_ratio:.2f}")
            print(f"\n  {cr.verdict()}")
        except (KeyError, ValueError) as exc:
            print(f"  SKIPPED: {exc}")
    else:
        section("4. CORRELATION")
        print(
            "  SKIPPED — no price history supplied (--prices closes.csv).\n"
            "  Not estimated. A correlation invented from no data is worse than\n"
            "  an absent one, because it looks like a measurement."
        )

    section("5. DRAWDOWN RECOVERY (§5 concentration expiry)")
    print(f"  Contribution assumption: ${contribution:,.0f}/yr\n")
    print(f"  {'Drawdown':>10} {'Dollars lost':>14} {'Years to rebuild':>18}")
    for depth, dollars, years in risk.horizon_grid(book.total_value, contribution):
        flag = "  <-- past the 5-year limit" if years > 5 else ""
        print(f"  {depth:>9.0%} {dollars:>14,.0f} {years:>18.1f}{flag}")


def report_scenarios(book: Book) -> None:
    section("6. SCENARIO ANALYSIS")
    weights = book.weights()
    value = book.total_value
    results = scenarios.run_all(BOOK, weights)

    print(f"  Portfolio ${value:,.0f} (equity ${book.equity_value:,.0f} + cash ${book.cash:,.0f})")
    print("  Equity impacts below; cash is unshocked, so whole-portfolio")
    print("  damage is proportionally smaller while the cash is uninvested.\n")
    width = max(len(r.scenario.name) for r in results)
    print(f"  {'Scenario':<{width}} {'Equity':>9} {'Dollars':>12}")
    print(f"  {THIN[:width + 23]}")
    for r in results:
        dollars = book.equity_value * r.portfolio_return
        print(f"  {r.scenario.name:<{width}} {r.portfolio_return:>8.1%} {dollars:>12,.0f}")

    worst = results[0]
    print(f"\n{THIN}")
    print(f"  WORST CASE: {worst.scenario.name}")
    print(f"{THIN}")
    print(f"  {worst.scenario.rationale}\n")
    print(f"  Analogue: {worst.scenario.analogue}\n")
    if worst.scenario.probability_note:
        print(f"  Note: {worst.scenario.probability_note}\n")

    print("  By position:")
    for pos in sorted(worst.positions, key=lambda p: p.total_return):
        factor, impact = pos.dominant_factor()
        print(
            f"    {pos.ticker:<7} {pos.total_return:>7.1%}   "
            f"(worst factor: {factor} at {impact:+.1%})"
        )

    print("\n  Factor attribution of the portfolio move:")
    for factor, contribution in worst.factor_attribution().items():
        print(f"    {factor:<16} {contribution:+.2%}")


def report_candidate(book: Book, ticker: str, contribution: float) -> None:
    section(f"7. CANDIDATE TEST — {ticker} at ${TARGET_COST_BASIS:,.0f}")
    if ticker not in CANDIDATES and ticker not in BOOK:
        print(f"  No factor profile for {ticker}. Declare one in factors.py first.")
        print("  An undeclared position is an unmeasured risk.")
        return

    profile = CANDIDATES.get(ticker) or BOOK[ticker]
    theme_guess = "ai_hardware"
    hypothetical = Book(
        positions=book.positions
        + [
            Position(
                ticker=ticker,
                cost_basis=TARGET_COST_BASIS,
                market_value=TARGET_COST_BASIS,
                theme=theme_guess,
                sleeve="core",
            )
        ],
        cash=max(0.0, book.cash - TARGET_COST_BASIS),
        cash_purpose=book.cash_purpose,
        cash_decision_date=book.cash_decision_date,
    )

    print(f"  Thesis on file: {profile.thesis}\n")

    before = risk.factor_concentration(BOOK, book.weights())
    merged = {**BOOK, ticker: profile}
    after = risk.factor_concentration(merged, hypothetical.weights())

    print(f"  {'Factor':<16} {'before':>8} {'after':>8} {'change':>9}")
    print(f"  {THIN[:45]}")
    for factor in sorted(set(before.loadings) | set(after.loadings)):
        b = before.loadings.get(factor, 0.0)
        a = after.loadings.get(factor, 0.0)
        marker = "  <--" if abs(a) > abs(b) + 0.05 else ""
        print(f"  {factor:<16} {b:>+8.2f} {a:>+8.2f} {a - b:>+9.2f}{marker}")

    print(f"\n  {after.verdict()}")

    cb = risk.concentration(book.weights())
    ca = risk.concentration(hypothetical.weights())
    print(
        f"\n  Effective positions: {cb.effective_positions:.2f} -> "
        f"{ca.effective_positions:.2f}"
    )

    print("\n  Policy effect of the addition:")
    for f in audit(hypothetical, contribution):
        if f.severity is not Severity.NOTE:
            print(f"    {f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    here = Path(__file__).parent
    parser.add_argument("--portfolio", type=Path, default=here / "portfolio.json")
    parser.add_argument("--prices", type=Path, default=None)
    parser.add_argument("--candidate", type=str, default=None)
    parser.add_argument("--brief", type=str, default=None)
    args = parser.parse_args(argv)

    if args.brief:
        print(brief(args.brief.upper()))
        return 0

    if not args.portfolio.exists():
        print(f"portfolio file not found: {args.portfolio}", file=sys.stderr)
        return 2

    book, contribution, using_basis = load_book(args.portfolio)

    prices = None
    if args.prices:
        prices = pd.read_csv(args.prices, index_col=0, parse_dates=True)

    print(RULE)
    print("PORTFOLIO REVIEW".center(78))
    print(RULE)

    if report_assumptions() != 0:
        return 1
    report_policy(book, contribution, using_basis)
    report_risk(book, contribution, prices)
    report_scenarios(book)
    if args.candidate:
        report_candidate(book, args.candidate.upper(), contribution)

    print(f"\n{RULE}")
    print("This report measures risk and enforces policy. It does not pick")
    print("stocks, and no part of it should be read as a recommendation.")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
