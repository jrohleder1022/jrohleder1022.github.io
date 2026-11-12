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
