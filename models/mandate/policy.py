"""
Investment Policy Statement, encoded as machine-checkable rules.
================================================================

WHY MECHANIZE THE POLICY
------------------------
The policy was written to be consulted under pressure, and the entire failure
mode of a written policy is that it gets read generously at exactly the moment
it should be read strictly. A rule that is checked by arithmetic cannot be
talked out of its conclusion by a good story about why this position is
different.

So every section of the IPS that can be reduced to a number lives here. The
sections that cannot — "moat explainable in three sentences", "sell falling
value, never falling price" — are enforced in `rubric.py` as gates on the
research instead, because they are judgments about evidence rather than
arithmetic about weights.

SEVERITY
--------
    BREACH   The policy is violated right now. Act.
    WARNING  Within tolerance of a limit, or a limit is about to bind.
    NOTE     Structural observation worth knowing; no action implied.

A BREACH is not advice to sell. It is a statement that the book and the policy
disagree, and that one of them has to change — deliberately, in writing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

# ---------------------------------------------------------------------------
# Policy constants — edit here, not in the checks
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Parameters, tuned for a ROTH IRA
# ---------------------------------------------------------------------------
#
# WHAT IS DIFFERENT ABOUT A ROTH, and what it changes here:
#
#   No tax on sales.          Rebalancing is free. Nothing in this policy is
#                             tax-motivated, and "trim on weight, never on
#                             gain" is a discipline rule, not a tax rule.
#                             Tax-loss harvesting does not apply.
#   Dividends compound        A dividend here is worth more than the same
#   tax-free.                 dividend in a taxable account.
#   Contributions are CAPPED. $7,500 for 2026. Capital cannot be replaced
#                             freely, which is the whole reason the §5
#                             rebuild-time logic is the right test.
#   Unused room EXPIRES.      Headroom not used by the filing deadline is
#                             gone permanently. Tracked below, because it is
#                             usually the largest number in the system.
#   No withdrawals to 59.5.   So the horizon is real. A 23-year-old has 36+
#                             years and no liquidity need, which is what
#                             makes concentration affordable.
#   No margin, no shorting.   Leverage is not available, so a total loss is
#                             the floor. Scenario impacts are capped at -100%.

# --- §4 position limits ----------------------------------------------------
MAX_SINGLE_POSITION = 0.35
# RAISED from 0.25 on 17 Nov 2026. 25% was unreachable for a deliberately
# concentrated book of five or six names: with four positions equal-weighted
# you are AT the cap, and any winner puts you through it. The result was a
# permanent breach the owner learned to step past, which is worse than no
# rule. 35% permits a concentrated book while still catching a position that
# has genuinely run away.

# The core/satellite line is PROPORTIONAL, not a fixed dollar figure.
# This fixes a real bug. A fixed $1,500 minimum against a percentage-based
# satellite cap created a DEAD ZONE -- at a $16,000 book, anything between
# $800 and $1,500 breached either way, too big for a satellite and too small
# to qualify as core. Making both proportional closes the gap at every size.
CORE_MINIMUM_PCT = 0.08             # >= 8% of the book is a core position
CORE_MINIMUM_FLOOR = 500.0          # but never call anything under $500 core

# --- §3 sleeve limits ------------------------------------------------------
MAX_SATELLITE_SLEEVE = 0.15
MAX_SINGLE_SATELLITE = 0.08         # raised from 0.05 to meet CORE_MINIMUM_PCT
# These two now MEET rather than leaving a gap: under 8% is a satellite, 8%
# and over is core. No position can be non-compliant on size alone.

TARGET_COST_BASIS = 5_000.0         # equal-cost-basis structure
EDA_BAND = (0.20, 0.35)             # widened; SNPS alone can exceed 30%
WARN_TOLERANCE = 0.03

# --- §3 theme ceiling, now conditional -------------------------------------
# The 60% AI ceiling was unconditional and permanently breached. It is now
# tied to §5, like the non-correlated floor it mirrors: concentration in one
# theme is affordable for exactly as long as concentration generally is.
# Below the first expiry rung there is no ceiling; above it, the ceiling
# binds. That makes the rule say what the owner actually believes.
AI_COMPLEX_CEILING_BY_SIZE: tuple[tuple[float, float], ...] = (
    (0.0,      1.00),   # below $40k: no ceiling
    (40_000.0, 0.75),
    (75_000.0, 0.60),
)

# --- §5 concentration expiry ------------------------------------------------
# Concentration is affordable only while annual contributions can rebuild a
# 50% drawdown inside five years. Past that, diversification stops being
# optional because TIME, not money, becomes the binding constraint.
EXPIRY_LADDER: tuple[tuple[float, float], ...] = (
    (20_000.0, 0.00),
    (40_000.0, 0.20),
    (75_000.0, 0.30),
)
ASSUMED_ANNUAL_CONTRIBUTION = 2_740.0
REBUILD_YEARS_LIMIT = 5.0

# --- Roth contribution headroom --------------------------------------------
# 2026 limit per IRS Notice 2025-67. Update each year.
ROTH_LIMIT = 7_500.0
ROTH_CATCHUP_50 = 1_100.0
ROTH_DEADLINE = "15 April of the following year"


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
    ceiling = 1.00
    for threshold, limit in AI_COMPLEX_CEILING_BY_SIZE:
        if book.total_value >= threshold:
            ceiling = limit
    if ai_complex > ceiling:
        findings.append(
            Finding(
                Severity.BREACH,
                "3",
                f"AI/semiconductor complex is {ai_complex:.1%} of equity, above "
                f"the {ceiling:.0%} ceiling that applies at a book value of "
                f"${book.total_value:,.0f}.",
                "New money goes to non-correlated names until this clears.",
            )
        )
    elif ceiling >= 1.0:
        findings.append(
            Finding(
                Severity.NOTE,
                "3",
                f"AI/semiconductor complex is {ai_complex:.1%}. No ceiling "
                f"applies below ${AI_COMPLEX_CEILING_BY_SIZE[1][0]:,.0f} — "
                f"single-theme concentration is affordable for as long as "
                f"concentration generally is, per §5.",
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

    floor = core_minimum(book.total_value)
    for p in book.positions:
        w = book.weights().get(p.ticker, 0.0)
        if p.sleeve == "core" and p.market_value < floor:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "4",
                    f"{p.ticker} is classified core at ${p.market_value:,.0f} "
                    f"but the core minimum at this book size is ${floor:,.0f}.",
                    "Reclassify as satellite, or add to it.",
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


def core_minimum(book_total: float) -> float:
    """The core/satellite threshold in dollars, at this book size."""
    return max(CORE_MINIMUM_FLOOR, book_total * CORE_MINIMUM_PCT)


def _check_sizing_dead_zone(book: Book) -> list[Finding]:
    """Confirm the satellite cap and the core minimum still meet.

    They are both proportional now, so there should be no gap. This check
    survives as a regression guard: if someone edits one constant and not the
    other, a dead zone reappears silently and every subsequent purchase in it
    looks non-compliant for no visible reason.
    """
    total = book.total_value
    if total <= 0:
        return []
    cap = total * MAX_SINGLE_SATELLITE
    floor = core_minimum(total)
    if cap >= floor - 1.0:
        return [
            Finding(
                Severity.NOTE,
                "3/4",
                f"Sizing is continuous: satellite below ${cap:,.0f}, core at "
                f"${floor:,.0f}+. No dead zone — any position size is "
                f"classifiable.",
            )
        ]
    return [
        Finding(
            Severity.WARNING,
            "3/4",
            f"DEAD ZONE REOPENED: ${cap:,.0f}-${floor:,.0f}. The satellite cap "
            f"and core minimum no longer meet, so a position in that range "
            f"breaches either way. Someone changed one constant without the "
            f"other.",
            "Set MAX_SINGLE_SATELLITE equal to CORE_MINIMUM_PCT.",
        )
    ]


def _check_roth_headroom(book: Book, annual_contribution: float) -> list[Finding]:
    """Unused Roth contribution room, which expires permanently.

    This is usually the largest number in the whole report and it has nothing
    to do with security selection. It is in the policy because a limit you do
    not use is not carried forward.
    """
    gap = ROTH_LIMIT - annual_contribution
    if gap <= 0:
        return [
            Finding(
                Severity.NOTE,
                "9",
                f"Roth contributions at or above the ${ROTH_LIMIT:,.0f} limit. "
                "No headroom being lost.",
            )
        ]

    def fv(pmt: float, rate: float, years: int) -> float:
        return pmt * (((1 + rate) ** years - 1) / rate)

    ten_year = fv(gap, 0.15, 10)
    return [
        Finding(
            Severity.NOTE,
            "9",
            f"ROTH HEADROOM: ${gap:,.0f}/yr unused against the "
            f"${ROTH_LIMIT:,.0f} limit (${gap / 26:,.0f} per biweekly "
            f"paycheck). At 15% that unused room is worth ~${ten_year:,.0f} "
            f"over ten years — typically more than any allocation decision in "
            f"this report. Unused room expires on {ROTH_DEADLINE} and is not "
            f"carried forward.",
        )
    ]


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
    findings += _check_sizing_dead_zone(book)
    findings += _check_roth_headroom(book, annual_contribution)
    findings += _check_cash(book)
    findings += _check_funding(book)

    order = {Severity.BREACH: 0, Severity.WARNING: 1, Severity.NOTE: 2}
    return sorted(findings, key=lambda f: order[f.severity])
