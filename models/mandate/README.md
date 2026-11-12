# `mandate` — portfolio risk, policy enforcement, and research gating

## What this does not do

It does not pick stocks. No script does. If one could reliably select ten-year
winners it would be the most valuable software ever written and it would not be
in a personal repository.

Anything that claims otherwise is showing you a backtest, which is a record of
how well a rule would have worked on the data used to invent it.

## What it does instead

Three things that humans and language models both get reliably wrong, and that
arithmetic gets reliably right.

| Module | Job |
|---|---|
| `policy.py` | Enforces the IPS mechanically. A limit cannot be talked out of its conclusion by a good story. |
| `risk.py` | Measures concentration the eye cannot see — effective positions, effective *bets* after correlation, weighted factor loading. |
| `scenarios.py` | Propagates named macro shocks through declared exposures. "What breaks, and roughly how much." |
| `factors.py` | The assumption layer. Every downstream number descends from the exposures declared here. |
| `rubric.py` | Gates research completeness. The tractable part of "let agents pick stocks". |

## Quick start

```bash
cd models
python -m mandate.review                    # full review
python -m mandate.review --candidate AMD    # what would adding AMD do?
python -m mandate.review --brief AMD        # research brief for an agent
python -m mandate.review --prices closes.csv  # enables correlation
```

Python 3.10+. Verified on 3.11 (typical Anaconda) and 3.13. Needs only numpy
and pandas, both of which Anaconda already has.

## Spyder

**Open `models/run_review.py`, not a file inside the package.** The package
uses relative imports, which is correct for a package and is exactly what
breaks under F5 — `runfile()` executes a script as `__main__` with no package
context, so a relative import has nothing to be relative to. `run_review.py`
sits above the package, fixes `sys.path`, and imports absolutely.

It is split into `#%%` cells. Ctrl+Enter runs the cell under the cursor and
leaves everything in the namespace, so `book`, `factor_table`, `scenario_df`
and `grid` are all inspectable in the Variable Explorer. That is the reason to
work here rather than in a terminal: **the printed report is the summary, the
objects are the actual work.**

| Cell | What it leaves behind |
|---|---|
| 2 | `book` — positions, weights, themes, funding plan |
| 3 | `findings_df` — policy audit, sortable |
| 4 | `factor_table` — current vs. each candidate, with `worst_delta` |
| 5 | `corr` — correlation matrix and effective bets (needs prices) |
| 6 | `scenario_df`, `attribution` |
| 7 | `grid` — per-position × per-scenario returns |

### TensorFlow

Installed but deliberately unused. There is no supervised learning problem
here. A network fitted to a few years of returns yields a confident number with
no information in it, and it is *harder to argue with* than arithmetic — which
makes it worse, not better. The judgment in this package lives in
`factors.py`, where it is written down and can be contradicted.

`--prices` wants a CSV with a date index and one adjusted-close column per
ticker. Without it, correlation is **skipped rather than estimated**. A
correlation invented from no data is worse than an absent one, because it looks
like a measurement.

## The design principle

**Arithmetic belongs in code. Judgment belongs in data, written down and
sourced.**

Every factor exposure in `factors.py` carries a `basis` string explaining why
it holds that value. `validate()` refuses an exposure with an empty basis. This
is not bureaucracy — it is the whole point. An exposure you cannot justify is a
guess with a decimal point on it, and the decimal point is what makes it
dangerous.

The same rule governs `scenarios.py`: every scenario requires a historical
`analogue`, and the constructor raises without one. A scenario you cannot
anchor to something that has actually happened is a number you invented.

## Using it with an agent

1. `python3.13 -m mandate.review --brief TICKER` → hand the output to the agent
2. Agent returns a completed `Brief`
3. `Brief.gate()` → binary admissibility

If the gate fails, the recommendation is not admissible. Not "weak", not "needs
another pass". **Inadmissible.** Send it back.

The gate rejects, among other things:

- any claim without a source
- fewer than three named ways to lose money
- fewer than two tripwires
- **tripwires expressed as price levels** — §7 sells falling value, never
  falling price
- a candidate assessed in isolation rather than against the existing book

The dominant failure mode in concentrated investing is not bad analysis. It is
*incomplete* analysis that felt complete, because the easy parts were
researched thoroughly and the hard parts were skipped. A gate that fails on
missing evidence turns a silent failure into a loud one.

## The ten-year fields

Three fields exist only because the horizon is ten years:

- **`terminal_question`** — what must be true in 2036 for this to have worked?
- **`obsolescence_path`** — what replaces this, and what is the first evidence?
  "Nothing" is not an acceptable answer.
- **`budget_line`** — capital or operating?

The third is the one most writeups omit and the one that best predicts downturn
behaviour. Revenue sitting in somebody's **capital** budget gets deferred in
lumps. Revenue in an **operating** budget does not. This distinction is why an
EDA vendor and an accelerator vendor behave completely differently in the same
AI downturn, despite selling into the same industry.

## Limitations worth knowing

- The factor model is **linear and single-period**. No convexity, no contagion,
  no correlations going to 1 in a crisis.
- Scenario severities are **calibrated judgments**, not probabilities. The
  engine deliberately does not weight scenarios by likelihood, because doing so
  would hide the calibration inside a single number.
- Weight-based metrics work without price history; correlation-based ones do
  not and will say so rather than guess.
- `portfolio.json` ships with `market_value: null`, which makes the review fall
  back to **cost-basis weights** and print a warning. Cost-basis weighting
  flatters concentration by understating winners. Fill in real values.
