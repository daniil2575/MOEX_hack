"""TInvest sandbox adapter — skeleton.

Wires `BrokerGateway` to T-Bank's TInvest sandbox via the official
`tinkoff-investments` Python SDK. The implementation is a stub until
`TINVEST_SANDBOX_TOKEN` is in `.env` and a smoke order has been confirmed
manually — see `notes/quant_reading_log.md` for the order book of the
hackathon's broker integration.

Methods raise `NotImplementedError` deliberately: the interface is fixed
(matches `BrokerGateway`), but the SDK calls are deferred to the day a
sandbox token is available. Tests use `MockBrokerGateway` instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.execution.contracts import BrokerFill, BrokerOrder, OrderState
from src.execution.gateway import BrokerGateway

_NOT_READY = "TInvestSandboxAdapter is not implemented yet — gated on sandbox token + smoke test"


class TInvestSandboxAdapter(BrokerGateway):
    def __init__(self, token: str, account_id: str) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        self._token = token
        self._account_id = account_id

    async def place_order(self, order: BrokerOrder) -> OrderState:
        raise NotImplementedError(_NOT_READY)

    async def cancel_order(self, client_order_id: str) -> OrderState:
        raise NotImplementedError(_NOT_READY)

    async def get_state(self, client_order_id: str) -> OrderState:
        raise NotImplementedError(_NOT_READY)

    async def drain_fills(self, client_order_id: str) -> list[BrokerFill]:
        raise NotImplementedError(_NOT_READY)

    @staticmethod
    def _stub_now() -> datetime:  # pragma: no cover — placeholder
        return datetime.now(UTC)
