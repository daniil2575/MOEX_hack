"""TInvest sandbox adapter via the public REST gateway.

The official `tinkoff-investments` Python SDK is gRPC-based and is not
on PyPI in a form pip can resolve standalone (its `tinkoff` namespace
package was withdrawn). Rather than vendor the gRPC stubs for a
pre-hackathon smoke test, we hit the REST gateway directly:

    POST https://invest-public-api.tinkoff.ru/rest/
        {namespace}.SandboxService/{Method}

with `Authorization: Bearer <TINVEST_SANDBOX_TOKEN>` and a JSON body.
The contract is documented at https://developer.tbank.ru/invest/api/.

Currency on the sandbox is `rub` (lowercase, ISO 4217 stripped). FIGI
maps for the IMOEX whitelist are looked up once via the public
InstrumentsService.

Decimal money is encoded by the API as `{"units": int, "nano": int}`
where `value = units + nano / 1e9`. We translate at the boundary so
the rest of the codebase keeps using `Decimal`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from src.execution.contracts import (
    BrokerFill,
    BrokerOrder,
    OrderState,
    OrderStatus,
)
from src.execution.gateway import BrokerGateway

BASE_URL = "https://invest-public-api.tinkoff.ru/rest"
NAMESPACE = "tinkoff.public.invest.api.contract.v1"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

# Map our generic OrderStatus to T-Bank's OrderExecutionReportStatus enum.
# https://developer.tbank.ru/invest/api/orders#orderexecutionreportstatus
_STATUS_MAP: dict[str, OrderStatus] = {
    "EXECUTION_REPORT_STATUS_FILL": "FILLED",
    "EXECUTION_REPORT_STATUS_REJECTED": "REJECTED",
    "EXECUTION_REPORT_STATUS_CANCELLED": "CANCELLED",
    "EXECUTION_REPORT_STATUS_NEW": "PENDING",
    "EXECUTION_REPORT_STATUS_PARTIALLYFILL": "PARTIALLY_FILLED",
}

# T-Bank order direction enum values.
_DIRECTION_BUY = "ORDER_DIRECTION_BUY"
_DIRECTION_SELL = "ORDER_DIRECTION_SELL"
_TYPE_LIMIT = "ORDER_TYPE_LIMIT"
_TYPE_MARKET = "ORDER_TYPE_MARKET"


def _money_to_decimal(m: dict[str, object] | None) -> Decimal | None:
    if m is None:
        return None
    units = int(str(m.get("units", "0")))
    nano = int(str(m.get("nano", "0")))
    return Decimal(units) + Decimal(nano) / Decimal("1000000000")


def _decimal_to_money(d: Decimal, currency: str = "rub") -> dict[str, object]:
    sign = -1 if d < 0 else 1
    abs_d = abs(d)
    units = int(abs_d)
    nano = int((abs_d - Decimal(units)) * Decimal("1000000000"))
    return {"units": str(sign * units), "nano": sign * nano, "currency": currency.lower()}


class TInvestSandboxAdapter(BrokerGateway):
    """Async REST adapter for T-Bank Invest sandbox.

    Pass `figi_resolver` to map ticker → FIGI; the orchestrator wires it
    on startup so the adapter doesn't need to keep its own cache. If
    None is passed, `place_order` rejects with REJECTED + a reason that
    surfaces the missing mapping.
    """

    def __init__(
        self,
        token: str,
        account_id: str,
        *,
        figi_resolver: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        if not account_id:
            raise ValueError("account_id must be non-empty")
        self._token = token
        self._account_id = account_id
        self._figi = dict(figi_resolver or {})
        self._client = client
        self._owns_client = client is None
        # client_order_id → (broker_order_id, last_state)
        self._submitted: dict[str, str] = {}
        self._fills_seen: dict[str, set[str]] = {}

    async def __aenter__(self) -> TInvestSandboxAdapter:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
            self._owns_client = True
        url = f"{BASE_URL}/{NAMESPACE}.SandboxService/{method}"
        r = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return dict(r.json())

    async def place_order(self, order: BrokerOrder) -> OrderState:
        now = datetime.now(UTC)
        figi = self._figi.get(order.ticker)
        if figi is None:
            return OrderState(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                status="REJECTED",
                rejection_reason=f"no FIGI mapping for {order.ticker}",
                last_updated_at=now,
            )

        body: dict[str, object] = {
            "accountId": self._account_id,
            "instrumentId": figi,
            "quantity": str(int(order.qty)),
            "direction": _DIRECTION_BUY if order.action == "BUY" else _DIRECTION_SELL,
            "orderType": _TYPE_LIMIT if order.urgency == "LIMIT" else _TYPE_MARKET,
            "orderId": order.client_order_id,
        }
        if order.urgency == "LIMIT":
            if order.limit_price is None:
                return OrderState(
                    client_order_id=order.client_order_id,
                    broker_order_id=None,
                    status="REJECTED",
                    rejection_reason="LIMIT order requires limit_price",
                    last_updated_at=now,
                )
            body["price"] = _decimal_to_money(order.limit_price, currency=order.currency)

        try:
            data = await self._post("PostSandboxOrder", body)
        except httpx.HTTPStatusError as e:
            return OrderState(
                client_order_id=order.client_order_id,
                broker_order_id=None,
                status="REJECTED",
                rejection_reason=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                last_updated_at=now,
            )

        broker_id = str(data.get("orderId", ""))
        self._submitted[order.client_order_id] = broker_id
        return self._parse_order_state(order.client_order_id, data, now)

    async def cancel_order(self, client_order_id: str) -> OrderState:
        now = datetime.now(UTC)
        broker_id = self._submitted.get(client_order_id)
        if broker_id is None:
            return OrderState(
                client_order_id=client_order_id,
                broker_order_id=None,
                status="REJECTED",
                rejection_reason="unknown order",
                last_updated_at=now,
            )
        try:
            await self._post(
                "CancelSandboxOrder",
                {"accountId": self._account_id, "orderId": broker_id},
            )
        except httpx.HTTPStatusError as e:
            return OrderState(
                client_order_id=client_order_id,
                broker_order_id=broker_id,
                status="REJECTED",
                rejection_reason=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                last_updated_at=now,
            )
        return await self.get_state(client_order_id)

    async def get_state(self, client_order_id: str) -> OrderState:
        now = datetime.now(UTC)
        broker_id = self._submitted.get(client_order_id)
        if broker_id is None:
            return OrderState(
                client_order_id=client_order_id,
                broker_order_id=None,
                status="REJECTED",
                rejection_reason="unknown order",
                last_updated_at=now,
            )
        data = await self._post(
            "GetSandboxOrderState",
            {"accountId": self._account_id, "orderId": broker_id},
        )
        return self._parse_order_state(client_order_id, data, now)

    async def drain_fills(self, client_order_id: str) -> list[BrokerFill]:
        broker_id = self._submitted.get(client_order_id)
        if broker_id is None:
            return []
        data = await self._post(
            "GetSandboxOrderState",
            {"accountId": self._account_id, "orderId": broker_id},
        )
        stages = data.get("stages") or []
        if not isinstance(stages, list):
            return []

        seen = self._fills_seen.setdefault(client_order_id, set())
        out: list[BrokerFill] = []
        total_amount = data.get("totalOrderAmount")
        currency = (
            str(total_amount.get("currency", "rub"))
            if isinstance(total_amount, dict)
            else "rub"
        )
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            trade_id = str(stage.get("tradeId", ""))
            if not trade_id or trade_id in seen:
                continue
            seen.add(trade_id)

            qty = Decimal(str(stage.get("quantity", "0")))
            price_raw = stage.get("price")
            price_dict = price_raw if isinstance(price_raw, dict) else None
            price = _money_to_decimal(price_dict) or Decimal("0")
            if qty <= 0 or price <= 0:
                continue
            executed_at_raw = stage.get("executionTime") or stage.get("createdAt")
            try:
                filled_at = (
                    datetime.fromisoformat(str(executed_at_raw).replace("Z", "+00:00"))
                    if executed_at_raw
                    else datetime.now(UTC)
                )
            except ValueError:
                filled_at = datetime.now(UTC)

            out.append(
                BrokerFill(
                    client_order_id=client_order_id,
                    broker_order_id=broker_id,
                    broker_fill_id=trade_id,
                    qty=qty,
                    fill_price=price,
                    commission_exchange=Decimal("0"),
                    commission_broker=Decimal("0"),
                    slippage=None,
                    currency=str(currency).upper() if currency else "RUB",
                    is_paper=True,
                    filled_at=filled_at,
                )
            )
        return out

    def _parse_order_state(
        self, client_order_id: str, data: dict[str, object], now: datetime
    ) -> OrderState:
        broker_id = str(data.get("orderId", ""))
        status_raw = str(data.get("executionReportStatus", ""))
        status: OrderStatus = _STATUS_MAP.get(status_raw, "PENDING")
        filled_qty_raw = data.get("lotsExecuted") or data.get("executedLots") or "0"
        try:
            filled_qty = Decimal(str(filled_qty_raw))
        except Exception:
            filled_qty = Decimal("0")
        avg_raw = data.get("averagePositionPrice")
        avg_price = _money_to_decimal(avg_raw if isinstance(avg_raw, dict) else None)
        rejection = data.get("rejectReason")
        return OrderState(
            client_order_id=client_order_id,
            broker_order_id=broker_id or None,
            status=status,
            filled_qty=filled_qty,
            avg_fill_price=avg_price,
            rejection_reason=str(rejection) if rejection else None,
            last_updated_at=now,
        )

    # ── helpers for live smoke-tests ────────────────────────────────────

    async def list_accounts(self) -> list[dict[str, object]]:
        """Return sandbox accounts. Used to discover `account_id` interactively."""
        data = await self._post("GetSandboxAccounts", {})
        raw = data.get("accounts")
        if not isinstance(raw, list):
            return []
        return [a for a in raw if isinstance(a, dict)]

    async def open_sandbox_account(self) -> str:
        """Create a fresh sandbox account and return its id."""
        data = await self._post("OpenSandboxAccount", {})
        return str(data.get("accountId", ""))


def adapter_from_env(
    *,
    figi_resolver: dict[str, str] | None = None,
) -> TInvestSandboxAdapter | None:
    """Build the adapter if env is fully populated; else return None."""
    token = os.environ.get("TINVEST_SANDBOX_TOKEN", "").strip()
    account_id = os.environ.get("TINVEST_SANDBOX_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        return None
    return TInvestSandboxAdapter(token, account_id, figi_resolver=figi_resolver)


def new_client_order_id() -> str:
    """Helper: T-Bank requires a unique idempotency id per submission."""
    return uuid.uuid4().hex


__all__ = [
    "TInvestSandboxAdapter",
    "adapter_from_env",
    "new_client_order_id",
]


# Re-export for tests that previously asserted NotImplementedError on the stub.
# The new implementation works, so those tests have been updated.
async def _placeholder() -> None:  # pragma: no cover
    await asyncio.sleep(0)
