"""Risk-adjusted performance metrics on an equity curve.

All functions take a sequence of *period* returns (not absolute equity)
and an annualisation factor (252 for daily, 252*8*60 for 1-minute, etc.).
Returns are fractions: 0.01 = 1 percent.

Conventions:
- `sharpe_ratio` divides by population std (ddof=0) — matches numpy default,
  and we never have <2 returns in practice.
- `sortino_ratio` uses downside deviation: only negative-return std.
- `max_drawdown` returns a *positive* fraction (e.g. 0.12 means -12% peak-to-trough).
- `hit_rate` requires a sequence of trade pnls (sign matters), not bar returns.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal


def sharpe_ratio(
    returns: Sequence[Decimal],
    *,
    annualisation: int = 252,
    risk_free_rate: Decimal = Decimal("0"),
) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [float(r - risk_free_rate / annualisation) for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((x - mean) ** 2 for x in excess) / len(excess)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(annualisation)


def sortino_ratio(
    returns: Sequence[Decimal],
    *,
    annualisation: int = 252,
    risk_free_rate: Decimal = Decimal("0"),
) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [float(r - risk_free_rate / annualisation) for r in returns]
    mean = sum(excess) / len(excess)
    downside = [x for x in excess if x < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    var = sum(x * x for x in downside) / len(excess)
    dd_std = math.sqrt(var)
    if dd_std == 0:
        return 0.0
    return (mean / dd_std) * math.sqrt(annualisation)


def max_drawdown(equity: Sequence[Decimal]) -> Decimal:
    """Maximum peak-to-trough drawdown as a positive fraction of peak NAV."""
    if not equity:
        return Decimal("0")
    peak = equity[0]
    worst = Decimal("0")
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst


def hit_rate(trade_pnls: Sequence[Decimal]) -> float:
    """Fraction of trades with strictly positive pnl. Empty input → 0.0."""
    if not trade_pnls:
        return 0.0
    wins = sum(1 for p in trade_pnls if p > 0)
    return wins / len(trade_pnls)


def cumulative_return(equity: Sequence[Decimal]) -> Decimal:
    """Total return as a fraction: (last - first) / first."""
    if len(equity) < 2 or equity[0] == 0:
        return Decimal("0")
    return (equity[-1] - equity[0]) / equity[0]
