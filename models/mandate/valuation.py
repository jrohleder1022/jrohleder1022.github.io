"""
Intrinsic value — DCF, reverse DCF, sensitivity, and multiple convergence.
==========================================================================

THE PROBLEM WITH DCF, STATED PLAINLY
------------------------------------
For a growth company, 70-85% of the present value a DCF produces sits in the
TERMINAL VALUE — a number derived from assumptions about year 11 onward that
nobody can verify. The explicit forecast period, where all the apparent work
happens, usually drives less than a third of the answer.

This means a forward DCF is mostly a restatement of your terminal assumptions
with extra arithmetic in front of it. Change terminal growth by 100bp and the
"intrinsic value" moves 20-30%. That is not a valuation; it is an opinion
wearing a spreadsheet.

So this module does three things differently from a stock DCF:

  1. It REPORTS the terminal value share and warns loudly above 75%. If most
     of your answer comes from year 11+, you should know that before you act
     on it.

  2. It leads with REVERSE DCF. Instead of "my model says $X so the stock is
     cheap", it asks "what growth does today's price require, and is that
     plausible?" That question is falsifiable. The forward one mostly is not.

  3. It cross-checks against MULTIPLE CONVERGENCE, which needs no terminal
     assumption at all:

         annualized return ~= EPS growth + annualized multiple change

     This is the framework that showed SNPS at ~23%/yr against CDNS at ~7%/yr
     on identical EPS growth, with the entire difference coming from the
     starting multiple.

WHEN A DCF IS THEATRE
---------------------
`dcf()` refuses to run on negative free cash flow. A DCF on a pre-profit
company values the terminal assumption and nothing else, and dressing that up
as intrinsic value is how people talk themselves into Cerebras at 32x sales.
Use reverse DCF or multiple convergence there instead, and be honest that you
are underwriting a story.

ASSUMPTIONS CARRY SOURCES
-------------------------
Same discipline as factors.py: every assumption field has a `basis`. An
unsourced WACC is a number someone liked the look of.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

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
