"""Trader tests — deterministic ManagerPlan → TraderDecision."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.agents import ManagerPlan, Trader


def _plan(
    *,
    recommendation: str = "BUY",
    size: Decimal = Decimal("0.03"),
    horizon: int = 14,
    dissent: bool = False,
) -> ManagerPlan:
    return ManagerPlan(
        agent_name="Manager",
        confidence=0.65,
        rationale="x",
        produced_at=datetime(2026, 4, 29, tzinfo=UTC),
        ticker="SBER",
        recommendation=recommendation,  # type: ignore[arg-type]
        conviction=0.7,
        size_hint_pct_nav=size,
        horizon_days=horizon,
        key_thesis="cheap, growing, technically bid",
        dissent=dissent,
    )


class TestTrader:
    def test_buy_with_atr_derives_stops(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="BUY"),
            current_price=Decimal("300"),
            atr=Decimal("3"),  # 1% ATR
        )
        assert decision.action == "BUY"
        assert decision.qty_pct_nav == Decimal("0.03")
        # 2 * 0.01 = 0.02 stop, 3 * 0.01 = 0.03 take
        assert decision.stop_loss_pct == Decimal("0.02")
        assert decision.take_profit_pct == Decimal("0.03")
        assert decision.time_stop_bars == 14 * 6

    def test_sell_recommendation(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="SELL"),
            current_price=Decimal("300"),
            atr=Decimal("3"),
        )
        assert decision.action == "SELL"

    def test_hold_emits_zero_qty_decision(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="HOLD"),
            current_price=Decimal("300"),
        )
        assert decision.action == "HOLD"
        assert decision.qty_pct_nav == Decimal("0")

    def test_avoid_treated_like_hold(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="AVOID"),
            current_price=Decimal("300"),
        )
        assert decision.action == "HOLD"
        assert decision.qty_pct_nav == Decimal("0")

    def test_missing_atr_uses_fallback(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="BUY"),
            current_price=Decimal("300"),
            atr=None,
        )
        # Fallback ATR 2% → stop 4%, take 6%
        assert decision.stop_loss_pct == Decimal("0.04")
        assert decision.take_profit_pct == Decimal("0.06")

    def test_clamps_stops_to_contract_bounds(self) -> None:
        # Huge ATR should not blow past TraderDecision validation
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="BUY"),
            current_price=Decimal("100"),
            atr=Decimal("50"),  # 50% ATR — pathological
        )
        assert decision.stop_loss_pct <= Decimal("0.20")
        assert decision.take_profit_pct is not None
        assert decision.take_profit_pct <= Decimal("1.0")

    def test_clamps_time_stop_to_200_bars(self) -> None:
        trader = Trader()
        decision = trader.decide(
            _plan(recommendation="BUY", horizon=90),  # 90 * 6 = 540 → clamp to 200
            current_price=Decimal("300"),
            atr=Decimal("3"),
        )
        assert decision.time_stop_bars == 200

    def test_rejects_zero_price(self) -> None:
        trader = Trader()
        with pytest.raises(ValueError):
            trader.decide(
                _plan(recommendation="BUY"),
                current_price=Decimal("0"),
            )
