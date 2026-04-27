"""Feature engineering — pure-pandas implementations of the v1 indicator set.

Indicators (all on close-on-bar, no look-ahead):
    - rsi(close, period=14)
    - macd(close, fast=12, slow=26, signal=9) → (macd, signal, hist)
    - atr(high, low, close, period=14)
    - volume_profile(close, volume, bins=20) → DataFrame[price_bin, volume_share]

Convention: input frames must have float dtype on OHLCV columns. Use
`src.data.iss.to_float_frame()` to convert from the Decimal-typed ISS frame.

Look-ahead guard: every indicator uses only past values up to (and including)
the current bar — `min_periods=period` ensures we don't emit values seeded
from a partial window. Callers should `dropna()` before passing to agents.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI on a close-price series."""
    if period < 1:
        raise ValueError("period must be >= 1")

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out.rename("rsi")


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD line, signal line, histogram. All EMAs (Wilder-equivalent on `adjust=False`)."""
    if not (fast < slow):
        raise ValueError("fast must be < slow")
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": hist})


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range — Wilder's smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().rename("atr")


def volume_profile(
    close: pd.Series,
    volume: pd.Series,
    bins: int = 20,
) -> pd.DataFrame:
    """Volume distribution across `bins` equal-width price bands.

    Returns a DataFrame with `price_low`, `price_high`, `volume_share` (sum == 1.0
    if total volume > 0; empty rows have share = 0). This is a simplified VP —
    no value-area or POC marking; agents that need POC compute it from this.
    """
    if bins < 2:
        raise ValueError("bins must be >= 2")
    if close.empty:
        return pd.DataFrame(columns=["price_low", "price_high", "volume_share"])

    edges = np.linspace(close.min(), close.max(), bins + 1)
    cuts = pd.cut(close, bins=edges, include_lowest=True)
    grouped = volume.groupby(cuts, observed=False).sum()

    total = float(volume.sum()) or 1.0
    intervals = list(grouped.index)
    shares = np.asarray(grouped.values, dtype=float) / total
    out = pd.DataFrame(
        {
            "price_low": [iv.left for iv in intervals],
            "price_high": [iv.right for iv in intervals],
            "volume_share": shares,
        }
    )
    return out


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Apply RSI/MACD/ATR to an OHLCV float frame and return the joined frame.

    Volume profile is *not* a per-bar feature — call `volume_profile()`
    separately when you need a snapshot for the agent context.
    """
    out = df.copy()
    out["rsi"] = rsi(df["close"])
    out = out.join(macd(df["close"]))
    out["atr"] = atr(df["high"], df["low"], df["close"])
    return out
