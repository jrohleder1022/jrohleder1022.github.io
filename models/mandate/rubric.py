"""
The research gate — what an agent must establish before a BUY is admissible.
============================================================================

WHAT THIS IS FOR
----------------
This is the part of "let agents pick stocks" that is actually tractable. No
script can tell you which company wins over ten years. What a script can do is
refuse to let a recommendation through until the uncomfortable questions have
been answered with sources attached.

That is not a consolation prize. The dominant failure mode in concentrated
investing is not bad analysis — it is *incomplete* analysis that felt complete
because the parts that were easy to research were researched thoroughly and the
parts that were hard were skipped. A gate that fails on missing evidence
converts that silent failure into a loud one.

HOW TO USE IT WITH AN AGENT
---------------------------
Hand the agent `brief()` as its instructions. It returns a Brief with every
field filled and a source per field. Run `Brief.gate()`. If the gate fails,
the recommendation is not admissible — not "weak", not "needs work".
Inadmissible. Send it back.

THE TEN-YEAR DISCIPLINE
-----------------------
Three fields exist specifically because the horizon is ten years and nothing
else in a normal writeup addresses that span:

    terminal_question   What must be true in 2036 for this to have worked?
    obsolescence_path   What technology or business model replaces this?
    budget_line         Whose budget pays, and is it capital or operating?

The third is the one most writeups omit and the one that most reliably predicts
how a position behaves in a downturn. Revenue that sits in somebody's capital
budget gets deferred in lumps. Revenue in an operating budget does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


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
