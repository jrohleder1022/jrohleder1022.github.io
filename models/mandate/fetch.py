"""
Data fetching — prices from Yahoo, fundamentals from SEC XBRL.
==============================================================

WHAT THIS FIXES
---------------
Three gaps that have been open since the package was written:

  1. Correlation was always SKIPPED, because no price history was supplied.
     This writes closes.csv, which turns it on.
  2. Market values had to be typed in by hand, so the weights drifted out of
     date between sessions.
  3. Balance-sheet fields in the watchlist sat at 0.0, which made ROIC
     uncomputable for every candidate.

NETWORK CODE IS UNTESTED IN THE AUTHORING SANDBOX
-------------------------------------------------
Both yahoo and data.sec.gov are blocked by the proxy where this file was
written, so the HTTP paths here have NOT been executed. The parsing and the
JSON handling were tested against saved fixtures; the requests themselves were
not. Run `python -m mandate.fetch --check` first: it reports exactly which
endpoints answer, so a failure is loud rather than silent.

If something is wrong it will be in the request layer, not the arithmetic.

TWO SOURCES, DELIBERATELY
-------------------------
    PRICES        yfinance. Free, no key, good enough for closes.
    FUNDAMENTALS  SEC XBRL company-facts API. Authoritative, free, no key.
                  Yahoo's fundamentals are inconsistent across tickers; the
                  SEC's are the numbers the company actually filed.

Nothing here needs an API key, so there is no credential to store.

ON THE USER-AGENT
-----------------
The SEC asks automated clients to identify themselves. This sends a generic
tool name and NO personal information. Do not put a real email address in it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SEC_UA = "mandate-portfolio-tool/0.1 (personal research)"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"

# CIK numbers for every ticker in the book and watchlist. These are stable
# identifiers; the SEC API takes them zero-padded to ten digits.
CIK = {
    "GOOGL": 1652044, "SNPS": 883241, "NOW": 1373715, "AMD": 2488,
    "CORT": 1088856, "CRDO": 1807794, "LNG": 3570, "CME": 1156375,
    "WM": 823768, "PGR": 80661, "V": 1403161, "MU": 723125,
    "NVDA": 1045810, "INTC": 50863, "RKLB": 1819994, "LUNR": 1844452,
    "IONQ": 1824920, "CRWV": 1769628, "CBRS": 2021728,
}

# XBRL tags for the fields company.py needs. A company may report under a
# different tag, in which case the fetch returns None for that field rather
# than guessing — a missing number is better than a wrong one.
TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "net_income": "NetIncomeLoss",
    "ebit": "OperatingIncomeLoss",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "equity": "StockholdersEquity",
    "goodwill": "Goodwill",
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "shares_diluted": "WeightedAverageNumberOfDilutedSharesOutstanding",
    # Needed for the DCF: base FCF is CFO minus capex, and net debt is
    # total debt minus cash. Without these the intrinsic-value block cannot
    # be built, which was the gap.
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "debt_long": "LongTermDebtNoncurrent",
    "debt_short": "LongTermDebtCurrent",
}


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def fetch_closes(tickers: list[str], period: str = "3y") -> pd.DataFrame:
    """Daily adjusted closes as a dates x tickers frame.

    Three years is the practical minimum for correlation. A single quiet year
    tells you how things behaved while nothing happened, which is the opposite
    of what the measurement is for.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is not installed. In an Anaconda Prompt:\n"
            "    pip install yfinance"
        ) from exc

    data = yf.download(tickers, period=period, progress=False, auto_adjust=True)
    if data is None or len(data) == 0:
        raise RuntimeError(
            "yfinance returned nothing. Usually a network block or a bad "
            "ticker. Try one ticker alone to isolate it."
        )
    closes = data["Close"] if "Close" in data else data
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    return closes.dropna(how="all")


def fetch_quote(ticker: str) -> float | None:
    """Latest close for one ticker, or None if it cannot be had."""
    try:
        frame = fetch_closes([ticker], period="5d")
        series = frame[ticker].dropna()
        return float(series.iloc[-1]) if len(series) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fundamentals from SEC XBRL
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    tag: str
    value: float
    period_end: str
    form: str
    frame: str


def fetch_sec_concept(ticker: str, tag: str, timeout: int = 20) -> Fact | None:
    """Most recent reported value of one XBRL tag, or None.

    Returns None rather than raising on a missing tag, because companies
    legitimately report under different tags and a gap is informative. It
    DOES raise on a network or auth failure, so a broken connection cannot be
    mistaken for a company that does not report the field.
    """
    import urllib.error
    import urllib.request

    cik = CIK.get(ticker)
    if cik is None:
        raise KeyError(f"no CIK recorded for {ticker}. Add it to fetch.CIK.")

    url = SEC_FACTS.format(cik=cik, tag=tag)
    request = urllib.request.Request(url, headers={"User-Agent": SEC_UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # company does not report this tag
        raise RuntimeError(f"SEC returned HTTP {exc.code} for {ticker}/{tag}") from exc

    units = payload.get("units", {}).get("USD") or payload.get("units", {}).get("shares")
    if not units:
        return None

    # Prefer the most recent quarterly or annual figure that has a frame,
    # which filters out the restated and duplicated entries.
    framed = [u for u in units if u.get("frame")]
    chosen = max(framed or units, key=lambda u: u.get("end", ""))
    return Fact(
        tag=tag, value=float(chosen["val"]), period_end=chosen.get("end", ""),
        form=chosen.get("form", ""), frame=chosen.get("frame", ""),
    )


def fetch_fundamentals(ticker: str, pause: float = 0.15) -> dict[str, Fact | None]:
    """Every field in TAGS for one ticker.

    `pause` respects the SEC's rate guidance of roughly ten requests a second.
    """
    out: dict[str, Fact | None] = {}
    for field, tag in TAGS.items():
        out[field] = fetch_sec_concept(ticker, tag)
        time.sleep(pause)
    return out


# ---------------------------------------------------------------------------
# Updating the portfolio file
# ---------------------------------------------------------------------------


def update_market_values(path: Path, dry_run: bool = False) -> list[str]:
    """Recompute market_value as shares x latest close.

    REQUIRES a `shares` field on each position. Without it there is no way to
    turn a price into a market value, and the whole point of this function is
    to stop the weights going stale between sessions. Positions without
    `shares` are left exactly as they are and reported.
    """
    data = json.loads(path.read_text())
    notes: list[str] = []
    for row in data["positions"]:
        ticker = row["ticker"]
        shares = row.get("shares")
        if not shares:
            notes.append(f"{ticker}: no `shares` field — market_value left unchanged")
            continue
        price = fetch_quote(ticker)
        if price is None:
            notes.append(f"{ticker}: quote failed — market_value left unchanged")
            continue
        new_value = round(shares * price, 2)
        old_value = row.get("market_value")
        notes.append(
            f"{ticker}: {shares} x ${price:,.2f} = ${new_value:,.2f}"
            + (f"  (was ${old_value:,.2f})" if old_value else "")
        )
        if not dry_run:
            row["market_value"] = new_value
    if not dry_run:
        data["_fetched_at"] = time.strftime("%Y-%m-%d %H:%M")
        path.write_text(json.dumps(data, indent=2) + "\n")
    return notes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def check() -> int:
    """Probe both endpoints and say plainly which work."""
    print("CONNECTIVITY CHECK\n")
    ok = 0

    print("  yfinance (prices)")
    try:
        price = fetch_quote("SNPS")
        if price:
            print(f"    OK   SNPS last close ${price:,.2f}")
            ok += 1
        else:
            print("    FAIL returned no data")
    except Exception as exc:
        print(f"    FAIL {type(exc).__name__}: {str(exc)[:90]}")

    print("\n  data.sec.gov (fundamentals)")
    try:
        fact = fetch_sec_concept("SNPS", TAGS["equity"])
        if fact:
            print(f"    OK   SNPS StockholdersEquity ${fact.value:,.0f}"
                  f" as of {fact.period_end} ({fact.form})")
            ok += 1
        else:
            print("    FAIL tag not reported (unexpected for this one)")
    except Exception as exc:
        print(f"    FAIL {type(exc).__name__}: {str(exc)[:90]}")

    print(f"\n  {ok}/2 sources reachable")
    if ok < 2:
        print("\n  A failure here is a network or install problem, not a bug in")
        print("  the arithmetic. pip install yfinance, and check whether a VPN or")
        print("  corporate proxy is blocking the hosts.")
    return 0 if ok == 2 else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Fetch prices and fundamentals.")
    parser.add_argument("--check", action="store_true", help="probe both endpoints")
    parser.add_argument("--prices", action="store_true", help="write closes.csv")
    parser.add_argument("--values", action="store_true", help="update market values")
    parser.add_argument("--facts", type=str, help="print SEC fundamentals for a ticker")
    parser.add_argument("--scaffold", type=str,
                        help="emit a paste-ready block for a new ticker")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--portfolio", type=Path, default=here / "portfolio.json")
    parser.add_argument("--out", type=Path, default=here.parent / "closes.csv")
    parser.add_argument("--period", type=str, default="3y")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    if args.prices:
        data = json.loads(args.portfolio.read_text())
        tickers = [r["ticker"] for r in data["positions"]]
        print(f"fetching {args.period} of closes for {', '.join(tickers)} ...")
        frame = fetch_closes(tickers, args.period)
        frame.to_csv(args.out)
        print(f"wrote {args.out}  ({len(frame)} rows, {len(frame.columns)} tickers)")
        print("\nCorrelation now works:")
        print(f"  python -m mandate.review --prices {args.out}")
        return 0

    if args.values:
        for note in update_market_values(args.portfolio, dry_run=args.dry_run):
            print(f"  {note}")
        if args.dry_run:
            print("\n  dry run — nothing written")
        return 0

    if args.facts:
        ticker = args.facts.upper()
        print(f"SEC XBRL facts for {ticker}\n")
        for field, fact in fetch_fundamentals(ticker).items():
            if fact is None:
                print(f"  {field:<16} not reported under {TAGS[field]}")
            else:
                print(f"  {field:<16} {fact.value:>20,.0f}   {fact.period_end}  {fact.form}")
        print("\n  Paste these into a Fundamentals block. A 'not reported' line")
        print("  means the company files under a different tag — look it up in")
        print("  the filing rather than substituting a guess.")
        return 0

    if args.scaffold:
        print(scaffold(args.scaffold, fetch_quote(args.scaffold.upper())))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Scaffolding a new ticker
# ---------------------------------------------------------------------------


def scaffold(ticker: str, price: float | None = None) -> str:
    """Emit a paste-ready block for a new ticker, with real SEC figures in it.

    This is as far as automation honestly goes. It fills in everything that is
    a FACT — revenue, earnings, cash flow, the balance sheet, share count,
    straight from the company's own XBRL filings — and leaves every field that
    is a JUDGMENT marked REPLACE.

    The division is not arbitrary. A filing can tell you what a company earned.
    It cannot tell you whether its moat holds for ten years, whose budget its
    revenue comes out of, or what multiple it deserves. Those are the inputs
    that actually drive the output, and a tool that guessed at them would be
    producing confident numbers with nothing behind them.
    """
    ticker = ticker.upper()
    if ticker not in CIK:
        return (
            f"# {ticker} has no CIK recorded. Look it up at\n"
            f"#   https://www.sec.gov/cgi-bin/browse-edgar?company={ticker}\n"
            f"# and add it to fetch.CIK, then re-run."
        )

    facts = fetch_fundamentals(ticker)

    def value(field: str) -> str:
        fact = facts.get(field)
        return f"{fact.value:_.0f}" if fact else "0.0  # NOT REPORTED — look it up"

    def dated(field: str) -> str:
        fact = facts.get(field)
        return f"{fact.period_end} {fact.form}" if fact else "missing"

    px = f"{price:.2f}" if price else "0.0  # REPLACE with the current price"
    px_plain = f"{price:.2f}" if price else "0.0"

    def _num(field: str) -> float | None:
        fact = facts.get(field)
        return fact.value if fact else None

    _cfo, _capex = _num("cfo"), _num("capex")
    fcf = (f"{_cfo - abs(_capex):_.0f}" if _cfo is not None and _capex is not None
           else "0.0  # CFO or capex not reported — compute by hand")

    capex_v = (f"{abs(_capex):_.0f}" if _capex is not None
               else "0.0  # NOT REPORTED — purchases of PP&E, look it up")

    _dl, _ds, _cash = _num("debt_long"), _num("debt_short"), _num("cash")
    debt_v = (f"{(_dl or 0) + (_ds or 0):_.0f}"
              if (_dl is not None or _ds is not None)
              else "0.0  # NOT REPORTED — short + long term debt, look it up")
    if _cash is not None and (_dl is not None or _ds is not None):
        _nd = (_dl or 0) + (_ds or 0) - _cash
        netdebt = f"{_nd:_.0f}"
    else:
        netdebt = "0.0  # debt or cash not reported — compute by hand"

    return f'''
# ===========================================================================
# {ticker} — scaffolded from SEC XBRL. Facts filled in; judgments marked.
# Revenue as of {dated("revenue")}.  Equity as of {dated("equity")}.
# ===========================================================================

# --- FACTS: straight from the filings. Spot-check the dates above. ---------
{ticker}_FUNDAMENTALS = Fundamentals(
    ticker="{ticker}",
    revenue={value("revenue")},
    revenue_prior=0.0,              # REPLACE: same period a year earlier
    gross_profit=0.0,               # REPLACE: not a standard XBRL tag
    ebit={value("ebit")},
    net_income={value("net_income")},
    interest_expense=0.0,           # REPLACE: from the debt footnote
    tax_rate=0.21,                  # REPLACE with the effective rate
    cfo={value("cfo")},
    capex={capex_v},
    total_debt={debt_v},
    cash={value("cash")},
    equity={value("equity")},
    goodwill={value("goodwill")},
    shares_diluted={value("shares_diluted")},
    shares_diluted_prior=0.0,       # REPLACE
    price={px},
    wacc=QUALITY_WACC.value(),
    basis={{"revenue": "SEC XBRL {dated("revenue")}",
           "cfo": "SEC XBRL {dated("cfo")}",
           "total_debt": "SEC XBRL long-term + short-term"}},
)

# --- JUDGMENTS: no filing contains these. They drive the whole output. -----
# Factor names: ai_capex semi_rd china_policy rates_duration enterprise_it
#   ad_cycle regulatory gov_appropriation saas_disintermediation
#   digital_services_tax consumer_spending commodity_cycle clinical_regulatory
#   financing_cost market_volatility market_beta   <- market_beta REQUIRED
# Beta is an elasticity: 1.0 = full pass-through, negative = position GAINS.

CANDIDATES["{ticker}"] = ExposureSet(
    ticker="{ticker}",
    thesis="REPLACE: what it does, who pays, latest hard numbers with dates.",
    exposures=[
        Exposure("market_beta", 1.00, "REPLACE: why this number."),
        # add three to five more
    ],
)

ESTIMATES["{ticker}"] = ReturnEstimate(
    "{ticker}", eps_growth=0.00, current_multiple=0.0, target_multiple=0.0,
    applicable=False,               # set True once the multiples are real
    basis="REPLACE: where the growth rate and target multiple come from.",
)

# --- 3. INTRINSIC VALUE: base_fcf and net_debt computed from the facts -----
# base_fcf = CFO - capex.  net_debt = long-term + short-term debt - cash.
# A NEGATIVE net_debt means net cash, which is correct and the code expects it.
# The growth rates are the only judgments here, and they drive everything.

{ticker}_WACC = WACCInputs(
    risk_free=0.0415,               # 10Y Treasury
    equity_risk_premium=0.045,
    beta=1.00,                      # REPLACE: match market_beta above
    cost_of_debt=0.050,
    tax_rate=0.21,
    debt_weight=0.00,               # REPLACE: debt / (debt + market cap)
    basis="REPLACE: where these came from.",
)

{ticker}_DCF = DCFAssumptions(
    ticker="{ticker}",
    base_fcf={fcf},
    shares_diluted={value("shares_diluted")},
    net_debt={netdebt},
    initial_growth=0.00,            # REPLACE: your year-1 FCF growth view
    terminal_growth=0.03,           # the code rejects anything above ~4%
    years=10,
    wacc={ticker}_WACC,
    basis={{"base_fcf": "SEC XBRL: CFO {dated("cfo")} less capex",
           "initial_growth": "REPLACE: my estimate",
           "terminal_growth": "~nominal GDP"}},
)

# --- then run ---------------------------------------------------------------
# All three levels at once. Pass the current price for the DCF upside.
# analyze("{ticker}", CANDIDATES["{ticker}"], {ticker}_FUNDAMENTALS,
#         {ticker}_DCF, price={px_plain})
#
# The DCF REFUSES to run on negative base_fcf, by design. For a pre-profit
# company use multiple_convergence() in cell 6 instead and be explicit that
# you are underwriting a story rather than a cash flow.
'''
