"""Risk Manager contracts: Portfolio, MarketState, ProposedOrder, Verdict, Limits."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TradingStatus = Literal["T", "DA", "H", "U"]
Action = Literal["BUY", "SELL"]
Urgency = Literal["MARKET", "LIMIT"]
Severity = Literal["INFO", "WARN", "BLOCK", "HALT"]


class ProposedOrder(BaseModel):
    """Order proposed by Trader, evaluated by Risk Manager.

    Sector resolved by rules from `MarketState.sector_map` — Trader doesn't supply it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    action: Action
    qty_pct_nav: Decimal = Field(..., ge=Decimal("0"), le=Decimal("0.20"))
    urgency: Urgency


class Position(BaseModel):
    """Held position. `qty` signed: positive=long, negative=short."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    qty: Decimal
    avg_price: Decimal = Field(..., gt=Decimal("0"))
    market_value: Decimal


class Portfolio(BaseModel):
    """Account state. `daily_pnl_pct_intraday_peak` is the high-water-mark for DD-from-peak."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nav: Decimal = Field(..., gt=Decimal("0"))
    cash: Decimal
    positions: list[Position] = Field(default_factory=list)
    daily_pnl_pct: Decimal
    daily_pnl_pct_intraday_peak: Decimal
    sector_exposures: dict[str, Decimal] = Field(default_factory=dict)


class MarketState(BaseModel):
    """Slice of market data used by Risk Manager.

    `adv`: average daily volume in RUB per ticker (20-day window) — feeds LiquidityRule.
    `returns_252d`: trailing 252 daily returns per ticker — feeds VaRRule.
    Missing key in `adv` or `returns_252d` is treated as «no data» → reject.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    trading_status: dict[str, TradingStatus]
    sector_map: dict[str, str]
    whitelist: frozenset[str]
    adv: dict[str, Decimal] = Field(default_factory=dict)
    returns_252d: dict[str, list[Decimal]] = Field(default_factory=dict)


class RiskLimits(BaseModel):
    """Configurable risk thresholds. All values fractions of NAV unless stated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_position_pct_nav: Decimal = Decimal("0.05")
    max_sector_pct_nav: Decimal = Decimal("0.30")
    max_gross_pct_nav: Decimal = Decimal("1.00")
    dd_warning_pct: Decimal = Decimal("-0.03")
    dd_halt_pct: Decimal = Decimal("-0.05")
    max_order_pct_adv: Decimal = Decimal("0.05")
    max_var_pct_nav: Decimal = Decimal("0.02")
    var_alpha: Decimal = Decimal("0.05")


class RiskVerdict(BaseModel):
    """Output of Risk Manager evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    rule: str
    reason: str
    severity: Severity
