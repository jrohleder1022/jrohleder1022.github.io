"""
Portfolio Rebalancing Engine
============================

Computes drift against a target allocation and emits an executable trade plan.

CORE MATH
---------
    total          = sum(holdings.values()) + new_cash
    current_weight = value_i / total
    target_value   = total * target_weight_i
    trade_i        = target_value_i - value_i        (+ buy, - sell)

By construction sum(trade_i) == new_cash, so a plan with no new cash is
self-funding: every dollar sold is a dollar bought.

DRIFT: TWO DEFINITIONS THAT DISAGREE
------------------------------------
"5% drift" is ambiguous and the two readings diverge sharply for small
positions. Both are supported via `DriftMode`:

    ABSOLUTE  |current - target|            in percentage points
              A 2% position with a 1% target drifts 1pp  -> no alert at 5pp.

    RELATIVE  |current - target| / target   as a fraction of the target
              That same position drifts 100% -> immediate alert.

ABSOLUTE is the right default for a concentrated book (it cares about dollars
at risk). RELATIVE is better when small satellite sleeves must stay
proportionate. Choosing the wrong one silently ignores drift you care about.

CASH-FLOW REBALANCING
---------------------
`allow_sells=False` restricts the plan to directing `new_cash` into whichever
positions are underweight, rather than selling winners. In a taxable account
this is usually preferable — no realized gains, no tax event. In a tax-advantaged
account (IRA/401k) selling is free of tax friction, so full rebalancing is fine.

USAGE
-----
    plan = build_plan(holdings, targets, threshold=0.05, prices=prices)
    print(format_plan(plan))
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #

Number = float
WEIGHT_TOLERANCE = 1e-6          # allowed error when validating target sums


class DriftMode(str, Enum):
    """How to measure distance from target. See module docstring."""
    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class RebalanceError(ValueError):
    """Raised when inputs are structurally invalid."""


@dataclass(frozen=True)
class AssetPlan:
    """Per-asset drift analysis and resulting trade."""
    ticker: str
    current_value: float
    current_weight: float
    target_weight: float
    target_value: float
    drift_pp: float                  # signed, in percentage points (+ = overweight)
    drift_relative: float            # signed, as a fraction of target weight
    breached: bool
    trade_value: float               # + = buy, - = sell, in fiat
    price: float | None = None
    shares: float | None = None      # approximate; sign matches trade_value

    @property
    def action(self) -> str:
        if self.trade_value > 0:
            return "BUY"
        if self.trade_value < 0:
            return "SELL"
        return "HOLD"


@dataclass(frozen=True)
class RebalancePlan:
    """Full portfolio plan. `assets` is sorted by absolute trade size."""
    total_value: float               # holdings only, before new cash
    new_cash: float
    investable_total: float          # total_value + new_cash
    assets: tuple[AssetPlan, ...]
    threshold: float
    mode: DriftMode
    allow_sells: bool

    @property
    def breached(self) -> tuple[AssetPlan, ...]:
        return tuple(a for a in self.assets if a.breached)

    @property
    def needs_rebalance(self) -> bool:
        return bool(self.breached)

    @property
    def trades(self) -> tuple[AssetPlan, ...]:
        return tuple(a for a in self.assets if a.action != "HOLD")

    @property
    def total_buys(self) -> float:
        return sum(a.trade_value for a in self.assets if a.trade_value > 0)

    @property
    def total_sells(self) -> float:
        return -sum(a.trade_value for a in self.assets if a.trade_value < 0)

    @property
    def turnover(self) -> float:
        """Fraction of the portfolio changing hands (one-way)."""
        if self.investable_total <= 0:
            return 0.0
        return self.total_sells / self.investable_total


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate_inputs(
    holdings: Mapping[str, Number],
    targets: Mapping[str, Number],
    new_cash: Number = 0.0,
) -> None:
    """Fail fast on structurally invalid input.

    Catches the three mistakes that silently corrupt a rebalance: negative
    values, targets that don't sum to 100%, and an empty portfolio.
    """
    if not holdings and new_cash <= 0:
        raise RebalanceError("Portfolio is empty and no new cash was supplied.")
    if not targets:
        raise RebalanceError("No target allocation supplied.")

    for ticker, value in holdings.items():
        if value < 0:
            raise RebalanceError(f"{ticker}: negative holding value ({value}).")
    for ticker, weight in targets.items():
        if weight < 0:
            raise RebalanceError(f"{ticker}: negative target weight ({weight}).")

    total_target = sum(targets.values())
    if abs(total_target - 1.0) > WEIGHT_TOLERANCE:
        raise RebalanceError(
            f"Target weights sum to {total_target:.6f}, expected 1.0. "
            "(Pass decimals, e.g. 0.25 for 25%.)"
        )
    if new_cash < 0:
        raise RebalanceError(f"new_cash cannot be negative ({new_cash}).")


def reconcile_universe(
    holdings: Mapping[str, Number],
    targets: Mapping[str, Number],
) -> list[str]:
    """Union of tickers, with implicit zeros filled in.

    A holding with no target has an implied target of 0% (full liquidation);
    a target with no holding is a new position to open. Both are legitimate,
    so we return the union rather than erroring.
    """
    return sorted(set(holdings) | set(targets))


# --------------------------------------------------------------------------- #
# Core engine
# --------------------------------------------------------------------------- #

def _compute_drift(
    current_weight: float,
    target_weight: float,
    mode: DriftMode,
) -> tuple[float, float]:
    """Return (drift_pp, drift_relative), both signed (+ = overweight)."""
    drift_pp = current_weight - target_weight
    if target_weight > 0:
        drift_relative = drift_pp / target_weight
    else:
        # No target: any holding is infinitely overweight. Use 1.0 (=100%) as a
        # finite stand-in so downstream comparisons and formatting stay sane.
        drift_relative = 1.0 if current_weight > 0 else 0.0
    return drift_pp, drift_relative


def build_plan(
    holdings: Mapping[str, Number],
    targets: Mapping[str, Number],
    *,
    threshold: float = 0.05,
    mode: DriftMode = DriftMode.ABSOLUTE,
    new_cash: Number = 0.0,
    allow_sells: bool = True,
    prices: Mapping[str, Number] | None = None,
    min_trade: float = 0.0,
    whole_shares: bool = False,
) -> RebalancePlan:
    """Analyze drift and produce an executable trade plan.

    Args:
        holdings:     {ticker: current market value}
        targets:      {ticker: target weight as a decimal}; must sum to 1.0
        threshold:    drift trigger, e.g. 0.05 for 5pp (ABSOLUTE) or 5% (RELATIVE)
        mode:         ABSOLUTE (percentage points) or RELATIVE (share of target)
        new_cash:     cash being added; funds buys before any selling is needed
        allow_sells:  False = cash-flow rebalancing only (no taxable sales)
        prices:       optional {ticker: price} to convert fiat into share counts
        min_trade:    suppress trades below this fiat amount (avoids $3 orders)
        whole_shares: round share counts toward zero (no fractional-share support)

    Returns:
        RebalancePlan with per-asset detail and portfolio aggregates.
    """
    validate_inputs(holdings, targets, new_cash)
    tickers = reconcile_universe(holdings, targets)

    total_value = float(sum(holdings.values()))
    investable = total_value + float(new_cash)
    if investable <= 0:
        raise RebalanceError("Investable total is zero — nothing to allocate.")

    # ---- Pass 1: weights, drift, and the unconstrained gap to target -------- #
    rows: list[dict] = []
    for ticker in tickers:
        value = float(holdings.get(ticker, 0.0))
        target_weight = float(targets.get(ticker, 0.0))
        current_weight = value / investable            # weight AFTER cash lands
        drift_pp, drift_rel = _compute_drift(current_weight, target_weight, mode)

        measured = abs(drift_pp) if mode is DriftMode.ABSOLUTE else abs(drift_rel)
        rows.append({
            "ticker": ticker,
            "value": value,
            "current_weight": current_weight,
            "target_weight": target_weight,
            "target_value": investable * target_weight,
            "drift_pp": drift_pp,
            "drift_relative": drift_rel,
            "breached": measured > threshold,
            "gap": investable * target_weight - value,   # + = underweight
        })

    # ---- Pass 2: turn gaps into trades ------------------------------------- #
    if allow_sells:
        # Full rebalance: trade the entire gap. Sum of trades == new_cash.
        for row in rows:
            row["trade"] = row["gap"]
    else:
        # Cash-flow only: distribute new_cash across underweights, pro-rata to
        # the size of each shortfall. Never sells, so drift closes gradually.
        shortfalls = {r["ticker"]: max(0.0, r["gap"]) for r in rows}
        total_shortfall = sum(shortfalls.values())
        for row in rows:
            if total_shortfall > 0 and new_cash > 0:
                share = shortfalls[row["ticker"]] / total_shortfall
                row["trade"] = new_cash * share
            else:
                row["trade"] = 0.0

    # ---- Pass 3: suppress dust, attach share counts ------------------------- #
    assets: list[AssetPlan] = []
    for row in rows:
        trade = row["trade"]
        if abs(trade) < min_trade:
            trade = 0.0

        price = float(prices[row["ticker"]]) if prices and row["ticker"] in prices else None
        shares: float | None = None
        if price and price > 0 and trade:
            shares = trade / price
            if whole_shares:
                # Round toward zero so a buy never overspends available cash.
                shares = float(int(shares))
                trade = shares * price

        assets.append(AssetPlan(
            ticker=row["ticker"],
            current_value=row["value"],
            current_weight=row["current_weight"],
            target_weight=row["target_weight"],
            target_value=row["target_value"],
            drift_pp=row["drift_pp"],
            drift_relative=row["drift_relative"],
            breached=row["breached"],
            trade_value=trade,
            price=price,
            shares=shares,
        ))

    assets.sort(key=lambda a: abs(a.trade_value), reverse=True)
    return RebalancePlan(
        total_value=total_value,
        new_cash=float(new_cash),
        investable_total=investable,
        assets=tuple(assets),
        threshold=threshold,
        mode=mode,
        allow_sells=allow_sells,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def format_plan(plan: RebalancePlan, currency: str = "$") -> str:
    """Render a plan as an aligned, human-readable execution report."""
    out: list[str] = []
    add = out.append

    add("=" * 78)
    add("PORTFOLIO REBALANCE PLAN")
    add("=" * 78)
    add(f"Holdings value   : {currency}{plan.total_value:,.2f}")
    if plan.new_cash:
        add(f"New cash         : {currency}{plan.new_cash:,.2f}")
        add(f"Investable total : {currency}{plan.investable_total:,.2f}")
    mode_label = "percentage points" if plan.mode is DriftMode.ABSOLUTE else "of target"
    add(f"Drift threshold  : {plan.threshold:.1%} ({mode_label})")
    add(f"Mode             : {'full rebalance' if plan.allow_sells else 'cash-flow only (no sells)'}")
    add("")

    # ---- Drift table ---- #
    add("CURRENT vs TARGET")
    add("-" * 78)
    add(f"{'Ticker':<8}{'Value':>14}{'Current':>10}{'Target':>10}{'Drift':>10}  {'Status':<12}")
    add("-" * 78)
    for a in sorted(plan.assets, key=lambda x: x.current_value, reverse=True):
        drift = a.drift_pp if plan.mode is DriftMode.ABSOLUTE else a.drift_relative
        status = "** BREACH **" if a.breached else "ok"
        add(f"{a.ticker:<8}{currency + format(a.current_value, ',.2f'):>14}"
            f"{a.current_weight:>9.1%}{a.target_weight:>10.1%}{drift:>+10.1%}  {status:<12}")
    add("-" * 78)

    # ---- Verdict ---- #
    add("")
    if plan.needs_rebalance:
        names = ", ".join(a.ticker for a in plan.breached)
        add(f"ALERT: {len(plan.breached)} position(s) beyond threshold -> {names}")
    else:
        add("No position exceeds the drift threshold. No action required.")

    # ---- Trades ---- #
    trades = plan.trades
    if trades:
        add("")
        add("EXECUTION PLAN")
        add("-" * 78)
        add(f"{'Action':<7}{'Ticker':<8}{'Amount':>14}{'Price':>12}{'Shares':>12}")
        add("-" * 78)
        for a in trades:
            price = f"{currency}{a.price:,.2f}" if a.price else "n/a"
            shares = f"{a.shares:+,.4f}" if a.shares is not None else "n/a"
            add(f"{a.action:<7}{a.ticker:<8}"
                f"{currency + format(abs(a.trade_value), ',.2f'):>14}{price:>12}{shares:>12}")
        add("-" * 78)
        add(f"Total buys : {currency}{plan.total_buys:,.2f}")
        add(f"Total sells: {currency}{plan.total_sells:,.2f}")
        add(f"Turnover   : {plan.turnover:.1%} of portfolio")
        if plan.total_sells > 0:
            add("")
            add("NOTE: sells may realize capital gains in a taxable account.")
            add("      In an IRA/401k there is no tax consequence.")
    add("=" * 78)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Execution example
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # Current market values.
    holdings: dict[str, float] = {
        "NVDA":  5306.95,
        "GOOGL": 5182.99,
        "NOW":   3508.52,
        "SNPS":  2950.76,
        "VST":   1329.68,
        "NEE":   1273.74,
    }

    # Desired long-run allocation (must sum to 1.0).
    targets: dict[str, float] = {
        "NVDA":  0.22,
        "GOOGL": 0.22,
        "NOW":   0.15,
        "SNPS":  0.18,
        "VST":   0.11,
        "NEE":   0.12,
    }

    # Optional: last traded prices, to convert dollars into share counts.
    prices: dict[str, float] = {
        "NVDA":  221.52,
        "GOOGL": 363.53,
        "NOW":   116.69,
        "SNPS":  403.46,
        "VST":   141.38,
        "NEE":    85.67,
    }

    print("\n### 1. Full rebalance, 5 percentage-point threshold ###\n")
    plan = build_plan(holdings, targets, threshold=0.05, prices=prices, min_trade=25.0)
    print(format_plan(plan))

    print("\n\n### 2. Cash-flow rebalance: deploy $1,000 without selling ###\n")
    cash_plan = build_plan(
        holdings, targets,
        threshold=0.05,
        new_cash=1000.0,
        allow_sells=False,          # no taxable sales
        prices=prices,
        min_trade=25.0,
    )
    print(format_plan(cash_plan))

    print("\n\n### 3. Relative drift mode — catches small-sleeve drift ###\n")
    rel_plan = build_plan(
        holdings, targets,
        threshold=0.25,             # 25% away from target weight
        mode=DriftMode.RELATIVE,
        prices=prices,
    )
    print(format_plan(rel_plan))
