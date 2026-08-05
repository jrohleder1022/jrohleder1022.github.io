"""
Mean-Variance Efficient Frontier — Markowitz (1952) portfolio optimization.
===========================================================================

THE MATH, IN BRIEF
------------------
Given N assets with annualized expected-return vector `mu` (N,) and annualized
covariance matrix `Sigma` (N,N), a portfolio is a weight vector `w` (N,) with
`w.sum() == 1`.

    Portfolio return      mu_p    = w' mu                        (linear in w)
    Portfolio variance    var_p   = w' Sigma w                   (quadratic in w)
    Portfolio volatility  sigma_p = sqrt(w' Sigma w)
    Sharpe ratio          S       = (mu_p - rf) / sigma_p

The *efficient frontier* is the set of portfolios that minimize `sigma_p` for
each achievable level of `mu_p`. Two points on it get special attention:

  * Minimum-Variance Portfolio (MVP) — the global left-most point of the frontier.
  * Maximum-Sharpe (tangency) Portfolio — the point where a ray from the
    risk-free rate is tangent to the frontier; it maximizes excess return per
    unit of risk.

Because variance is quadratic and the constraints are linear, each optimization
is a well-behaved convex program; SLSQP solves it quickly. We still use
multiple random restarts so that a single bad starting point cannot produce a
silent non-convergence.

ANNUALIZATION
-------------
With T trading days per year, and i.i.d. daily simple returns:
    mu_annual    = mu_daily * T          (means add)
    Sigma_annual = Sigma_daily * T       (variance scales linearly with time)

CAVEAT WORTH READING
--------------------
MPT optimizes on *historical* moments. Sample means are notoriously noisy
estimators of expected return, so max-Sharpe weights are unstable and tend to
concentrate in whatever asset happened to do best in-sample. Treat the output
as a diagnostic of correlation structure, not a trading instruction. The
minimum-variance portfolio depends only on the covariance matrix (estimated far
more reliably than means) and is correspondingly more robust.

USAGE
-----
    python efficient_frontier.py --tickers GOOGL NVDA NOW SNPS VST NEE
    python efficient_frontier.py --tickers AAPL MSFT --years 5 --rf 0.045
    python efficient_frontier.py --allow-shorts --no-plot
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.04
DEFAULT_TICKERS = ["GOOGL", "NVDA", "NOW", "SNPS", "VST", "NEE"]

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("frontier")


class OptimizationError(RuntimeError):
    """Raised when no optimizer restart converges to a feasible solution."""


# --------------------------------------------------------------------------- #
# 1. Data layer — fetch real prices, fall back to a simulated market
# --------------------------------------------------------------------------- #

def fetch_prices(tickers: Sequence[str], years: int = 3) -> pd.DataFrame:
    """Download adjusted daily closes; fall back to simulation on any failure.

    Returns a DataFrame indexed by date with one column per ticker. Any ticker
    that comes back entirely empty is dropped with a warning rather than
    poisoning the covariance matrix with NaNs.
    """
    try:
        import yfinance as yf  # imported lazily so the script runs without it
    except ImportError:
        log.warning("yfinance not installed — using simulated price data.")
        return simulate_prices(tickers, years)

    try:
        raw = yf.download(
            list(tickers),
            period=f"{years}y",
            interval="1d",
            auto_adjust=True,      # splits/dividends folded into the close
            progress=False,
        )
        # yfinance returns a column MultiIndex for multi-ticker requests.
        prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers[0])
        prices = prices.dropna(axis=1, how="all")
        if prices.empty or prices.shape[1] == 0:
            raise ValueError("download returned no usable price columns")
    except Exception as exc:                       # network, rate-limit, schema drift
        log.warning("Price download failed (%s) — using simulated data.", exc)
        return simulate_prices(tickers, years)

    missing = set(tickers) - set(prices.columns)
    if missing:
        log.warning("No data for %s — excluded.", ", ".join(sorted(missing)))
    log.info("Fetched %d rows x %d tickers from yfinance.", *prices.shape)
    return prices.dropna()


def simulate_prices(
    tickers: Sequence[str],
    years: int = 3,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate correlated geometric-Brownian-motion paths for offline testing.

    Uses a one-factor structure so the assets are *realistically* correlated:

        r_i = beta_i * r_market + eps_i

    which yields a positive-definite covariance matrix with the kind of
    pairwise correlations (0.3-0.7) you actually see in equities — unlike
    independent draws, which would make diversification look far too effective.
    """
    rng = np.random.default_rng(seed)
    n_days = int(years * TRADING_DAYS_PER_YEAR)
    n_assets = len(tickers)

    # Market factor: ~8% annual drift, ~18% annual vol.
    market = rng.normal(
        0.08 / TRADING_DAYS_PER_YEAR,
        0.18 / np.sqrt(TRADING_DAYS_PER_YEAR),
        size=n_days,
    )
    betas = rng.uniform(0.6, 1.6, size=n_assets)
    idio_vol = rng.uniform(0.15, 0.40, size=n_assets) / np.sqrt(TRADING_DAYS_PER_YEAR)
    alpha = rng.uniform(-0.04, 0.12, size=n_assets) / TRADING_DAYS_PER_YEAR

    shocks = rng.normal(0.0, 1.0, size=(n_days, n_assets)) * idio_vol
    daily_returns = alpha + np.outer(market, betas) + shocks

    prices = 100.0 * np.exp(np.cumsum(daily_returns, axis=0))
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)
    log.info("Simulated %d days x %d assets (one-factor model, seed=%d).",
             n_days, n_assets, seed)
    return pd.DataFrame(prices, index=index, columns=list(tickers))


# --------------------------------------------------------------------------- #
# 2. Statistics layer — annualized moments
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MarketData:
    """Annualized inputs to the optimizer."""
    tickers: list[str]
    mu: np.ndarray          # (N,)  annualized expected returns
    cov: np.ndarray         # (N,N) annualized covariance matrix
    returns: pd.DataFrame   # daily simple returns, kept for diagnostics

    @property
    def n_assets(self) -> int:
        return len(self.tickers)

    @property
    def vols(self) -> np.ndarray:
        """Annualized standalone volatility of each asset."""
        return np.sqrt(np.diag(self.cov))

    @property
    def correlation(self) -> pd.DataFrame:
        d = np.outer(self.vols, self.vols)
        return pd.DataFrame(self.cov / d, index=self.tickers, columns=self.tickers)


def compute_statistics(prices: pd.DataFrame) -> MarketData:
    """Convert a price panel into annualized (mu, Sigma).

    Simple (not log) returns are used because portfolio return is the weighted
    *arithmetic* mean of asset returns — log returns are not additive across
    assets, only across time.
    """
    if prices.shape[1] < 2:
        raise ValueError("Need at least 2 assets to build a frontier.")

    returns = prices.pct_change().dropna(how="any")
    if len(returns) < 30:
        raise ValueError(f"Only {len(returns)} return observations — too few.")

    mu = returns.mean().to_numpy() * TRADING_DAYS_PER_YEAR
    cov = returns.cov().to_numpy() * TRADING_DAYS_PER_YEAR

    # Guard against a singular covariance matrix (duplicate/collinear tickers).
    if np.linalg.matrix_rank(cov) < cov.shape[0]:
        log.warning("Covariance matrix is rank-deficient; applying shrinkage.")
        cov = cov + np.eye(cov.shape[0]) * 1e-8

    return MarketData(
        tickers=list(prices.columns),
        mu=mu,
        cov=cov,
        returns=returns,
    )


# --------------------------------------------------------------------------- #
# 3. Portfolio math
# --------------------------------------------------------------------------- #

def portfolio_return(weights: np.ndarray, mu: np.ndarray) -> float:
    """mu_p = w' mu"""
    return float(weights @ mu)


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """sigma_p = sqrt(w' Sigma w); clipped at 0 to absorb tiny negative roundoff."""
    variance = float(weights @ cov @ weights)
    return float(np.sqrt(max(variance, 0.0)))


def sharpe_ratio(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """S = (mu_p - rf) / sigma_p. Returns -inf for a degenerate zero-vol portfolio."""
    vol = portfolio_volatility(weights, cov)
    if vol < 1e-12:
        return float("-inf")
    return (portfolio_return(weights, mu) - risk_free_rate) / vol


# --------------------------------------------------------------------------- #
# 4. Optimization engine
# --------------------------------------------------------------------------- #

def _solve(
    objective: Callable[[np.ndarray], float],
    n_assets: int,
    bounds: tuple[tuple[float, float], ...],
    constraints: list[dict],
    n_restarts: int = 12,
    seed: int = 0,
) -> np.ndarray:
    """Minimize `objective` over the weight simplex with multi-start SLSQP.

    Convex problems should converge from any start, but real covariance
    matrices can be near-singular. Trying several starting points and keeping
    the best *successful* result makes the routine robust; if every restart
    fails we raise rather than silently returning garbage weights.
    """
    rng = np.random.default_rng(seed)
    starts = [np.repeat(1.0 / n_assets, n_assets)]
    starts += [rng.dirichlet(np.ones(n_assets)) for _ in range(n_restarts - 1)]

    best_x, best_f, failures = None, np.inf, 0
    for x0 in starts:
        try:
            res = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 1000, "ftol": 1e-12},
            )
        except Exception as exc:                    # pragma: no cover - defensive
            failures += 1
            log.debug("Restart raised %s", exc)
            continue
        if res.success and np.isfinite(res.fun) and res.fun < best_f:
            best_x, best_f = res.x, res.fun
        elif not res.success:
            failures += 1

    if best_x is None:
        raise OptimizationError(
            f"All {n_restarts} restarts failed to converge "
            f"({failures} explicit failures). Check for NaNs or collinear assets."
        )
    if failures:
        log.debug("%d/%d restarts failed; using best successful solution.",
                  failures, n_restarts)

    # Renormalize to kill floating-point drift off the sum-to-one constraint.
    return np.asarray(best_x) / np.sum(best_x)


def _bounds_and_budget(n_assets: int, allow_shorts: bool):
    """Weight bounds plus the fully-invested constraint sum(w) = 1."""
    bounds = tuple((-1.0, 1.0) if allow_shorts else (0.0, 1.0) for _ in range(n_assets))
    budget = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    return bounds, budget


def max_sharpe_portfolio(
    data: MarketData,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    allow_shorts: bool = False,
) -> np.ndarray:
    """Tangency portfolio: maximize (mu_p - rf)/sigma_p.

    Implemented as minimization of the negative Sharpe ratio, since
    scipy.optimize only minimizes.
    """
    bounds, constraints = _bounds_and_budget(data.n_assets, allow_shorts)
    neg_sharpe = lambda w: -sharpe_ratio(w, data.mu, data.cov, risk_free_rate)
    return _solve(neg_sharpe, data.n_assets, bounds, constraints)


def min_variance_portfolio(
    data: MarketData,
    allow_shorts: bool = False,
) -> np.ndarray:
    """Global minimum-variance portfolio: minimize w' Sigma w.

    Note this depends only on the covariance matrix — no expected-return
    estimates — which is why it is the most statistically reliable point on
    the frontier.
    """
    bounds, constraints = _bounds_and_budget(data.n_assets, allow_shorts)
    variance = lambda w: float(w @ data.cov @ w)
    return _solve(variance, data.n_assets, bounds, constraints)


def efficient_frontier(
    data: MarketData,
    n_points: int = 60,
    allow_shorts: bool = False,
) -> pd.DataFrame:
    """Trace the frontier by minimizing volatility subject to a target return.

    For each target mu*, solve:
        min  w' Sigma w
        s.t. w' mu = mu*,  sum(w) = 1,  bounds

    Targets span from the MVP's return (the frontier's left tip — nothing
    efficient exists below it) to the highest single-asset return.
    """
    bounds, budget = _bounds_and_budget(data.n_assets, allow_shorts)

    mvp_weights = min_variance_portfolio(data, allow_shorts)
    lo = portfolio_return(mvp_weights, data.mu)
    hi = float(np.max(data.mu))
    if hi <= lo:                     # degenerate: all assets have equal means
        hi = lo + 1e-4
    targets = np.linspace(lo, hi, n_points)

    rows = []
    for target in targets:
        constraints = budget + [
            {"type": "eq", "fun": lambda w, t=target: portfolio_return(w, data.mu) - t}
        ]
        try:
            w = _solve(
                lambda w: float(w @ data.cov @ w),
                data.n_assets,
                bounds,
                constraints,
                n_restarts=6,        # fewer restarts: this runs n_points times
            )
        except OptimizationError:
            log.debug("No feasible portfolio at target return %.4f — skipped.", target)
            continue
        rows.append({
            "target_return": target,
            "return": portfolio_return(w, data.mu),
            "volatility": portfolio_volatility(w, data.cov),
            "weights": w,
        })

    if not rows:
        raise OptimizationError("Frontier is empty — every target return was infeasible.")
    log.info("Traced %d/%d efficient frontier points.", len(rows), n_points)
    return pd.DataFrame(rows)


def random_portfolios(data: MarketData, n: int = 4000, seed: int = 7) -> pd.DataFrame:
    """Monte-Carlo cloud of feasible long-only portfolios, for plot context."""
    rng = np.random.default_rng(seed)
    weights = rng.dirichlet(np.ones(data.n_assets), size=n)
    rets = weights @ data.mu
    vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, data.cov, weights))
    return pd.DataFrame({"return": rets, "volatility": vols})


# --------------------------------------------------------------------------- #
# 5. Reporting & plotting
# --------------------------------------------------------------------------- #

def describe_portfolio(
    name: str,
    weights: np.ndarray,
    data: MarketData,
    risk_free_rate: float,
) -> pd.Series:
    """One-line summary plus the weight vector, as a tidy Series."""
    summary = {
        "Return": portfolio_return(weights, data.mu),
        "Volatility": portfolio_volatility(weights, data.cov),
        "Sharpe": sharpe_ratio(weights, data.mu, data.cov, risk_free_rate),
    }
    summary.update({t: w for t, w in zip(data.tickers, weights)})
    return pd.Series(summary, name=name)


def plot_frontier(
    data: MarketData,
    frontier: pd.DataFrame,
    max_sharpe_w: np.ndarray,
    min_var_w: np.ndarray,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    outfile: str | None = "efficient_frontier.png",
    show: bool = False,
):
    """Plot the frontier, the random-portfolio cloud, and both key portfolios."""
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg")          # headless-safe
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not installed — skipping plot.")
        return None

    cloud = random_portfolios(data)
    ms_ret = portfolio_return(max_sharpe_w, data.mu)
    ms_vol = portfolio_volatility(max_sharpe_w, data.cov)
    mv_ret = portfolio_return(min_var_w, data.mu)
    mv_vol = portfolio_volatility(min_var_w, data.cov)

    fig, ax = plt.subplots(figsize=(11, 7))

    # Feasible set: random long-only portfolios, shaded by Sharpe.
    sharpes = (cloud["return"] - risk_free_rate) / cloud["volatility"]
    sc = ax.scatter(cloud["volatility"], cloud["return"], c=sharpes,
                    cmap="viridis", s=6, alpha=0.35, label="Random portfolios")
    fig.colorbar(sc, ax=ax, label="Sharpe ratio")

    # The frontier itself.
    ax.plot(frontier["volatility"], frontier["return"],
            color="#1f3864", lw=2.5, label="Efficient frontier", zorder=3)

    # Capital Allocation Line: rf -> tangency portfolio, extended.
    if ms_vol > 0:
        x_max = float(max(cloud["volatility"].max(), frontier["volatility"].max()))
        cal_x = np.linspace(0, x_max, 50)
        cal_y = risk_free_rate + (ms_ret - risk_free_rate) / ms_vol * cal_x
        ax.plot(cal_x, cal_y, "--", color="#888888", lw=1.2,
                label="Capital Allocation Line", zorder=2)

    # The two headline portfolios.
    ax.scatter([ms_vol], [ms_ret], marker="*", s=420, color="#c00000",
               edgecolor="white", linewidth=1.2, zorder=5,
               label=f"Max Sharpe ({sharpe_ratio(max_sharpe_w, data.mu, data.cov, risk_free_rate):.2f})")
    ax.scatter([mv_vol], [mv_ret], marker="D", s=150, color="#2e7d32",
               edgecolor="white", linewidth=1.2, zorder=5,
               label=f"Min Variance ({mv_vol:.1%} vol)")

    # Individual assets for reference.
    ax.scatter(data.vols, data.mu, marker="o", s=70, facecolor="none",
               edgecolor="#333333", linewidth=1.4, zorder=4, label="Individual assets")
    for ticker, vol, ret in zip(data.tickers, data.vols, data.mu):
        ax.annotate(ticker, (vol, ret), xytext=(6, 4), textcoords="offset points",
                    fontsize=9, color="#333333")

    ax.set_xlabel("Annualized volatility (σ)")
    ax.set_ylabel("Annualized expected return (μ)")
    ax.set_title("Mean-Variance Efficient Frontier")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax.grid(alpha=0.25, linestyle=":")
    ax.legend(loc="upper left", framealpha=0.9)
    fig.tight_layout()

    if outfile:
        fig.savefig(outfile, dpi=150)
        log.info("Saved plot to %s", outfile)
    if show:
        plt.show()
    return fig


# --------------------------------------------------------------------------- #
# 6. Entry point
# --------------------------------------------------------------------------- #

def run(
    tickers: Sequence[str],
    years: int = 3,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    allow_shorts: bool = False,
    make_plot: bool = True,
    outfile: str = "efficient_frontier.png",
) -> dict:
    """Full pipeline: fetch -> estimate -> optimize -> report -> plot."""
    prices = fetch_prices(tickers, years)
    data = compute_statistics(prices)

    max_sharpe_w = max_sharpe_portfolio(data, risk_free_rate, allow_shorts)
    min_var_w = min_variance_portfolio(data, allow_shorts)
    frontier = efficient_frontier(data, allow_shorts=allow_shorts)

    report = pd.DataFrame([
        describe_portfolio("Max Sharpe", max_sharpe_w, data, risk_free_rate),
        describe_portfolio("Min Variance", min_var_w, data, risk_free_rate),
        describe_portfolio("Equal Weight",
                           np.repeat(1 / data.n_assets, data.n_assets),
                           data, risk_free_rate),
    ])

    pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
    print("\n=== Annualized asset statistics ===")
    print(pd.DataFrame({"Return": data.mu, "Volatility": data.vols},
                       index=data.tickers).to_string())
    print("\n=== Correlation matrix ===")
    print(data.correlation.round(2).to_string())
    print("\n=== Optimal portfolios (weights as decimals) ===")
    print(report.to_string())

    fig = None
    if make_plot:
        fig = plot_frontier(data, frontier, max_sharpe_w, min_var_w,
                            risk_free_rate, outfile=outfile)

    return {
        "data": data,
        "frontier": frontier,
        "max_sharpe_weights": max_sharpe_w,
        "min_variance_weights": min_var_w,
        "report": report,
        "figure": fig,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compute the mean-variance efficient frontier for a set of tickers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS,
                   help="Ticker symbols to include.")
    p.add_argument("--years", type=int, default=3, help="Years of daily history.")
    p.add_argument("--rf", type=float, default=DEFAULT_RISK_FREE_RATE,
                   help="Annual risk-free rate (decimal).")
    p.add_argument("--allow-shorts", action="store_true",
                   help="Permit negative weights down to -100%% per asset.")
    p.add_argument("--no-plot", action="store_true", help="Skip chart generation.")
    p.add_argument("--outfile", default="efficient_frontier.png",
                   help="Path for the saved chart.")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(
            tickers=args.tickers,
            years=args.years,
            risk_free_rate=args.rf,
            allow_shorts=args.allow_shorts,
            make_plot=not args.no_plot,
            outfile=args.outfile,
        )
    except (ValueError, OptimizationError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
