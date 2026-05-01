"""Execution layer tests.

Live TInvest path is intentionally untested here — gated on a sandbox
token; only the stub's `NotImplementedError` is asserted. The mock
gateway, by contrast, fully exercises the BrokerGateway surface and
the schema-review fill semantics (commission split, signed slippage,
partial fills).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.execution import (
    BrokerFill,
    BrokerOrder,
    MockBrokerGateway,
    OrderState,
    TInvestSandboxAdapter,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ────────────────────────────── Contracts ──────────────────────────────


class TestBrokerOrderContract:
    def test_minimal_market_order(self) -> None:
        o = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("10"), urgency="MARKET"
        )
        assert o.qty == Decimal("10")
        assert o.currency == "RUB"
        assert len(o.client_order_id) > 0

    def test_rejects_zero_qty(self) -> None:
        with pytest.raises(ValidationError):
            BrokerOrder(ticker="SBER", action="BUY", qty=Decimal("0"), urgency="MARKET")

    def test_rejects_lowercase_ticker(self) -> None:
        with pytest.raises(ValidationError):
            BrokerOrder(ticker="sber", action="BUY", qty=Decimal("1"), urgency="MARKET")


class TestBrokerFillContract:
    def test_split_commissions(self) -> None:
        f = BrokerFill(
            client_order_id="x",
            qty=Decimal("10"),
            fill_price=Decimal("300"),
            commission_exchange=Decimal("0.3"),
            commission_broker=Decimal("1.2"),
            slippage=Decimal("0.05"),
            filled_at=datetime(2026, 4, 28, tzinfo=UTC),
        )
        assert f.commission_exchange + f.commission_broker == Decimal("1.5")
        assert f.is_paper is True


# ────────────────────────────── MockBrokerGateway ──────────────────────────────


class TestMockBrokerGateway:
    def test_market_buy_fills_with_positive_slippage(self) -> None:
        gw = MockBrokerGateway(quotes={"SBER": Decimal("300")}, slippage_bps=Decimal("10"))
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("10"), urgency="MARKET"
        )
        state = _run(gw.place_order(order))
        assert state.status == "FILLED"
        assert state.filled_qty == Decimal("10")
        # 10 bps slippage on a 300 anchor → 300.30
        assert state.avg_fill_price == Decimal("300.3")

        fills = _run(gw.drain_fills(order.client_order_id))
        assert len(fills) == 1
        assert fills[0].slippage == Decimal("0.3")
        assert fills[0].slippage > 0  # BUY pays up

    def test_market_sell_fills_with_negative_slippage(self) -> None:
        gw = MockBrokerGateway(quotes={"GAZP": Decimal("150")}, slippage_bps=Decimal("20"))
        order = BrokerOrder(
            ticker="GAZP", action="SELL", qty=Decimal("5"), urgency="MARKET"
        )
        state = _run(gw.place_order(order))
        assert state.status == "FILLED"
        # -20 bps on 150 → 149.7
        assert state.avg_fill_price == Decimal("149.7")
        fills = _run(gw.drain_fills(order.client_order_id))
        assert fills[0].slippage == Decimal("-0.3")

    def test_limit_fills_at_limit_price_no_slippage(self) -> None:
        gw = MockBrokerGateway(quotes={"SBER": Decimal("300")}, slippage_bps=Decimal("100"))
        order = BrokerOrder(
            ticker="SBER",
            action="BUY",
            qty=Decimal("4"),
            urgency="LIMIT",
            limit_price=Decimal("298.50"),
        )
        state = _run(gw.place_order(order))
        assert state.avg_fill_price == Decimal("298.50")
        fills = _run(gw.drain_fills(order.client_order_id))
        assert fills[0].slippage == Decimal("0")

    def test_unknown_ticker_market_order_rejected(self) -> None:
        gw = MockBrokerGateway(quotes={})
        order = BrokerOrder(
            ticker="UNKNOWN", action="BUY", qty=Decimal("1"), urgency="MARKET"
        )
        state = _run(gw.place_order(order))
        assert state.status == "REJECTED"
        assert state.rejection_reason and "UNKNOWN" in state.rejection_reason

    def test_partial_fill_emits_two_fills(self) -> None:
        gw = MockBrokerGateway(
            quotes={"SBER": Decimal("300")},
            partial_fill_ratio=Decimal("0.4"),
            slippage_bps=Decimal("0"),
        )
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("10"), urgency="MARKET"
        )
        state = _run(gw.place_order(order))
        # full qty filled across two fills → status FILLED
        assert state.status == "FILLED"
        assert state.filled_qty == Decimal("10")
        fills = _run(gw.drain_fills(order.client_order_id))
        assert len(fills) == 2
        assert fills[0].qty == Decimal("4")
        assert fills[1].qty == Decimal("6")
        assert all(f.broker_order_id == fills[0].broker_order_id for f in fills)
        # broker_fill_id should differ
        assert fills[0].broker_fill_id != fills[1].broker_fill_id

    def test_commission_split_recorded(self) -> None:
        gw = MockBrokerGateway(
            quotes={"SBER": Decimal("100")},
            slippage_bps=Decimal("0"),
            commission_exchange_bps=Decimal("2"),
            commission_broker_bps=Decimal("8"),
        )
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("100"), urgency="MARKET"
        )
        _run(gw.place_order(order))
        fills = _run(gw.drain_fills(order.client_order_id))
        assert len(fills) == 1
        # notional = 100 * 100 = 10_000; 2bps = 2.0, 8bps = 8.0
        assert fills[0].commission_exchange == Decimal("2.0")
        assert fills[0].commission_broker == Decimal("8.0")

    def test_drain_is_idempotent(self) -> None:
        gw = MockBrokerGateway(quotes={"SBER": Decimal("300")})
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("1"), urgency="MARKET"
        )
        _run(gw.place_order(order))
        first = _run(gw.drain_fills(order.client_order_id))
        second = _run(gw.drain_fills(order.client_order_id))
        assert len(first) == 1
        assert second == []

    def test_cancel_unknown_order_returns_rejected(self) -> None:
        gw = MockBrokerGateway()
        state = _run(gw.cancel_order("does-not-exist"))
        assert state.status == "REJECTED"

    def test_cancel_after_fill_is_noop(self) -> None:
        gw = MockBrokerGateway(quotes={"SBER": Decimal("300")})
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("1"), urgency="MARKET"
        )
        placed = _run(gw.place_order(order))
        assert placed.status == "FILLED"
        cancelled = _run(gw.cancel_order(order.client_order_id))
        assert cancelled.status == "FILLED", "cancel must not move terminal orders"

    def test_get_state_unknown_order(self) -> None:
        gw = MockBrokerGateway()
        state = _run(gw.get_state("nope"))
        assert state.status == "REJECTED"


# ────────────────────────────── TInvestSandboxAdapter ──────────────────────────────


class TestTInvestSandboxAdapter:
    def test_rejects_empty_token(self) -> None:
        with pytest.raises(ValueError):
            TInvestSandboxAdapter(token="", account_id="acct-1")

    def test_rejects_empty_account_id(self) -> None:
        with pytest.raises(ValueError):
            TInvestSandboxAdapter(token="dummy", account_id="")

    def test_place_order_rejects_unknown_ticker(self) -> None:
        # No FIGI mapping → REJECTED locally without hitting the network.
        adapter = TInvestSandboxAdapter(
            token="dummy", account_id="acct-1", figi_resolver={}
        )
        order = BrokerOrder(
            ticker="UNKNOWN", action="BUY", qty=Decimal("1"), urgency="MARKET"
        )
        state = _run(adapter.place_order(order))
        assert state.status == "REJECTED"
        assert state.rejection_reason and "UNKNOWN" in state.rejection_reason
        assert state.broker_order_id is None

    def test_place_limit_order_requires_limit_price(self) -> None:
        adapter = TInvestSandboxAdapter(
            token="dummy",
            account_id="acct-1",
            figi_resolver={"SBER": "BBG004730N88"},
        )
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("1"), urgency="LIMIT"
        )
        # No limit_price → adapter rejects locally.
        state = _run(adapter.place_order(order))
        assert state.status == "REJECTED"
        assert state.rejection_reason and "limit_price" in state.rejection_reason

    def test_get_state_unknown_order_returns_rejected(self) -> None:
        adapter = TInvestSandboxAdapter(
            token="dummy", account_id="acct-1", figi_resolver={}
        )
        state = _run(adapter.get_state("never-submitted"))
        assert state.status == "REJECTED"

    def test_drain_fills_unknown_order_returns_empty(self) -> None:
        adapter = TInvestSandboxAdapter(
            token="dummy", account_id="acct-1", figi_resolver={}
        )
        fills = _run(adapter.drain_fills("never-submitted"))
        assert fills == []

    def test_cancel_unknown_order_returns_rejected(self) -> None:
        adapter = TInvestSandboxAdapter(
            token="dummy", account_id="acct-1", figi_resolver={}
        )
        state = _run(adapter.cancel_order("never-submitted"))
        assert state.status == "REJECTED"


# ────────────────────────────── Light invariants ──────────────────────────────


class TestOrderStateInvariants:
    def test_avg_fill_price_consistent_with_fills(self) -> None:
        gw = MockBrokerGateway(
            quotes={"SBER": Decimal("100")},
            partial_fill_ratio=Decimal("0.3"),
            slippage_bps=Decimal("0"),
        )
        order = BrokerOrder(
            ticker="SBER", action="BUY", qty=Decimal("10"), urgency="MARKET"
        )
        state: OrderState = _run(gw.place_order(order))
        fills = _run(gw.drain_fills(order.client_order_id))
        weighted = sum((f.qty * f.fill_price for f in fills), start=Decimal("0"))
        total_qty = sum((f.qty for f in fills), start=Decimal("0"))
        assert state.avg_fill_price == weighted / total_qty
