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
