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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
