"""BrokerGateway ABC + MockBrokerGateway for tests and paper-trading dev.

The real adapters (TInvestSandboxAdapter, future AlphaSandboxAdapter) live
alongside this module and inherit from BrokerGateway.

Mock semantics: orders are filled deterministically on `place_order()`:
- MARKET orders fill at `quote * (1 + slippage_bps/10_000)` for BUY,
  symmetric for SELL.
- LIMIT orders fill at `limit_price` exactly (zero slippage by definition);
  a configurable `partial_fill_ratio < 1` splits the order into two fills
  to exercise the partial-fill code path downstream.
- Commissions are flat fractions of notional, split exchange/broker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.execution.contracts import (
    BrokerFill,
    BrokerOrder,
    OrderState,
)

if TYPE_CHECKING:
    pass


class BrokerGateway(ABC):
    """Minimal surface area: place, cancel, query state, drain fills."""

    @abstractmethod
    async def place_order(self, order: BrokerOrder) -> OrderState:
        """Submit `order` to the broker. Returns initial state (PENDING/REJECTED)."""

    @abstractmethod
    async def cancel_order(self, client_order_id: str) -> OrderState:
        """Best-effort cancel. Returns the resulting state."""

    @abstractmethod
    async def get_state(self, client_order_id: str) -> OrderState:
        """Snapshot of an order — used by the orchestrator to poll progress."""

    @abstractmethod
    async def drain_fills(self, client_order_id: str) -> list[BrokerFill]:
        """Pop all unread fills for an order. Empty list if none new."""


class MockBrokerGateway(BrokerGateway):
    """Deterministic in-memory broker for tests and offline dev runs.

    Configuration:
        quotes              — last-trade prices keyed by ticker, used as
                              fill anchor for MARKET orders. Missing ticker
                              causes the order to be rejected.
        slippage_bps        — basis points of adverse slippage on MARKET
                              orders (BUY pays more, SELL receives less).
        commission_exchange_bps / commission_broker_bps  — flat bps of
                              notional, split into the two columns the
                              schema review agreed on.
        partial_fill_ratio  — if 0 < r < 1, the order fills in two halves
                              (`qty * r` then `qty * (1 - r)`), letting tests
                              exercise PARTIALLY_FILLED → FILLED transitions.
        is_paper            — propagated to every BrokerFill.
    """

    def __init__(
        self,
        *,
        quotes: dict[str, Decimal] | None = None,
        slippage_bps: Decimal = Decimal("5"),
        commission_exchange_bps: Decimal = Decimal("1"),
        commission_broker_bps: Decimal = Decimal("4"),
        partial_fill_ratio: Decimal | None = None,
        is_paper: bool = True,
    ) -> None:
        self._quotes: dict[str, Decimal] = dict(quotes or {})
        self._slip = slippage_bps
        self._comm_ex = commission_exchange_bps
        self._comm_br = commission_broker_bps
        self._partial = partial_fill_ratio
        self._is_paper = is_paper

        self._state: dict[str, OrderState] = {}
        self._pending_fills: dict[str, list[BrokerFill]] = {}
        self._counter = 0

    # ── public test helpers ─────────────────────────────────────────────

    def set_quote(self, ticker: str, price: Decimal) -> None:
        self._quotes[ticker] = price

    # ── BrokerGateway ───────────────────────────────────────────────────

    async def place_order(self, order: BrokerOrder) -> OrderState:
        now = datetime.now(UTC)
        broker_id = self._next_broker_id()

        anchor = self._fill_anchor(order)
        if anchor is None:
            self._state[order.client_order_id] = OrderState(
                client_order_id=order.client_order_id,
                broker_order_id=broker_id,
                status="REJECTED",
                rejection_reason=f"no quote for {order.ticker}",
                last_updated_at=now,
            )
            return self._state[order.client_order_id]

        fills = self._build_fills(order, anchor, broker_id, now)
        self._pending_fills.setdefault(order.client_order_id, []).extend(fills)

        filled_qty = sum((f.qty for f in fills), start=Decimal("0"))
        avg = sum((f.qty * f.fill_price for f in fills), start=Decimal("0")) / filled_qty
        state = OrderState(
            client_order_id=order.client_order_id,
            broker_order_id=broker_id,
            status="FILLED" if filled_qty == order.qty else "PARTIALLY_FILLED",
            filled_qty=filled_qty,
            avg_fill_price=avg,
            last_updated_at=now,
        )
        self._state[order.client_order_id] = state
        return state

    async def cancel_order(self, client_order_id: str) -> OrderState:
        existing = self._state.get(client_order_id)
        now = datetime.now(UTC)
        if existing is None:
            state = OrderState(
                client_order_id=client_order_id,
                broker_order_id=None,
                status="REJECTED",
                rejection_reason="unknown order",
                last_updated_at=now,
            )
            self._state[client_order_id] = state
            return state

        # If already terminal, return existing.
        if existing.status in ("FILLED", "CANCELLED", "REJECTED"):
            return existing

        cancelled = OrderState(
            client_order_id=existing.client_order_id,
            broker_order_id=existing.broker_order_id,
            status="CANCELLED",
            filled_qty=existing.filled_qty,
            avg_fill_price=existing.avg_fill_price,
            last_updated_at=now,
        )
        self._state[client_order_id] = cancelled
        return cancelled

    async def get_state(self, client_order_id: str) -> OrderState:
        existing = self._state.get(client_order_id)
        if existing is not None:
            return existing
        return OrderState(
            client_order_id=client_order_id,
            broker_order_id=None,
            status="REJECTED",
            rejection_reason="unknown order",
            last_updated_at=datetime.now(UTC),
        )

    async def drain_fills(self, client_order_id: str) -> list[BrokerFill]:
        out = self._pending_fills.get(client_order_id, [])
        self._pending_fills[client_order_id] = []
        return out

    # ── internals ───────────────────────────────────────────────────────

    def _fill_anchor(self, order: BrokerOrder) -> Decimal | None:
        if order.urgency == "LIMIT":
            return order.limit_price
        return self._quotes.get(order.ticker)

    def _build_fills(
        self,
        order: BrokerOrder,
        anchor: Decimal,
        broker_id: str,
        now: datetime,
    ) -> list[BrokerFill]:
        if order.urgency == "MARKET":
            slip_factor = self._slip / Decimal("10000")
            sign = Decimal("1") if order.action == "BUY" else Decimal("-1")
            fill_price = anchor * (Decimal("1") + sign * slip_factor)
            slippage: Decimal | None = fill_price - anchor
        else:
            fill_price = anchor
            slippage = Decimal("0")

        if self._partial and Decimal("0") < self._partial < Decimal("1"):
            qty1 = (order.qty * self._partial).quantize(Decimal("0.00000001"))
            qty2 = order.qty - qty1
            quantities = [qty1, qty2]
        else:
            quantities = [order.qty]

        fills: list[BrokerFill] = []
        for i, q in enumerate(quantities):
            notional = q * fill_price
            comm_ex = notional * self._comm_ex / Decimal("10000")
            comm_br = notional * self._comm_br / Decimal("10000")
            fills.append(
                BrokerFill(
                    client_order_id=order.client_order_id,
                    broker_order_id=broker_id,
                    broker_fill_id=f"{broker_id}-{i + 1}",
                    qty=q,
                    fill_price=fill_price,
                    commission_exchange=comm_ex,
                    commission_broker=comm_br,
                    slippage=slippage,
                    currency=order.currency,
                    is_paper=self._is_paper,
                    filled_at=now,
                )
            )
        return fills

    def _next_broker_id(self) -> str:
        self._counter += 1
        return f"mock-{self._counter:08d}"
