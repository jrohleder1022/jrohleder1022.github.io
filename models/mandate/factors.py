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
    "clinical_regulatory": (
        "Binary approval risk at a drug or device regulator. Distinct from "
        "`regulatory`, which constrains HOW a business may operate: this one "
        "decides WHETHER a product may be sold at all. The defining features "
        "are that it is binary, dated (a PDUFA action date), and essentially "
        "unhedgeable — no amount of operating excellence changes the answer, "
        "and the outcome is not correlated with anything else in a portfolio."
    ),
    "financing_cost": (
        "Exposure to the cost and availability of debt. Distinct from "
        "`rates_duration`, which is a VALUATION effect on the discount rate: "
        "this one hits the INCOME STATEMENT through interest expense, and in "
        "the extreme determines whether maturities can be rolled at all. A "
        "company funding depreciating assets with debt has fixed obligations "
        "against revenue that is not fixed, which is the oldest way to go "
        "broke while growing."
    ),
    "memory_cycle": (
        "Where the SEMICONDUCTOR MEMORY industry sits in its capacity cycle. "
        "The mechanism is supply, not demand: peak margins fund the fabs that "
        "destroy them, with a two-to-three-year lag between the capex decision "
        "and the fab coming online. The signature is gross margin far above "
        "the long-run mean plus an industry-wide capex increase. A low P/E on "
        "peak earnings is not cheapness, it is the market discounting earnings "
        "it does not believe. "
        "SPLIT OUT OF `commodity_cycle` after a coverage audit: the memory "
        "scenario was shocking every holding that carried the old combined "
        "factor, so a DRAM glut registered as a loss against an LNG exporter "
        "and a turbine maker. Two unrelated supply cycles sharing one factor "
        "is a correlation the model asserts and the world does not."
    ),
    "commodity_cycle": (
        "Exposure to PHYSICAL commodity prices — energy, metals, castings — on "
        "either side of the income statement: as an input cost, or as the "
        "price of what is sold. Now distinct from `memory_cycle`, which is the "
        "semiconductor capacity cycle and moves for entirely different "
        "reasons. Use this one for a gas exporter whose spreads compress as "
        "global liquefaction capacity arrives, or a manufacturer whose steel "
        "and copper bill rises. Do NOT use it for a fab."
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
    # SPCX moved here from CANDIDATES on 15 Nov 2026: bought 13 Nov, so it is
    # a HOLDING now. The scenario engine requires every position in
    # portfolio.json to have a profile in BOOK, and a held name left in
    # CANDIDATES raises KeyError rather than silently scoring zero -- which is
    # the right failure, but it has to be fixed when a purchase is recorded.
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
    # AMD moved here from CANDIDATES on 15 Nov 2026: bought, so it is a
    # HOLDING. Every ticker in portfolio.json needs a profile in BOOK or the
    # scenario engine raises KeyError rather than scoring it zero.
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
}


# ---------------------------------------------------------------------------
# Candidates under consideration — same discipline, no position taken
# ---------------------------------------------------------------------------

CANDIDATES: dict[str, ExposureSet] = {
    "SNDK": ExposureSet(
        ticker="SNDK",
        thesis=(
            "Sandisk. Pure-play NAND flash, spun out of Western Digital in "
            "February 2025; WD kept the hard-disk business. No DRAM, and "
            "therefore no HBM -- HBM is stacked DRAM, so this is structurally "
            "impossible for Sandisk, not merely absent. "
            "THE NUMBERS ARE THE MOST VIOLENT CYCLE TURN IN THE FILE. FY2025 "
            "(June): revenue $7.36B, gross margin 30.1%, an operating LOSS of "
            "$1.38B and a net LOSS of $1.64B. FY2026: revenue $20.25B, gross "
            "margin 71.5%, operating income $12.39B, net income $11.43B. "
            "Quarterly gross margin ran 29.8%, 50.9%, 78.4%, 84.6%, 85.0% "
            "across five quarters. Q1 FY2027 (Sep 2026) alone: revenue $11.03B "
            "(+378% YoY), gross margin 85.0%, operating income $8.78B, "
            "non-GAAP EPS $49.51 against $44-46 guided. Q2 guided to $12.2-12.6B "
            "of revenue, 84.5-85.5% margin, $55-57 EPS pre-split. An 8-for-1 "
            "split takes effect for trading on 20 November 2026. "
            "THE FINDING THAT MATTERS, AND IT CUTS AGAINST BOTH NAMES: Sandisk "
            "grew 378% with an 85% gross margin while owning NO DRAM and NO "
            "HBM. Micron grew 379% with an 87% gross margin. If the AI/HBM "
            "story were the driver, the tight DRAM oligopoly (3 players) would "
            "be dramatically outperforming the fragmented NAND market (6 "
            "players: Samsung, SK Hynix/Solidigm, Kioxia, Sandisk, Micron, "
            "YMTC). It is not. The worst-structured memory market on earth is "
            "matching the best one almost exactly, which means this is a "
            "SHORTAGE rather than a structural re-rating -- and shortages are "
            "cured by capacity. "
            "DEMAND DESTRUCTION IS ALREADY VISIBLE in the mix: data-centre "
            "revenue rose 61% sequentially to $4.8B, 44% of the total, while "
            "CONSUMER revenue FELL 29% sequentially to $397M as, in "
            "management's framing, the market absorbs higher prices. Customers "
            "buying less because it costs too much is the classic late-cycle "
            "signal, and the data-centre strength is masking it. It also means "
            "Sandisk's mix is shifting TOWARD the AI-levered end, so it is "
            "becoming more cyclical, not less. "
            "CAPITAL ALLOCATION IS THE REAL DIFFERENCE FROM MICRON. Sandisk is "
            "harvesting: $5.0B of stock repurchased in ONE quarter against a "
            "~$150B market cap (3.3% of the company in 90 days), $5.1B of cash, "
            "NO debt, and gross capex guided to a mid-single-digit percentage "
            "of FY2027 revenue. Micron is reinvesting: capex was $27.37B on "
            "$133.19B of revenue, ~20.6%, and guided higher. One company is "
            "behaving as though it is at a peak; the other as though the peak "
            "is the new level. CAVEAT: Sandisk's fab capacity sits in joint "
            "ventures with Kioxia, so its own reported capex understates the "
            "capacity actually being added on its behalf. Do not read "
            "mid-single-digit capex as 'not adding supply'. "
            "AND THE MARKET IS VOTING. Both stocks are FALLING on record "
            "results. Sandisk fell ~13% after this print and is reported down "
            "roughly 42% from its high, around $920 pre-split. Micron reached "
            "a $1 trillion market cap on 26 May 2026 and trades near $720 for "
            "~$815B. Forward multiples on guided earnings are ~4.1-4.6x for "
            "Sandisk and ~4.7x for Micron. That is not cheapness. That is the "
            "market declining to capitalise earnings it does not believe will "
            "persist -- the exact condition the memory_cycle factor exists to "
            "flag."
        ),
        exposures=[
            Exposure(
                "memory_cycle",
                1.30,
                "HIGHER than Micron's 1.25, for three reasons. NAND has six "
                "credible suppliers against DRAM's three, so pricing "
                "discipline is historically worse and returns structurally "
                "lower. Sandisk is a pure play with no second product to "
                "cushion a NAND correction. And an 85% gross margin in a "
                "business that earned 7.1% in FY2023 and 16.1% in FY2024 is "
                "not a franchise margin -- it is a shortage margin, with a "
                "date on it that nobody knows.",
            ),
            Exposure(
                "ai_capex",
                0.70,
                "Data-centre is 44% of revenue and grew 61% sequentially, "
                "while consumer FELL 29%. Below Micron's 1.00 because there is "
                "no HBM here, but rising every quarter as the mix shifts: "
                "enterprise SSD demand for AI storage tiers is the growth, and "
                "the historic consumer base is shrinking under the price rises.",
            ),
            Exposure(
                "china_policy",
                0.35,
                "YMTC is a state-backed Chinese NAND competitor and the "
                "swing factor in future supply; export controls cut both ways; "
                "and China is a large end market for consumer flash.",
            ),
            Exposure(
                "rates_duration",
                0.30,
                "Low. Earnings are enormous and present, the multiple is ~4x "
                "forward, and there is no debt. Duration is not this "
                "position's problem -- the cycle is.",
            ),
            Exposure(
                "market_beta",
                1.60,
                "Very high. A pure-play commodity producer at a cycle peak, "
                "already down ~42% from its high while reporting the best "
                "numbers in its history.",
            ),
        ],
    ),
    "NFLX": ExposureSet(
        ticker="NFLX",
        thesis=(
            "Netflix. Streaming subscriptions in ~190 countries, plus an "
            "ad-supported tier and a live-events push. "
            "THE FIRST THING TO KNOW IS THAT YOU CANNOT ANALYSE IT ON "
            "SUBSCRIBERS ANY MORE. Netflix announced in April 2024 that from "
            "Q1 2025 it would stop disclosing quarterly subscriber additions, "
            "and it dropped average revenue per user at the same time. "
            "Management's reason is defensible: with password-sharing "
            "conversions and a cheap ad tier, a $7.99 account and a $24.99 "
            "account stopped being the same unit, so counting them identically "
            "had become misleading. The consequence is still that the metric "
            "the market tracked for fifteen years is gone. The last official "
            "count was 269.6M at the end of March 2024. Investors were "
            "explicitly redirected to revenue and operating margin. "
            "AND THE MARGIN IS THE REAL STORY: operating margin went 17.8% in "
            "FY2022, 20.6% in FY2023, 26.7% in FY2024, 29.5% in FY2025, and "
            "31.3% on a trailing-twelve-month basis, on revenue compounding "
            "15-16%. TTM revenue $49.7B (+14.7%), operating income $15.6B. "
            "Q3 2026: revenue $12.87B (+12%), operating margin 34.6% against "
            "28.2% a year earlier, diluted EPS $0.87 against $0.59, and a "
            "RECORD $4.80B of buyback in the quarter. "
            "TWO THINGS NOT TO MISREAD. Q4 2026 is guided to a 26.0% operating "
            "margin, which looks like a collapse from 34.6% and is not: Q4 is "
            "seasonally the weakest quarter (22.2% in 2024, 24.5% in 2025), so "
            "26.0% is an improvement, and it carries ~120bp of drag from "
            "announced headcount reductions. And TTM reported net income of "
            "$14.77B is overstated -- Q1 2026 booked $5.28B of NET income on "
            "$3.96B of OPERATING income, a ~$1.3B non-operating item. "
            "Operating income taxed at ~15% implies clean TTM earnings nearer "
            "$13.2B. "
            "WHY IT MATTERS FOR THIS BOOK: ai_capex 0.00. Netflix's costs are "
            "PROGRAMMING, which is semi-fixed and discretionary, not a capital "
            "budget being deferred in lumps by four committees. It is the only "
            "name on this list with a genuine consumer-subscription annuity "
            "and no exposure to the AI capital cycle in either direction. "
            "Price ~$65.78 on a single third-party source -- VERIFY IT. That "
            "is consistent with ~4,211M shares (backed out of $3,664M of Q3 "
            "net income at $0.87 diluted), ~$277B of market cap and ~19x "
            "trailing reported earnings. The 10-for-1 split took effect 17 Nov "
            "2025 at ~$111, so the stock is down roughly 41% in a year."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                0.00,
                "None, in either direction. The second name in this file with "
                "zero AI linkage, after CORT. Netflix buys compute like any "
                "large company but its revenue does not come out of anyone's "
                "AI capital budget and its costs are not set by GPU prices.",
            ),
            Exposure(
                "consumer_spending",
                0.45,
                "Discretionary, but the most defensible kind. Streaming is "
                "cheap entertainment that historically holds up in downturns, "
                "and the mechanism is churn rather than a cancelled order. The "
                "ad tier gives price-sensitive households somewhere to go DOWN "
                "to instead of out, which blunts this further.",
            ),
            Exposure(
                "ad_cycle",
                0.30,
                "The ad tier is real but still small -- FY2026 advertising "
                "revenue is around $2.7-3.0B against ~$50B of total revenue, "
                "roughly 6%, and the guidance was reportedly trimmed from ~$3B "
                "toward $2.7B. Growing fast enough that this exposure rises "
                "each year. Second name after GOOGL to carry it, which now "
                "matters because an advertising-recession scenario exists.",
            ),
            Exposure(
                "digital_services_tax",
                0.25,
                "Operates in ~190 countries and is a standing target for "
                "digital services taxes and local content quotas, especially "
                "in the EU. A margin tax rather than a demand shock.",
            ),
            Exposure(
                "rates_duration",
                0.55,
                "~19-21x earnings is not a demanding multiple, which caps "
                "this. But a subscription annuity is long-duration by "
                "construction and content is partly debt-funded.",
            ),
            Exposure(
                "market_beta",
                1.10,
                "Slightly above market. Mega-cap and profitable, but it has "
                "fallen ~41% in a year on guidance and ad-revenue "
                "disappointments, so it is not a low-volatility holding.",
            ),
        ],
    ),
    "VRT": ExposureSet(
        ticker="VRT",
        thesis=(
            "Vertiv. Data-centre power and thermal: UPS, busway, switchgear, "
            "and the liquid cooling that high-density AI racks require. Spun "
            "out of Emerson Network Power via SPAC in 2020. Q3 2026: revenue "
            "$4.31B (+61%, +55% organic), GAAP operating margin 22.8%, "
            "adjusted operating profit $1.09B (+83%), adjusted EPS $2.21. TTM "
            "revenue $13.12B (+35%), operating margin 20.1%, net income "
            "$2.10B. FY2026 guided to ~$14.65B. Backlog was $15.0B (+109%) as "
            "of Q2. Price $202.07 on 13 Nov 2026, ~385.1M shares, ~$77.8B cap, "
            "37.1x trailing earnings. "
            "TWO THINGS TO WEIGH. Management said it is 'not planning to share "
            "orders data going forward' -- a company in a boom withdrawing its "
            "own leading indicator, which removes the number that would have "
            "told you first when demand turned. And the stock went $240.51 on "
            "28 October, the day it beat and raised, to $202.07 by 13 "
            "November: -16% in two weeks on no news. That is what owning the "
            "purest version of this trade feels like."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                1.10,
                "THE WHOLE POSITION. There is no second business here. Vertiv "
                "sells into the data-centre capital budget and essentially "
                "nothing else, which puts it level with NVDA and above AMD on "
                "this factor. Compare GEV at 0.35, where roughly half the "
                "backlog is services on installed turbines. Buying VRT is not "
                "diversifying an AI book, it is concentrating it.",
            ),
            Exposure(
                "rates_duration",
                0.70,
                "37x trailing earnings on a capital-goods order book. The "
                "earnings are real and present, which caps this below a "
                "pre-profit name, but the multiple assumes the ramp continues.",
            ),
            Exposure(
                "regulatory",
                0.25,
                "Data-centre siting and interconnection. State-level "
                "moratoriums and local permitting fights bite the builder's "
                "schedule, and Vertiv's revenue is that schedule.",
            ),
            Exposure(
                "financing_cost",
                0.45,
                "Hyperscalers self-fund, but the neoclouds and colocation "
                "developers that make up a growing share of the customer base "
                "are financed, and their cost of capital sets their build rate.",
            ),
            Exposure(
                "commodity_cycle",
                0.20,
                "Copper and steel in busway, switchgear and enclosures. Real "
                "but second-order against a 38% gross margin.",
            ),
            Exposure(
                "market_beta",
                1.55,
                "High. A momentum name with a 37x multiple and a single end "
                "market. The -16% fortnight after a beat is the evidence.",
            ),
        ],
    ),
    "SBGSY": ExposureSet(
        ticker="SBGSY",
        thesis=(
            "Schneider Electric, via the US ADR. Energy management (power "
            "distribution, 3-phase UPS under the APC brand, prefabricated "
            "data-centre modules, cooling) plus industrial automation. Q3 "
            "2026: record revenue ~EUR 11.5B, +17% organic. Energy Management "
            "is 84% of the group and grew 18.8% organic, driven by data "
            "centre, where growth was triple-digit for a third consecutive "
            "quarter. Industrial Automation grew only 8.1% to ~EUR 1.85B. "
            "FY2026 organic growth guidance raised to 12-14%. "
            "GENUINELY MORE DIVERSIFIED than Vertiv -- buildings, "
            "infrastructure, residential, industry and utilities are real end "
            "markets here, not a rounding error -- but data centre is the "
            "swing factor in the segment that is five-sixths of the company. "
            "ROTH-SPECIFIC COST, see the ai_capex and dividend notes: French "
            "withholding on the dividend is UNRECOVERABLE in this account."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                0.45,
                "Higher than GEV's 0.35, not lower. Data centre is ~20-25% of "
                "group revenue and the dominant growth driver of the 84% "
                "segment, where it is compounding at triple digits. The offset "
                "is that Schneider carries a ~27x multiple against GEV's ~42x, "
                "so there is less multiple to lose, and no progress-payment "
                "cash flow dynamic to reverse.",
            ),
            Exposure(
                "rates_duration",
                0.40,
                "Mid. A ~27x multiple on a diversified industrial compounder "
                "with real current earnings.",
            ),
            Exposure(
                "consumer_spending",
                0.15,
                "Residential and light-commercial buildings. Small, and the "
                "only name on this list with any direct household link.",
            ),
            Exposure(
                "regulatory",
                0.25,
                "European energy-efficiency mandates cut the other way here -- "
                "they are a tailwind. Netted against data-centre siting and "
                "EU industrial policy, roughly ordinary exposure.",
            ),
            Exposure(
                "commodity_cycle",
                0.25,
                "Copper, aluminium, steel and electrical steel for "
                "transformers. A genuine input-cost exposure on a ~40% gross "
                "margin.",
            ),
            Exposure(
                "market_beta",
                1.00,
                "Market-like. EUR 130B+ of market cap, four end markets, a "
                "dividend, and a century of operating history. The lowest beta "
                "of the three electrification names.",
            ),
        ],
    ),
    "GEV": ExposureSet(
        ticker="GEV",
        thesis=(
            "GE Vernova. Spun out of GE in April 2024. Three segments: Power "
            "(gas turbines and the services book on ~7,000 installed units), "
            "Wind (onshore and offshore, the loss-maker), and Electrification "
            "(grid equipment, transformers, switchgear). Q3 2026: revenue "
            "$12.64B (+27%, +18% organic), operating income $1.39B for an 11.0% "
            "margin against 3.7% a year earlier, orders $29.3B (+96% organic), "
            "backlog ~$197B of which ~$104B equipment and ~$93B services. "
            "FY2026 guided to $46.5-47.5B of revenue, 13.5-14.5% adjusted "
            "EBITDA margin, $16-17B of free cash flow. Buyback authorization "
            "doubled to $20B; $1.6B repurchased in the quarter. "
            "TWO FIGURES IN THE FILINGS ARE TRAPS. (1) TTM GAAP net income is "
            "$10.37B, but ~$7.1B of it is non-recurring: a ~$4.5B pre-tax "
            "remeasurement gain on buying the remaining 50% of Prolec GE in "
            "Q1 2026, plus a $2.57B tax benefit in Q4 2025. GAAP EPS that "
            "quarter was $17.44 against $1.98 adjusted. (2) TTM free cash flow "
            "is $17.1B against $3.7B for the whole of FY2025 -- a 4.6x jump on "
            "17% revenue growth. Current liabilities exceed current assets by "
            "$11.8B, so the business is funded by customer progress payments on "
            "the order book. That inflow is real cash but it is not earnings, "
            "and it stops when order growth stops."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                0.35,
                "REVISED DOWN from 0.55 against the company's own disclosure. "
                "Data centres were ~$1.4B of $29.3B of Q3 orders (4.8%) and "
                ">$6B year to date, and they are ~20% of Electrification's "
                "~100-customer base against 80% traditional utility and "
                "industrial. Of the ~$197B backlog, ~$93B (47%) is services on "
                "an already-installed base -- annuity revenue paid whether or "
                "not another data centre is built -- and Wind has no AI link "
                "at all. Even the gas turbine demand that IS load-driven sits "
                "on US load growth of which data centres are a third to a "
                "half, with the rest reshored manufacturing, transport and "
                "building electrification, and coal retirements needing "
                "replacement capacity. Revenue-weighted AI linkage is more "
                "like 15-20%. "
                "0.35 rather than 0.20 because the EQUITY is more AI-levered "
                "than the revenue: at ~42x annualized Q3 earnings the multiple "
                "prices continued order growth, and the $17.1B of trailing "
                "free cash flow is progress payments on a rising order book, "
                "so an order slowdown reverses the cash dynamic rather than "
                "merely slowing revenue. The beta is an elasticity on the "
                "share price, not a revenue share.",
            ),
            Exposure(
                "regulatory",
                0.45,
                "High, and it is the Wind segment. Offshore permitting, "
                "production and investment tax credits, and interconnection "
                "queues have whipsawed this business into losses. Policy is a "
                "first-order driver here, not background noise.",
            ),
            Exposure(
                "financing_cost",
                0.40,
                "Customers are utilities and independent power producers "
                "financing multi-billion-dollar projects. Higher rates delay "
                "final investment decisions, which shows up as orders not "
                "booked rather than as revenue lost.",
            ),
            Exposure(
                "rates_duration",
                0.50,
                "Earnings are present and growing, which caps this. But the "
                "stock is ~42x annualized Q3 earnings, and the thesis is a "
                "margin ramp years out, so a rate move still compresses it.",
            ),
            Exposure(
                "commodity_cycle",
                0.30,
                "Input costs -- steel, copper, castings -- and, on the demand "
                "side, gas prices setting the economics of gas generation "
                "against alternatives.",
            ),
            Exposure(
                "market_beta",
                1.30,
                "Above 1. Capital goods with a high multiple and a cyclical "
                "order book. The equity has been volatile since the spin.",
            ),
        ],
    ),
    "CORT": ExposureSet(
        ticker="CORT",
        thesis=(
            "Cortisol modulation. Korlym plus its authorized generic treats "
            "Cushing's syndrome; Lifyorli (relacorilant) was approved March "
            "2026 for platinum-resistant ovarian cancer, more than three "
            "months early. Q3 2026: revenue $340.5M (+64% YoY) — Korlym "
            "$249.1M, Lifyorli $91.4M — and net income $126.8M against $19.7M "
            "a year earlier. FY2026 guided $1.1-1.2B. Management targets $2B+ "
            "of Cushing's revenue by the end of the decade, $3-5B if "
            "relacorilant is approved for it. NOTE THE DATE: relacorilant's "
            "Cushing's PDUFA is 17 December 2026, after an earlier complete "
            "response letter, with labeling around a liver-injury signal "
            "unresolved."
        ),
        exposures=[
            Exposure(
                "clinical_regulatory",
                0.85,
                "A dated binary event 32 days out. The earlier CRL and the "
                "unresolved liver-injury labeling question mean this is not a "
                "formality. Approval unlocks the $3-5B case; rejection leaves a "
                "still-profitable company growing 64% on two approved drugs.",
            ),
            Exposure(
                "rates_duration",
                0.45,
                "Low for a biotech, because the earnings are real and present — "
                "$126.8M of net income in the quarter, not a pipeline promise.",
            ),
            Exposure(
                "regulatory",
                0.30,
                "Drug pricing policy and the authorized-generic dynamic on "
                "Korlym. Ordinary pharma exposure.",
            ),
            Exposure(
                "ai_capex",
                0.00,
                "None. This is the first candidate in this file with zero "
                "connection to AI capital spending in either direction.",
            ),
            Exposure(
                "market_beta",
                0.75,
                "Below 1. Cushing's patients are treated regardless of the "
                "index, and the revenue is reimbursed rather than discretionary.",
            ),
        ],
    ),
    "LNG": ExposureSet(
        ticker="LNG",
        thesis=(
            "Cheniere Energy. LNG liquefaction and export from Sabine Pass and "
            "Corpus Christi, sold mostly on long-term take-or-pay contracts "
            "where the fixed fee is paid whether or not the cargo lifts. Q3 "
            "2026: adjusted EBITDA ~$1.9B, distributable cash flow ~$1.2B, net "
            "income ~$1.2B, a record 188 cargoes (+17% YoY). FY2026 EBITDA "
            "guidance RAISED a third consecutive time to $8.75-9.25B, DCF to "
            "$6.05-6.55B. Dividend raised over 12% to $0.625 quarterly, with a "
            "buyback authorization above $10B."
        ),
        exposures=[
            Exposure(
                "commodity_cycle",
                0.45,
                "The real risk, and it is a SUPPLY story. Qatar's expansion and "
                "a wave of US projects add global liquefaction capacity through "
                "2028, compressing spreads on uncontracted volumes. The "
                "contracted book is insulated — the fixed fee is paid "
                "regardless — so this bites the marginal cargo, not the base.",
            ),
            Exposure(
                "financing_cost",
                0.40,
                "A levered infrastructure business, but term-financed against "
                "contracted cash flows rather than funding capex out of "
                "spot revenue. Management targets ~7x capex/EBITDA and 10% "
                "unlevered contracted returns.",
            ),
            Exposure(
                "regulatory",
                0.40,
                "FERC and DOE export authorizations, environmental permitting. "
                "Slow-moving, and the same barriers are why a competitor cannot "
                "simply build a terminal.",
            ),
            Exposure(
                "rates_duration",
                0.35,
                "Low. Cash flows are contracted and near-term, returned through "
                "a growing dividend and large buybacks rather than promised.",
            ),
            Exposure(
                "ai_capex",
                0.10,
                "Small and POSITIVE in direction: data center power demand is "
                "lifting US gas consumption. Real but second-order next to the "
                "export contracts.",
            ),
            Exposure(
                "market_beta",
                0.75,
                "Below 1. Contracted take-or-pay revenue does not track the "
                "equity market.",
            ),
        ],
    ),
    "CRDO": ExposureSet(
        ticker="CRDO",
        thesis=(
            "Credo Technology. High-speed connectivity for AI data centers — "
            "active electrical cables, SerDes IP, retimers — with roughly 93% "
            "share of the AEC niche. Q1 FY2027: revenue ~$479M (+115% YoY, "
            "+10% sequential), Q2 guided $525-535M, FY2027 guided to grow more "
            "than 85%. THE RISK IS NAMEABLE: the top four customers were 84% of "
            "Q1 revenue (33%, 28%, 13%, 10%), and none is bound by a long-term "
            "purchase commitment."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                1.05,
                "Sells into the interconnect layer of AI data center builds. "
                "Above full pass-through on operating leverage.",
            ),
            Exposure(
                "rates_duration",
                1.00,
                "High multiple on hypergrowth earnings. Long duration.",
            ),
            Exposure(
                "china_policy",
                0.30,
                "Components for AI infrastructure sit inside the export-control "
                "perimeter, though less directly than an accelerator.",
            ),
            Exposure(
                "market_volatility",
                0.35,
                "It has already fallen 30% once on a single print. Concentrated "
                "revenue plus a rich multiple makes for violent repricing.",
            ),
            Exposure(
                "market_beta",
                1.50,
                "High-beta small cap in the most crowded theme in the market.",
            ),
        ],
    ),
    "CRWV": ExposureSet(
        ticker="CRWV",
        thesis=(
            "GPU cloud. Buys NVIDIA accelerators with borrowed money and rents "
            "them on contract. Q3 2026: revenue $3,661M (+168% YoY), backlog "
            "$132.5B, FY2026 guided $13-13.3B. Adjusted operating income $379M "
            "beat guidance of $200-260M. But capex was $14,511M in the quarter "
            "— 396% of revenue — interest expense $846M (23% of revenue) "
            "guided to $1.05-1.15B in Q4, and the GAAP net loss widened to "
            "$709M from $110M a year earlier. Only 26% of the backlog converts "
            "within 24 months."
        ),
        exposures=[
            Exposure(
                "ai_capex",
                1.40,
                "The highest loading in this file. CoreWeave does not merely "
                "sell into AI capex — it IS AI capex, financed with debt. "
                "Capex at 396% of revenue in a single quarter is a leveraged "
                "bet that demand for rented compute persists long enough to "
                "repay it.",
            ),
            Exposure(
                "financing_cost",
                1.30,
                "THE position risk, and the reason the factor was added. "
                "Interest is already 23% of revenue and guided higher. "
                "Annualized $3.4B of interest implies roughly $31-38B of debt "
                "at 9-11%. The obligations are fixed; GPU rental rates are not, "
                "and they fall as each new generation ships. Any tightening of "
                "credit, or a single missed refinancing window, is existential "
                "rather than merely expensive.",
            ),
            Exposure(
                "rates_duration",
                1.15,
                "Separate from financing_cost and stacked on top of it. The "
                "equity is a long-duration claim on the residual after debt "
                "service, which is the most rate-sensitive position in a "
                "capital structure.",
            ),
            Exposure(
                "market_volatility",
                0.70,
                "High. A company that must continuously raise debt and equity "
                "to fund capex depends on markets staying open. Volatility "
                "closes the window precisely when the next tranche is due.",
            ),
            Exposure(
                "china_policy",
                0.15,
                "Indirect. Export controls affect GPU supply and pricing, but "
                "CoreWeave sells compute in permitted jurisdictions.",
            ),
            Exposure(
                "market_beta",
                1.75,
                "Among the highest in the file. Leveraged, recently public, "
                "narrative-sensitive.",
            ),
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
                "memory_cycle",
                1.25,
                "THE WHOLE POSITION, and the reason the factor was added. "
                "UPDATE 19 Nov 2026: the single strongest piece of evidence "
                "for this exposure now comes from OUTSIDE Micron. Sandisk -- "
                "pure-play NAND, no DRAM, no HBM, in a SIX-supplier market -- "
                "grew revenue 378% YoY with an 85.0% gross margin in the same "
                "window Micron grew 379% with 87.0%. If HBM and the AI mix "
                "were doing the work, the three-player DRAM oligopoly would be "
                "crushing the fragmented NAND market. It is not. The "
                "worst-structured memory market on earth is matching the best "
                "one, which means a SHORTAGE is doing the work, not a "
                "structural re-rating. That is the bear case stated with a "
                "control group. An "
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
            "Wafer-scale inference accelerators. The engineering "
            "differentiation on latency is genuine. REWRITTEN 18 Nov 2026 "
            "after the Q3 print: the earlier entry said 'pre-profit' and put "
            "UAE concentration at ~43%, and both were wrong. "
            "IPO 14 May 2026 at $185, popped 68% to ~$311, traded $108.72 on "
            "13 Nov -- -41% from the IPO price, ~-65% from the peak, ~$28B of "
            "market cap against ~$48B at listing. "
            "ON PROFITABILITY: FY2025 reported net income of +$237.8M on "
            "$510M of revenue, and that is not profit. Operating income was "
            "NEGATIVE $145.3M. The gap is ~$390M of non-operating gains, "
            "almost all in Q2 2025 (+$309.5M net against a $57.2M operating "
            "loss) -- a pre-IPO fair-value mark on preferred and warrant "
            "liabilities, an accounting entry rather than cash earned. "
            "Cerebras has never had a profitable year on the operating line. "
            "Nine months of 2026: revenue $584.3M, operating income -$716.3M. "
            "ON THE GROSS MARGIN, which is the real finding: 44.6% in Q1 "
            "2026, 14.2% in Q2, 20.0% in Q3. It halved. The cause is a mix "
            "shift -- Q3 cloud services revenue rose 265% to $142M while "
            "direct hardware system sales FELL 29% to $69M. "
            "READ THAT CORRECTLY: falling hardware REVENUE is not falling "
            "hardware PRODUCTION. The WSE-3 is in production and shipping more "
            "silicon per rack than ever -- the CS-4 system launched August 2026 "
            "packs THREE overclocked WSE-3 Turbo wafers into one rack, and "
            "265% cloud growth requires more installed wafers, not fewer. What "
            "changed is who owns them. Selling a system books revenue once at "
            "a ~40-45% hardware margin and leaves the customer holding the "
            "depreciation; renting compute on a fleet you own books revenue "
            "over years while YOU carry the depreciation through COGS, which "
            "compresses gross margin until utilization catches up. The margin "
            "collapse is a revenue-recognition and asset-ownership change, not "
            "evidence the product got worse. Whether it REVERSES depends on "
            "utilization and on what Cerebras charges per MW, which is the "
            "number to find in the filings. "
            "Cerebras is converting itself from a chip vendor into a cloud "
            "operator, "
            "absorbing depreciation on its own fleet, and has taken on debt to "
            "do it (~$75M/yr of interest expense against zero pre-IPO). That "
            "makes it a neocloud, the most leveraged link in the AI capital "
            "chain. "
            "ON CONCENTRATION: it rotated, it did not fall. G42 went from 85% "
            "of 2024 revenue to 24% of 2025, but MBZUAI -- also Abu Dhabi -- "
            "was 62% of 2025, so the two together were ~86%. By Q3 2026 it was "
            "MBZUAI ~38% plus OpenAI ~34%: ~72% in two names. "
            "Q3 revenue $210.8M (+55%), core revenue $230.9M (+70%), GAAP net "
            "loss $161M, core net income ~$30M, the difference being stock "
            "compensation. FY2026 core revenue guided $940-960M; management "
            "expects revenue to triple in 2027. Backlog ~$26B, including a "
            "750MW OpenAI agreement valued above $20B -- which makes the "
            "backlog a CREDIT question about OpenAI, not a demand question. "
            "ON THE AWS RELATIONSHIP, which is more substantial than a "
            "marketplace listing and also more double-edged: it is "
            "DISAGGREGATED INFERENCE. Announced March 2026, definitive "
            "agreement June 2026. AWS deploys CS-3 systems inside AWS data "
            "centres, offered through Bedrock, with TRAINIUM 3 doing the "
            "PREFILL and the CS-3 doing the DECODE. Those two halves have "
            "opposite hardware requirements: prefill processes the whole "
            "prompt at once and is compute-bound, which suits cheap parallel "
            "FLOPs; decode emits one token at a time and must re-read the "
            "model's weights for each one, so it is memory-bandwidth-bound. "
            "The WSE-3 holds weights in ~44GB of on-die SRAM at ~21 PB/s "
            "against an H100's ~3.35 TB/s of HBM, so Amazon rents Cerebras "
            "for the half where its own silicon is bandwidth-starved. Cerebras "
            "is not displacing Trainium; it is being bolted onto it. "
            "THE TERMS CUT THE OTHER WAY, THOUGH. Per the 10-Q the agreement "
            "carries an initial multi-year LEASE of Cerebras systems, options "
            "for future procurement, pricing commitments, exclusivity, minimum "
            "manufacturing capacity guarantees, and -- in the filing's own "
            "words -- 'certain other protections in favor of Amazon'. "
            "Exclusivity and capacity floors running toward the CUSTOMER is a "
            "counterparty with leverage, not a partner on equal footing, and "
            "Cerebras separately warns that Amazon 'may represent a material "
            "percentage of our revenue'. So AWS is a step away from "
            "sovereign-adjacent concentration and simultaneously the third "
            "rotation of the same concentration problem. Terms undisclosed. "
            "ON THE ROADMAP: there is no WSE-4. The CS-4 is an overclock of "
            "the same 5nm WSE-3 silicon launched in March 2024, now in its "
            "third year, against competitors shipping a new architecture "
            "roughly annually. A systems-level upgrade on old silicon is a "
            "cheaper way to add performance and also a sign of where the "
            "engineering budget is going. WSE-4 is expected no earlier than "
            "2027 and was unannounced as of September 2026."
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
                "Accelerator export regime applies, and the counterparty "
                "concentration sits inside the same review process. CORRECTED: "
                "the Abu Dhabi share is far higher than the ~43% this basis "
                "once claimed. MBZUAI was 62% of FY2025 revenue and G42 24%, "
                "about 86% between two related entities, and G42 is also an "
                "investor. By Q3 2026 MBZUAI was ~38%. Sovereign-adjacent "
                "demand from one emirate, reviewable by CFIUS and the export "
                "regime, is a political exposure wearing a customer's clothes.",
            ),
            Exposure(
                "rates_duration",
                1.20,
                "No operating profit in any year. Essentially all value is "
                "terminal value, which is the definition of maximum duration.",
            ),
            Exposure(
                "financing_cost",
                0.95,
                "ADDED 18 Nov 2026. Cerebras is becoming a cloud operator, not "
                "just a chip vendor: Q3 cloud revenue +265% to $142M while "
                "hardware sales fell 29%, gross margin halved to 20%, and "
                "interest expense is now ~$75M/yr against zero before the IPO. "
                "Owning the fleet means funding the fleet. That puts it in the "
                "neocloud layer, where floating-rate paper is secured on "
                "depreciating accelerators -- and its largest forward "
                "counterparty, OpenAI, is itself not cash-flow positive. The "
                "~$26B backlog is only worth what the counterparties can pay. "
                "Amazon is the exception that proves the rule: it can pay, and "
                "the price of having it as a customer was exclusivity and "
                "minimum capacity guarantees in ITS favour.",
            ),
            Exposure("market_beta", 1.60, "Recent IPO, thin float, lockup supply still clearing. Already -65% from its post-IPO peak."),
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

from .valuation import ReturnEstimate  # noqa: E402

ESTIMATES: dict[str, ReturnEstimate] = {
    "SNDK": ReturnEstimate(
        "SNDK", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="DELIBERATELY NOT COMPUTED. Multiple convergence needs a "
              "multiple that means something, and ~4.1-4.6x forward does not: "
              "it is a low number on peak-cycle earnings, which the engine's "
              "own memory_cycle note calls 'the market discounting earnings it "
              "does not believe'. Running the arithmetic would produce a "
              "spectacular expected return by assuming an 85% gross margin "
              "persists for a decade in a six-supplier commodity market that "
              "earned a 7.1% gross margin in FY2023. The honest output is a "
              "refusal. If you want to underwrite this, the question is not "
              "the multiple -- it is what mid-cycle NAND gross margin is "
              "(history says 25-35%) and what EPS looks like there.",
        caveat="Same treatment as MU and for the same reason. To value either, "
               "normalize the margin first and then decide what to pay for "
               "normalized earnings. Anything else is extrapolating a shortage.",
    ),
    "NFLX": ReturnEstimate(
        "NFLX", eps_growth=0.16, current_multiple=20.9, target_multiple=20.0,
        basis="Revenue compounds low-to-mid teens (TTM +14.7%) and operating "
              "margin has added roughly 350bp a year since 2022 (17.8% -> "
              "31.3%), so EPS grows faster than revenue; FY2025 net income rose "
              "26% on 15.9% revenue growth. A record $4.80B of buyback in Q3 "
              "alone adds per-share accretion on top. 16% assumes that "
              "decelerates -- margin expansion cannot run at 350bp/yr forever. "
              "20.9x is CLEAN earnings (~$13.2B, operating income taxed at "
              "~15%), deliberately NOT the 19.0x on reported TTM net income, "
              "which is flattered by a ~$1.3B non-operating item in Q1 2026. "
              "Target 20x assumes essentially NO further compression, which is "
              "the whole bull case: a 31%-margin consumer annuity growing "
              "low-teens is already AT a mature multiple, having historically "
              "traded 30-50x. No dividend; capital returns come as buyback.",
        caveat="The subscriber count is gone and so is ARPU. You are taking "
               "management's word on the composition of the revenue -- how "
               "much is price rises versus new accounts versus ad-tier mix -- "
               "and there is no longer a public number to check it against. "
               "Same pattern as Vertiv withdrawing orders data, with a better "
               "stated reason. Judge it on revenue and margin, which is what "
               "they asked for, and accept that you cannot see underneath.",
    ),
    "VRT": ReturnEstimate(
        "VRT", eps_growth=0.20, current_multiple=37.1, target_multiple=22.0,
        basis="TTM revenue grew 35.3% and Q3 alone 61%, with operating margin "
              "at 20.1% TTM against 22.8% in the quarter, so margin is still "
              "expanding. 20% long-run EPS growth is well below the current "
              "ramp and assumes the AI buildout keeps going without "
              "accelerating. 37.1x is $77.8B over $2.10B of TTM net income -- "
              "clean, with no non-recurring items to strip. 22x is a mature "
              "industrial-technology multiple, implying -5.1%/yr of "
              "compression. No dividend.",
        caveat="Management WITHDREW orders disclosure this quarter. In a "
               "demand boom the order book is the leading indicator, and it "
               "is now the one number you cannot see. Treat the $15.0B Q2 "
               "backlog as the last hard datapoint. Separately, the stock fell "
               "16% in the fortnight after beating and raising, which is the "
               "volatility you are signing up for at ai_capex 1.10.",
    ),
    "SBGSY": ReturnEstimate(
        "SBGSY", eps_growth=0.13, current_multiple=27.0, target_multiple=22.0,
        dividend_yield=0.0153,
        basis="FY2026 organic revenue growth guided to 12-14%; 13% EPS growth "
              "assumes that holds with modest margin expansion and the "
              "buyback. 27x to 22x over ten years is -2.0%/yr of compression, "
              "the mildest of the three electrification names because the "
              "starting multiple is the lowest. "
              "DIVIDEND IS NET, NOT GROSS. The gross yield is ~1.8%; 1.53% is "
              "what reaches a Roth after 15% French treaty withholding. In a "
              "TAXABLE account that 27bp would come back as a foreign tax "
              "credit. In a Roth there is no US tax liability to credit it "
              "against, so it is a permanent, unrecoverable leak -- and if the "
              "broker applies the 25% statutory rate instead of the treaty "
              "rate, the leak is 45bp/yr. Over a decade that is roughly 3-4.5% "
              "of cumulative value, spent purely on the account type.",
        caveat="A EUR-denominated ADR traded OTC. Currency is an unhedged "
               "second bet, the spread is wider than a listed US name, and ADR "
               "custody fees run ~1-3c/share/yr on top of the withholding. "
               "None of that is in the return estimate.",
    ),
    "GEV": ReturnEstimate(
        "GEV", eps_growth=0.22, current_multiple=42.0, target_multiple=28.0,
        dividend_yield=0.0025,
        basis="22% is the margin ramp, not revenue growth: Q3 2026 operating "
              "margin was 11.0% against 3.7% a year earlier, on revenue up "
              "18% organically, and FY2026 is guided to a 13.5-14.5% adjusted "
              "EBITDA margin. Revenue alone compounds mid-teens against a "
              "$197B backlog (4.5 years booked); margin does the rest. 42x is "
              "ANNUALIZED Q3 GAAP EPS of $4.81 -- deliberately NOT the TTM P/E "
              "of 20.8x, which is flattered by $7.1B of non-recurring Prolec "
              "and tax items. 28x is a premium capital-goods multiple a decade "
              "out, which still assumes -4.0%/yr of compression.",
        caveat="The DCF is NOT resolvable from public figures, and that is the "
               "finding. Reverse DCF on reported TTM FCF of $17.1B says the "
               "price requires -2.7% growth; on FCF with the working-capital "
               "inflow stripped out ($1.4B) it requires +63.7%. A 66-point "
               "spread on one input. Everything depends on how much of the "
               "$17.1B is customer progress payments rather than earnings, and "
               "the press release line items needed to settle it were not "
               "reachable. Read the 10-Q cash flow statement yourself.",
    ),
    "SNPS": ReturnEstimate(
        "SNPS", eps_growth=0.22, current_multiple=22.5, target_multiple=22.0,
        basis="Guided ~22% EPS CAGR. Multiple held flat: 22.5x is near its own "
              "ten-year average, so no re-rating is assumed in either direction.",
    ),
    "GOOGL": ReturnEstimate(
        "GOOGL", eps_growth=0.16, current_multiple=22.0, target_multiple=21.0,
        dividend_yield=0.004,
        basis="RAISED from 14% growth / 20x target on 16 Nov 2026. The original "
              "estimate priced advertising plus cloud and gave no weight to TPU "
              "as an EXTERNAL hardware business, which is now a real line: Meta "
              "signed a multi-year multibillion deal to rent TPUs (~Feb 2026, "
              "neither party confirming terms), Google runs a JV leasing TPUs to "
              "outside customers, and Alphabet's CFO has said some TPU hardware "
              "revenue lands in 2026 with the larger impact in 2027. Press "
              "reports an internal Google Cloud aspiration to capture ~10% of "
              "NVIDIA's annual revenue (~$200B) through TPU sales -- that figure "
              "is an aspiration, not guidance, and is NOT in this estimate. 16% "
              "and a near-flat multiple is the conservative read: it credits TPU "
              "as additive without pricing the aspiration.",
        caveat="Antitrust remains unresolved. TPU upside is deliberately "
               "under-weighted rather than excluded.",
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
    "CORT": ReturnEstimate(
        "CORT", eps_growth=0.25, current_multiple=20.0, target_multiple=18.0,
        basis="Net income $126.8M in Q3 against $19.7M a year earlier; FY2026 "
              "guided $1.1-1.2B of revenue. 25% is a conservative long-run EPS "
              "rate well below the current ramp. Mild compression assumed. This "
              "EXCLUDES the relacorilant Cushing's decision on 17 Dec 2026 -- "
              "approval opens a $3-5B revenue case that no multiple here "
              "reflects, and the estimate deliberately does not price it.",
        caveat="Binary PDUFA event 32 days out. Size as if it can go either way.",
    ),
    "LNG": ReturnEstimate(
        "LNG", eps_growth=0.07, current_multiple=14.0, target_multiple=14.0,
        dividend_yield=0.028,
        basis="Contracted take-or-pay cash flows, FY2026 EBITDA guidance raised "
              "three consecutive quarters to $8.75-9.25B, DCF $6.05-6.55B. "
              "Dividend raised 12%+ and a $10B buyback shrinking the count, so "
              "per-share growth exceeds EBITDA growth. Multiple held flat: "
              "infrastructure does not re-rate much in either direction.",
    ),
    "CRDO": ReturnEstimate(
        "CRDO", eps_growth=0.30, current_multiple=60.0, target_multiple=30.0,
        basis="FY2027 guided to grow 85%+, so 30% is a long-run rate far below "
              "the current ramp. Target 30x still rich. The multiple does most "
              "of the work here, and the top four customers at 84% of revenue "
              "with no purchase commitments is why it could compress fast.",
        caveat="Customer concentration is the thesis risk, not a footnote.",
    ),
    "CRWV": ReturnEstimate(
        "CRWV", eps_growth=0.0, current_multiple=0.0, target_multiple=0.0,
        applicable=False,
        basis="GAAP net loss $709M, widened from $110M. Interest alone is 23% "
              "of revenue and rising. There is no earnings base to converge "
              "from, and the $132.5B backlog is a gross revenue figure with no "
              "debt service netted against it.",
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
