"""Indicator sanity tests + look-ahead guards.

These don't aim for textbook-exact values (TA-Lib parity is out of scope) —
instead they assert structural properties: shapes, NaN behavior on warm-up,
boundedness, and that no future bar leaks into a past computation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.features import atr, compute_all, macd, rsi, volume_profile


@pytest.fixture
def trending_close() -> pd.Series:
    rng = np.random.default_rng(42)
    walk = rng.normal(loc=0.05, scale=0.5, size=200).cumsum() + 100.0
    idx = pd.date_range("2026-01-01", periods=200, freq="1min")
    return pd.Series(walk, index=idx, name="close")


@pytest.fixture
def ohlcv(trending_close: pd.Series) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    high = trending_close + np.abs(rng.normal(0, 0.3, len(trending_close)))
    low = trending_close - np.abs(rng.normal(0, 0.3, len(trending_close)))
    open_ = trending_close.shift(1).fillna(trending_close.iloc[0])
    volume = rng.integers(100, 10_000, size=len(trending_close))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": trending_close, "volume": volume},
        index=trending_close.index,
    )


# ────────────────────────────── RSI ──────────────────────────────


class TestRSI:
    def test_warmup_window_is_nan(self, trending_close: pd.Series) -> None:
        out = rsi(trending_close, period=14)
        assert out.iloc[:13].isna().all(), "first period-1 bars must be NaN"
        assert not out.iloc[14:].isna().any(), "after warm-up, no NaNs allowed"

    def test_bounded_0_100(self, trending_close: pd.Series) -> None:
        out = rsi(trending_close).dropna()
        assert (out >= 0).all() and (out <= 100).all()

    def test_rejects_invalid_period(self, trending_close: pd.Series) -> None:
        with pytest.raises(ValueError):
            rsi(trending_close, period=0)


# ────────────────────────────── MACD ──────────────────────────────


class TestMACD:
    def test_columns(self, trending_close: pd.Series) -> None:
        out = macd(trending_close)
        assert list(out.columns) == ["macd", "macd_signal", "macd_hist"]

    def test_hist_is_macd_minus_signal(self, trending_close: pd.Series) -> None:
        out = macd(trending_close).dropna()
        diff = (out["macd"] - out["macd_signal"]) - out["macd_hist"]
        assert diff.abs().max() < 1e-9

    def test_rejects_fast_geq_slow(self, trending_close: pd.Series) -> None:
        with pytest.raises(ValueError):
            macd(trending_close, fast=20, slow=10)


# ────────────────────────────── ATR ──────────────────────────────


class TestATR:
    def test_atr_positive(self, ohlcv: pd.DataFrame) -> None:
        out = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"]).dropna()
        assert (out > 0).all()

    def test_warmup_window_is_nan(self, ohlcv: pd.DataFrame) -> None:
        out = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], period=14)
        assert out.iloc[:13].isna().all()


# ────────────────────────────── Volume Profile ──────────────────────────────


class TestVolumeProfile:
    def test_shares_sum_to_one(self, ohlcv: pd.DataFrame) -> None:
        out = volume_profile(ohlcv["close"], ohlcv["volume"], bins=20)
        assert abs(out["volume_share"].sum() - 1.0) < 1e-9

    def test_empty_input_returns_empty_frame(self) -> None:
        empty = pd.Series(dtype=float)
        out = volume_profile(empty, empty)
        assert out.empty
        assert list(out.columns) == ["price_low", "price_high", "volume_share"]

    def test_rejects_too_few_bins(self, ohlcv: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            volume_profile(ohlcv["close"], ohlcv["volume"], bins=1)


# ────────────────────────────── Look-ahead guards ──────────────────────────────


class TestNoLookAhead:
    """Mutating bar N+k for k>0 must not change indicator values at bar N."""

    def test_rsi_no_lookahead(self, trending_close: pd.Series) -> None:
        full = rsi(trending_close).dropna()
        truncated = rsi(trending_close.iloc[:100]).dropna()
        common = truncated.index.intersection(full.index)
        assert (full.loc[common] - truncated.loc[common]).abs().max() < 1e-9

    def test_macd_no_lookahead(self, trending_close: pd.Series) -> None:
        full = macd(trending_close).dropna()
        truncated = macd(trending_close.iloc[:100]).dropna()
        common = truncated.index.intersection(full.index)
        for col in ("macd", "macd_signal", "macd_hist"):
            assert (full.loc[common, col] - truncated.loc[common, col]).abs().max() < 1e-9


# ────────────────────────────── compute_all ──────────────────────────────


class TestComputeAll:
    def test_produces_all_features(self, ohlcv: pd.DataFrame) -> None:
        out = compute_all(ohlcv).dropna()
        assert {"rsi", "macd", "macd_signal", "macd_hist", "atr"}.issubset(out.columns)
        assert not out.isna().any().any(), "after dropna(), no leftover NaNs allowed"
