"""
Risk factors and position exposures — the assumption layer.
===========================================================

WHY THIS FILE EXISTS, AND WHY IT IS DATA AND NOT CODE
-----------------------------------------------------
Every scenario number this package produces is a consequence of the exposures
declared here. The arithmetic downstream is trivial; the judgment is all in
this file. That is deliberate and it mirrors how a real risk desk works: the
model is a calculator, the assumptions are the work product.

So each exposure carries a `basis` string. If you cannot write the basis, you
do not know the exposure, and you should not pretend to by leaving a number in
the dictionary. `validate()` refuses exposures with an empty basis.

THE FACTOR MODEL
----------------
A position's return under a scenario is a linear combination of factor shocks:

    r_i = sum_f  exposure[i][f] * shock[f]

`exposure` is an elasticity, not a correlation:

    1.0   full pass-through — a shock that costs a pure-play 10% costs this 10%
    0.5   half pass-through
    0.0   no transmission
   -0.4   inverse — the position *gains* when this factor is shocked adversely

`shock[f]` is expressed as the equity impact on a hypothetical pure-play with
exposure 1.0. So `ai_capex: -0.30` means "a pure AI-capex play loses 30%."

WHAT THIS MODEL CANNOT DO
-------------------------
It is linear and single-period. It will not capture convexity, contagion,
second-order effects, or the fact that correlations go to 1 in a crisis. It is
a structured way to ask "what breaks, and roughly how much" — not a VaR engine,
and emphatically not a forecast.

CALIBRATION NOTE
----------------
Exposures below were set from the research in this repo and the reasoning in
the advisory record. They are opinions with sources attached, not measurements.
Re-derive them when the thesis changes; that is what `basis` is for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

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
