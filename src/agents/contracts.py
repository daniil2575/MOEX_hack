"""Pydantic outputs for the analyst agents.

These shape what each agent must return — Instructor (in `LLMProvider`)
forces the LLM to produce JSON conforming to these schemas, so a malformed
or hallucinated output is a parse error, not a downstream surprise.

Convention:
- All confidence values are fractions in [0, 1].
- All money in Decimal.
- `agent_name` lets the Manager dedupe / weight opinions later.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Regime = Literal["bullish", "bearish", "neutral"]
Sentiment = Literal["positive", "negative", "neutral"]
Impact = Literal["high", "medium", "low"]
Recommendation = Literal["BUY", "SELL", "HOLD", "AVOID"]
FundamentalRating = Literal["strong_buy", "buy", "hold", "sell", "strong_sell"]


class _OpinionBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_name: str = Field(..., min_length=1, max_length=64)
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=1, max_length=4000)
    produced_at: datetime


class TechnicalOpinion(_OpinionBase):
    """Output of `TechnicalAnalyst.analyze(ticker, ohlcv, features)`."""

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    regime: Regime
    horizon_bars: int = Field(..., ge=1, le=480)
    support: Decimal | None = Field(default=None, gt=Decimal("0"))
    resistance: Decimal | None = Field(default=None, gt=Decimal("0"))
    signals: list[str] = Field(default_factory=list, max_length=10)


class TickerSentiment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    sentiment: Sentiment
    impact: Impact


class NewsOpinion(_OpinionBase):
    """Output of `NewsAnalyst.analyze(news_items)`."""

    overall_sentiment: Sentiment
    urgency: Impact
    ticker_sentiments: list[TickerSentiment] = Field(default_factory=list, max_length=20)
    key_themes: list[str] = Field(default_factory=list, max_length=10)


class FundamentalSnapshot(BaseModel):
    """Per-ticker fundamentals snapshot — input to `FundamentalAnalyst`.

    Sourced from ISS aggregates / Algopack on the data layer; the agent
    only consumes the snapshot and never re-fetches.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    as_of: datetime
    pe_ratio: Decimal | None = None
    pb_ratio: Decimal | None = None
    dividend_yield_pct: Decimal | None = Field(default=None, ge=Decimal("0"))
    roe_pct: Decimal | None = None
    debt_to_equity: Decimal | None = Field(default=None, ge=Decimal("0"))
    revenue_growth_yoy_pct: Decimal | None = None
    sector_pe_median: Decimal | None = None


class FundamentalOpinion(_OpinionBase):
    """Output of `FundamentalAnalyst.analyze(snapshot)`."""

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    rating: FundamentalRating
    fair_value: Decimal | None = Field(default=None, gt=Decimal("0"))
    key_strengths: list[str] = Field(default_factory=list, max_length=5)
    key_concerns: list[str] = Field(default_factory=list, max_length=5)


class ManagerPlan(_OpinionBase):
    """Aggregate plan from `Manager.synthesize(...)` over the 3 analyst opinions.

    `dissent` is True when the analysts disagree strongly enough that the
    plan should be downstream-treated with extra caution (e.g. smaller
    sizing, prefer LIMIT over MARKET). The flag is the LLM's judgement,
    not a deterministic computation.
    """

    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Z0-9]+$")
    recommendation: Recommendation
    conviction: float = Field(..., ge=0.0, le=1.0)
    size_hint_pct_nav: Decimal = Field(..., ge=Decimal("0"), le=Decimal("0.05"))
    horizon_days: int = Field(..., ge=1, le=90)
    key_thesis: str = Field(..., min_length=1, max_length=2000)
    key_risks: list[str] = Field(default_factory=list, max_length=5)
    dissent: bool = False
