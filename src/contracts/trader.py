"""Trader agent output contract — consumed by Risk Manager."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["BUY", "SELL", "HOLD"]
Urgency = Literal["MARKET", "LIMIT"]


class TraderDecision(BaseModel):
    """Decision emitted by Trader agent.

    `stop_loss_pct` / `take_profit_pct` are fractions of entry price
    (0.02 = 2%) — Risk Manager doesn't need to know fill_price.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    action: Action
    qty_pct_nav: Decimal = Field(..., ge=Decimal("0"), le=Decimal("0.20"))
    stop_loss_pct: Decimal = Field(..., ge=Decimal("0.001"), le=Decimal("0.20"))
    take_profit_pct: Decimal | None = Field(default=None, ge=Decimal("0.001"), le=Decimal("1.0"))
    time_stop_bars: int = Field(..., ge=1, le=200)
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=1, max_length=2000)
    urgency: Urgency = "LIMIT"
