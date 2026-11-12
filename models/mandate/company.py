"""
Single-company evaluation — quality, durability, and what you are paying.
=========================================================================

WHERE THIS SITS
---------------
`valuation.py` answers "what is it worth". This answers the five questions you
should settle BEFORE caring what it is worth, because a cheap business that
destroys capital is not cheap:

  1. Does it create value?      ROIC vs WACC
  2. Is the growth real?        FCF conversion, accrual quality
  3. Can it survive?            leverage, interest coverage
  4. Am I being diluted?        share count trend
  5. What am I paying?          multiples, in context

THE ONE THAT MATTERS MOST
-------------------------
    ROIC - WACC  =  the value-creation spread

If a business earns 8% on invested capital and its capital costs 9%, then every
dollar it reinvests destroys a cent of value, and GROWTH MAKES IT WORSE. This
single comparison separates a compounder from a treadmill, and it is absent
from most retail analysis because it requires reconstructing invested capital
rather than reading a ratio off a screen.

    NOPAT            = EBIT x (1 - tax rate)
    Invested capital = total debt + equity - cash
    ROIC             = NOPAT / invested capital

EARNINGS QUALITY
----------------
    FCF conversion = free cash flow / net income

Sustained conversion below ~0.8 means reported profit is not turning into cash.
Sometimes that is heavy growth capex, which is fine and temporary. Sometimes it
is receivables stretching, capitalised costs, or revenue recognised before cash
arrives, which is neither. The ratio does not tell you which — it tells you
where to look.

NO DATA FEED
------------
Inputs are entered by hand from filings, same as everywhere else in this
package. That is a feature: pulling six numbers off an income statement forces
you to see the statement. Every field names where it comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
    def roic(self) -> float | None:
        ic = self.invested_capital
        return self.nopat / ic if ic > 0 else None

    @property
    def value_spread(self) -> float | None:
        """ROIC minus WACC. Positive means reinvestment creates value."""
        if self.roic is None or self.wacc is None:
            return None
        return self.roic - self.wacc

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
    if spread is not None and spread <= 0:
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
