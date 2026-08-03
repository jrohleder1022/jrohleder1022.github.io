# Symbotic (SYM) — DCF Valuation & 3-Statement Model

`SYM_Valuation_Model.xlsx` — built July 20, 2026, from Symbotic's Q2 FY2026 results
(the ir.symbotic.com/node/11021 filing, cross-sourced from SEC 8-K/10-K mirrors)
plus current market data.

## Contents

| Sheet | What it does |
|---|---|
| Cover | Legend, instructions, full source URLs |
| Assumptions | Scenario switch (1=Base, 2=Bull, 3=Bear), all growth/margin/WC/capex/tax levers, WACC & terminal inputs, scenario probability weights |
| Historicals | FY2022–FY2025 actuals + FY2026 quarterly build (Q1/Q2 actual, Q3 guidance, Q4 extrapolated) |
| Model_3S | Fully linked income statement, balance sheet, cash flow, working capital, capex/PP&E and debt schedules, FY2026E–FY2035E; balance check row = 0 in every year |
| WACC | CAPM build: 10Y UST 4.55%, beta 1.90, ERP 4.75% → WACC ≈ 13.4% |
| DCF | Unlevered FCF (mid-year convention), terminal value by Gordon growth **and** exit multiple, 3 sensitivity tables (WACC×g, WACC×exit multiple, growth×margin) |
| Comps | Warehouse/industrial automation peer multiples and implied value |
| Precedents | Precedent M&A transactions and implied value |
| LBO | 5-yr hold, 4.5x leverage, FCF sweep; max entry price at 15/20/25/30% IRR |
| Monte_Carlo | 500 live RAND() trials over growth/margin/WACC/exit multiple + scenario probability-weighted value |
| Football_Field | Summary chart of all methodologies vs. the current price |

## Headline outputs (Base case, at build time)

- DCF value/share: ~$12 (Gordon) to ~$18 (exit multiple) vs. market $42.51
- Scenario-weighted (50/30/20 Base/Bull/Bear): ~$19
- LBO floor: ~$10–15/share; comps: ~$13–32/share
- The market price embeds materially faster backlog conversion and margin
  expansion than the Base case — see the Bull toggle and sensitivity tables.

Educational model, not investment advice. Estimated cells are flagged on-sheet.

**Update (July 20, 2026):** added an `Implied_Expectations` reverse-DCF sheet —
backs out what $42.51 requires: ~29% revenue CAGR for nine years at 21% terminal
EBITDA margins (vs. ~12% Base, ~17% Bull), cumulative revenue of ~4.8x today's
$22.7B backlog, and >100% implied probability of the Bull case. The market is
pricing GreenBox/new-vertical optionality beyond this model's horizon.


---

# Vistra Corp. (VST) — DCF Valuation & 3-Statement Model

`VST_Valuation_Model.xlsx` — built July 20, 2026, from SEC-mapped financials, live
quote/beta, consensus estimates and peer multiples pulled via Alpha Vantage
(VST, CEG, NRG, TLN), 7/17–7/20/2026.

Same 11-sheet architecture as the SYM model, adapted for an IPP: real debt burden
($20.4B, ~5.8% avg rate) with a refinance-at-maturity schedule + revolver,
dividends and buybacks in the equity roll, ~$2.0B preferred in the bridge, and
power-sector comps/precedents (Constellation–Calpine, ECP–Calpine, Vistra–Dynegy,
Vistra–Energy Harbor, TXU LBO). GAAP history is shown but the model anchors on
adjusted EBITDA (guidance ~$6.9B FY26E) and consensus revenue, since GAAP swings
with commodity mark-to-market.

Headline outputs (Base, at build time): DCF $132 (Gordon) – $171 (exit multiple)
vs. $155.44 market — roughly fair value; probability-weighted ~$180;
Monte Carlo P(value > price) ≈ 58%; LBO floor ~$99–145; precedents $79–121.

---

# X-Energy (XE) — DCF Valuation & 3-Statement Model

`XE_Valuation_Model.xlsx` — built July 20, 2026. X-Energy is the Amazon-backed
SMR/TRISO-fuel company that IPO'd April 24, 2026 at $23 (price at build: $14.02).

Same 11-sheet architecture, re-engineered for a pre-commercial company: fixed +
variable opex (burn doesn't scale with revenue), capex as a program budget, D&A
off the PP&E balance, revolver as a funding-gap indicator, an all-equity growth
take-private in place of a conventional LBO (EBITDA is negative — debt capacity
is zero), and comps/precedents on an EV-per-pipeline-GW framework (OKLO,
NuScale). Warrant mark-to-market excluded from the operating model.

Headline outputs (Base, at build time): 10-yr DCF $1.8 (Gordon) – $7.3 (exit
multiple) vs. $14.02 market — most SMR value sits beyond a 10-year window and
the workbook says so on its face; comps EV/GW $14–24; precedent framework
$11–20; probability-weighted ~$8.4; Monte Carlo P(value > price) ≈ 8%. The Base
case also surfaces a ~$0.7B external funding need around FY2030–33 (revolver
row) before FCF turns positive in FY2034.

---

# Cadence Design Systems (CDNS) — DCF Valuation & 3-Statement Model

`CDNS_Valuation_Model.xlsx` — built July 20, 2026. FY2026E revenue $6,175mm
(guidance midpoint, +17% incl. ~$160mm Hexagon), non-GAAP EPS guide ~$7.90,
Q1-26 backlog $8.0B.

Same 11-sheet architecture, tuned for a high-margin EDA compounder: 88% gross
margin, cash-opex leverage to a 50% terminal EBITDA margin (Base), $3.08B notes
with a refinance schedule, $1.3B/yr buybacks, and the Hexagon acquisition
modeled as a $3.1B(e) FY26 cash outflow landing in goodwill with $0.6B(e) new
debt. Comps: SNPS/ADSK/MSFT/ORCL. Precedents: Synopsys–Ansys (15.4x rev),
Siemens–Altair, Renesas–Altium, Siemens–Mentor.

Headline outputs (Base, at build time, price $330.10): DCF $182 (Gordon) – $297
(exit 20x) vs. market — exit-multiple DCF and comps ($248–356) bracket the
price; probability-weighted ~$310; Monte Carlo P(value > price) ≈ 24%; LBO
floor $147–222 (a CDNS buyout would be the largest tech LBO ever attempted).

---

# Synopsys (SNPS) — DCF Valuation & 3-Statement Model

`SNPS_Valuation_Model.xlsx` — built July 20, 2026. First full post-Ansys year:
FY2026E revenue $9,665mm / non-GAAP EPS $14.76 (raised guidance), net debt
$8.7B with a $1B/yr deleveraging schedule modeled, price $384.28 (52-wk
$366–652).

Headline outputs (Base): DCF $299 (Gordon) – $452 (exit 18x); comps $360–559;
precedent framework $365–567; probability-weighted ~$458; **Monte Carlo
P(value > price) ≈ 76%** — post-drawdown, SNPS is the only name in this set
where nearly every methodology sits above the market price. LBO floor $228–346.

---

# Growth_Comparison.xlsx

Cross-company chart comparing all five models' Base cases: modeled FY26→35
revenue CAGR, terminal EBITDA margin, probability-weighted upside, and Monte
Carlo odds. Verdict: X-Energy is the fastest grower (~40% CAGR, highest risk);
Synopsys is the best growth-adjusted-for-price (+19% weighted upside, 76% MC
odds); Symbotic and X-Energy are the growth you're asked to overpay for;
Cadence is a fair price for the best business.

---

# Industry_Ranking.xlsx

Six-way, 10-20-year industry ranking (July 2026): EDA (SNPS/CDNS), electricity
(VST), AI monetization (META), agentic SaaS (NOW), photonics/litho (VECO).
SNPS/CDNS/VST use their full workbooks' probability-weighted values; VECO, META
and NOW get compact scenario DCF sheets in this file (same framework,
condensed). Weighted upsides at build: SNPS +19%, VST +16%, META +5%, NOW +50%
(highest variance — agentic-disruption bear case), VECO −44% (price ~80% above
analyst median after the CPO run). Verdict: EDA first on moat + entry price,
power second on demand certainty, META third, NOW fourth (deep value or value
trap), VECO fifth (right industry, wrong price).

---

# Progress Software (PRGS) — DCF Valuation & 3-Statement Model

`PRGS_Valuation_Model.xlsx` — built July 21, 2026. Levered infrastructure-software
M&A roll-up: FY2026E revenue $996mm (raised guidance), non-GAAP EPS ~$6.15, adj
FCF ~$277mm, ARR +2% cc, ~$1.2B debt, price $39.58 (~6.4x fwd EPS, ~17% FCF
yield). Organic business only — serial M&A treated as unmodeled optionality.

Headline outputs (Base): DCF $77 (exit 8x) – $91 (Gordon); comps $49–79;
take-private precedents $59–89; probability-weighted ~$67; Monte Carlo
P(value > price) ≈ 100%; and the LBO actually pencils — a sponsor clears 20%+
IRR paying up to ~$56 (+40%), making the PE bid a live valuation floor. The
bear case ($32, 35% weight) is legacy decay — the market's central fear.

---

# T1 Energy (TE) — DCF Valuation & 3-Statement Model

`TE_Valuation_Model.xlsx` — built August 2026. US solar manufacturer (formerly
FREYR Battery). Q2-2026 prelim: revenue $245-255mm on 835 MW, net loss $34-37mm,
NEGATIVE adj. EBITDA, cash $156.4mm. G2_Austin cell plant Phase 1 capex raised to
$510mm, first cells delayed to Q1-2027. Price ~$6.81, ~279mm shares, ~$670mm debt.

Architecture adds an explicit **45X production tax credit line and statutory
phase-out schedule** (100% through 2029 → 75/50/25/0% 2030-33), because the
credits — not operating margin — are the profit engine. Gap-funding row flags
external financing needs (dilution not modeled).

Headline outputs (Base): FY29 EBITDA $516mm collapses to $183mm by FY33 as
credits zero out, even with revenue doubling; FY33 unlevered FCF turns negative.
DCF $0.82 (Gordon) – $2.61 (exit 7x) vs. $6.81 market; comps $0.60-$12.39
(EV/revenue vs peak-45X EV/EBITDA); Monte Carlo median $5.13, P(value > price)
39%, P(equity≈zero) 6%; probability-weighted $7.74. LBO/buyout capacity ≈ $0 —
a financial buyer cannot underwrite the equity on these assumptions.
