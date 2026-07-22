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
