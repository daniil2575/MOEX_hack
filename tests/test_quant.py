"""Quant module tests: metrics, look-ahead guards, stress, walk-forward."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.contracts import Portfolio, Position
from src.news.contracts import NewsItem
from src.quant import (
    SCENARIOS,
    BacktestResult,
    StrategyOrder,
    StressScenario,
    look_ahead,
    metrics,
    run_walk_forward,
    stress_test_portfolio,
)

# ────────────────────────────── metrics ──────────────────────────────


class TestMetrics:
    def test_sharpe_zero_variance_is_zero(self) -> None:
        assert metrics.sharpe_ratio([Decimal("0.001")] * 50) == 0.0

    def test_sharpe_positive_when_returns_positive(self) -> None:
        returns = [Decimal("0.01"), Decimal("0.005"), Decimal("0.012"), Decimal("0.003")]
        assert metrics.sharpe_ratio(returns) > 0

    def test_sortino_handles_no_downside(self) -> None:
        returns = [Decimal("0.01"), Decimal("0.02"), Decimal("0.005")]
        assert metrics.sortino_ratio(returns) == float("inf")

    def test_max_drawdown_is_positive_fraction(self) -> None:
        # equity goes 100 -> 120 -> 90 -> 110: peak 120, trough 90, MDD = 0.25
        equity = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")]
        assert metrics.max_drawdown(equity) == Decimal("0.25")

    def test_max_drawdown_zero_for_monotone_increasing(self) -> None:
        assert metrics.max_drawdown([Decimal("100"), Decimal("110"), Decimal("120")]) == Decimal("0")

    def test_hit_rate_counts_strict_positives(self) -> None:
        pnls = [Decimal("1"), Decimal("-1"), Decimal("0"), Decimal("2")]
        assert metrics.hit_rate(pnls) == pytest.approx(0.5)

    def test_cumulative_return_first_to_last(self) -> None:
        equity = [Decimal("100"), Decimal("90"), Decimal("105")]
        assert metrics.cumulative_return(equity) == Decimal("0.05")


# ────────────────────────────── look-ahead guards ──────────────────────────────


class TestLookAhead:
    def _frame(self) -> pd.DataFrame:
        idx = pd.date_range("2026-04-01", periods=10, freq="1h", tz="UTC")
        return pd.DataFrame({"close": np.arange(10, dtype=float)}, index=idx)

    def test_g1_passes_when_frame_within_horizon(self) -> None:
        f = self._frame()
        as_of = datetime(2026, 4, 1, 9, tzinfo=UTC)
        look_ahead.assert_frame_no_future(f, as_of, name="x")

    def test_g1_raises_on_future_bar(self) -> None:
        f = self._frame()
        as_of = datetime(2026, 4, 1, 0, tzinfo=UTC)
        with pytest.raises(look_ahead.LookAheadError):
            look_ahead.assert_frame_no_future(f, as_of, name="x")

    def test_g2_disjoint_windows_ok(self) -> None:
        look_ahead.assert_disjoint_windows(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 3, 31, tzinfo=UTC),
            datetime(2026, 4, 1, tzinfo=UTC),
            datetime(2026, 6, 30, tzinfo=UTC),
        )

    def test_g2_overlapping_windows_raise(self) -> None:
        with pytest.raises(look_ahead.LookAheadError):
            look_ahead.assert_disjoint_windows(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 4, 5, tzinfo=UTC),
                datetime(2026, 4, 1, tzinfo=UTC),
                datetime(2026, 6, 30, tzinfo=UTC),
            )

    def test_g3_warmup_nan_check(self) -> None:
        s = pd.Series([float("nan")] * 13 + [1.0] * 5)  # period 14 → first 13 NaN
        look_ahead.assert_indicator_warmup_nan(s, period=14, name="rsi")

    def test_g3_raises_when_warmup_has_value(self) -> None:
        s = pd.Series([0.5] + [float("nan")] * 12 + [1.0] * 5)
        with pytest.raises(look_ahead.LookAheadError):
            look_ahead.assert_indicator_warmup_nan(s, period=14, name="rsi")

    def test_g4_fill_must_be_one_bar_after_decision(self) -> None:
        decided = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
        filled = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
        look_ahead.assert_fill_after_decision(decided, filled, bar_seconds=3600)

    def test_g4_raises_on_same_bar_fill(self) -> None:
        t = datetime(2026, 4, 1, 9, tzinfo=UTC)
        with pytest.raises(look_ahead.LookAheadError):
            look_ahead.assert_fill_after_decision(t, t, bar_seconds=3600)

    def test_g5_news_no_future(self) -> None:
        items = [
            NewsItem(
                channel="x",
                message_id=1,
                posted_at=datetime(2026, 4, 1, 9, tzinfo=UTC),
                text="ok",
                fetched_at=datetime(2026, 4, 1, 10, tzinfo=UTC),
            )
        ]
        look_ahead.assert_news_no_future(items, datetime(2026, 4, 1, 9, tzinfo=UTC))

    def test_g5_raises_on_future_news(self) -> None:
        items = [
            NewsItem(
                channel="x",
                message_id=1,
                posted_at=datetime(2026, 4, 1, 12, tzinfo=UTC),
                text="ok",
                fetched_at=datetime(2026, 4, 1, 13, tzinfo=UTC),
            )
        ]
        with pytest.raises(look_ahead.LookAheadError):
            look_ahead.assert_news_no_future(items, datetime(2026, 4, 1, 9, tzinfo=UTC))


# ────────────────────────────── stress ──────────────────────────────


class TestStress:
    def _portfolio(self, market_value: Decimal) -> Portfolio:
        return Portfolio(
            nav=Decimal("1000000"),
            cash=Decimal("500000"),
            positions=[
                Position(
                    ticker="SBER",
                    qty=Decimal("1000"),
                    avg_price=Decimal("300"),
                    market_value=market_value,
                )
            ],
            daily_pnl_pct=Decimal("0"),
            daily_pnl_pct_intraday_peak=Decimal("0"),
            sector_exposures={},
        )

    def test_zero_pnl_when_scenario_lacks_ticker(self) -> None:
        scen = StressScenario(
            name="x",
            start=date(2026, 1, 1),
            end=date(2026, 1, 5),
            description="no data for SBER",
            returns={"GAZP": [Decimal("-0.1")] * 5},
        )
        port = self._portfolio(Decimal("500000"))
        assert stress_test_portfolio(port, scen) == Decimal("0")

    def test_compounded_return_applied_at_position_weight(self) -> None:
        # Position weight = 500000 / 1000000 = 0.5
        # Returns -10% then -5%  → compounded = 0.9 * 0.95 - 1 = -0.145
        # Weighted = 0.5 * -0.145 = -0.0725
        scen = StressScenario(
            name="x",
            start=date(2026, 1, 1),
            end=date(2026, 1, 2),
            description="2 down days",
            returns={"SBER": [Decimal("-0.10"), Decimal("-0.05")]},
        )
        port = self._portfolio(Decimal("500000"))
        result = stress_test_portfolio(port, scen)
        assert result == Decimal("-0.0725")

    def test_all_four_scenarios_present_and_dated(self) -> None:
        keys = {"crisis_2008", "ruble_2014", "feb_2022", "dec_2024_mini"}
        assert set(SCENARIOS) == keys
        for s in SCENARIOS.values():
            assert s.start <= s.end


# ────────────────────────────── walk-forward ──────────────────────────────


class _BuyAndHold:
    """Buys 1 unit on the first bar, holds forever."""

    def __init__(self) -> None:
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
        self._fired = True
        return StrategyOrder(action="BUY", qty=Decimal("100"))


class _AlwaysHold:
    def decide(
        self,
        features_window: pd.DataFrame,
        cash: Decimal,
        position_qty: Decimal,
        as_of: datetime,
    ) -> StrategyOrder | None:
        return None


class _BuyThenSell:
    """Buys on bar 0, sells everything on bar 5."""

    def decide(
        self,
        features_window: pd.DataFrame,
        cash: Decimal,
        position_qty: Decimal,
        as_of: datetime,
    ) -> StrategyOrder | None:
        i = len(features_window) - 1
        if i == 0:
            return StrategyOrder(action="BUY", qty=Decimal("100"))
        if i == 5 and position_qty > 0:
            return StrategyOrder(action="SELL", qty=position_qty)
        return None


def _features(n: int = 30, drift: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range("2026-04-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    closes = 300.0 * np.cumprod(1 + rng.normal(drift, 0.005, n))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame({"open": opens, "close": closes}, index=idx)


class TestWalkForward:
    def test_buy_and_hold_produces_equity_curve_and_metrics(self) -> None:
        feats = _features(n=30, drift=0.002)
        result = run_walk_forward(features=feats, strategy=_BuyAndHold())
        assert isinstance(result, BacktestResult)
        assert len(result.equity) == 30
        assert len(result.timestamps) == 30
        # 29 inter-bar returns on a 30-bar curve
        assert len(result.bar_returns) == 29
        # No closed trades for buy-and-hold → hit_rate is 0
        assert result.n_trades == 0
        assert result.hit_rate == 0.0
        # Metrics computed without exception
        assert result.max_drawdown >= Decimal("0")

    def test_no_orders_keeps_cash_flat(self) -> None:
        feats = _features(n=20)
        result = run_walk_forward(features=feats, strategy=_AlwaysHold())
        assert result.equity[0] == Decimal("1000000")
        assert result.equity[-1] == Decimal("1000000")
        assert result.cumulative_return == Decimal("0")
        assert result.n_trades == 0

    def test_round_trip_records_realised_pnl(self) -> None:
        # Strong positive drift should produce a winning trade
        feats = _features(n=15, drift=0.01)
        result = run_walk_forward(features=feats, strategy=_BuyThenSell())
        assert result.n_trades == 1
        # Hit rate is 1.0 if pnl > 0
        if result.trade_pnls[0] > 0:
            assert result.hit_rate == 1.0

    def test_rejects_non_monotonic_index(self) -> None:
        feats = _features(n=10)
        feats = pd.concat([feats.iloc[5:], feats.iloc[:5]])  # shuffle
        with pytest.raises(look_ahead.LookAheadError):
            run_walk_forward(features=feats, strategy=_AlwaysHold())

    def test_rejects_empty_frame(self) -> None:
        with pytest.raises(ValueError):
            run_walk_forward(features=pd.DataFrame(), strategy=_AlwaysHold())

    def test_rejects_missing_close_column(self) -> None:
        idx = pd.date_range("2026-04-01", periods=5, freq="1h", tz=UTC)
        feats = pd.DataFrame({"open": [1.0] * 5}, index=idx)
        with pytest.raises(ValueError):
            run_walk_forward(features=feats, strategy=_AlwaysHold())
