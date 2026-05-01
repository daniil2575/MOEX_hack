"""Pydantic contracts at the broker boundary.

These are *separate* from `src.contracts.risk.ProposedOrder` — by the time
an order reaches the gateway, it has been:
  1. Validated by the Risk Manager
  2. Converted from `qty_pct_nav` (Decimal fraction) into an absolute lot
     count (broker speaks lots/shares, not portfolio percentages)
  3. Augmented with a client-side `client_order_id` for idempotency

`BrokerFill` mirrors the schema-review fields agreed with the Quant role
during team-phase: split commissions, signed slippage, currency, is_paper.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["BUY", "SELL"]
Urgency = Literal["MARKET", "LIMIT"]
OrderStatus = Literal[
    "PENDING",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
]


class BrokerOrder(BaseModel):
    """An order sized in absolute units, ready to send to a broker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Dashed UUID format (e.g. "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx") — T-Bank
    # rejects hex-only UUIDs at the API boundary, so we standardise here.
    client_order_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=64)
    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    action: Action
    qty: Decimal = Field(..., gt=Decimal("0"))
    limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    urgency: Urgency
    currency: str = Field(default="RUB", min_length=3, max_length=3)


class BrokerFill(BaseModel):
    """A single execution. One BrokerOrder may produce many BrokerFills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str
    broker_order_id: str | None = None
    broker_fill_id: str | None = None
    qty: Decimal = Field(..., gt=Decimal("0"))
    fill_price: Decimal = Field(..., gt=Decimal("0"))
    commission_exchange: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    commission_broker: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    slippage: Decimal | None = None
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    is_paper: bool = True
    filled_at: datetime


class OrderState(BaseModel):
    """Snapshot of an order's lifecycle as the broker reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str
    broker_order_id: str | None
    status: OrderStatus
    filled_qty: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    avg_fill_price: Decimal | None = None
    rejection_reason: str | None = None
    last_updated_at: datetime
