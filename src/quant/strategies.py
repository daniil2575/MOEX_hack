"""Baseline strategies for the walk-forward harness.

Two strategies, both implementing the `Strategy` Protocol:

- `BuyAndHold`           — buys once on the first bar with `target_pct_nav`,
                            holds forever. Acts as the IMOEX benchmark when
                            run on IMOEX OHLCV.
- `MACDRSIStrategy`      — entry on MACD bullish cross + RSI < `rsi_buy_max`;
                            exit (full SELL) on MACD bearish cross or
                            RSI > `rsi_sell_min`. Long-only.

Sizing: a fixed fraction of starting cash per entry, capped at the position-
size guideline (5% NAV — matches Risk Manager). The harness will pass this
through to fills at next-bar OPEN, so look-ahead is not an issue here.

Both strategies are deterministic and fully testable with synthetic OHLCV.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd

from src.quant.walk_forward import StrategyOrder

DEFAULT_INITIAL_CASH = Decimal("1000000")


class BuyAndHold:
    """Spend `target_pct_nav` of starting cash on bar 0; hold forever.

    This is the IMOEX benchmark when fed with IMOEX index OHLCV.
    """

    def __init__(
        self,
        *,
        target_pct_nav: Decimal = Decimal("1.0"),
        initial_cash: Decimal = DEFAULT_INITIAL_CASH,
        slippage_buffer_bps: Decimal = Decimal("20"),
    ) -> None:
        if not (Decimal("0") < target_pct_nav <= Decimal("1")):
            raise ValueError("target_pct_nav must be in (0, 1]")
        self._target = target_pct_nav
        self._initial_cash = initial_cash
        # Trim qty by the buffer so fill-time slippage doesn't push cost > cash.
        # Default 20 bps comfortably covers walk_forward's default 5 bps slippage.
        self._buffer = slippage_buffer_bps / Decimal("10000")
        self._fired = False

    def decide(
        self,
        features_window: pd.DataFrame,
        cash: Decimal,
        position_qty: Decimal,
        as_of: datetime,
    ) -> StrategyOrder | None:
        if self._fired:
            return None
        last_close = Decimal(str(features_window["close"].iloc[-1]))
        if last_close <= 0:
            return None
        notional = self._initial_cash * self._target * (Decimal("1") - self._buffer)
        qty = (notional / last_close).quantize(Decimal("0.00000001"))
        if qty <= 0:
            return None
        self._fired = True
        return StrategyOrder(action="BUY", qty=qty)


class MACDRSIStrategy:
    """Entry: MACD line crosses above signal line AND RSI < `rsi_buy_max`.
    Exit:  MACD line crosses below signal line OR RSI > `rsi_sell_min`.

    Single position at a time, long-only. Required columns in features:
    `close`, `macd`, `macd_signal`, `rsi`. Bars where any required value
    is NaN (warm-up window) emit no order.
    """

    REQUIRED_COLUMNS = ("close", "macd", "macd_signal", "rsi")

    def __init__(
        self,
        *,
        target_pct_nav: Decimal = Decimal("0.05"),
        rsi_buy_max: Decimal = Decimal("70"),
        rsi_sell_min: Decimal = Decimal("75"),
        initial_cash: Decimal = DEFAULT_INITIAL_CASH,
    ) -> None:
        if not (Decimal("0") < target_pct_nav <= Decimal("0.05")):
            raise ValueError("target_pct_nav must be in (0, 0.05] (Risk Manager cap)")
        if rsi_buy_max <= 0 or rsi_sell_min <= 0:
            raise ValueError("rsi thresholds must be positive")
        self._target = target_pct_nav
        self._rsi_buy_max = rsi_buy_max
        self._rsi_sell_min = rsi_sell_min
        self._initial_cash = initial_cash

    def decide(
        self,
        features_window: pd.DataFrame,
        cash: Decimal,
        position_qty: Decimal,
        as_of: datetime,
    ) -> StrategyOrder | None:
        if len(features_window) < 2:
            return None
        for col in self.REQUIRED_COLUMNS:
            if col not in features_window.columns:
                raise KeyError(f"MACDRSIStrategy requires column {col!r}")

        last = features_window.iloc[-1]
        prev = features_window.iloc[-2]
        # Skip if any input is NaN (warm-up of MACD/RSI).
        if any(pd.isna(last[c]) or pd.isna(prev[c]) for c in ("macd", "macd_signal", "rsi")):
            return None

        macd_curr = float(last["macd"])
        sig_curr = float(last["macd_signal"])
        macd_prev = float(prev["macd"])
        sig_prev = float(prev["macd_signal"])
        rsi_curr = Decimal(str(last["rsi"]))
        last_close = Decimal(str(last["close"]))
        if last_close <= 0:
            return None

        crossed_up = (macd_prev <= sig_prev) and (macd_curr > sig_curr)
        crossed_down = (macd_prev >= sig_prev) and (macd_curr < sig_curr)

        if position_qty == 0 and crossed_up and rsi_curr < self._rsi_buy_max:
            notional = self._initial_cash * self._target
            qty = (notional / last_close).quantize(Decimal("0.00000001"))
            if qty > 0:
                return StrategyOrder(action="BUY", qty=qty)
            return None

        if position_qty > 0 and (crossed_down or rsi_curr > self._rsi_sell_min):
            return StrategyOrder(action="SELL", qty=position_qty)

        return None
