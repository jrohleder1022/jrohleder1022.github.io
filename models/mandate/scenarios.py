"""
Scenario transmission engine — "what breaks, and roughly how much".
===================================================================

METHOD
------
A scenario is a named vector of factor shocks plus the reasoning that justifies
it. Position impact is the dot product of the position's factor exposures with
the scenario's shock vector:

    r_i = sum_f  exposure[i][f] * shock[f]

Portfolio impact is the weight-average of position impacts. Because the mapping
is linear, every number the engine prints can be decomposed back into "this
much of the loss came from this factor", which is the only property that makes
a risk model arguable rather than oracular.

WHY SCENARIOS AND NOT VALUE-AT-RISK
-----------------------------------
VaR answers "how bad is a bad day" using the covariance of the recent past. It
is useless for the risks that actually threaten a ten-year concentrated book,
because those risks have no history in the sample: an export-control regime
change, a founder leaving, a siting moratorium. Scenario analysis handles
exactly these — you specify the shock rather than estimating it from returns
that never contained one.

The cost is that a scenario is only as good as its calibration, and calibration
is judgment. Hence `rationale` and `analogue` on every scenario. A scenario
without a historical analogue is a number someone made up.

SEVERITY CONVENTION
-------------------
Shocks are the equity impact on a hypothetical PURE PLAY with exposure 1.0.
They are deliberately severe — a scenario calibrated to a mild outcome tells
you nothing you did not already know. These are "this is a bad year" levels,
not "this is the end" levels, except where marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .factors import FACTORS, ExposureSet


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
