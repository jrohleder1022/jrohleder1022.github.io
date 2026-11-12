"""
Concentration and correlation diagnostics — measuring what you cannot see.
==========================================================================

THE PROBLEM THIS SOLVES
-----------------------
A book of three or four names *feels* diversified because it has more than one
name in it. Whether it actually is depends on whether those names lose money
for the same reason, and that is not something intuition is good at. These are
the numbers that answer it.

EFFECTIVE NUMBER OF POSITIONS (inverse Herfindahl)
--------------------------------------------------
    HHI  = sum_i w_i^2
    N_eff = 1 / HHI

Four equal positions give N_eff = 4. Four positions weighted 70/10/10/10 give
N_eff = 2.0 — you own four things and carry the concentration of two. N_eff
counts *weights only*; it says nothing about whether the positions are alike.

EFFECTIVE NUMBER OF BETS (correlation-adjusted)
-----------------------------------------------
    DR    = (sum_i w_i * sigma_i) / sigma_portfolio
    N_bet = DR^2

The diversification ratio compares the weighted-average standalone volatility
to the realized portfolio volatility. If positions were uncorrelated the
portfolio vol would be much lower than the average, DR would be large, and
N_bet would approach the position count. When everything moves together, DR
approaches 1 and N_bet approaches 1 — you own one bet wearing several tickers.

This is the number that matters for a thematic book, and it is almost always
worse than the position count suggests.

FACTOR CONCENTRATION
--------------------
Weight-average absolute factor exposure across the book. A book can look
diversified by ticker, by sector, even by correlation over a quiet sample, and
still have every position loading on the same factor. This catches that
directly rather than inferring it from returns that may not contain a shock.

DATA NOTE
---------
Correlation requires a return history, which this package does not fetch for
you. Supply a DataFrame of daily closes (dates x tickers) from whatever source
you use. Without it, the weight-based metrics still work and the
correlation-based ones are skipped rather than faked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .factors import ExposureSet

TRADING_DAYS = 252


@dataclass
class ConcentrationReport:
    n_positions: int
    hhi: float
    effective_positions: float
    largest_weight: float
    largest_ticker: str
    top_two_share: float

    def verdict(self) -> str:
        ratio = self.effective_positions / self.n_positions if self.n_positions else 0.0
        if ratio > 0.90:
            evenness = "Evenly weighted — weight concentration is not the issue."
        elif ratio > 0.70:
            evenness = "Mild weight concentration; tolerable."
        else:
            evenness = (
                f"Heavy weight concentration: {self.n_positions} positions "
                f"carrying the risk of {self.effective_positions:.1f}."
            )
        if self.n_positions < 4:
            evenness += (
                f" Separately: {self.n_positions} positions is a small absolute "
                "count. Even weighting does not help when a single thesis error "
                "costs a third of the book — and this metric cannot see whether "
                "the positions are alike. Read it with the factor table below."
            )
        return evenness


@dataclass
class CorrelationReport:
    tickers: list[str]
    matrix: pd.DataFrame
    average_pairwise: float
    diversification_ratio: float
    effective_bets: float
    portfolio_vol: float
    window_days: int

    def verdict(self) -> str:
        if self.average_pairwise > 0.75:
            quality = (
                "These are not separate positions in any risk sense. They are "
                "one bet with several tickers on it."
            )
        elif self.average_pairwise > 0.55:
            quality = (
                "Substantially the same bet. Diversification here is nominal, "
                "not economic."
            )
        elif self.average_pairwise > 0.35:
            quality = "Related but not identical. Some genuine spread of risk."
        else:
            quality = "Genuinely distinct risk drivers."
        return (
            f"Average pairwise correlation {self.average_pairwise:.2f} over "
            f"{self.window_days} days. Effective bets: {self.effective_bets:.1f} "
            f"across {len(self.tickers)} positions. {quality}"
        )


@dataclass
class FactorConcentration:
    loadings: dict[str, float]

    def dominant(self) -> tuple[str, float]:
        if not self.loadings:
            return ("none", 0.0)
        return max(self.loadings.items(), key=lambda kv: abs(kv[1]))

    def verdict(self) -> str:
        factor, load = self.dominant()
        if abs(load) > 0.70:
            return (
                f"Dominant factor '{factor}' at {load:+.2f} weighted loading. "
                "A single shock to this factor moves most of the book at once; "
                "position count is not protecting you."
            )
        if abs(load) > 0.45:
            return f"Concentrated in '{factor}' at {load:+.2f}; material but not extreme."
        return f"No single factor dominates; largest is '{factor}' at {load:+.2f}."


def concentration(weights: Mapping[str, float]) -> ConcentrationReport:
    if not weights:
        raise ValueError("no weights supplied")
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    w = np.array([v for _, v in items], dtype=float)
    total = w.sum()
    if not np.isclose(total, 1.0, atol=1e-6):
        w = w / total  # normalize rather than refuse; callers pass sub-books
    hhi = float(np.sum(w**2))
    return ConcentrationReport(
        n_positions=len(items),
        hhi=hhi,
        effective_positions=1.0 / hhi,
        largest_weight=float(w[0]),
        largest_ticker=items[0][0],
        top_two_share=float(w[:2].sum()),
    )


def correlation(
    prices: pd.DataFrame, weights: Mapping[str, float]
) -> CorrelationReport:
    """Correlation diagnostics from a dates x tickers frame of closes."""
    tickers = [t for t in weights if t in prices.columns]
    missing = [t for t in weights if t not in prices.columns]
    if missing:
        raise KeyError(f"no price history for: {missing}")
    if len(tickers) < 2:
        raise ValueError("correlation needs at least two positions with history")

    # fill_method=None is explicit for cross-version pandas: 2.1+ deprecated
    # the old forward-filling default, and silently filling gaps would
    # manufacture zero-return days that bias correlation upward.
    rets = prices[tickers].pct_change(fill_method=None).dropna()
    if len(rets) < 60:
        raise ValueError(
            f"only {len(rets)} return observations; correlation estimated on "
            "less than a quarter of data is noise."
        )

    w = np.array([weights[t] for t in tickers], dtype=float)
    w = w / w.sum()

    corr = rets.corr()
    cov = rets.cov().to_numpy() * TRADING_DAYS
    vols = np.sqrt(np.diag(cov))

    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(port_var))
    weighted_avg_vol = float(w @ vols)
    dr = weighted_avg_vol / port_vol if port_vol > 0 else 1.0

    n = len(tickers)
    upper = corr.to_numpy()[np.triu_indices(n, k=1)]

    return CorrelationReport(
        tickers=tickers,
        matrix=corr,
        average_pairwise=float(np.mean(upper)),
        diversification_ratio=dr,
        effective_bets=dr**2,
        portfolio_vol=port_vol,
        window_days=len(rets),
    )


def factor_concentration(
    exposures: Mapping[str, ExposureSet], weights: Mapping[str, float]
) -> FactorConcentration:
    """Weight-average factor loading across the book."""
    out: dict[str, float] = {}
    total = sum(weights.values()) or 1.0
    for ticker, weight in weights.items():
        profile = exposures.get(ticker)
        if profile is None:
            continue
        for factor, beta in profile.as_map().items():
            out[factor] = out.get(factor, 0.0) + beta * (weight / total)
    return FactorConcentration(dict(sorted(out.items(), key=lambda kv: -abs(kv[1]))))


def rebuild_years(
    portfolio_value: float, drawdown_pct: float, annual_contribution: float
) -> float:
    """Years of contributions required to replace a drawdown of given depth."""
    if annual_contribution <= 0:
        return float("inf")
    return (portfolio_value * drawdown_pct) / annual_contribution


def horizon_grid(
    portfolio_value: float,
    annual_contribution: float,
    depths: tuple[float, ...] = (0.25, 0.40, 0.50, 0.65),
) -> list[tuple[float, float, float]]:
    """(depth, dollars lost, years to rebuild) across a range of drawdowns.

    The point of the grid is that the ladder in §5 is a step function applied to
    a continuous problem. Seeing the whole curve makes it obvious where the
    policy's thresholds actually bite.
    """
    return [
        (d, portfolio_value * d, rebuild_years(portfolio_value, d, annual_contribution))
        for d in depths
    ]
