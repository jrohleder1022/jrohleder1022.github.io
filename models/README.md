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
