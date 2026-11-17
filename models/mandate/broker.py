"""
Broker statement import — turn a positions export into portfolio.json.
======================================================================

WHY THIS IS BETTER THAN FETCHING PRICES
---------------------------------------
A broker export already contains shares, market value AND cost basis, all
as of the same instant and all reconciled to the account. Fetching prices
gives you one of those three and requires the share count you were trying to
avoid typing. So this needs no network, no API key, and cannot drift out of
sync with itself.

It also keeps your holdings on your machine. Nothing here uploads anything.

FIDELITY
--------
Positions > Download. You get `Portfolio_Positions_<date>.csv` with a header
row, one row per holding, then several footer rows of disclaimer text that
have to be skipped — they are not data and they are not consistently
formatted.

Columns used: Symbol, Quantity, Current Value, Cost Basis Total.
Money arrives as "$4,664.58" and has to be unwrapped.

SPAXX and similar sweep tickers are treated as CASH rather than a position,
which is what they are.

OTHER BROKERS
-------------
Schwab and Vanguard exports are close enough in shape that the same parser
handles them with a different column map. If yours is not recognised, run with
`--columns` and it prints what it found so a map can be added.

WHAT IT WILL NOT DO
-------------------
It cannot know a position's `theme` or `sleeve` — those are judgments, not
data. Existing values in portfolio.json are preserved; genuinely new tickers
come in as theme "UNCLASSIFIED" and must be set by hand before the scenario
engine will run, because an unclassified holding is an unmeasured risk.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Sweep and money-market tickers that are cash, not holdings.
CASH_TICKERS = {"SPAXX", "FDRXX", "FZFXX", "SPRXX", "FCASH", "QACDS", "CORE"}

COLUMN_MAPS = {
    "fidelity": {
        "ticker": "Symbol",
        "shares": "Quantity",
        "market_value": "Current Value",
        "cost_basis": "Cost Basis Total",
    },
    "schwab": {
        "ticker": "Symbol",
        "shares": "Quantity",
        "market_value": "Market Value",
        "cost_basis": "Cost Basis",
    },
    "vanguard": {
        "ticker": "Symbol",
        "shares": "Shares",
        "market_value": "Total Value",
        "cost_basis": "Total Cost",
    },
}


@dataclass
class Holding:
    ticker: str
    shares: float
    market_value: float
    cost_basis: float


def _money(raw: str | None) -> float | None:
    """Unwrap "$4,664.58", "(1,234.00)", "--", "n/a" into a float or None.

    Parentheses are the accounting convention for negative, which a naive
    float() would silently mis-parse as an error rather than a sign.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text in {"", "--", "n/a", "N/A", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", "."}:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value


def read_positions(path: Path, flavour: str = "fidelity") -> tuple[list[Holding], float, list[str]]:
    """Parse a positions export. Returns (holdings, cash, notes)."""
    if flavour not in COLUMN_MAPS:
        raise ValueError(f"unknown flavour {flavour!r}; known: {sorted(COLUMN_MAPS)}")
    cols = COLUMN_MAPS[flavour]

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Find the header row: the first line containing the ticker column name.
    header_index = next(
        (i for i, line in enumerate(lines) if cols["ticker"] in line), None
    )
    if header_index is None:
        raise ValueError(
            f"no column named {cols['ticker']!r} found. Run with --columns to see "
            "what the file actually contains."
        )

    reader = csv.DictReader(lines[header_index:])
    holdings: list[Holding] = []
    cash = 0.0
    notes: list[str] = []

    for row in reader:
        ticker = (row.get(cols["ticker"]) or "").strip().upper()
        # Footer disclaimer rows have no ticker, or prose in the field.
        if not ticker or len(ticker) > 6 or " " in ticker:
            continue

        value = _money(row.get(cols["market_value"]))
        if value is None:
            notes.append(f"{ticker}: no market value — skipped")
            continue

        if ticker in CASH_TICKERS:
            cash += value
            notes.append(f"{ticker}: ${value:,.2f} treated as CASH")
            continue

        holdings.append(Holding(
            ticker=ticker,
            shares=_money(row.get(cols["shares"])) or 0.0,
            market_value=value,
            cost_basis=_money(row.get(cols["cost_basis"])) or 0.0,
        ))

    return holdings, cash, notes


def merge_into_portfolio(
    holdings: list[Holding], cash: float, path: Path, dry_run: bool = False
) -> list[str]:
    """Write holdings into portfolio.json, preserving theme and sleeve.

    theme and sleeve are judgments that no export contains, so existing ones
    are kept and new tickers are marked UNCLASSIFIED rather than guessed at.
    """
    if path.exists():
        data = json.loads(path.read_text())
    else:
        template = path.parent / "portfolio.example.json"
        data = json.loads(template.read_text()) if template.exists() else {
            "positions": [], "cash": 0.0, "annual_contribution": 0.0,
        }
        data["positions"] = []

    existing = {r["ticker"]: r for r in data.get("positions", [])}
    notes: list[str] = []
    rows = []

    for h in holdings:
        prior = existing.get(h.ticker, {})
        theme = prior.get("theme", "UNCLASSIFIED")
        sleeve = prior.get("sleeve", "core" if h.market_value >= 1500 else "satellite")
        if h.ticker not in existing:
            notes.append(
                f"{h.ticker}: NEW — theme set to UNCLASSIFIED. Set it, and add a "
                "factor profile in factors.py BOOK, before the scenarios will run."
            )
        rows.append({
            "ticker": h.ticker,
            "cost_basis": round(h.cost_basis, 2),
            "market_value": round(h.market_value, 2),
            "shares": h.shares,
            "theme": theme,
            "sleeve": sleeve,
        })

    gone = set(existing) - {h.ticker for h in holdings}
    for ticker in sorted(gone):
        notes.append(f"{ticker}: in portfolio.json but NOT in the export — removed")

    data["positions"] = rows
    data["cash"] = round(cash, 2)
    data.setdefault("cash_purpose", "sweep balance from broker export")
    data.setdefault("cash_decision_date", "")
    data["_imported_from_broker"] = True

    if not dry_run:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return notes


def main(argv: list[str] | None = None) -> int:
    import argparse

    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("csv_path", type=Path, help="broker positions export")
    parser.add_argument("--flavour", default="fidelity", choices=sorted(COLUMN_MAPS))
    parser.add_argument("--portfolio", type=Path, default=here / "portfolio.json")
    parser.add_argument("--columns", action="store_true",
                        help="print the columns found and exit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.csv_path.exists():
        print(f"not found: {args.csv_path}")
        return 2

    if args.columns:
        text = args.csv_path.read_text(encoding="utf-8-sig", errors="replace")
        for i, line in enumerate(text.splitlines()[:12]):
            print(f"  {i}: {line[:150]}")
        return 0

    holdings, cash, parse_notes = read_positions(args.csv_path, args.flavour)
    print(f"Read {len(holdings)} holdings and ${cash:,.2f} of cash\n")
    for h in holdings:
        unreal = h.market_value - h.cost_basis
        print(f"  {h.ticker:<7}{h.shares:>12,.4f} sh  ${h.market_value:>11,.2f}  "
              f"cost ${h.cost_basis:>10,.2f}  {unreal:>+11,.2f}")
    for note in parse_notes:
        print(f"  note: {note}")

    print()
    for note in merge_into_portfolio(holdings, cash, args.portfolio, args.dry_run):
        print(f"  ! {note}")

    if args.dry_run:
        print("\n  dry run — nothing written")
    else:
        print(f"\n  wrote {args.portfolio}")
        print("  now run:  python -m mandate.review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
