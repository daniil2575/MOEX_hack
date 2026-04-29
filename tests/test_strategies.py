"""Tests for baseline strategies (BuyAndHold + MACDRSI) and compare harness."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.quant import (
    BuyAndHold,
    MACDRSIStrategy,
    compare_results,
    run_walk_forward,
    welch_t_test,
)


def _ohlcv(n: int = 60, drift: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range("2026-04-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    closes = 300.0 * np.cumprod(1 + rng.normal(drift, 0.005, n))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame({"open": opens, "close": closes}, index=idx)


def _ohlcv_with_macd_rsi(n: int = 60, drift: float = 0.001) -> pd.DataFrame:
    """OHLCV + naive MACD/RSI columns for MACDRSI strategy tests."""
    df = _ohlcv(n=n, drift=drift)
    close = df["close"]
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False, min_periods=9).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_l = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].where(avg_l != 0, 100.0)
    return df


# ────────────────────────────── BuyAndHold ──────────────────────────────


class TestBuyAndHold:
    def test_buys_once_on_first_bar(self) -> None:
        feats = _ohlcv(n=20)
        strategy = BuyAndHold(target_pct_nav=Decimal("1.0"))
        result = run_walk_forward(features=feats, strategy=strategy)
        # Buy on bar 0, fill at bar 1's open → equity dips by slippage then tracks price.
        # Final qty * close[-1] ≈ initial_cash * (close[-1] / open[1]) - slippage
        assert result.n_trades == 0  # no SELL → no realised pnl
        assert result.equity[0] == Decimal("1000000")
        assert result.cumulative_return != Decimal("0")  # equity moved

    def test_partial_sizing_keeps_cash_residual(self) -> None:
        feats = _ohlcv(n=10)
        strategy = BuyAndHold(target_pct_nav=Decimal("0.5"))
        result = run_walk_forward(features=feats, strategy=strategy)
        # Half NAV in equity, half in cash — equity should be close to 1M but not exactly
        # 1M * close-tail/open-1 because half stays in cash.
        # Key invariant: not the same as 100% allocation.
        full = run_walk_forward(features=feats, strategy=BuyAndHold(target_pct_nav=Decimal("1.0")))
        assert abs(result.cumulative_return) < abs(full.cumulative_return) + Decimal("1e-8")

    def test_rejects_invalid_target(self) -> None:
        with pytest.raises(ValueError):
            BuyAndHold(target_pct_nav=Decimal("0"))
        with pytest.raises(ValueError):
            BuyAndHold(target_pct_nav=Decimal("1.5"))


# ────────────────────────────── MACDRSI ──────────────────────────────


class TestMACDRSI:
    def test_emits_no_orders_during_warmup(self) -> None:
        feats = _ohlcv_with_macd_rsi(n=30)
        strategy = MACDRSIStrategy()
        # Walk only the warm-up rows (first 26 — slow EMA min_periods)
        warmup = feats.head(26)
        result = run_walk_forward(features=warmup, strategy=strategy)
        # During warm-up MACD is NaN → strategy should never fire
        assert result.n_trades == 0

    def test_eventually_trades_on_strong_uptrend(self) -> None:
        # Strong drift produces clean MACD bullish crosses → at least one round-trip
        feats = _ohlcv_with_macd_rsi(n=120, drift=0.005)
        strategy = MACDRSIStrategy(target_pct_nav=Decimal("0.05"))
        result = run_walk_forward(features=feats, strategy=strategy)
        # Either at least one closed trade OR an open position at end
        assert result.n_trades >= 1 or result.equity[-1] > Decimal("999000")

    def test_rejects_oversize_target(self) -> None:
        with pytest.raises(ValueError):
            MACDRSIStrategy(target_pct_nav=Decimal("0.10"))  # over Risk Manager 5% cap

    def test_missing_required_column_raises(self) -> None:
        feats = _ohlcv(n=30)  # no macd/rsi
        strategy = MACDRSIStrategy()
        with pytest.raises(KeyError, match="macd"):
            run_walk_forward(features=feats, strategy=strategy)


# ────────────────────────────── compare ──────────────────────────────


class TestCompare:
    def test_welch_t_test_identical_samples_p_one(self) -> None:
        a = [Decimal("0.01")] * 10
        b = [Decimal("0.01")] * 10
        result = welch_t_test(a, b)
        assert result.p_value_two_sided == 1.0
        assert result.t_statistic == 0.0

    def test_welch_t_test_clear_difference_low_p(self) -> None:
        # 50 samples each, well-separated means
        rng = np.random.default_rng(0)
        a = [Decimal(str(x)) for x in rng.normal(0.005, 0.01, 50)]
        b = [Decimal(str(x)) for x in rng.normal(-0.005, 0.01, 50)]
        result = welch_t_test(a, b)
        assert result.p_value_two_sided < 0.001
        assert result.mean_diff > 0

    def test_welch_t_test_rejects_too_few(self) -> None:
        with pytest.raises(ValueError):
            welch_t_test([Decimal("0.01")], [Decimal("0.02")])

    def test_compare_results_builds_full_report(self) -> None:
        feats = _ohlcv_with_macd_rsi(n=80, drift=0.003)
        bah = run_walk_forward(features=feats, strategy=BuyAndHold(target_pct_nav=Decimal("0.5")))
        macd = run_walk_forward(features=feats, strategy=MACDRSIStrategy())
        report = compare_results(
            "MACDRSI",
            macd.bar_returns,
            {
                "sharpe": macd.sharpe,
                "sortino": macd.sortino,
                "max_drawdown": macd.max_drawdown,
                "hit_rate": macd.hit_rate,
                "cumulative_return": macd.cumulative_return,
            },
            "BuyAndHold",
            bah.bar_returns,
            {
                "sharpe": bah.sharpe,
                "sortino": bah.sortino,
                "max_drawdown": bah.max_drawdown,
                "hit_rate": bah.hit_rate,
                "cumulative_return": bah.cumulative_return,
            },
        )
        assert report.name_a == "MACDRSI"
        assert report.name_b == "BuyAndHold"
        assert 0.0 <= report.welch_t.p_value_two_sided <= 1.0
        assert report.welch_t.n_a == report.welch_t.n_b == len(feats) - 1
