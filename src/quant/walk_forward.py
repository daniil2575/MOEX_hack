"""Walk-forward backtester.

Strategy-agnostic: takes a `Strategy` callable and a sliced OHLCV+features
frame, simulates a paper-trading account bar-by-bar with a strict
no-look-ahead contract:

    For bar t:
        decision  = strategy.decide(features.iloc[: t + 1], portfolio, t)
        fill, if any, occurs at the OPEN of bar t + 1
        equity at t = cash + sum(position.qty * close[t])

The harness enforces look-ahead invariants:
- Strategy receives `features.iloc[: t + 1]` only (G1).
- Fills happen one bar later than decisions (G4).
- Indices must be sorted ascending (a single check at start).

Output is a `BacktestResult` with the equity curve, per-bar returns,
trade pnls, and the headline metrics (sharpe / sortino / MDD / hit rate /
cumulative return).

This v1 simulator is single-ticker, single-position, long-only, and uses
LIMIT-at-bar-open fills with a flat slippage in bps. Multi-ticker and
short-side support land in v2 (post-hackathon).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

import pandas as pd

from src.quant import metrics
from src.quant.look_ahead import (
    LookAheadError,
    assert_frame_no_future,
)


@dataclass(frozen=True)
class StrategyOrder:
    """Lightweight order emitted by a Strategy. Negative qty for SELL."""

    action: Literal["BUY", "SELL"]
    qty: Decimal


class Strategy(Protocol):
    def decide(
        self,
        features_window: pd.DataFrame,
        cash: Decimal,
        position_qty: Decimal,
        as_of: datetime,
    ) -> StrategyOrder | None: ...


@dataclass
class BacktestResult:
    equity: list[Decimal] = field(default_factory=list)
    timestamps: list[datetime] = field(default_factory=list)
    bar_returns: list[Decimal] = field(default_factory=list)
    trade_pnls: list[Decimal] = field(default_factory=list)
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: Decimal = Decimal("0")
    hit_rate: float = 0.0
    cumulative_return: Decimal = Decimal("0")
    n_trades: int = 0


def run_walk_forward(
    *,
    features: pd.DataFrame,
    strategy: Strategy,
    initial_cash: Decimal = Decimal("1000000"),
    slippage_bps: Decimal = Decimal("5"),
    annualisation: int = 252,
) -> BacktestResult:
    """Replay `features` bar-by-bar through `strategy` and report metrics.

    `features` must be a DataFrame indexed by tz-aware timestamp with at
    least the column `close`; an `open` column is used as fill price for
    the next-bar order, falling back to `close` when absent.
    """
    if features.empty:
        raise ValueError("features frame is empty")
    if not features.index.is_monotonic_increasing:
        raise LookAheadError("features index must be monotonic increasing")
    if "close" not in features.columns:
        raise ValueError("features must contain a 'close' column")

    has_open = "open" in features.columns
    cash = initial_cash
    qty = Decimal("0")
    avg_cost = Decimal("0")
    pending: StrategyOrder | None = None

    result = BacktestResult()
    prev_equity: Decimal | None = None
    slippage_factor = slippage_bps / Decimal("10000")

    for i in range(len(features)):
        ts = features.index[i]
        as_of = ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts
        bar_open = Decimal(str(features["open"].iloc[i])) if has_open else Decimal(
            str(features["close"].iloc[i])
        )
        bar_close = Decimal(str(features["close"].iloc[i]))

        # Fill any pending order at THIS bar's open (placed at i-1).
        if pending is not None:
            fill_price = bar_open * (
                Decimal("1") + slippage_factor
                if pending.action == "BUY"
                else Decimal("1") - slippage_factor
            )
            if pending.action == "BUY":
                cost = fill_price * pending.qty
                if cost <= cash:
                    new_qty = qty + pending.qty
                    if new_qty > 0:
                        avg_cost = (qty * avg_cost + cost) / new_qty
                    qty = new_qty
                    cash -= cost
            else:  # SELL
                sell_qty = min(pending.qty, qty)
                if sell_qty > 0:
                    proceeds = fill_price * sell_qty
                    realised = (fill_price - avg_cost) * sell_qty
                    qty -= sell_qty
                    cash += proceeds
                    result.trade_pnls.append(realised)
                    result.n_trades += 1
            pending = None

        # Strategy sees only past+current bars (G1).
        window = features.iloc[: i + 1]
        assert_frame_no_future(window, as_of, name="walk_forward.window")

        order = strategy.decide(window, cash=cash, position_qty=qty, as_of=as_of)
        if order is not None and order.qty > 0:
            pending = order  # will fill next bar (G4)

        equity = cash + qty * bar_close
        result.equity.append(equity)
        result.timestamps.append(as_of)
        if prev_equity is not None and prev_equity > 0:
            result.bar_returns.append((equity - prev_equity) / prev_equity)
        prev_equity = equity

    result.sharpe = metrics.sharpe_ratio(result.bar_returns, annualisation=annualisation)
    result.sortino = metrics.sortino_ratio(result.bar_returns, annualisation=annualisation)
    result.max_drawdown = metrics.max_drawdown(result.equity)
    result.hit_rate = metrics.hit_rate(result.trade_pnls)
    result.cumulative_return = metrics.cumulative_return(result.equity)
    return result
