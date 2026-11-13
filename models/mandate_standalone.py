"""
mandate — single-file build. GENERATED; do not edit by hand.

Source of truth is the mandate/ package. Edit there and re-run
build_standalone.py, or your changes are lost on the next build.

Open this file in Spyder and press F5. It needs numpy and pandas and
nothing else — the portfolio is embedded below.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence


# Embedded portfolio, used when no JSON file sits beside this script.
_EMBEDDED_PORTFOLIO_JSON = r"""
{
  "_comment": [
    "Current book. cost_basis figures are exact as of 2026-11-12.",
    "market_value: replace the placeholders with real values from the broker.",
    "Until you do, review.py weights the book by COST BASIS and says so --",
    "that understates winners and overstates laggards, which flatters the",
    "concentration numbers. The real ones will look worse."
  ],
  "as_of": "2026-11-12",
  "annual_contribution": 2740.0,
  "cash": 4500.0,
  "cash_purpose": "researching the NVDA replacement",
  "cash_decision_date": "",
  "positions": [
    {
      "ticker": "GOOGL",
      "cost_basis": 4664.58,
      "market_value": null,
      "theme": "ai_platform",
      "sleeve": "core"
    },
    {
      "ticker": "SNPS",
      "cost_basis": 4012.32,
      "market_value": null,
      "theme": "eda",
      "sleeve": "core"
    },
    {
      "ticker": "NOW",
      "cost_basis": 3559.7,
      "market_value": null,
      "theme": "ai_platform",
      "sleeve": "core"
    }
  ]
}
"""
_EMBEDDED_PORTFOLIO = json.loads(_EMBEDDED_PORTFOLIO_JSON)


# ----------------------------------------------------------------------------
# Module aliases
# ----------------------------------------------------------------------------
# In the package, review.py does `from . import risk, scenarios` and then
# calls risk.concentration(...). Here everything shares one namespace, so
# those relative imports were stripped -- which left the FUNCTIONS defined
# but the MODULE names undefined, and every qualified call raised
# NameError at runtime rather than at import.
#
# This shim resolves attribute lookups straight into this file's globals.
# __getattr__ runs at call time, so names defined further down are found
# even though the alias is created up here.


class _ModuleAlias:
    """Makes `risk.concentration` resolve to the flat global of that name."""

    def __getattr__(self, name: str):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(
                f'{name!r} is not defined in this single-file build'
            ) from None


factors = policy = risk = rubric = scenarios = valuation = _ModuleAlias()


# ============================================================================
# MODULE: valuation.py
# ============================================================================
# Intrinsic value — DCF, reverse DCF, sensitivity, and multiple convergence.
# ==========================================================================
#
# THE PROBLEM WITH DCF, STATED PLAINLY
# ------------------------------------
# For a growth company, 70-85% of the present value a DCF produces sits in the
# TERMINAL VALUE — a number derived from assumptions about year 11 onward that
# nobody can verify. The explicit forecast period, where all the apparent work
# happens, usually drives less than a third of the answer.
#
# This means a forward DCF is mostly a restatement of your terminal assumptions
# with extra arithmetic in front of it. Change terminal growth by 100bp and the
# "intrinsic value" moves 20-30%. That is not a valuation; it is an opinion
# wearing a spreadsheet.
#
# So this module does three things differently from a stock DCF:
#
#   1. It REPORTS the terminal value share and warns loudly above 75%. If most
#      of your answer comes from year 11+, you should know that before you act
#      on it.
#
#   2. It leads with REVERSE DCF. Instead of "my model says $X so the stock is
#      cheap", it asks "what growth does today's price require, and is that
#      plausible?" That question is falsifiable. The forward one mostly is not.
#
#   3. It cross-checks against MULTIPLE CONVERGENCE, which needs no terminal
#      assumption at all:
#
#          annualized return ~= EPS growth + annualized multiple change
#
#      This is the framework that showed SNPS at ~23%/yr against CDNS at ~7%/yr
#      on identical EPS growth, with the entire difference coming from the
#      starting multiple.
#
# WHEN A DCF IS THEATRE
# ---------------------
# `dcf()` refuses to run on negative free cash flow. A DCF on a pre-profit
# company values the terminal assumption and nothing else, and dressing that up
# as intrinsic value is how people talk themselves into Cerebras at 32x sales.
# Use reverse DCF or multiple convergence there instead, and be honest that you
# are underwriting a story.
#
# ASSUMPTIONS CARRY SOURCES
# -------------------------
# Same discipline as factors.py: every assumption field has a `basis`. An
# unsourced WACC is a number someone liked the look of.





# ---------------------------------------------------------------------------
# Cost of capital
# ---------------------------------------------------------------------------


@dataclass
class WACCInputs:
    """Weighted average cost of capital, CAPM-based."""

    risk_free: float
    equity_risk_premium: float
    beta: float
    cost_of_debt: float = 0.05
    tax_rate: float = 0.21
    debt_weight: float = 0.0
    basis: str = ""

    def cost_of_equity(self) -> float:
        return self.risk_free + self.beta * self.equity_risk_premium

    def value(self) -> float:
        equity_weight = 1.0 - self.debt_weight
        return (
            equity_weight * self.cost_of_equity()
            + self.debt_weight * self.cost_of_debt * (1 - self.tax_rate)
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.basis.strip():
            problems.append("WACC has no basis recorded.")
        if not 0.0 <= self.debt_weight < 1.0:
            problems.append(f"debt_weight {self.debt_weight} outside [0, 1).")
        if self.beta <= 0:
            problems.append(f"beta {self.beta} must be positive.")
        if self.value() > 0.20:
            problems.append(
                f"WACC {self.value():.1%} above 20%. Possible, but at this level "
                "the discount rate dominates every other assumption — check it."
            )
        return problems


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------


@dataclass
class DCFAssumptions:
    """Everything a DCF needs, with the reasoning that set each number."""

    ticker: str
    base_fcf: float               # trailing twelve-month free cash flow
    shares_diluted: float
    net_debt: float               # positive = net debt, negative = net cash
    initial_growth: float         # year-1 FCF growth
    terminal_growth: float        # perpetuity growth, year N+1 onward
    years: int = 10
    wacc: WACCInputs | None = None
    basis: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.wacc is None:
            problems.append("no WACC supplied.")
        else:
            problems.extend(self.wacc.validate())
            if self.terminal_growth >= self.wacc.value():
                problems.append(
                    f"terminal growth {self.terminal_growth:.1%} >= WACC "
                    f"{self.wacc.value():.1%}. The perpetuity formula diverges: "
                    "a company growing forever faster than its discount rate "
                    "has infinite value, which is why this is always an input "
                    "error and never a finding."
                )
        if self.terminal_growth > 0.04:
            problems.append(
                f"terminal growth {self.terminal_growth:.1%} exceeds ~4%. In "
                "perpetuity this means outgrowing global GDP forever and "
                "eventually becoming the entire economy. Nominal GDP growth "
                "(2.5-3.5%) is the honest ceiling."
            )
        for key in ("base_fcf", "initial_growth", "terminal_growth"):
            if key not in self.basis or not self.basis[key].strip():
                problems.append(f"{key}: no basis recorded.")
        if self.shares_diluted <= 0:
            problems.append("shares_diluted must be positive.")
        return problems


@dataclass
class DCFResult:
    ticker: str
    per_share: float
    enterprise_value: float
    equity_value: float
    pv_explicit: float
    pv_terminal: float
    projected_fcf: list[float]
    discount_rate: float

    @property
    def terminal_share(self) -> float:
        total = self.pv_explicit + self.pv_terminal
        return self.pv_terminal / total if total else 0.0

    def upside(self, price: float) -> float:
        return self.per_share / price - 1.0 if price > 0 else float("nan")

    def honesty_note(self) -> str:
        share = self.terminal_share
        if share > 0.85:
            return (
                f"TERMINAL VALUE IS {share:.0%} OF THE ANSWER. This is not a "
                "valuation of the business, it is a valuation of your "
                "perpetuity assumption. The explicit forecast is decoration. "
                "Do not act on the point estimate — read the sensitivity grid."
            )
        if share > 0.75:
            return (
                f"Terminal value is {share:.0%} of present value. Most of this "
                "number comes from years you cannot forecast. Treat the point "
                "estimate as the midpoint of a wide range, never as a target."
            )
        if share > 0.60:
            return (
                f"Terminal value is {share:.0%} of present value — normal for a "
                "growth business, and still the dominant assumption."
            )
        return (
            f"Terminal value is {share:.0%} of present value. Unusually low; "
            "the explicit forecast is doing real work here."
        )


def _growth_path(initial: float, terminal: float, years: int) -> np.ndarray:
    """Linear fade from initial growth to terminal growth.

    Real businesses do not grow at one rate then step down to another. A fade
    is the standard convention and it matters: a flat-then-cliff model
    overstates value by front-loading growth that a maturing company is
    already losing.
    """
    return np.linspace(initial, terminal, years)


def dcf(assumptions: DCFAssumptions) -> DCFResult:
    """Unlevered DCF with a linear growth fade and perpetuity terminal value."""
    problems = assumptions.validate()
    blocking = [p for p in problems if "no basis" not in p]
    if blocking:
        raise ValueError("DCF assumptions invalid:\n  " + "\n  ".join(blocking))
    if assumptions.base_fcf <= 0:
        raise ValueError(
            f"{assumptions.ticker}: base FCF is {assumptions.base_fcf:,.0f}. A "
            "DCF on negative free cash flow values the terminal assumption and "
            "nothing else. Use reverse_dcf() or multiple_convergence() and be "
            "explicit that you are underwriting a story, not a cash flow."
        )

    assert assumptions.wacc is not None
    r = assumptions.wacc.value()
    g_path = _growth_path(
        assumptions.initial_growth, assumptions.terminal_growth, assumptions.years
    )

    fcf: list[float] = []
    current = assumptions.base_fcf
    for g in g_path:
        current = current * (1 + g)
        fcf.append(current)

    discounts = np.array([(1 + r) ** t for t in range(1, assumptions.years + 1)])
    pv_explicit = float(np.sum(np.array(fcf) / discounts))

    terminal_fcf = fcf[-1] * (1 + assumptions.terminal_growth)
    terminal_value = terminal_fcf / (r - assumptions.terminal_growth)
    pv_terminal = terminal_value / discounts[-1]

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - assumptions.net_debt

    return DCFResult(
        ticker=assumptions.ticker,
        per_share=equity_value / assumptions.shares_diluted,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        projected_fcf=fcf,
        discount_rate=r,
    )


# ---------------------------------------------------------------------------
# Reverse DCF — the one worth leading with
# ---------------------------------------------------------------------------


def reverse_dcf(
    assumptions: DCFAssumptions,
    price: float,
    lo: float = -0.50,
    hi: float = 1.50,
    tolerance: float = 1e-5,
) -> float:
    """Solve for the year-1 FCF growth the current price requires.

    This inverts the usual question. Rather than producing a target price from
    assumptions you chose, it extracts the assumption the market is already
    making, which you can then judge against what the company has actually
    done. "Is 24% plausible for a business that grew 19% last year?" is a
    question with an answer. "Is my $340 target right?" is not.

    Bisection, because the value function is monotonic in growth and bisection
    cannot diverge the way Newton's method can near the perpetuity asymptote.
    """
    assert assumptions.wacc is not None
    target_equity = price * assumptions.shares_diluted + assumptions.net_debt

    def value_at(g: float) -> float:
        trial = DCFAssumptions(
            ticker=assumptions.ticker,
            base_fcf=assumptions.base_fcf,
            shares_diluted=assumptions.shares_diluted,
            net_debt=assumptions.net_debt,
            initial_growth=g,
            terminal_growth=assumptions.terminal_growth,
            years=assumptions.years,
            wacc=assumptions.wacc,
            basis=assumptions.basis,
        )
        result = dcf(trial)
        return result.equity_value + assumptions.net_debt - target_equity

    f_lo, f_hi = value_at(lo), value_at(hi)
    if f_lo * f_hi > 0:
        raise ValueError(
            f"price {price:,.2f} is not reachable with growth in "
            f"[{lo:.0%}, {hi:.0%}]. Either the price embeds assumptions outside "
            "any plausible range, or base FCF is wrong."
        )

    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = value_at(mid)
        if abs(f_mid) < tolerance * target_equity:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------


def sensitivity(
    assumptions: DCFAssumptions,
    wacc_range: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
    growth_range: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
) -> tuple[list[float], list[float], np.ndarray]:
    """WACC x terminal-growth grid of per-share values.

    The grid is the real output of any DCF. A single number implies a precision
    the method does not have; the grid shows how fast the answer moves when two
    unverifiable inputs move by amounts well inside estimation error.
    """
    assert assumptions.wacc is not None
    base_wacc = assumptions.wacc.value()
    base_growth = assumptions.terminal_growth

    waccs = [base_wacc + d for d in wacc_range]
    growths = [base_growth + d for d in growth_range]
    grid = np.full((len(waccs), len(growths)), np.nan)

    for i, w in enumerate(waccs):
        for j, g in enumerate(growths):
            if g >= w:
                continue  # perpetuity diverges
            trial_wacc = WACCInputs(
                risk_free=assumptions.wacc.risk_free,
                equity_risk_premium=assumptions.wacc.equity_risk_premium,
                beta=assumptions.wacc.beta,
                cost_of_debt=assumptions.wacc.cost_of_debt,
                tax_rate=assumptions.wacc.tax_rate,
                debt_weight=assumptions.wacc.debt_weight,
                basis=assumptions.wacc.basis,
            )
            # Override the computed WACC by solving beta back out is fragile;
            # simplest honest approach is a thin shim that returns w directly.
            trial_wacc.value = lambda w=w: w  # type: ignore[method-assign]
            trial = DCFAssumptions(
                ticker=assumptions.ticker,
                base_fcf=assumptions.base_fcf,
                shares_diluted=assumptions.shares_diluted,
                net_debt=assumptions.net_debt,
                initial_growth=assumptions.initial_growth,
                terminal_growth=g,
                years=assumptions.years,
                wacc=trial_wacc,
                basis=assumptions.basis,
            )
            grid[i, j] = dcf(trial).per_share

    return waccs, growths, grid


# ---------------------------------------------------------------------------
# Multiple convergence — no terminal assumption required
# ---------------------------------------------------------------------------


@dataclass
class ConvergenceResult:
    ticker: str
    years: int
    eps_growth: float
    current_multiple: float
    target_multiple: float
    multiple_drag: float
    total_return: float

    def __str__(self) -> str:
        return (
            f"{self.ticker}: {self.eps_growth:+.1%} EPS growth "
            f"{self.multiple_drag:+.1%} multiple change = "
            f"{self.total_return:+.1%}/yr over {self.years}y "
            f"({self.current_multiple:.1f}x -> {self.target_multiple:.1f}x)"
        )


def multiple_convergence(
    ticker: str,
    eps_growth: float,
    current_multiple: float,
    target_multiple: float,
    years: int = 10,
) -> ConvergenceResult:
    """Expected annualized return decomposed into growth and re-rating.

    No terminal value, no WACC, no perpetuity. Just: earnings compound at one
    rate, the multiple travels from here to there, and the two combine.

        total = (1 + g) * (target/current)^(1/N) - 1

    The virtue is that both inputs are observable. You can check EPS growth
    against guidance and the multiple against a decade of history. Neither
    requires a view about the year 2041.
    """
    if current_multiple <= 0 or target_multiple <= 0:
        raise ValueError(
            f"{ticker}: multiples must be positive. For a loss-making company, "
            "P/E is undefined and this framework does not apply — use price/"
            "sales convergence with an explicit margin assumption instead."
        )
    drag = (target_multiple / current_multiple) ** (1 / years) - 1
    total = (1 + eps_growth) * (1 + drag) - 1
    return ConvergenceResult(
        ticker=ticker,
        years=years,
        eps_growth=eps_growth,
        current_multiple=current_multiple,
        target_multiple=target_multiple,
        multiple_drag=drag,
        total_return=total,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def report(assumptions: DCFAssumptions, price: float) -> str:
    """Full valuation writeup: reverse DCF first, then DCF, then sensitivity."""
    lines: list[str] = []
    rule = "=" * 72
    assert assumptions.wacc is not None

    lines.append(rule)
    lines.append(f"INTRINSIC VALUE — {assumptions.ticker}   (price ${price:,.2f})")
    lines.append(rule)

    soft = [p for p in assumptions.validate() if "no basis" in p]
    if soft:
        lines.append("\nUNSOURCED ASSUMPTIONS (the model runs; trust it less):")
        lines.extend(f"  ! {p}" for p in soft)

    lines.append(f"\nWACC {assumptions.wacc.value():.2%}")
    lines.append(
        f"  cost of equity {assumptions.wacc.cost_of_equity():.2%} "
        f"= {assumptions.wacc.risk_free:.2%} rf "
        f"+ {assumptions.wacc.beta:.2f} beta x "
        f"{assumptions.wacc.equity_risk_premium:.2%} ERP"
    )
    if assumptions.wacc.basis:
        lines.append(f"  basis: {assumptions.wacc.basis}")

    # 1. Reverse DCF
    lines.append(f"\n{'-' * 72}\n1. REVERSE DCF — what the price already assumes\n{'-' * 72}")
    try:
        implied = reverse_dcf(assumptions, price)
        lines.append(
            f"  Today's price requires year-1 FCF growth of {implied:+.1%}, "
            f"fading to {assumptions.terminal_growth:.1%} over "
            f"{assumptions.years} years."
        )
        lines.append(
            f"  Your assumption is {assumptions.initial_growth:+.1%}. "
            f"Gap: {assumptions.initial_growth - implied:+.1%}."
        )
        if implied > assumptions.initial_growth:
            lines.append(
                "  The market requires MORE growth than you forecast. For this "
                "to work out, the market has to be wrong in your favour — which "
                "is a bet on sentiment, not on the business."
            )
        else:
            lines.append(
                "  The market requires LESS growth than you forecast. If your "
                "number is right you are paid for the difference. Now go and "
                "argue the other side of your own forecast."
            )
    except ValueError as exc:
        lines.append(f"  not solvable: {exc}")

    # 2. Forward DCF
    lines.append(f"\n{'-' * 72}\n2. DCF\n{'-' * 72}")
    try:
        result = dcf(assumptions)
        lines.append(f"  Enterprise value     ${result.enterprise_value:,.0f}")
        lines.append(f"  Less net debt        ${assumptions.net_debt:,.0f}")
        lines.append(f"  Equity value         ${result.equity_value:,.0f}")
        lines.append(f"  Per share            ${result.per_share:,.2f}")
        lines.append(f"  Upside to price      {result.upside(price):+.1%}")
        lines.append(
            f"\n  PV of explicit years  ${result.pv_explicit:,.0f} "
            f"({1 - result.terminal_share:.0%})"
        )
        lines.append(
            f"  PV of terminal value  ${result.pv_terminal:,.0f} "
            f"({result.terminal_share:.0%})"
        )
        lines.append(f"\n  {result.honesty_note()}")
    except ValueError as exc:
        lines.append(f"  NOT RUN: {exc}")

    # 3. Sensitivity
    lines.append(f"\n{'-' * 72}\n3. SENSITIVITY — per-share value\n{'-' * 72}")
    try:
        waccs, growths, grid = sensitivity(assumptions)
        header = "  WACC \\ g   " + "".join(f"{g:>9.2%}" for g in growths)
        lines.append(header)
        for i, w in enumerate(waccs):
            row = f"  {w:>8.2%}   "
            for j in range(len(growths)):
                val = grid[i, j]
                row += "        -" if np.isnan(val) else f"{val:>9,.0f}"
            lines.append(row)
        finite = grid[~np.isnan(grid)]
        if finite.size:
            lines.append(
                f"\n  Range ${finite.min():,.0f} to ${finite.max():,.0f} — a "
                f"{finite.max() / finite.min() - 1:.0%} spread from moving two "
                "inputs by 100bp. That spread is the honest width of the answer."
            )
    except (ValueError, AssertionError) as exc:
        lines.append(f"  not computed: {exc}")

    lines.append(f"\n{rule}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Expected return estimates, paired with risk
# ---------------------------------------------------------------------------


@dataclass
class ReturnEstimate:
    """A defensible expected-return view on one name, with its reasoning.

    Deliberately built on multiple convergence rather than a DCF, because both
    inputs are observable: you can check EPS growth against guidance and the
    multiple against a decade of history. Neither needs a view about 2041.

        annualized return ~= EPS growth + annualized multiple change + yield

    `applicable` is False where the framework simply does not work — a company
    with no earnings has no P/E, and pretending otherwise by substituting
    price-to-sales smuggles in a margin assumption without stating it.
    """

    ticker: str
    eps_growth: float
    current_multiple: float
    target_multiple: float
    dividend_yield: float = 0.0
    years: int = 10
    applicable: bool = True
    basis: str = ""
    caveat: str = ""

    @property
    def multiple_drag(self) -> float | None:
        if not self.applicable or self.current_multiple <= 0:
            return None
        return (self.target_multiple / self.current_multiple) ** (1 / self.years) - 1

    @property
    def total_return(self) -> float | None:
        drag = self.multiple_drag
        if drag is None:
            return None
        return (1 + self.eps_growth) * (1 + drag) - 1 + self.dividend_yield

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.basis.strip():
            problems.append(f"{self.ticker}: return estimate has no basis.")
        if self.applicable and self.eps_growth > 0.40:
            problems.append(
                f"{self.ticker}: {self.eps_growth:.0%} EPS growth sustained for "
                f"{self.years} years compounds to "
                f"{(1+self.eps_growth)**self.years:.0f}x. Almost nothing does "
                "this. Check it against a longer-run rate."
            )
        return problems

# ============================================================================
# MODULE: factors.py
# ============================================================================
# Risk factors and position exposures — the assumption layer.
# ===========================================================
#
# WHY THIS FILE EXISTS, AND WHY IT IS DATA AND NOT CODE
# -----------------------------------------------------
# Every scenario number this package produces is a consequence of the exposures
# declared here. The arithmetic downstream is trivial; the judgment is all in
# this file. That is deliberate and it mirrors how a real risk desk works: the
# model is a calculator, the assumptions are the work product.
#
# So each exposure carries a `basis` string. If you cannot write the basis, you
# do not know the exposure, and you should not pretend to by leaving a number in
# the dictionary. `validate()` refuses exposures with an empty basis.
#
# THE FACTOR MODEL
# ----------------
# A position's return under a scenario is a linear combination of factor shocks:
#
#     r_i = sum_f  exposure[i][f] * shock[f]
#
# `exposure` is an elasticity, not a correlation:
#
#     1.0   full pass-through — a shock that costs a pure-play 10% costs this 10%
#     0.5   half pass-through
#     0.0   no transmission
#    -0.4   inverse — the position *gains* when this factor is shocked adversely
#
# `shock[f]` is expressed as the equity impact on a hypothetical pure-play with
# exposure 1.0. So `ai_capex: -0.30` means "a pure AI-capex play loses 30%."
#
# WHAT THIS MODEL CANNOT DO
# -------------------------
# It is linear and single-period. It will not capture convexity, contagion,
# second-order effects, or the fact that correlations go to 1 in a crisis. It is
# a structured way to ask "what breaks, and roughly how much" — not a VaR engine,
# and emphatically not a forecast.
#
# CALIBRATION NOTE
# ----------------
# Exposures below were set from the research in this repo and the reasoning in
# the advisory record. They are opinions with sources attached, not measurements.
# Re-derive them when the thesis changes; that is what `basis` is for.




# ---------------------------------------------------------------------------
# Factor taxonomy
# ---------------------------------------------------------------------------

FACTORS: dict[str, str] = {
    "ai_capex": (
        "Revenue depends on AI data-center buildout — servers, accelerators, "
        "power, the physical plant. This is somebody's CAPITAL budget, which "
        "means it is approved in lumps, deferred in downturns, and whipsawed."
    ),
    "semi_rd": (
        "Revenue depends on semiconductor R&D budgets. This is OPERATING "
        "expense: it funds engineers and the tools they use, and it is cut only "
        "in a genuine industry recession, long after capex has been cut."
    ),
    "china_policy": (
        "Revenue exposed to US-China export controls, licensing regimes, or "
        "retaliation. Distinct from general regulatory risk: the mechanism is "
        "an administrative action that can land without warning."
    ),
    "rates_duration": (
        "Valuation sensitivity to long real rates. A high multiple is a long "
        "duration asset; its present value falls hardest when discount rates "
        "rise. Proxy the exposure off the forward multiple, not the business."
    ),
    "enterprise_it": (
        "Revenue depends on corporate software and IT budgets — seat counts, "
        "renewal rates, and the willingness of a CFO to sign a multi-year deal."
    ),
    "ad_cycle": (
        "Revenue depends on advertising spend, which is the most cyclical line "
        "item in most marketing budgets and leads GDP down and up."
    ),
    "regulatory": (
        "Antitrust, forced divestiture, or political intervention that "
        "constrains how the business is permitted to operate."
    ),
    "gov_appropriation": (
        "Revenue depends on government budgets — defense, civil space, or "
        "industrial policy. Distinct from `regulatory`, which constrains how a "
        "business operates: this one IS the demand. Appropriation risk cuts "
        "both ways, because criticality puts a floor under the equity and a "
        "ceiling over the multiple: the state's objectives (onshoring, "
        "redundancy, domestic price restraint) are not shareholder returns."
    ),
    "saas_disintermediation": (
        "Revenue depends on per-seat software pricing surviving agentic AI. "
        "The mechanism is seat compression, not product replacement: if agents "
        "do the work of three people, the customer buys fewer seats. Leads "
        "through cRPO roughly four quarters before it reaches revenue, which "
        "is why profitability metrics miss it entirely."
    ),
    "digital_services_tax": (
        "Exposure to sales/use tax extension onto SaaS and digital products. "
        "Borne by the BUYER, not the seller, so the transmission is demand "
        "elasticity rather than margin. Small in isolation; the risk is "
        "precedent spreading across states and stacking with seat compression "
        "on the same budget line."
    ),
    "commodity_cycle": (
        "Exposure to where a fungible-product industry sits in its CAPACITY "
        "cycle. Distinct from every demand factor here, because the mechanism "
        "is supply: peak margins fund the capacity that destroys them, with a "
        "two-to-three-year lag between the capex decision and the fab coming "
        "online. The signature is margins far above the long-run mean plus an "
        "industry-wide capex increase. A low P/E on peak earnings is not "
        "cheapness, it is the market discounting earnings it does not believe."
    ),
    "consumer_spending": (
        "Revenue scales with household consumption — retail sales, travel, "
        "discretionary purchases. Distinct from `market_beta`, which is a "
        "valuation effect: this one moves the actual revenue line. Softer and "
        "more persistent than a capital budget, because consumption falls a "
        "little in a recession rather than stopping outright the way a "
        "deferred factory does."
    ),
    "market_volatility": (
        "Exposure to realized volatility itself, separate from market "
        "direction. Positive loading = hurt by rising volatility (most "
        "businesses, via demand uncertainty and deal deferral). NEGATIVE "
        "loading = helped by it. Exchanges, brokers and clearing houses earn "
        "per contract traded, and volume spikes precisely when everything else "
        "is falling. This factor exists because genuine ballast is not merely "
        "low beta — it is a business whose revenue moves the other way."
    ),
    "market_beta": (
        "Undifferentiated exposure to a broad equity de-rating. Everything has "
        "some; nothing is immune."
    ),
}


# ---------------------------------------------------------------------------
# Exposure records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Exposure:
    """One position's loading on one factor, with the reasoning that set it."""

    factor: str
    beta: float
    basis: str

    def __post_init__(self) -> None:
        if self.factor not in FACTORS:
            raise ValueError(
                f"unknown factor {self.factor!r}; known: {sorted(FACTORS)}"
            )
        if not -2.0 <= self.beta <= 2.0:
            raise ValueError(
                f"{self.factor}: beta {self.beta} outside [-2, 2]. Elasticities "
                "beyond full double pass-through are almost always an error."
            )


@dataclass
class ExposureSet:
    """The complete factor profile for one ticker."""

    ticker: str
    thesis: str
    exposures: list[Exposure] = field(default_factory=list)

    def as_map(self) -> dict[str, float]:
        return {e.factor: e.beta for e in self.exposures}

    def validate(self) -> list[str]:
        """Return a list of problems. Empty list means the profile is usable."""
        problems: list[str] = []
        if not self.thesis.strip():
            problems.append(f"{self.ticker}: no thesis recorded")
        seen: set[str] = set()
        for exp in self.exposures:
            if not exp.basis.strip():
                problems.append(
                    f"{self.ticker}/{exp.factor}: beta {exp.beta} has no basis. "
                    "An exposure you cannot justify is a guess with a decimal "
                    "point on it."
                )
            if exp.factor in seen:
                problems.append(f"{self.ticker}: duplicate factor {exp.factor}")
            seen.add(exp.factor)
        if "market_beta" not in seen:
            problems.append(
                f"{self.ticker}: no market_beta declared. Nothing is immune to a "
                "broad de-rating; declare it even if it is low."
            )
        return problems


# ---------------------------------------------------------------------------
# The book, as currently understood
# ---------------------------------------------------------------------------

BOOK: dict[str, ExposureSet] = {
    "GOOGL": ExposureSet(
        ticker="GOOGL",
        thesis=(
            "Advertising and cloud franchise with a self-funded AI program. "
            "Owns distribution (Search, YouTube, Android, Chrome) and the "
            "silicon (TPU), so it does not pay the NVIDIA toll on its own "
            "training. Earnings are real and the multiple is the lowest in the "
            "AI complex."
        ),
        exposures=[
            Exposure(
                "ad_cycle",
                0.75,
                "Advertising is still the majority of revenue and effectively "
                "all of near-term operating profit. This, not AI, is what "
                "actually moves the earnings line.",
            ),
            Exposure(
                "ai_capex",
                -0.20,
                "INVERSE and deliberately so. Alphabet is a BUYER of AI "
                "infrastructure, not a seller. A capex winter cuts its own "
                "~41%-of-revenue spend and frees cash flow. Offsetting that, "
                "the market reads a capex cut as evidence AI demand is "
                "softening and compresses the multiple — so the net is a small "
                "negative, not the large one a supplier would take.",
            ),
            Exposure(
                "regulatory",
                0.60,
                "Live antitrust exposure in search and ad tech. The September "
                "2025 remedies ruling avoided a Chrome divestiture, which "
                "capped the tail, but the structural risk has not gone away and "
                "a Democratic Congress raises the ambient temperature.",
            ),
            Exposure(
                "rates_duration",
                0.45,
                "Trades at a modest forward multiple relative to the complex, "
                "so it carries less duration than NOW or SNPS. Real earnings "
                "today discount less painfully than earnings promised in 2032.",
            ),
            Exposure(
                "china_policy",
                0.10,
                "Minimal direct China revenue. The exposure is indirect, via "
                "hardware supply chains and the general tech-policy climate.",
            ),
            Exposure("market_beta", 1.00, "Mega-cap index constituent; moves with the tape."),
        ],
    ),
    "SNPS": ExposureSet(
        ticker="SNPS",
        thesis=(
            "A take-rate on global semiconductor R&D. Sells the tools used to "
            "design chips, so it is indifferent to which chip designer wins — "
            "NVIDIA, AMD, Broadcom, and every hyperscaler custom-silicon team "
            "are all customers. Requalification cost makes the toolchain "
            "extremely sticky once a design starts."
        ),
        exposures=[
            Exposure(
                "semi_rd",
                0.95,
                "This IS the business. EDA revenue is approximately a 9-12% "
                "take-rate on semiconductor R&D spending. If those budgets "
                "shrink, the take-rate business shrinks regardless of share.",
            ),
            Exposure(
                "ai_capex",
                0.15,
                "Low BY CONSTRUCTION, and this is the central reason to own it. "
                "Synopsys sells into R&D opex, not buildout capex. Chip design "
                "continues whether or not a specific data center gets permitted. "
                "Not zero — a severe enough capex winter eventually reaches R&D "
                "budgets — but the transmission is slow and heavily damped.",
            ),
            Exposure(
                "china_policy",
                0.70,
                "ALREADY REALIZED ONCE. BIS 'is-informed' letter of 29 May 2025 "
                "imposed a license requirement on EDA exports to China. China "
                "was ~$1B / ~16% of FY2024 revenue; FY2025 China revenue fell "
                "22% YoY and Synopsys cited disrupted design starts hitting "
                "Design IP. EDA is the highest-leverage chokepoint in the "
                "semiconductor stack, which makes it a standing policy target.",
            ),
            Exposure(
                "rates_duration",
                0.80,
                "High forward multiple (~22-23x) against a long runway. Long "
                "duration asset; re-rates hard on real-rate moves.",
            ),
            Exposure("market_beta", 1.05, "Semi-adjacent; amplifies broad moves modestly."),
        ],
    ),
    "NOW": ExposureSet(
        ticker="NOW",
        thesis=(
            "Workflow system of record for enterprise IT and increasingly for "
            "HR, finance and customer service. Switching cost is the moat: "
            "ripping it out means re-implementing the processes it encodes. "
            "cRPO leads revenue by roughly four quarters."
        ),
        exposures=[
            Exposure(
                "enterprise_it",
                0.90,
                "Subscription revenue tied directly to corporate IT budgets and "
                "seat expansion. DBNR around 109% means growth depends on both "
                "new logos and existing customers expanding.",
            ),
            Exposure(
                "rates_duration",
                1.00,
                "The highest-duration asset in the book. Premium SaaS multiple "
                "means most of the present value sits in distant cash flows, "
                "which is precisely what a rate shock discounts hardest.",
            ),
            Exposure(
                "ai_capex",
                -0.10,
                "Slightly INVERSE. ServiceNow consumes compute, it does not "
                "build it. Cheaper, more available compute in a capex winter "
                "lowers its cost of goods; scarce compute raises it.",
            ),
            Exposure(
                "saas_disintermediation",
                0.85,
                "THE live risk, and it was missing from this model until now. "
                "ServiceNow prices per seat; agentic AI compresses seat counts. "
                "Stock -44% over one year on this thesis while Q3 2026 "
                "subscription revenue still grew 21% and FCF margin guidance "
                "ROSE 35%->36% — the damage is entirely in the multiple so far. "
                "Partial offsets: >50% of new business is consumption/outcome "
                "priced, and agentic consumption in production rose 13x. The "
                "tell is cRPO, which Q4 guidance already shows decelerating.",
            ),
            Exposure(
                "digital_services_tax",
                0.60,
                "California SB 122 (signed 29 June 2026, effective 1 January "
                "2027) extends sales and use tax to SaaS at ~9% all-in. Borne "
                "by the customer, not ServiceNow, and applied equally to every "
                "competitor — so it is a price-level change, not a competitive "
                "disadvantage. Estimated direct revenue impact ~0.4%. The "
                "exposure is set well above that because the real risk is other "
                "states copying a $1.4B revenue idea, and because it stacks "
                "with seat compression on the same budget line.",
            ),
            Exposure(
                "regulatory",
                0.10,
                "Minimal. No antitrust exposure of consequence; data-residency "
                "rules are a compliance cost, not a structural threat.",
            ),
            Exposure("market_beta", 1.15, "High-multiple software; beta above 1 is the norm."),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Candidates under consideration — same discipline, no position taken
# ---------------------------------------------------------------------------

CANDIDATES: dict[str, ExposureSet] = {
    "AMD": ExposureSet(
        ticker="AMD",
        thesis=(
            "The credible second source for AI accelerators. Q3 2026 data "
            "center revenue $8.5B, +97% YoY, segment operating margin 34% up "
            "from 25%. OpenAI agreement covers up to 6GW. Management guides "
            "data center to exceed 80% of total revenue in 2027."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                0.90,
                "Guided to 80%+ of revenue from data center in 2027. The "
                "client, gaming and embedded segments that once provided "
                "ballast are becoming rounding errors. AMD is becoming LESS "
                "diversified as it grows, not more.",
            ),
            Exposure(
                "china_policy",
                0.55,
                "Accelerator export licensing applies to AMD as it does to "
                "NVIDIA. Less China revenue already embedded in guidance than "
                "NVIDIA had, so arguably more left to lose.",
            ),
            Exposure(
                "semi_rd",
                0.15,
                "A consumer of EDA, not a seller. Its own R&D is a cost, so "
                "an industry R&D recession is mildly favourable to margin and "
                "unfavourable to the roadmap. Small net exposure.",
            ),
            Exposure(
                "rates_duration",
                0.75,
                "High forward multiple on earnings that are expected to "
                "roughly double. Substantial duration.",
            ),
            Exposure("market_beta", 1.40, "High-beta semiconductor; amplifies the tape."),
        ],
    ),
    "MU": ExposureSet(
        ticker="MU",
        thesis=(
            "DRAM, NAND and — the reason anyone cares now — HBM for AI "
            "accelerators. FQ4 FY2026 (ended 3 Sept): revenue $54.2B (+379% "
            "YoY), gross margin 87%, adjusted EPS $33.42. FY2026: revenue "
            "$133.2B (+256%), gross margin 81.1% against ABOUT 40% in FY2025. "
            "FQ1 FY2027 guided to $61.5B revenue, 86.25% gross margin, $38.15 "
            "adjusted EPS. Cloud Memory (including HBM) $16.3B, +18% "
            "sequentially, with most of calendar 2027 HBM bit supply already "
            "contracted at significantly higher prices. Capex $27.37B in "
            "FY2026 and guided higher for FY2027. Price $798.44 on 12 Nov 2026."
        ),
        exposures=[
            Exposure(
                "commodity_cycle",
                1.25,
                "THE WHOLE POSITION, and the reason the factor was added. An "
                "87% gross margin in a commodity industry whose long-run "
                "mid-cycle margin is 25-35% is not a new normal; it is a peak "
                "with a date on it. Memory has all five boom ingredients — "
                "fungible product, fixed short-run capacity, inelastic demand, "
                "extreme operating leverage, spot pricing — which is exactly "
                "why margins went from 40% to 81% in one year and exactly why "
                "they will go back. The $27.37B of FY2026 capex, guided higher "
                "still, IS the mechanism of reversal: it arrives as supply in "
                "2028-29. Above full pass-through because operating leverage "
                "amplifies the move in both directions.",
            ),
            Exposure(
                "ai_capex",
                1.00,
                "HBM is sold into accelerator bills of materials, so demand is "
                "the AI buildout. Partially mitigated by multi-year contracted "
                "pricing — most of CY2027 HBM is already committed — which is "
                "a genuine difference from spot DRAM and the strongest part of "
                "the structural case.",
            ),
            Exposure(
                "china_policy",
                0.50,
                "Memory export licensing, plus the separate and underrated "
                "threat of Chinese domestic capacity (CXMT) entering "
                "commodity DRAM with state funding and no return requirement.",
            ),
            Exposure(
                "rates_duration",
                0.25,
                "GENUINELY LOW, and the number most likely to be misread. "
                "Almost all of Micron's present value sits in the next two or "
                "three years rather than in 2040, so a discount-rate shock "
                "barely touches it. That is a statement about WHEN the value "
                "is, not about whether it is safe — the risk here is the "
                "commodity cycle, not the yield curve.",
            ),
            Exposure(
                "market_volatility",
                0.20,
                "Modest. The equity is volatile, but the business does not "
                "depend on markets staying open: it is funding capex from "
                "enormous current cash flow, not from issuance.",
            ),
            Exposure(
                "semi_rd",
                0.10,
                "A consumer of EDA, not a seller. Minor.",
            ),
            Exposure(
                "market_beta",
                1.55,
                "Among the highest-beta large caps. Memory equities have "
                "historically drawn down 60-80% peak to trough across a full "
                "cycle, with revenue still positive throughout.",
            ),
        ],
    ),
    "NVDA": ExposureSet(
        ticker="NVDA",
        thesis=(
            "The AI accelerator standard, and CUDA is the moat rather than the "
            "silicon. Q2 FY2027: revenue $96.22B (+106% YoY), data center "
            "$89.0B (+117%). Q3 guided to $108B +/-2% at 74% gross margin, "
            "EXPLICITLY excluding all China data center compute. SOLD from this "
            "book on 12 Nov 2026 when the written tripwire fired on Huang's "
            "resignation. Held here to monitor the re-entry conditions, not as "
            "a candidate."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                1.10,
                "Above full pass-through. It sells the single most expensive "
                "line item in the AI buildout, with operating leverage that "
                "amplifies the factor in both directions.",
            ),
            Exposure(
                "china_policy",
                0.40,
                "LOWER than it looks, and this is the counterintuitive part. "
                "The $108B guide already excludes all China data center "
                "revenue, so the loss is realized rather than pending. China "
                "is now upside optionality. The residual exposure is the "
                "regime tightening further on allied jurisdictions.",
            ),
            Exposure(
                "regulatory",
                0.70,
                "Elevated sharply after the resignation. Bipartisan calls for a "
                "federal probe, Warren and Coons demanding record preservation, "
                "and the Chip Security Act and AI Overwatch Act moving through "
                "the NDAA. The company lost its most effective lobbyist against "
                "export controls and gained an investigation in the same week.",
            ),
            Exposure(
                "rates_duration",
                0.65,
                "Enormous current earnings relative to the multiple, which "
                "keeps duration below the pre-profit names despite the growth.",
            ),
            Exposure(
                "semi_rd",
                0.20,
                "A heavy consumer of EDA rather than a seller. An industry R&D "
                "recession would ease competition and slow its own roadmap.",
            ),
            Exposure("market_beta", 1.45, "The highest-weight stock in the index complex."),
        ],
    ),
    "IONQ": ExposureSet(
        ticker="IONQ",
        thesis=(
            "Trapped-ion quantum computing, now with a semiconductor "
            "manufacturing arm after the SkyWater acquisition. Q3 2026: revenue "
            "$173.8M (+336% YoY), of which the platform business was $90.3M. "
            "RPO ~$1.2B. FY2026 guided $505-515M. READ THE PROFIT LINE "
            "CAREFULLY: GAAP net income of ~$564M (EPS $1.42) includes an $896M "
            "NON-CASH gain from marking warrant liabilities to market. The "
            "operating loss was ~$433M for the quarter and nine-month operating "
            "cash flow was about -$570M."
        ),
        exposures=[
            Exposure(
                "gov_appropriation",
                0.60,
                "National labs, defense research and allied-government "
                "contracts are the bulk of credible near-term quantum demand. "
                "Commercial production use remains thin.",
            ),
            Exposure(
                "ai_capex",
                0.30,
                "Partially coupled. Quantum sits in the same speculative "
                "research budgets that AI enthusiasm inflated, so sentiment "
                "transmits even though the technology does not compete.",
            ),
            Exposure(
                "rates_duration",
                1.35,
                "The highest in this file, and deservedly. Burning ~$570M of "
                "operating cash over nine months against a commercial payoff "
                "that is years away means essentially all value is terminal "
                "value. This is the definition of maximum duration, and it is "
                "why a rate shock hurts speculative technology hardest.",
            ),
            Exposure(
                "market_volatility",
                0.55,
                "Positive and high. A pre-commercial company funded by equity "
                "issuance depends on markets staying open — it raised ~$2B in "
                "October. Volatility closes that window precisely when cash is "
                "needed.",
            ),
            Exposure("market_beta", 1.80, "The highest beta in the file. Narrative-driven."),
        ],
    ),
    "CBRS": ExposureSet(
        ticker="CBRS",
        thesis=(
            "Wafer-scale inference accelerators. Genuine engineering "
            "differentiation on latency. Pre-profit, six months public, and "
            "the revenue base is concentrated to a degree that is itself the "
            "thesis risk."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                1.30,
                "Above full pass-through. Revenue is 100% dependent on new AI "
                "capacity being built AND energized, with no other segment to "
                "cushion a pause. A pure-play with operating leverage amplifies "
                "the factor rather than tracking it.",
            ),
            Exposure(
                "china_policy",
                0.45,
                "Accelerator export regime applies. Separately, ~43% of Q2 2026 "
                "revenue came from two UAE-affiliated entities (MBZUAI 34%, G42 "
                "9%), and G42 is also an investor — related-party revenue that "
                "sits inside the same geopolitical review process.",
            ),
            Exposure(
                "rates_duration",
                1.20,
                "Pre-profit. Essentially all value is terminal value, which is "
                "the definition of maximum duration.",
            ),
            Exposure("market_beta", 1.60, "Recent IPO, thin float, lockup supply still clearing."),
        ],
    ),
    "SPCX": ExposureSet(
        ticker="SPCX",
        thesis=(
            "Launch and satellite broadband operator that has become, by "
            "revenue, an AI infrastructure company. Q3 2026: 'Super "
            "Intelligence' revenue $7.6B of $14.6B total — 52%, outselling "
            "Starlink for the first time."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                0.85,
                "52% of revenue is AI, and Q4 capex guided to $35-40B against "
                "$14.6B quarterly revenue (~250% of revenue). The capex "
                "commitment is itself a leveraged bet on AI demand continuing.",
            ),
            Exposure(
                "rates_duration",
                1.10,
                "~32.5x price/sales, one quarter into profitability, funding a "
                "capex program far larger than revenue. Extreme duration and "
                "extreme financing sensitivity.",
            ),
            Exposure(
                "regulatory",
                0.35,
                "Spectrum, launch licensing, and orbital-debris rules. Also a "
                "major government contractor, which cuts both ways.",
            ),
            Exposure("market_beta", 1.45, "Staggered lockup releases still in progress."),
        ],
    ),
    "RKLB": ExposureSet(
        ticker="RKLB",
        thesis=(
            "Small-launch operator (Electron) plus a larger Space Systems "
            "components business, with medium-lift Neutron in development. "
            "Q3 2026: revenue $267.8M +73% YoY, record backlog $3.57B +52% "
            "sequentially, 117 launches booked. Neutron slipped to 2027 at the "
            "earliest, and the GAAP loss widened to $79.7M from $18.3M."
        ),
        exposures=[
            Exposure(
                "gov_appropriation",
                0.65,
                "NASA, Space Force and defense programs are the anchor demand, "
                "alongside commercial constellation operators. This is the "
                "FIRST candidate in this file whose primary demand driver is "
                "not AI — which is precisely what the book is missing.",
            ),
            Exposure(
                "ai_capex",
                0.10,
                "Near-zero direct linkage. Some satellite demand traces back to "
                "data infrastructure, but launch cadence is set by constellation "
                "schedules and government programs, not by hyperscaler capital "
                "budgets.",
            ),
            Exposure(
                "rates_duration",
                0.95,
                "Pre-profit with a widening loss, and Neutron — the entire "
                "medium-lift thesis — is a 2027+ event. Nearly all value is "
                "terminal value, which is maximum duration.",
            ),
            Exposure(
                "regulatory",
                0.25,
                "FAA launch licensing, range access, orbital debris rules. Real "
                "but routine for an established operator.",
            ),
            Exposure("market_beta", 1.50, "Pre-profit small cap; amplifies the tape sharply."),
        ],
    ),
    # -- Ballast candidates -------------------------------------------------
    # Screened on the OPPOSITE properties to everything above: profitable now,
    # cash-generative now, modest duration, low beta, and a demand driver with
    # no connection to AI. These are structurally boring, and the boringness
    # is the entire function.
    "CME": ExposureSet(
        ticker="CME",
        thesis=(
            "Derivatives exchange and clearing house. Earns a fee per contract "
            "traded across rates, equities, FX, energy, metals and agriculture. "
            "Q3 2026: record revenue $1.74B (+13%), ADV 29.4M contracts (+16%), "
            "double-digit growth in all six asset classes. Market data revenue "
            "$243M, its 34th consecutive quarter of growth. Q1 2026 set an ADV "
            "record of 36.2M (+22%) during a volatile quarter. Dividend yield "
            "roughly 3.9% at $316."
        ),
        exposures=[
            Exposure(
                "market_volatility",
                -0.70,
                "THE REASON TO OWN IT. Revenue is a toll per contract traded, "
                "and volume spikes when markets are frightened. Q1 2026 proved "
                "it: record ADV +22% in a volatile quarter. This is the only "
                "negative volatility loading available in this file, and the "
                "book's single worst scenario is a broad drawdown.",
            ),
            Exposure(
                "market_beta",
                0.55,
                "The STOCK still falls in a selloff — ballast is not a hedge. "
                "But it falls roughly half as hard as the book does, and the "
                "earnings move the other way, which is the combination that "
                "actually dampens a drawdown.",
            ),
            Exposure(
                "rates_duration",
                0.30,
                "Lowest duration of any name considered. Profits are real, "
                "near-term and largely returned as dividends and buybacks, so "
                "little value sits in distant cash flows for a discount rate to "
                "destroy.",
            ),
            Exposure(
                "regulatory",
                0.35,
                "CFTC oversight, clearing-capital rules, position limits, and "
                "periodic political interest in a transaction tax. Real, slow-"
                "moving, and the same barriers are why a new exchange cannot "
                "simply appear.",
            ),
            Exposure("ai_capex", 0.00, "No connection. Volume is driven by hedging need."),
        ],
    ),
    "V": ExposureSet(
        ticker="V",
        thesis=(
            "A toll on global card payment volume. Visa does not lend or carry "
            "credit risk; it runs the network and takes a fee per transaction. "
            "FY2026 (ended 30 Sept): net revenue $45.9B (+15%, +14% constant "
            "currency), payments volume +9% cc, cross-border volume +15% ex "
            "intra-Europe, GAAP EPS $12.32 (+21%), non-GAAP $13.27. The moat "
            "is a two-sided network effect: merchants accept it because "
            "cardholders carry it, and vice versa, which is close to "
            "impossible to rebuild from scratch."
        ),
        exposures=[
            Exposure(
                "consumer_spending",
                0.75,
                "The business IS a percentage of consumption. Payments volume "
                "+9% and cross-border +15% in FY2026 are the revenue line, not "
                "a proxy for it. Cross-border carries the highest take rate, "
                "which makes international travel the swing factor.",
            ),
            Exposure(
                "regulatory",
                0.65,
                "The largest risk by some distance, and the reason this is not "
                "a sleep-easy holding. Interchange fee caps, the proposed "
                "Credit Card Competition Act, and ongoing antitrust attention "
                "to network routing all attack the take rate directly. A "
                "legislated fee cap would hit revenue without touching volume.",
            ),
            Exposure(
                "market_beta",
                0.95,
                "Large-cap, lower volatility than the tech complex, but it "
                "still trades with the index.",
            ),
            Exposure(
                "rates_duration",
                0.55,
                "Moderate. Earnings are real and present rather than promised, "
                "so duration is well below NOW or SNPS — but the multiple is "
                "not cheap and this is NOT a low-duration asset. Visa is a "
                "quality compounder, not ballast.",
            ),
            Exposure(
                "market_volatility",
                0.10,
                "Slight. Consumers spend marginally less when frightened, but "
                "the effect is small next to the volume trend.",
            ),
            Exposure("ai_capex", 0.00, "No linkage. Volume is driven by consumption."),
        ],
    ),
    "WM": ExposureSet(
        ticker="WM",
        thesis=(
            "Solid waste collection and disposal. The moat is permitted "
            "landfill capacity, which is close to impossible to replicate "
            "because new permits are rarely granted, combined with route "
            "density that makes a competing truck uneconomic. Q3 2026: revenue "
            "+6.3% on core pricing +5.8%. FY2026 FCF guided $3.75-3.85B at the "
            "high end, EBITDA $8.15-8.25B."
        ),
        exposures=[
            Exposure(
                "market_beta",
                0.70,
                "Demand is the most inelastic there is — waste is generated "
                "whether or not the economy is growing. The cyclical part is "
                "construction and industrial volumes, not households.",
            ),
            Exposure(
                "rates_duration",
                0.45,
                "Steady contracted cash flows, but the multiple is not cheap "
                "and the ~1.5% yield leaves limited cushion if pricing power "
                "fades. Lower duration than the book, not dramatically so.",
            ),
            Exposure(
                "gov_appropriation",
                0.15,
                "Municipal collection contracts are government revenue, but "
                "they are essential-service budgets rather than discretionary "
                "appropriations. Low exposure.",
            ),
            Exposure(
                "regulatory",
                0.30,
                "Environmental rules cut both ways: compliance is a cost, and "
                "it is also exactly why nobody can open a competing landfill.",
            ),
            Exposure(
                "market_volatility",
                0.10,
                "Near-zero. Nothing about contracted waste collection responds "
                "to market volatility.",
            ),
            Exposure("ai_capex", 0.05, "Negligible; some data-center construction waste."),
        ],
    ),
    "PGR": ExposureSet(
        ticker="PGR",
        thesis=(
            "Auto insurer with a data and pricing advantage. Invests a $99.2B "
            "float at a 4.3% recurring book yield, 3.6-year duration. WARNING: "
            "the underwriting cycle is turning against it. Combined ratio drifted "
            "from 87.3 in Q2 2026 to 88.7 in Q3; the clean ratio worsened ~4 "
            "points YoY; premium per policy is FALLING; and written premium "
            "growth slowed to 6% in H1 2026 from 15% in H1 2025."
        ),
        exposures=[
            Exposure(
                "rates_duration",
                -0.35,
                "NEGATIVE, and the structural reason to look here. An insurer "
                "reinvests its float at prevailing yields, so higher rates "
                "raise earnings over time — the opposite of every other "
                "position in the book. Caveat: short-run mark-to-market still "
                "hurts (Q3 2026 total portfolio return was -1.5% on Treasury "
                "moves). The negative loading is right for a ten-year horizon "
                "and wrong for a quarter.",
            ),
            Exposure(
                "market_beta",
                0.45,
                "Low. People insure their cars regardless of the index.",
            ),
            Exposure(
                "regulatory",
                0.30,
                "State rate approval. Insurers must petition to raise prices, "
                "which delays recovery when loss costs rise — part of why the "
                "combined ratio is drifting now.",
            ),
            Exposure(
                "market_volatility",
                0.05,
                "Essentially none, beyond mark-to-market on the bond portfolio.",
            ),
            Exposure("ai_capex", 0.00, "No connection whatsoever."),
        ],
    ),
    "LUNR": ExposureSet(
        ticker="LUNR",
        thesis=(
            "Lunar landers and space infrastructure services, pivoting toward "
            "national security and commercial work. Q3 2026 (12 Nov): revenue "
            "$269M, gross margin 26%, adjusted EBITDA +$8M, FREE CASH FLOW "
            "+$33M, net loss only $4.0M. Backlog $1.87B against $213M at "
            "December 2025, though $645M of that came from the Lanteris and "
            "Goonhilly acquisitions. FY2026 guided $920-950M. National security "
            "revenue went from 3% to 30% of the mix year over year."
        ),
        exposures=[
            Exposure(
                "gov_appropriation",
                0.55,
                "Backlog is ~32% civil and ~25% defense, so ~57% government "
                "against 43% commercial. Lower government dependence than its "
                "NASA-lander reputation implies, and the defense share is "
                "rising fast.",
            ),
            Exposure(
                "ai_capex",
                0.05,
                "Essentially none. Demand comes from lunar programs, space "
                "communications and defense, not from hyperscaler budgets.",
            ),
            Exposure(
                "rates_duration",
                0.85,
                "REVISED UP from 0.70. The original basis was that LUNR is "
                "'already FCF-positive', which does not survive inspection. "
                "Q3's +$33M was CFO $66M less capex $33M, and the CFO "
                "attributed it to improved collections, cash from new contract "
                "wins and the absence of Q2's unfavourable timing — i.e. "
                "working capital, not earnings. 'Cash from new contract wins' "
                "means customer advances against a backlog that went from "
                "$213M to $1.9B: a liability, which reverses as the work is "
                "performed. Year-to-date FCF is about -$112M. Still below "
                "RKLB's 0.95, because a $4.0M net loss and +$8M adjusted "
                "EBITDA are genuinely closer to breakeven than a $79.7M loss "
                "that quadrupled — but this is not a cash-generative business.",
            ),
            Exposure(
                "regulatory",
                0.20,
                "Launch licensing and ITAR, routine for an established "
                "contractor.",
            ),
            Exposure(
                "market_beta",
                1.45,
                "Small-cap space name; high beta, though less extreme than a "
                "pre-revenue developer.",
            ),
        ],
    ),
    "INTC": ExposureSet(
        ticker="INTC",
        thesis=(
            "Domestic foundry turnaround on 18A/18A-P, underwritten by "
            "industrial policy. The US government bought 433M shares at $20.47 "
            "in August 2025 (~10%, no board seat). Q3 2026 Foundry segment: "
            "$6.7B revenue but $6.3B of that intersegment — EXTERNAL revenue "
            "was $411M and came from a non-recurring contract. Segment "
            "operating loss $1.9B."
        ),
        exposures=[
            Exposure(
                "gov_appropriation",
                0.70,
                "Industrial policy IS the thesis. The government is a ~10% "
                "shareholder and the strategic rationale for domestic leading-"
                "edge capacity is what funds the attempt. Note the trap: this "
                "is the 'strategically critical' profile — a floor under the "
                "equity and a ceiling over the multiple.",
            ),
            Exposure(
                "ai_capex",
                0.35,
                "Moderate. Foundry capacity utilisation depends partly on AI "
                "silicon demand, but the binding constraint today is winning "
                "external customers at all, not end-market strength.",
            ),
            Exposure(
                "china_policy",
                0.45,
                "Meaningful China revenue in the products business, plus export "
                "licensing on advanced nodes.",
            ),
            Exposure(
                "semi_rd",
                0.20,
                "Spends heavily on R&D rather than selling into it; an industry "
                "R&D recession would ease competitive pressure while worsening "
                "the roadmap gap.",
            ),
            Exposure(
                "rates_duration",
                0.60,
                "Value depends on foundry profitability years out. Long "
                "duration, though tempered by a real products business "
                "generating revenue today.",
            ),
            Exposure("market_beta", 1.25, "Large-cap semiconductor with turnaround volatility."),
        ],
    ),
}


def validate_all(sets: Mapping[str, ExposureSet]) -> list[str]:
    """Validate every profile in a mapping; empty result means all are usable."""
    problems: list[str] = []
    for exposure_set in sets.values():
        problems.extend(exposure_set.validate())
    return problems


# ---------------------------------------------------------------------------
# Expected-return views, to be read alongside the risk numbers
# ---------------------------------------------------------------------------
#
# Same discipline as the exposures above: these are sourced opinions, not
# measurements, and every one carries a basis. Where the framework does not
# apply -- a company with no earnings has no P/E -- `applicable=False` says so
# rather than substituting price-to-sales and hiding a margin assumption
# inside it.


ESTIMATES: dict[str, ReturnEstimate] = {
    "SNPS": ReturnEstimate(
        "SNPS", eps_growth=0.22, current_multiple=22.5, target_multiple=22.0,
        basis="Guided ~22% EPS CAGR. Multiple held flat: 22.5x is near its own "
              "ten-year average, so no re-rating is assumed in either direction.",
    ),
    "GOOGL": ReturnEstimate(
        "GOOGL", eps_growth=0.14, current_multiple=22.0, target_multiple=20.0,
        dividend_yield=0.004,
        basis="Mid-teens EPS growth on advertising plus cloud. Mild compression "
              "assumed because 22x already embeds AI optionality and antitrust "
              "is unresolved.",
    ),
    "NOW": ReturnEstimate(
        "NOW", eps_growth=0.18, current_multiple=30.0, target_multiple=24.0,
        basis="21% subscription growth, but the multiple has already compressed "
              "~44% over one year on seat-compression fears and the de-rating "
              "may not be finished.",
        caveat="Highest uncertainty in the book. Q4 cRPO is the test.",
    ),
    "CME": ReturnEstimate(
        "CME", eps_growth=0.08, current_multiple=24.0, target_multiple=22.0,
        dividend_yield=0.039,
        basis="Volume growth plus pricing; 13% revenue growth does not flow "
              "fully to EPS. Most of the return is the dividend, which is why "
              "this is a risk decision rather than a return decision.",
    ),
    "AMD": ReturnEstimate(
        "AMD", eps_growth=0.22, current_multiple=36.6, target_multiple=25.0,
        basis="$585.30 against ~$16.00 of 2027 consensus EPS. Target 25x still "
              "a premium. Note this UNDERSTATES the drag: up to 320M warrant "
              "shares for Meta and OpenAI vest on delivery, ~19% dilution, "
              "taking the entry multiple to 43.5x fully diluted.",
        caveat="Needs the multiple to hold near 36.6x to match SNPS.",
    ),
    "V": ReturnEstimate(
        "V", eps_growth=0.12, current_multiple=30.0, target_multiple=26.0,
        dividend_yield=0.007,
        basis="Low-teens EPS growth on payment volume plus buybacks. Mild "
              "compression for interchange and routing-antitrust risk.",
    ),
    "MU": ReturnEstimate(
        "MU", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="NOT APPLICABLE ON PURPOSE. The convergence framework assumes the "
              "current multiple sits on sustainable earnings. Micron's 87% "
              "gross margin against a 25-35% mid-cycle mean means the "
              "denominator is a peak, so a 5.2x forward P/E is a warning rather "
              "than an input. Value this off mid-cycle earnings or not at all.",
    ),
    "CBRS": ReturnEstimate(
        "CBRS", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False, basis="Pre-profit. No P/E exists.",
    ),
    "IONQ": ReturnEstimate(
        "IONQ", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="Pre-profit. Reported GAAP income is an $896M warrant "
              "mark-to-market against a $433M quarterly operating loss.",
    ),
    "RKLB": ReturnEstimate(
        "RKLB", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False, basis="Pre-profit; loss widened to $79.7M.",
    ),
    "LUNR": ReturnEstimate(
        "LUNR", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False, basis="Net loss $4.0M. Near breakeven but no "
                                "meaningful earnings base yet.",
    ),
    "SPCX": ReturnEstimate(
        "SPCX", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="One quarter into profitability at ~108x annualized earnings and "
              "~32.5x sales, funding capex at ~250% of revenue. No stable "
              "earnings base to converge from.",
    ),
    "INTC": ReturnEstimate(
        "INTC", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="Foundry segment operating loss $1.9B with external revenue of "
              "$411M from a non-recurring contract. A turnaround has no "
              "normalized earnings to grow from.",
    ),
    "WM": ReturnEstimate(
        "WM", eps_growth=0.09, current_multiple=30.0, target_multiple=26.0,
        dividend_yield=0.015,
        basis="Core pricing +5.8% driving high-single-digit EPS growth. Mild "
              "compression; the ~1.5% yield gives little cushion.",
    ),
    "PGR": ReturnEstimate(
        "PGR", eps_growth=0.07, current_multiple=16.0, target_multiple=15.0,
        dividend_yield=0.020,
        basis="Underwriting cycle turning against it -- combined ratio drifting "
              "87.3 to 88.7, premium per policy falling, written premium growth "
              "15% to 6%. Float income rises with rates and partly offsets.",
        caveat="Low multiple reflects a deteriorating underwriting cycle.",
    ),
}

# ============================================================================
# MODULE: policy.py
# ============================================================================
# Investment Policy Statement, encoded as machine-checkable rules.
# ================================================================
#
# WHY MECHANIZE THE POLICY
# ------------------------
# The policy was written to be consulted under pressure, and the entire failure
# mode of a written policy is that it gets read generously at exactly the moment
# it should be read strictly. A rule that is checked by arithmetic cannot be
# talked out of its conclusion by a good story about why this position is
# different.
#
# So every section of the IPS that can be reduced to a number lives here. The
# sections that cannot — "moat explainable in three sentences", "sell falling
# value, never falling price" — are enforced in `rubric.py` as gates on the
# research instead, because they are judgments about evidence rather than
# arithmetic about weights.
#
# SEVERITY
# --------
#     BREACH   The policy is violated right now. Act.
#     WARNING  Within tolerance of a limit, or a limit is about to bind.
#     NOTE     Structural observation worth knowing; no action implied.
#
# A BREACH is not advice to sell. It is a statement that the book and the policy
# disagree, and that one of them has to change — deliberately, in writing.




# ---------------------------------------------------------------------------
# Policy constants — edit here, not in the checks
# ---------------------------------------------------------------------------

MAX_SINGLE_POSITION = 0.25          # §4
TARGET_COST_BASIS = 5_000.0         # equal-cost-basis structure
CORE_MINIMUM = 1_500.0              # §4 core/satellite line
MAX_SATELLITE_SLEEVE = 0.15         # §3
MAX_SINGLE_SATELLITE = 0.05         # §3
MAX_AI_COMPLEX = 0.60               # §3
EDA_BAND = (0.20, 0.30)             # §3
WARN_TOLERANCE = 0.03               # how close to a limit triggers WARNING

# §5 concentration expiry: portfolio value -> required non-correlated floor.
# The logic: concentration is affordable only while annual contributions can
# rebuild a 50% drawdown inside five years. Past that, diversification stops
# being optional because time, not money, becomes the binding constraint.
EXPIRY_LADDER: tuple[tuple[float, float], ...] = (
    (20_000.0, 0.00),
    (40_000.0, 0.20),
    (75_000.0, 0.30),
)
ASSUMED_ANNUAL_CONTRIBUTION = 2_740.0  # implied by the §5 ladder's own arithmetic
REBUILD_YEARS_LIMIT = 5.0


class Severity(Enum):
    BREACH = "BREACH"
    WARNING = "WARNING"
    NOTE = "NOTE"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    section: str
    message: str
    remedy: str = ""

    def __str__(self) -> str:
        head = f"[{self.severity.value}] §{self.section}: {self.message}"
        return f"{head}\n    -> {self.remedy}" if self.remedy else head


@dataclass
class Position:
    ticker: str
    cost_basis: float
    market_value: float
    theme: str
    sleeve: str = "core"       # "core" | "satellite"

    def __post_init__(self) -> None:
        if self.sleeve not in ("core", "satellite"):
            raise ValueError(f"{self.ticker}: sleeve must be core or satellite")

    @property
    def unrealized(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def basis_gap(self) -> float:
        """Dollars still needed to reach the equal-cost-basis target."""
        return max(0.0, TARGET_COST_BASIS - self.cost_basis)


@dataclass
class Book:
    positions: list[Position] = field(default_factory=list)
    cash: float = 0.0
    cash_purpose: str = ""
    cash_decision_date: str = ""

    @property
    def equity_value(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def total_value(self) -> float:
        return self.equity_value + self.cash

    def weights(self, include_cash: bool = False) -> dict[str, float]:
        base = self.total_value if include_cash else self.equity_value
        if base <= 0:
            return {}
        return {p.ticker: p.market_value / base for p in self.positions}

    def theme_weights(self, include_cash: bool = False) -> dict[str, float]:
        base = self.total_value if include_cash else self.equity_value
        if base <= 0:
            return {}
        out: dict[str, float] = {}
        for p in self.positions:
            out[p.theme] = out.get(p.theme, 0.0) + p.market_value / base
        return out

    def funding_plan(self) -> list[tuple[str, float]]:
        """Largest-gap-first ordering for reaching equal cost basis."""
        gaps = [(p.ticker, p.basis_gap) for p in self.positions if p.basis_gap > 0]
        return sorted(gaps, key=lambda kv: kv[1], reverse=True)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_position_limits(book: Book) -> list[Finding]:
    findings: list[Finding] = []
    for ticker, weight in book.weights().items():
        if weight > MAX_SINGLE_POSITION:
            findings.append(
                Finding(
                    Severity.BREACH,
                    "4",
                    f"{ticker} is {weight:.1%} of equity, above the "
                    f"{MAX_SINGLE_POSITION:.0%} single-position cap.",
                    "Either direct new contributions elsewhere until the weight "
                    "falls, or amend §4 in writing. Do not trim a winner purely "
                    "because it won — trim on weight, never on gain.",
                )
            )
        elif weight > MAX_SINGLE_POSITION - WARN_TOLERANCE:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "4",
                    f"{ticker} is {weight:.1%}, within {WARN_TOLERANCE:.0%} of "
                    f"the {MAX_SINGLE_POSITION:.0%} cap.",
                    "Next contributions should go elsewhere.",
                )
            )
    return findings


def _check_structural_consistency(book: Book) -> list[Finding]:
    """The equal-cost-basis structure and the §4 cap constrain each other."""
    n = len(book.positions)
    if n == 0:
        return []
    implied = 1.0 / n
    if implied > MAX_SINGLE_POSITION:
        minimum_positions = int(1 / MAX_SINGLE_POSITION + 0.999)
        return [
            Finding(
                Severity.BREACH,
                "3/4",
                f"Equal-weight across {n} positions implies {implied:.0%} each, "
                f"which exceeds the {MAX_SINGLE_POSITION:.0%} cap. The "
                "equal-cost-basis structure and §4 are mathematically "
                f"incompatible below {minimum_positions} positions.",
                f"Hold at least {minimum_positions} positions, or raise the §4 "
                "cap deliberately. This is not a drift problem — it is the two "
                "rules contradicting each other, and it will not resolve itself.",
            )
        ]
    return []


def _check_themes(book: Book) -> list[Finding]:
    findings: list[Finding] = []
    themes = book.theme_weights()

    ai_complex = sum(w for t, w in themes.items() if t in ("ai_hardware", "ai_platform", "eda"))
    if ai_complex > MAX_AI_COMPLEX:
        findings.append(
            Finding(
                Severity.BREACH,
                "3",
                f"AI/semiconductor complex is {ai_complex:.1%} of equity, above "
                f"the {MAX_AI_COMPLEX:.0%} ceiling.",
                "New money goes to non-correlated names until this clears.",
            )
        )

    eda = themes.get("eda", 0.0)
    low, high = EDA_BAND
    if eda and not (low <= eda <= high):
        direction = "below" if eda < low else "above"
        findings.append(
            Finding(
                Severity.WARNING,
                "3",
                f"EDA sleeve is {eda:.1%}, {direction} the {low:.0%}-{high:.0%} band.",
                "Correct with contributions rather than trades where possible.",
            )
        )

    satellites = [p for p in book.positions if p.sleeve == "satellite"]
    sleeve_weight = sum(book.weights().get(p.ticker, 0.0) for p in satellites)
    if sleeve_weight > MAX_SATELLITE_SLEEVE:
        findings.append(
            Finding(
                Severity.BREACH,
                "3",
                f"Satellite sleeve is {sleeve_weight:.1%}, above "
                f"{MAX_SATELLITE_SLEEVE:.0%}.",
                "Stop adding to speculative names.",
            )
        )
    for p in satellites:
        w = book.weights().get(p.ticker, 0.0)
        if w > MAX_SINGLE_SATELLITE:
            findings.append(
                Finding(
                    Severity.BREACH,
                    "3",
                    f"Satellite {p.ticker} is {w:.1%}, above the "
                    f"{MAX_SINGLE_SATELLITE:.0%} single-satellite cap.",
                    "A satellite that grew into a core position is either "
                    "promoted on its merits, in writing, or trimmed.",
                )
            )
    return findings


def _check_concentration_expiry(
    book: Book, annual_contribution: float
) -> list[Finding]:
    """§5 — concentration is affordable only while contributions can rebuild it."""
    findings: list[Finding] = []
    total = book.total_value
    required = 0.0
    for threshold, floor in EXPIRY_LADDER:
        if total >= threshold:
            required = floor
    non_correlated = book.theme_weights(include_cash=False).get("non_correlated", 0.0)

    drawdown = total * 0.5
    rebuild_years = drawdown / annual_contribution if annual_contribution > 0 else float("inf")

    findings.append(
        Finding(
            Severity.NOTE,
            "5",
            f"Portfolio ${total:,.0f}. A 50% drawdown costs ${drawdown:,.0f} and "
            f"takes {rebuild_years:.1f} years to rebuild at "
            f"${annual_contribution:,.0f}/yr. Required non-correlated floor: "
            f"{required:.0%}. Actual: {non_correlated:.0%}.",
        )
    )

    if non_correlated < required:
        findings.append(
            Finding(
                Severity.BREACH,
                "5",
                f"Non-correlated sleeve is {non_correlated:.0%} against a "
                f"{required:.0%} floor at this portfolio size.",
                "Fund the ballast sleeve before adding to the complex.",
            )
        )
    elif rebuild_years > REBUILD_YEARS_LIMIT and required == 0.0:
        findings.append(
            Finding(
                Severity.WARNING,
                "5",
                f"Rebuild time is {rebuild_years:.1f} years, past the "
                f"{REBUILD_YEARS_LIMIT:.0f}-year limit, but the ladder has not "
                "yet stepped up. The ladder is lagging the arithmetic.",
                "Treat the ballast requirement as live now rather than waiting "
                "for the next threshold.",
            )
        )
    return findings


def _check_cash(book: Book) -> list[Finding]:
    """§3 — cash is permitted only with a purpose AND a date."""
    if book.cash <= 0:
        return []
    weight = book.cash / book.total_value if book.total_value else 0.0
    missing = []
    if not book.cash_purpose.strip():
        missing.append("purpose")
    if not book.cash_decision_date.strip():
        missing.append("decision date")
    if missing:
        return [
            Finding(
                Severity.BREACH,
                "3",
                f"${book.cash:,.0f} cash ({weight:.0%}) with no "
                f"{' and no '.join(missing)} recorded.",
                "Cash is a position. Undated cash is a decision being avoided, "
                "and it compounds at nothing while you avoid it.",
            )
        ]
    return [
        Finding(
            Severity.NOTE,
            "3",
            f"${book.cash:,.0f} cash ({weight:.0%}) held for "
            f"'{book.cash_purpose}', decision due {book.cash_decision_date}.",
        )
    ]


def _check_funding(book: Book) -> list[Finding]:
    plan = book.funding_plan()
    if not plan:
        return []
    total_gap = sum(gap for _, gap in plan)
    lines = ", ".join(f"{t} +${g:,.0f}" for t, g in plan)
    findings = [
        Finding(
            Severity.NOTE,
            "9",
            f"${total_gap:,.0f} needed to bring all positions to the "
            f"${TARGET_COST_BASIS:,.0f} cost-basis target. Largest gap first: {lines}.",
        )
    ]
    if book.cash >= total_gap:
        findings.append(
            Finding(
                Severity.WARNING,
                "9",
                f"Cash (${book.cash:,.0f}) fully covers the ${total_gap:,.0f} "
                "funding gap, yet the gap is still open.",
                "This is a decision already made and not executed. Free cash "
                f"after funding: ${book.cash - total_gap:,.0f}.",
            )
        )
    return findings


def audit(book: Book, annual_contribution: float = ASSUMED_ANNUAL_CONTRIBUTION) -> list[Finding]:
    """Run the full policy audit, most severe first."""
    findings: list[Finding] = []
    findings += _check_structural_consistency(book)
    findings += _check_position_limits(book)
    findings += _check_themes(book)
    findings += _check_concentration_expiry(book, annual_contribution)
    findings += _check_cash(book)
    findings += _check_funding(book)

    order = {Severity.BREACH: 0, Severity.WARNING: 1, Severity.NOTE: 2}
    return sorted(findings, key=lambda f: order[f.severity])

# ============================================================================
# MODULE: rubric.py
# ============================================================================
# The research gate — what an agent must establish before a BUY is admissible.
# ============================================================================
#
# WHAT THIS IS FOR
# ----------------
# This is the part of "let agents pick stocks" that is actually tractable. No
# script can tell you which company wins over ten years. What a script can do is
# refuse to let a recommendation through until the uncomfortable questions have
# been answered with sources attached.
#
# That is not a consolation prize. The dominant failure mode in concentrated
# investing is not bad analysis — it is *incomplete* analysis that felt complete
# because the parts that were easy to research were researched thoroughly and the
# parts that were hard were skipped. A gate that fails on missing evidence
# converts that silent failure into a loud one.
#
# HOW TO USE IT WITH AN AGENT
# ---------------------------
# Hand the agent `brief()` as its instructions. It returns a Brief with every
# field filled and a source per field. Run `Brief.gate()`. If the gate fails,
# the recommendation is not admissible — not "weak", not "needs work".
# Inadmissible. Send it back.
#
# THE TEN-YEAR DISCIPLINE
# -----------------------
# Three fields exist specifically because the horizon is ten years and nothing
# else in a normal writeup addresses that span:
#
#     terminal_question   What must be true in 2036 for this to have worked?
#     obsolescence_path   What technology or business model replaces this?
#     budget_line         Whose budget pays, and is it capital or operating?
#
# The third is the one most writeups omit and the one that most reliably predicts
# how a position behaves in a downturn. Revenue that sits in somebody's capital
# budget gets deferred in lumps. Revenue in an operating budget does not.





class BudgetLine(Enum):
    CAPEX = "capital"
    OPEX = "operating"
    CONSUMER = "consumer discretionary"
    GOVERNMENT = "government appropriation"
    MIXED = "mixed"


class MoatType(Enum):
    REQUALIFICATION = "requalification cost"
    SWITCHING_COST = "switching cost"
    NETWORK_EFFECT = "network effect"
    SCALE = "scale economics"
    REGULATORY = "regulatory barrier"
    BRAND = "brand"
    NONE = "none identified"


@dataclass
class Evidenced:
    """A claim with the source that supports it. Both are required."""

    claim: str
    source: str

    def is_complete(self) -> bool:
        return bool(self.claim.strip()) and bool(self.source.strip())


@dataclass
class Brief:
    """The completed research brief for one candidate."""

    ticker: str
    revenue_model: Evidenced
    budget_line: BudgetLine
    budget_line_evidence: Evidenced
    moat_type: MoatType
    moat_argument: Evidenced
    customer_concentration: Evidenced
    top_customer_pct: float
    tam_claim: Evidenced
    tam_reality_check: Evidenced
    terminal_question: Evidenced
    obsolescence_path: Evidenced
    ways_to_lose: list[Evidenced] = field(default_factory=list)
    tripwires: list[str] = field(default_factory=list)
    correlation_to_book: Evidenced | None = None
    proposed_sleeve: str = "satellite"

    # -- gates ------------------------------------------------------------

    def gate(self) -> tuple[bool, list[str]]:
        """Binary admissibility. Returns (passed, reasons_for_failure)."""
        failures: list[str] = []

        required = {
            "revenue_model": self.revenue_model,
            "budget_line_evidence": self.budget_line_evidence,
            "moat_argument": self.moat_argument,
            "customer_concentration": self.customer_concentration,
            "tam_claim": self.tam_claim,
            "tam_reality_check": self.tam_reality_check,
            "terminal_question": self.terminal_question,
            "obsolescence_path": self.obsolescence_path,
        }
        for name, ev in required.items():
            if ev is None or not ev.is_complete():
                failures.append(
                    f"{name}: missing claim or source. An unsourced assertion is "
                    "not research."
                )

        if len(self.ways_to_lose) < 3:
            failures.append(
                f"ways_to_lose: {len(self.ways_to_lose)} given, 3 required. If you "
                "cannot name three ways to lose money you have not finished "
                "looking — you have finished wanting to look."
            )
        for i, w in enumerate(self.ways_to_lose):
            if not w.is_complete():
                failures.append(f"ways_to_lose[{i}]: missing claim or source.")

        if len(self.tripwires) < 2:
            failures.append(
                f"tripwires: {len(self.tripwires)} given, 2 required. A position "
                "without a written exit condition is a position you will hold "
                "through the thing that should have ended it."
            )
        for i, t in enumerate(self.tripwires):
            if _looks_like_price_rule(t):
                failures.append(
                    f"tripwires[{i}]: {t!r} is a price rule. §7 sells falling "
                    "VALUE, never falling price. A tripwire must name a business "
                    "fact that can be observed independently of the quote."
                )

        if self.moat_type is MoatType.NONE:
            failures.append(
                "moat_type: none identified. §4 requires a moat explainable in "
                "three sentences for any core position."
            )

        if self.correlation_to_book is None or not self.correlation_to_book.is_complete():
            failures.append(
                "correlation_to_book: missing. A candidate must be assessed "
                "against what is already owned, not in isolation."
            )

        if self.proposed_sleeve not in ("core", "satellite"):
            failures.append("proposed_sleeve: must be 'core' or 'satellite'.")

        return (not failures, failures)

    # -- scoring ----------------------------------------------------------

    def quality_flags(self) -> list[str]:
        """Non-blocking observations about the shape of the business."""
        flags: list[str] = []

        if self.top_customer_pct >= 0.30:
            flags.append(
                f"CONCENTRATION: top customer is {self.top_customer_pct:.0%} of "
                "revenue. At this level the customer relationship IS the thesis, "
                "and it should be underwritten as such."
            )
        elif self.top_customer_pct >= 0.15:
            flags.append(
                f"Top customer {self.top_customer_pct:.0%} of revenue — material; "
                "track renewal risk explicitly."
            )

        if self.budget_line is BudgetLine.CAPEX:
            flags.append(
                "CYCLICALITY: revenue sits in a capital budget. Expect lumpy "
                "orders, deferral in downturns, and a far deeper trough than the "
                "end-demand decline implies."
            )
        elif self.budget_line is BudgetLine.OPEX:
            flags.append(
                "Revenue sits in an operating budget — structurally steadier "
                "through a downturn than any capex-funded supplier."
            )
        elif self.budget_line is BudgetLine.GOVERNMENT:
            flags.append(
                "GOVERNMENT-FUNDED: appropriation risk, procurement cycles, and "
                "political exposure. Criticality is a floor under the equity and "
                "a ceiling over the multiple."
            )

        if self.moat_type in (MoatType.REQUALIFICATION, MoatType.SWITCHING_COST):
            flags.append(
                f"Moat type '{self.moat_type.value}' is the most durable kind for "
                "a ten-year hold — it compounds with customer tenure rather than "
                "decaying with competition."
            )
        elif self.moat_type is MoatType.BRAND:
            flags.append(
                "Brand moats erode quietly and are the hardest to monitor. "
                "Tripwires matter more here, not less."
            )

        return flags


def _looks_like_price_rule(text: str) -> bool:
    lowered = text.lower()
    price_words = ("falls", "drops", "declines", "below $", "down ", "%", "price")
    business_words = (
        "revenue", "margin", "guidance", "customer", "budget", "ceo", "license",
        "backlog", "retention", "share", "contract", "approval", "ruling",
    )
    if any(b in lowered for b in business_words):
        return False
    return any(p in lowered for p in price_words)


# ---------------------------------------------------------------------------
# The instruction text handed to a research agent
# ---------------------------------------------------------------------------


def brief(ticker: str, horizon_years: int = 10) -> str:
    """Return the research instructions for one candidate."""
    return f"""\
RESEARCH BRIEF — {ticker}
Horizon: {horizon_years} years. Account: tax-advantaged, no tax friction on sales.

Complete EVERY field. Each requires a specific source — a filing, a transcript,
a dated release. "Analysts expect" and "it is widely believed" are not sources.
If a field cannot be completed, say so explicitly; do not approximate and move
on. An incomplete brief is inadmissible, not weak.

1. REVENUE MODEL
   One sentence: who pays, for what, how often.

2. BUDGET LINE  [capital | operating | consumer | government | mixed]
   Whose budget does this revenue come out of? Cite the customer type.
   This single field predicts downturn behaviour better than any valuation
   metric. Capital budgets get deferred in lumps; operating budgets do not.

3. MOAT  [requalification | switching cost | network effect | scale |
          regulatory | brand | none]
   State it in three sentences. Then answer: what would a well-funded
   competitor have to do to take a major customer, and how long would it take?

4. CUSTOMER CONCENTRATION
   Top customer as % of revenue. Top three combined. Name them. Disclose any
   related-party relationship — a customer who is also an investor is not an
   arm's-length customer.

5. TAM, WITH A REALITY CHECK
   State the published TAM. Then divide the incumbent's actual revenue by it.
   If the ratio is implausible, the TAM study is marketing. Report both numbers.

6. TERMINAL QUESTION
   What must be true in {2026 + horizon_years} for this to have worked? Write it
   as a falsifiable statement, not an aspiration.

7. OBSOLESCENCE PATH
   What technology or business model replaces this, and what would the first
   evidence of it look like? "Nothing" is not an acceptable answer.

8. THREE WAYS TO LOSE MONEY
   Named, specific, sourced. Not "competition" — which competitor, attacking
   which segment, with what. If you cannot find three, you have stopped looking
   rather than finished looking.

9. FACTOR EXPOSURES
   Assign a loading from -1 to +1 for each factor in factors.FACTORS, with a
   one-line basis for each. These feed the scenario engine directly, so a
   careless number here silently corrupts every downstream risk estimate.

10. TWO TRIPWIRES
    Falsifiable business conditions that would end the thesis. NOT price levels.
    §7 sells falling value, never falling price. Each must be observable from a
    filing, a release, or a regulatory action.

11. CORRELATION TO THE EXISTING BOOK
    Against current holdings: what does this add that is not already owned?
    If the answer is "more of the same factor", say so plainly. The purpose of
    a new position is to carry a risk the book does not already carry.

12. PROPOSED SLEEVE  [core | satellite]
    Core requires >= $1,500 and a moat explainable in three sentences.
    Satellite is < $1,500 and an expected outcome of either zero or several
    multiples. Size follows conviction AND durability, not conviction alone.
"""


def gate_report(briefs: Sequence[Brief]) -> str:
    """Human-readable admissibility report across several candidates."""
    lines: list[str] = []
    for b in briefs:
        passed, failures = b.gate()
        status = "ADMISSIBLE" if passed else "INADMISSIBLE"
        lines.append(f"\n{b.ticker}: {status}")
        for f in failures:
            lines.append(f"  FAIL  {f}")
        for flag in b.quality_flags():
            lines.append(f"  FLAG  {flag}")
    return "\n".join(lines)

# ============================================================================
# MODULE: company.py
# ============================================================================
# Single-company evaluation — quality, durability, and what you are paying.
# =========================================================================
#
# WHERE THIS SITS
# ---------------
# `valuation.py` answers "what is it worth". This answers the five questions you
# should settle BEFORE caring what it is worth, because a cheap business that
# destroys capital is not cheap:
#
#   1. Does it create value?      ROIC vs WACC
#   2. Is the growth real?        FCF conversion, accrual quality
#   3. Can it survive?            leverage, interest coverage
#   4. Am I being diluted?        share count trend
#   5. What am I paying?          multiples, in context
#
# THE ONE THAT MATTERS MOST
# -------------------------
#     ROIC - WACC  =  the value-creation spread
#
# If a business earns 8% on invested capital and its capital costs 9%, then every
# dollar it reinvests destroys a cent of value, and GROWTH MAKES IT WORSE. This
# single comparison separates a compounder from a treadmill, and it is absent
# from most retail analysis because it requires reconstructing invested capital
# rather than reading a ratio off a screen.
#
#     NOPAT            = EBIT x (1 - tax rate)
#     Invested capital = total debt + equity - cash
#     ROIC             = NOPAT / invested capital
#
# EARNINGS QUALITY
# ----------------
#     FCF conversion = free cash flow / net income
#
# Sustained conversion below ~0.8 means reported profit is not turning into cash.
# Sometimes that is heavy growth capex, which is fine and temporary. Sometimes it
# is receivables stretching, capitalised costs, or revenue recognised before cash
# arrives, which is neither. The ratio does not tell you which — it tells you
# where to look.
#
# NO DATA FEED
# ------------
# Inputs are entered by hand from filings, same as everywhere else in this
# package. That is a feature: pulling six numbers off an income statement forces
# you to see the statement. Every field names where it comes from.





class Verdict(Enum):
    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    WEAK = "WEAK"
    FAIL = "FAIL"


@dataclass
class Fundamentals:
    """One company, one period. All figures in the same currency and units.

    Source of each field, from the 10-K or 10-Q:
        revenue, revenue_prior   income statement, current and year-ago
        gross_profit             income statement
        ebit                     income statement (operating income)
        net_income               income statement (attributable to common)
        interest_expense         income statement, or the debt footnote
        tax_rate                 effective rate, or 0.21 US federal default
        cfo                      cash flow statement (operating activities)
        capex                    cash flow statement (purchases of PP&E)
        total_debt               balance sheet, short-term + long-term
        cash                     balance sheet, cash + short-term investments
        equity                   balance sheet, total stockholders' equity
        shares_diluted           income statement, diluted weighted average
        shares_diluted_prior     the same, year-ago
        price                    market
    """

    ticker: str
    revenue: float
    revenue_prior: float
    gross_profit: float
    ebit: float
    net_income: float
    cfo: float
    capex: float
    total_debt: float
    cash: float
    equity: float
    shares_diluted: float
    shares_diluted_prior: float
    price: float
    goodwill: float = 0.0
    interest_expense: float = 0.0
    tax_rate: float = 0.21
    wacc: float | None = None
    basis: dict[str, str] = field(default_factory=dict)

    # -- derived ----------------------------------------------------------

    @property
    def fcf(self) -> float:
        """Capex is reported as a negative in the cash flow statement; abs()
        makes the sign convention irrelevant to how the caller enters it."""
        return self.cfo - abs(self.capex)

    @property
    def nopat(self) -> float:
        return self.ebit * (1 - self.tax_rate)

    @property
    def invested_capital(self) -> float:
        return self.total_debt + self.equity - self.cash

    @property
    def invested_capital_ex_goodwill(self) -> float:
        return self.invested_capital - self.goodwill

    @property
    def roic(self) -> float | None:
        """ROIC on TOTAL invested capital, goodwill included.

        For an acquisitive company this answers "was the purchase price worth
        paying", because goodwill is literally the premium paid above book.
        """
        ic = self.invested_capital
        return self.nopat / ic if ic > 0 else None

    @property
    def roic_ex_goodwill(self) -> float | None:
        """ROIC on capital excluding goodwill.

        This answers a DIFFERENT question: are the underlying operations any
        good. Conflating the two is the most common error in analysing a serial
        acquirer. A software company with no factories has enormous returns on
        tangible capital while its balance sheet is mostly goodwill from
        deals — and a low blended ROIC then says the deals were expensive,
        not that the business is bad.

        Read them as a pair:
            ex-GW high,  incl-GW low   -> good business, dear acquisition
            both high                  -> good business bought well
            ex-GW low                  -> the operations themselves do not work
        """
        ic = self.invested_capital_ex_goodwill
        return self.nopat / ic if ic > 0 else None

    @property
    def value_spread(self) -> float | None:
        """ROIC minus WACC. Positive means reinvestment creates value."""
        if self.roic is None or self.wacc is None:
            return None
        return self.roic - self.wacc

    @property
    def value_spread_ex_goodwill(self) -> float | None:
        if self.roic_ex_goodwill is None or self.wacc is None:
            return None
        return self.roic_ex_goodwill - self.wacc

    @property
    def gross_margin(self) -> float:
        return self.gross_profit / self.revenue if self.revenue else 0.0

    @property
    def operating_margin(self) -> float:
        return self.ebit / self.revenue if self.revenue else 0.0

    @property
    def fcf_margin(self) -> float:
        return self.fcf / self.revenue if self.revenue else 0.0

    @property
    def revenue_growth(self) -> float:
        return self.revenue / self.revenue_prior - 1 if self.revenue_prior else 0.0

    @property
    def fcf_conversion(self) -> float | None:
        return self.fcf / self.net_income if self.net_income > 0 else None

    @property
    def net_debt(self) -> float:
        return self.total_debt - self.cash

    @property
    def ebitda_proxy(self) -> float:
        """EBIT is used as an EBITDA stand-in when D&A is not supplied.

        This understates EBITDA and therefore OVERSTATES leverage, which is
        the direction an honest default should err in.
        """
        return self.ebit

    @property
    def net_debt_to_ebitda(self) -> float | None:
        if self.ebitda_proxy <= 0:
            return None
        return self.net_debt / self.ebitda_proxy

    @property
    def interest_coverage(self) -> float | None:
        if self.interest_expense <= 0:
            return None
        return self.ebit / self.interest_expense

    @property
    def share_change(self) -> float:
        if not self.shares_diluted_prior:
            return 0.0
        return self.shares_diluted / self.shares_diluted_prior - 1

    @property
    def market_cap(self) -> float:
        return self.price * self.shares_diluted

    @property
    def enterprise_value(self) -> float:
        return self.market_cap + self.net_debt

    @property
    def pe(self) -> float | None:
        if self.net_income <= 0:
            return None
        return self.market_cap / self.net_income

    @property
    def p_fcf(self) -> float | None:
        return self.market_cap / self.fcf if self.fcf > 0 else None

    @property
    def ev_ebit(self) -> float | None:
        return self.enterprise_value / self.ebit if self.ebit > 0 else None

    @property
    def p_sales(self) -> float:
        return self.market_cap / self.revenue if self.revenue else 0.0

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.revenue <= 0:
            problems.append("revenue must be positive")
        if self.invested_capital <= 0:
            problems.append(
                "invested capital is zero or negative (debt + equity < cash). "
                "ROIC is undefined. This happens at net-cash-rich companies and "
                "means capital intensity is not the binding question for them."
            )
        if self.wacc is None:
            problems.append(
                "no WACC supplied, so the value-creation spread cannot be "
                "computed — and that spread is the most important number here. "
                "Build one with WACCInputs and pass wacc=w.value()."
            )
        for key in ("revenue", "cfo", "total_debt"):
            if key not in self.basis:
                problems.append(f"{key}: no source recorded")
        return problems


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    value: str
    verdict: Verdict
    note: str


def _grade(
    value: float | None,
    strong: float,
    adequate: float,
    weak: float,
    higher_is_better: bool = True,
) -> Verdict:
    if value is None:
        return Verdict.FAIL
    thresholds = (
        [(strong, Verdict.STRONG), (adequate, Verdict.ADEQUATE), (weak, Verdict.WEAK)]
        if higher_is_better
        else [(strong, Verdict.STRONG), (adequate, Verdict.ADEQUATE), (weak, Verdict.WEAK)]
    )
    for threshold, verdict in thresholds:
        if (higher_is_better and value >= threshold) or (
            not higher_is_better and value <= threshold
        ):
            return verdict
    return Verdict.FAIL


def scorecard(f: Fundamentals) -> list[Check]:
    """The five questions, graded."""
    checks: list[Check] = []

    # 1. Value creation
    spread = f.value_spread
    if spread is None:
        checks.append(
            Check(
                "ROIC vs WACC",
                "not computable",
                Verdict.FAIL,
                "Supply wacc= and ensure invested capital is positive. Without "
                "this you cannot tell a compounder from a treadmill.",
            )
        )
    else:
        ex_gw = f.value_spread_ex_goodwill
        if f.goodwill > 0 and ex_gw is not None and ex_gw > 0 and spread <= 0:
            checks.append(
                Check(
                    "ROIC vs WACC",
                    f"{f.roic:.1%} incl goodwill vs {f.roic_ex_goodwill:.1%} "
                    f"ex-goodwill, WACC {f.wacc:.1%}",
                    Verdict.ADEQUATE,
                    f"SPLIT VERDICT. On total capital the spread is "
                    f"{spread:+.1%}; excluding ${f.goodwill:,.0f} of goodwill "
                    f"it is {ex_gw:+.1%}. The operations earn well above the "
                    "cost of capital; the ACQUISITION PRICE is what drags the "
                    "blended figure down. The question is not whether the "
                    "business is good — it is whether the deal was worth it, "
                    "and that is answered by the blended ROIC rising over the "
                    "next few years as acquired earnings scale into a fixed "
                    "capital base. Flat or falling two years on means it was not.",
                )
            )
        else:
            checks.append(
            Check(
                "ROIC vs WACC",
                f"{f.roic:.1%} vs {f.wacc:.1%} = {spread:+.1%}",
                _grade(spread, 0.10, 0.03, 0.0),
                "THE test. Positive means reinvested capital creates value and "
                "growth compounds. Negative means growth destroys value and "
                "the company should be returning cash instead."
                if spread > 0
                else "NEGATIVE SPREAD. Every dollar reinvested destroys value. "
                "Growth makes this worse, not better. A low multiple here is "
                "not cheapness, it is the market pricing a treadmill.",
            )
        )

    # 2. Earnings quality
    conv = f.fcf_conversion
    checks.append(
        Check(
            "FCF conversion",
            "n/a (loss-making)" if conv is None else f"{conv:.2f}x",
            Verdict.WEAK if conv is None else _grade(conv, 1.0, 0.8, 0.6),
            "FCF / net income. Below ~0.8 sustained means reported profit is "
            "not becoming cash. Could be growth capex (fine, temporary) or "
            "receivables and capitalised costs (not fine). The ratio says "
            "where to look, not which it is.",
        )
    )

    # 3. Solvency
    nde = f.net_debt_to_ebitda
    if f.net_debt < 0:
        checks.append(
            Check(
                "Leverage",
                f"net CASH ${abs(f.net_debt):,.0f}",
                Verdict.STRONG,
                "Net cash. Survives a downturn without needing anyone's "
                "permission, which is the whole point of a balance sheet.",
            )
        )
    else:
        checks.append(
            Check(
                "Net debt / EBIT",
                "n/a" if nde is None else f"{nde:.1f}x",
                _grade(nde, 1.0, 2.5, 4.0, higher_is_better=False),
                "Uses EBIT as an EBITDA proxy, which overstates leverage — the "
                "safe direction to be wrong in. Above ~4x, refinancing risk "
                "starts driving the equity story.",
            )
        )

    cover = f.interest_coverage
    if cover is not None:
        checks.append(
            Check(
                "Interest coverage",
                f"{cover:.1f}x",
                _grade(cover, 8.0, 4.0, 2.0),
                "EBIT / interest expense. Below 2x, a bad year becomes a "
                "solvency question rather than an earnings question.",
            )
        )

    # 4. Dilution
    chg = f.share_change
    checks.append(
        Check(
            "Share count",
            f"{chg:+.1%} YoY",
            _grade(-chg, 0.01, -0.01, -0.03),
            "Buybacks shrink the count and raise per-share value. Steady "
            "issuance means your claim is being diluted — stock compensation "
            "is a real cost even though it never appears as cash.",
        )
    )

    # 5. Profitability
    checks.append(
        Check(
            "Operating margin",
            f"{f.operating_margin:.1%}",
            _grade(f.operating_margin, 0.25, 0.12, 0.05),
            "Pricing power and operating leverage. Compare within an industry "
            "only — a distributor at 5% can be excellent and a software "
            "company at 15% can be in trouble.",
        )
    )
    checks.append(
        Check(
            "Revenue growth",
            f"{f.revenue_growth:+.1%} YoY",
            _grade(f.revenue_growth, 0.15, 0.06, 0.0),
            "Growth is only good when the value spread is positive. Pair this "
            "check with the first one; never read it alone.",
        )
    )

    return checks


def multiples_block(f: Fundamentals) -> list[str]:
    lines = ["", "WHAT YOU ARE PAYING", "-" * 72]
    rows = [
        ("P/E", f.pe, "x"),
        ("P/FCF", f.p_fcf, "x"),
        ("EV/EBIT", f.ev_ebit, "x"),
        ("P/Sales", f.p_sales, "x"),
    ]
    for name, value, unit in rows:
        shown = "n/a (negative)" if value is None else f"{value:.1f}{unit}"
        lines.append(f"  {name:<10} {shown}")
    lines.append(f"  {'Market cap':<10} ${f.market_cap:,.0f}")
    lines.append(f"  {'EV':<10} ${f.enterprise_value:,.0f}")
    lines.append(
        "\n  A multiple is meaningless alone. It is only informative against "
        "this\n  company's own history and against the value spread above. "
        "A high\n  multiple on a wide positive spread can be cheap; a low one on "
        "a\n  negative spread is a value trap with a tidy ratio."
    )
    return lines


def evaluate(f: Fundamentals) -> str:
    """Full single-company report."""
    rule = "=" * 72
    out = [rule, f"COMPANY EVALUATION — {f.ticker}   (price ${f.price:,.2f})", rule]

    problems = f.validate()
    if problems:
        out.append("\nINPUT PROBLEMS:")
        out.extend(f"  ! {p}" for p in problems)

    out.append("")
    out.append("THE FIVE QUESTIONS")
    out.append("-" * 72)

    counts = {v: 0 for v in Verdict}
    for check in scorecard(f):
        counts[check.verdict] += 1
        out.append(f"\n  [{check.verdict.value:<8}] {check.name}: {check.value}")
        for line in _wrap(check.note, 66):
            out.append(f"             {line}")

    out.extend(multiples_block(f))

    out.append("")
    out.append("SUMMARY")
    out.append("-" * 72)
    out.append(
        f"  {counts[Verdict.STRONG]} strong, {counts[Verdict.ADEQUATE]} adequate, "
        f"{counts[Verdict.WEAK]} weak, {counts[Verdict.FAIL]} failing"
    )
    spread = f.value_spread
    ex_gw = f.value_spread_ex_goodwill
    if spread is not None and spread <= 0 and ex_gw is not None and ex_gw > 0:
        out.append(
            "\n  CONCLUSION: the blended spread is negative but the ex-goodwill\n"
            "  spread is positive. This is an acquisition-price question, not a\n"
            "  business-quality question. Monitor whether blended ROIC rises."
        )
    elif spread is not None and spread <= 0:
        out.append(
            "\n  OVERRIDING CONCLUSION: the value spread is negative. Whatever "
            "else\n  scores well, this business does not earn its cost of "
            "capital, and\n  growth therefore subtracts value. Treat every other "
            "metric as\n  secondary until that changes."
        )
    elif counts[Verdict.FAIL] or counts[Verdict.WEAK] >= 3:
        out.append(
            "\n  Multiple weak or failing checks. Not disqualifying on its own — "
            "a\n  turnaround looks exactly like this — but the thesis has to "
            "explain\n  each one explicitly rather than hope it resolves."
        )
    out.append(f"\n{rule}")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines

# ============================================================================
# MODULE: scenarios.py
# ============================================================================
# Scenario transmission engine — "what breaks, and roughly how much".
# ===================================================================
#
# METHOD
# ------
# A scenario is a named vector of factor shocks plus the reasoning that justifies
# it. Position impact is the dot product of the position's factor exposures with
# the scenario's shock vector:
#
#     r_i = sum_f  exposure[i][f] * shock[f]
#
# Portfolio impact is the weight-average of position impacts. Because the mapping
# is linear, every number the engine prints can be decomposed back into "this
# much of the loss came from this factor", which is the only property that makes
# a risk model arguable rather than oracular.
#
# WHY SCENARIOS AND NOT VALUE-AT-RISK
# -----------------------------------
# VaR answers "how bad is a bad day" using the covariance of the recent past. It
# is useless for the risks that actually threaten a ten-year concentrated book,
# because those risks have no history in the sample: an export-control regime
# change, a founder leaving, a siting moratorium. Scenario analysis handles
# exactly these — you specify the shock rather than estimating it from returns
# that never contained one.
#
# The cost is that a scenario is only as good as its calibration, and calibration
# is judgment. Hence `rationale` and `analogue` on every scenario. A scenario
# without a historical analogue is a number someone made up.
#
# SEVERITY CONVENTION
# -------------------
# Shocks are the equity impact on a hypothetical PURE PLAY with exposure 1.0.
# They are deliberately severe — a scenario calibrated to a mild outcome tells
# you nothing you did not already know. These are "this is a bad year" levels,
# not "this is the end" levels, except where marked.






@dataclass(frozen=True)
class Scenario:
    """A named macro shock with its justification."""

    key: str
    name: str
    shocks: Mapping[str, float]
    rationale: str
    analogue: str
    probability_note: str = ""

    def __post_init__(self) -> None:
        for factor in self.shocks:
            if factor not in FACTORS:
                raise ValueError(f"{self.key}: unknown factor {factor!r}")
        if not self.analogue.strip():
            raise ValueError(
                f"{self.key}: no historical analogue. A scenario you cannot "
                "anchor to something that has actually happened is a number "
                "you invented."
            )


TOTAL_LOSS = -1.0


@dataclass
class PositionImpact:
    ticker: str
    weight: float
    raw_return: float
    by_factor: dict[str, float] = field(default_factory=dict)

    @property
    def total_return(self) -> float:
        """Impact floored at a total loss.

        The factor model is LINEAR and ADDITIVE, so a position loading heavily
        on several factors that a scenario all shocks at once can compute below
        -100%. That is arithmetically meaningless for a long equity position:
        you cannot lose more than you paid.

        It is also a warning about the method rather than a finding about the
        company. Real factor shocks to a single name are correlated, not
        additive — a memory price collapse IS partly a beta event for a memory
        company, so counting both at full weight double-counts. When a position
        hits this floor, read the scenario as "this position is probably a
        total loss here" and stop trying to read precision into the number.
        """
        return max(self.raw_return, TOTAL_LOSS)

    @property
    def floored(self) -> bool:
        return self.raw_return < TOTAL_LOSS

    @property
    def contribution(self) -> float:
        """This position's share of the portfolio-level move."""
        return self.weight * self.total_return

    def dominant_factor(self) -> tuple[str, float]:
        if not self.by_factor:
            return ("none", 0.0)
        return min(self.by_factor.items(), key=lambda kv: kv[1])


@dataclass
class ScenarioResult:
    scenario: Scenario
    positions: list[PositionImpact]
    portfolio_return: float

    def factor_attribution(self) -> dict[str, float]:
        """Decompose the portfolio move into weighted factor contributions."""
        out: dict[str, float] = {}
        for pos in self.positions:
            for factor, impact in pos.by_factor.items():
                out[factor] = out.get(factor, 0.0) + pos.weight * impact
        return dict(sorted(out.items(), key=lambda kv: kv[1]))

    def dollar_impact(self, portfolio_value: float) -> float:
        return portfolio_value * self.portfolio_return


# ---------------------------------------------------------------------------
# The scenario library
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {
    "ai_capex_winter": Scenario(
        key="ai_capex_winter",
        name="AI capex winter",
        shocks={"ai_capex": -0.40, "semi_rd": -0.10, "market_beta": -0.12},
        rationale=(
            "Hyperscalers cut AI capital spending ~30% after a year in which "
            "monetization disappoints relative to the buildout. Suppliers take "
            "the hit first and hardest; R&D budgets follow much later and much "
            "less, because design programs already underway are expensive to "
            "stop and restart."
        ),
        analogue=(
            "Telecom equipment 2001-02: carrier capex fell ~50% from peak and "
            "equipment vendors lost 70-90% while the services layer survived. "
            "Also memory 2019 and 2023, where capex cuts led revenue by "
            "two to three quarters."
        ),
        probability_note=(
            "Not a forecast. This is the single most likely way a concentrated "
            "AI book loses half its value, so it is the scenario that should "
            "set position sizing."
        ),
    ),
    "datacenter_moratorium": Scenario(
        key="datacenter_moratorium",
        name="Data-center siting moratorium wave",
        shocks={"ai_capex": -0.22, "regulatory": -0.08, "market_beta": -0.05},
        rationale=(
            "State and local siting restrictions spread materially. The binding "
            "constraint becomes permits and interconnection rather than capital "
            "or chips. Buildout slows without demand falling, which compresses "
            "supplier revenue while leaving the demand narrative intact — so "
            "multiples hold up better than in a true capex winter."
        ),
        analogue=(
            "Already in motion: New York EO 62 (14 July 2026) paused permits "
            "above 50MW; moratorium bills pending in PA (HB 2533), MI (SB "
            "1018/1020), OK, NH, SD; 16 states considered statewide measures in "
            "2026 per NCSL. Oregon and Virginia have enacted differential "
            "pricing and consumption taxes respectively."
        ),
        probability_note=(
            "Partially realized already. The question is magnitude, not whether."
        ),
    ),
    "eda_export_denial": Scenario(
        key="eda_export_denial",
        name="EDA export regime tightens to denial",
        shocks={"china_policy": -0.35, "semi_rd": -0.05},
        rationale=(
            "BIS moves EDA from license-required to effective license-denial "
            "for China, or expands restricted ECCNs. China revenue goes to "
            "approximately zero rather than merely declining, and Design IP "
            "takes a second hit as design starts stop."
        ),
        analogue=(
            "The 29 May 2025 'is-informed' letter already did a milder version "
            "of this: Synopsys China revenue fell 22% in FY2025 from a ~$1B / "
            "~16%-of-revenue base. Equipment precedent is harsher — the October "
            "2022 and 2023 rules took some tool vendors' China business down by "
            "more than half."
        ),
        probability_note=(
            "Elevated. Chip Security Act and AI Overwatch Act are moving "
            "through the NDAA; a Democratic Congress with subpoena power seats "
            "on 3 January 2027; the Huang affair has discredited the industry's "
            "principal lobbyist against controls."
        ),
    ),
    "semi_rd_recession": Scenario(
        key="semi_rd_recession",
        name="Semiconductor R&D recession",
        shocks={"semi_rd": -0.45, "ai_capex": -0.25, "market_beta": -0.15},
        rationale=(
            "Aggregate R&D spending at the top five semiconductor customers "
            "declines year over year. This is the scenario that actually breaks "
            "an EDA thesis, because a take-rate business shrinks with the base "
            "no matter how good the software or how high the share. It has "
            "historically required a genuine industry downturn, not merely a "
            "soft patch."
        ),
        analogue=(
            "2008-09 and 2001-02 are the only two periods in modern "
            "semiconductor history when aggregate industry R&D actually "
            "declined year over year. Even the 2019 and 2023 memory busts left "
            "R&D growing."
        ),
        probability_note=(
            "Low probability, high severity. This is the SNPS-2 tripwire: watch "
            "the budgets, not the stock price."
        ),
    ),
    "agentic_seat_compression": Scenario(
        key="agentic_seat_compression",
        name="Agentic AI compresses SaaS seat counts",
        shocks={
            "saas_disintermediation": -0.45,
            "digital_services_tax": -0.08,
            "enterprise_it": -0.15,
            "market_beta": -0.08,
        },
        rationale=(
            "Per-seat pricing breaks down as agents do work that previously "
            "required headcount. Customers renew at lower seat counts, and the "
            "vendor's migration to consumption pricing does not keep pace. "
            "State digital-services taxes add a parallel squeeze on the same "
            "budget line. Note that revenue keeps growing throughout the early "
            "phase — the damage shows in cRPO and in the multiple long before "
            "it reaches the income statement, which is what makes it so easy to "
            "dismiss as sentiment."
        ),
        analogue=(
            "Already in motion. ServiceNow is down ~44% over the year to "
            "November 2026 against the S&P up ~11%, while Q3 2026 subscription "
            "revenue grew 21% and FCF margin guidance ROSE to 36%. The entire "
            "decline to date is multiple compression on a forward thesis. "
            "Structural precedent: Nokia and BlackBerry kept growing revenue "
            "for several quarters after the iPhone made their pricing model "
            "obsolete."
        ),
        probability_note=(
            "Partially realized. The open question is whether consumption "
            "pricing substitutes for lost seats fast enough. Q4 cRPO is the "
            "test, not revenue and not margin."
        ),
    ),
    "gov_budget_squeeze": Scenario(
        key="gov_budget_squeeze",
        name="Government space and industrial-policy budget squeeze",
        shocks={"gov_appropriation": -0.35, "market_beta": -0.10},
        rationale=(
            "Appropriations tighten under divided government and deficit "
            "politics. Civil space, defense space and industrial-policy "
            "subsidies are discretionary and therefore first in line. Included "
            "specifically so that the ballast candidates are stressed on THEIR "
            "risk rather than only on the book's existing ones — a diversifier "
            "that is never stress-tested is just an unexamined position."
        ),
        analogue=(
            "NASA budget flatlined in real terms through most of the 2010s. "
            "Sequestration (2013) cut defense procurement ~8% across the board. "
            "CHIPS Act disbursement has repeatedly slipped against schedule."
        ),
    ),
    "memory_cycle_bust": Scenario(
        key="memory_cycle_bust",
        name="Memory capacity cycle turns",
        shocks={
            "commodity_cycle": -0.55,
            "ai_capex": -0.15,
            "market_beta": -0.12,
            "semi_rd": -0.05,
        },
        rationale=(
            "The capacity funded at peak margins arrives. Gross margins "
            "normalize from the high 80s toward the long-run 25-35% "
            "mid-cycle level, and because operating leverage works both ways, "
            "earnings fall far more than revenue does. Note what this scenario "
            "does NOT require: no demand collapse, no thesis being wrong, no "
            "recession. It requires only that the industry does what peak "
            "margins have always caused it to do, which is build."
        ),
        analogue=(
            "Every memory cycle on record. 2017-19: DRAM contract prices fell "
            "roughly 60% from peak and Micron's gross margin went from ~61% to "
            "~20% in five quarters. 2021-23: a second round, with Micron "
            "posting negative gross margins at the trough. In both cases "
            "revenue stayed positive the whole way down while the equity fell "
            "60-80%. The lag from capex decision to new supply is two to three "
            "years, which is why the peak looks most durable right before it "
            "is not."
        ),
        probability_note=(
            "Not a forecast of timing. The scenario exists because an 87% "
            "gross margin in a fungible-product industry has a half-life, and "
            "the capex that ends it has already been committed."
        ),
    ),
    "rate_shock_150bp": Scenario(
        key="rate_shock_150bp",
        name="Long-rate shock, +150bp on the 10Y",
        shocks={"rates_duration": -0.30, "market_beta": -0.10, "market_volatility": -0.20},
        rationale=(
            "Term premium expands on fiscal supply and a re-steepening curve. "
            "High-multiple equities de-rate in proportion to duration: the "
            "further out the cash flows, the harder the discounting bites. No "
            "earnings downgrade is required for this to hurt."
        ),
        analogue=(
            "2022: the 10Y rose roughly 230bp and the highest-multiple software "
            "names lost 50-70% with revenue still growing. Multiple compression "
            "alone did all of it."
        ),
    ),
    "broad_drawdown": Scenario(
        key="broad_drawdown",
        name="Broad equity drawdown, -25%",
        shocks={"market_beta": -0.25, "rates_duration": -0.10, "market_volatility": -0.30,
                "consumer_spending": -0.15, "commodity_cycle": -0.20},
        rationale=(
            "A garden-variety bear market with no thesis-specific cause. "
            "Included because it is the most likely large loss in any given "
            "decade and because it tests the concentration-expiry arithmetic "
            "without requiring anything in the book to be wrong."
        ),
        analogue=(
            "The S&P 500 has drawn down 20%+ roughly once every six years since "
            "1950. Over a ten-year horizon this is closer to a certainty than "
            "a scenario."
        ),
    ),
    "ai_leadership_crisis": Scenario(
        key="ai_leadership_crisis",
        name="Governance shock at an AI bellwether",
        shocks={"ai_capex": -0.15, "market_beta": -0.10, "regulatory": -0.15},
        rationale=(
            "A founder-dependent leader at a systemically important AI company "
            "departs abruptly under a cloud. Direct damage is modest and "
            "company-specific; the transmission is sentiment and an invitation "
            "to policymakers who were already looking for a reason to act."
        ),
        analogue=(
            "NVIDIA, November 2026: Huang resigned amid an alleged Chinese "
            "intelligence matter; the stock fell 11-12%, bipartisan calls for a "
            "federal probe followed, and lawmakers moved to attach the Chip "
            "Security Act and AI Overwatch Act to the NDAA."
        ),
        probability_note="Realized once already in this book's lifetime.",
    ),
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def run_scenario(
    scenario: Scenario,
    exposures: Mapping[str, ExposureSet],
    weights: Mapping[str, float],
) -> ScenarioResult:
    """Apply one scenario to a weighted book."""
    impacts: list[PositionImpact] = []
    for ticker, weight in weights.items():
        profile = exposures.get(ticker)
        if profile is None:
            raise KeyError(
                f"no factor profile for {ticker!r}. Declare one in factors.py "
                "before putting it in the book — an undeclared position is an "
                "unmeasured risk."
            )
        betas = profile.as_map()
        by_factor = {
            factor: betas.get(factor, 0.0) * shock
            for factor, shock in scenario.shocks.items()
            if betas.get(factor, 0.0) != 0.0
        }
        impacts.append(
            PositionImpact(
                ticker=ticker,
                weight=weight,
                raw_return=sum(by_factor.values()),
                by_factor=by_factor,
            )
        )
    portfolio_return = sum(i.contribution for i in impacts)
    return ScenarioResult(scenario, impacts, portfolio_return)


def run_all(
    exposures: Mapping[str, ExposureSet],
    weights: Mapping[str, float],
    keys: Sequence[str] | None = None,
) -> list[ScenarioResult]:
    """Run the full library (or a named subset), worst outcome first."""
    chosen = [SCENARIOS[k] for k in keys] if keys else list(SCENARIOS.values())
    results = [run_scenario(s, exposures, weights) for s in chosen]
    return sorted(results, key=lambda r: r.portfolio_return)

# ============================================================================
# MODULE: risk.py
# ============================================================================
# Concentration and correlation diagnostics — measuring what you cannot see.
# ==========================================================================
#
# THE PROBLEM THIS SOLVES
# -----------------------
# A book of three or four names *feels* diversified because it has more than one
# name in it. Whether it actually is depends on whether those names lose money
# for the same reason, and that is not something intuition is good at. These are
# the numbers that answer it.
#
# EFFECTIVE NUMBER OF POSITIONS (inverse Herfindahl)
# --------------------------------------------------
#     HHI  = sum_i w_i^2
#     N_eff = 1 / HHI
#
# Four equal positions give N_eff = 4. Four positions weighted 70/10/10/10 give
# N_eff = 2.0 — you own four things and carry the concentration of two. N_eff
# counts *weights only*; it says nothing about whether the positions are alike.
#
# EFFECTIVE NUMBER OF BETS (correlation-adjusted)
# -----------------------------------------------
#     DR    = (sum_i w_i * sigma_i) / sigma_portfolio
#     N_bet = DR^2
#
# The diversification ratio compares the weighted-average standalone volatility
# to the realized portfolio volatility. If positions were uncorrelated the
# portfolio vol would be much lower than the average, DR would be large, and
# N_bet would approach the position count. When everything moves together, DR
# approaches 1 and N_bet approaches 1 — you own one bet wearing several tickers.
#
# This is the number that matters for a thematic book, and it is almost always
# worse than the position count suggests.
#
# FACTOR CONCENTRATION
# --------------------
# Weight-average absolute factor exposure across the book. A book can look
# diversified by ticker, by sector, even by correlation over a quiet sample, and
# still have every position loading on the same factor. This catches that
# directly rather than inferring it from returns that may not contain a shock.
#
# DATA NOTE
# ---------
# Correlation requires a return history, which this package does not fetch for
# you. Supply a DataFrame of daily closes (dates x tickers) from whatever source
# you use. Without it, the weight-based metrics still work and the
# correlation-based ones are skipped rather than faked.






TRADING_DAYS = 252


@dataclass
class ConcentrationReport:
    n_positions: int
    hhi: float
    effective_positions: float
    largest_weight: float
    largest_ticker: str
    top_two_share: float

    def verdict(self) -> str:
        ratio = self.effective_positions / self.n_positions if self.n_positions else 0.0
        if ratio > 0.90:
            evenness = "Evenly weighted — weight concentration is not the issue."
        elif ratio > 0.70:
            evenness = "Mild weight concentration; tolerable."
        else:
            evenness = (
                f"Heavy weight concentration: {self.n_positions} positions "
                f"carrying the risk of {self.effective_positions:.1f}."
            )
        if self.n_positions < 4:
            evenness += (
                f" Separately: {self.n_positions} positions is a small absolute "
                "count. Even weighting does not help when a single thesis error "
                "costs a third of the book — and this metric cannot see whether "
                "the positions are alike. Read it with the factor table below."
            )
        return evenness


@dataclass
class CorrelationReport:
    tickers: list[str]
    matrix: pd.DataFrame
    average_pairwise: float
    diversification_ratio: float
    effective_bets: float
    portfolio_vol: float
    window_days: int

    def verdict(self) -> str:
        if self.average_pairwise > 0.75:
            quality = (
                "These are not separate positions in any risk sense. They are "
                "one bet with several tickers on it."
            )
        elif self.average_pairwise > 0.55:
            quality = (
                "Substantially the same bet. Diversification here is nominal, "
                "not economic."
            )
        elif self.average_pairwise > 0.35:
            quality = "Related but not identical. Some genuine spread of risk."
        else:
            quality = "Genuinely distinct risk drivers."
        return (
            f"Average pairwise correlation {self.average_pairwise:.2f} over "
            f"{self.window_days} days. Effective bets: {self.effective_bets:.1f} "
            f"across {len(self.tickers)} positions. {quality}"
        )


@dataclass
class FactorConcentration:
    loadings: dict[str, float]

    def dominant(self) -> tuple[str, float]:
        if not self.loadings:
            return ("none", 0.0)
        return max(self.loadings.items(), key=lambda kv: abs(kv[1]))

    def verdict(self) -> str:
        factor, load = self.dominant()
        if abs(load) > 0.70:
            return (
                f"Dominant factor '{factor}' at {load:+.2f} weighted loading. "
                "A single shock to this factor moves most of the book at once; "
                "position count is not protecting you."
            )
        if abs(load) > 0.45:
            return f"Concentrated in '{factor}' at {load:+.2f}; material but not extreme."
        return f"No single factor dominates; largest is '{factor}' at {load:+.2f}."


def concentration(weights: Mapping[str, float]) -> ConcentrationReport:
    if not weights:
        raise ValueError("no weights supplied")
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    w = np.array([v for _, v in items], dtype=float)
    total = w.sum()
    if not np.isclose(total, 1.0, atol=1e-6):
        w = w / total  # normalize rather than refuse; callers pass sub-books
    hhi = float(np.sum(w**2))
    return ConcentrationReport(
        n_positions=len(items),
        hhi=hhi,
        effective_positions=1.0 / hhi,
        largest_weight=float(w[0]),
        largest_ticker=items[0][0],
        top_two_share=float(w[:2].sum()),
    )


def correlation(
    prices: pd.DataFrame, weights: Mapping[str, float]
) -> CorrelationReport:
    """Correlation diagnostics from a dates x tickers frame of closes."""
    tickers = [t for t in weights if t in prices.columns]
    missing = [t for t in weights if t not in prices.columns]
    if missing:
        raise KeyError(f"no price history for: {missing}")
    if len(tickers) < 2:
        raise ValueError("correlation needs at least two positions with history")

    # fill_method=None is explicit for cross-version pandas: 2.1+ deprecated
    # the old forward-filling default, and silently filling gaps would
    # manufacture zero-return days that bias correlation upward.
    rets = prices[tickers].pct_change(fill_method=None).dropna()
    if len(rets) < 60:
        raise ValueError(
            f"only {len(rets)} return observations; correlation estimated on "
            "less than a quarter of data is noise."
        )

    w = np.array([weights[t] for t in tickers], dtype=float)
    w = w / w.sum()

    corr = rets.corr()
    cov = rets.cov().to_numpy() * TRADING_DAYS
    vols = np.sqrt(np.diag(cov))

    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(port_var))
    weighted_avg_vol = float(w @ vols)
    dr = weighted_avg_vol / port_vol if port_vol > 0 else 1.0

    n = len(tickers)
    upper = corr.to_numpy()[np.triu_indices(n, k=1)]

    return CorrelationReport(
        tickers=tickers,
        matrix=corr,
        average_pairwise=float(np.mean(upper)),
        diversification_ratio=dr,
        effective_bets=dr**2,
        portfolio_vol=port_vol,
        window_days=len(rets),
    )


def factor_concentration(
    exposures: Mapping[str, ExposureSet], weights: Mapping[str, float]
) -> FactorConcentration:
    """Weight-average factor loading across the book."""
    out: dict[str, float] = {}
    total = sum(weights.values()) or 1.0
    for ticker, weight in weights.items():
        profile = exposures.get(ticker)
        if profile is None:
            continue
        for factor, beta in profile.as_map().items():
            out[factor] = out.get(factor, 0.0) + beta * (weight / total)
    return FactorConcentration(dict(sorted(out.items(), key=lambda kv: -abs(kv[1]))))


def rebuild_years(
    portfolio_value: float, drawdown_pct: float, annual_contribution: float
) -> float:
    """Years of contributions required to replace a drawdown of given depth."""
    if annual_contribution <= 0:
        return float("inf")
    return (portfolio_value * drawdown_pct) / annual_contribution


def horizon_grid(
    portfolio_value: float,
    annual_contribution: float,
    depths: tuple[float, ...] = (0.25, 0.40, 0.50, 0.65),
) -> list[tuple[float, float, float]]:
    """(depth, dollars lost, years to rebuild) across a range of drawdowns.

    The point of the grid is that the ladder in §5 is a step function applied to
    a continuous problem. Seeing the whole curve makes it obvious where the
    policy's thresholds actually bite.
    """
    return [
        (d, portfolio_value * d, rebuild_years(portfolio_value, d, annual_contribution))
        for d in depths
    ]

# ============================================================================
# MODULE: review.py
# ============================================================================
# Portfolio review — the entry point that ties the package together.
# ==================================================================
#
# USAGE
# -----
#     python3.13 -m mandate.review
#     python3.13 -m mandate.review --portfolio portfolio.json
#     python3.13 -m mandate.review --prices closes.csv       # enables correlation
#     python3.13 -m mandate.review --candidate AMD           # add a hypothetical
#     python3.13 -m mandate.review --brief AMD               # print research brief
#
# `--prices` expects a CSV with a date index and one column per ticker of
# adjusted closes. Without it, correlation diagnostics are SKIPPED rather than
# estimated from nothing — a correlation number invented from no data is worse
# than no correlation number.
#
# `--candidate TICKER` re-runs the whole review with that candidate added at the
# equal-cost-basis target, so you can see what a position would do to the book
# BEFORE buying it rather than after.






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
        flag = "  TOTAL LOSS (model floored; see note)" if pos.floored else ""
        print(
            f"    {pos.ticker:<7} {pos.total_return:>7.1%}   "
            f"(worst factor: {factor} at {impact:+.1%}){flag}"
        )
    if any(p.floored for p in worst.positions):
        print(
            "\n  NOTE: a position computed below -100% and was floored. The\n"
            "  factor model is additive, so heavy loadings on several factors\n"
            "  that one scenario shocks together overstate the loss — real\n"
            "  shocks to a single name are correlated, not additive. Read it\n"
            "  as 'probably a total loss here', not as a precise figure."
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


def script_dir() -> Path:
    """Directory of this file, or the working directory when run interactively.

    `__file__` is undefined when a function is called from an interactive
    console — Spyder's runfile sets it during execution and it is not present
    afterwards. Depending on it means `main()` works on F5 and raises
    NameError the moment someone calls it from the prompt, which is exactly
    the workflow this tool is meant to support.
    """
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    here = script_dir()
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




# ============================================================================
# STANDALONE ENTRY POINT
# ============================================================================
#
# Writes the embedded portfolio to disk if no JSON is present, then runs
# the review. In Spyder: press F5. In a terminal: python <thisfile>.py


def _ensure_portfolio() -> Path:
    path = script_dir() / 'portfolio.json'
    if not path.exists():
        path.write_text(json.dumps(_EMBEDDED_PORTFOLIO, indent=2), encoding='utf-8')
        print(f'Wrote a starter portfolio to {path}')
        print('Edit it with your real market values, then run again.\n')
    return path


if __name__ == '__main__':
    main(['--portfolio', str(_ensure_portfolio())])
