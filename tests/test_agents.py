"""Agent tests with a stub LLMProvider — no network, no real LLM."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError

from src.agents import (
    NewsAnalyst,
    NewsOpinion,
    TechnicalAnalyst,
    TechnicalOpinion,
    TickerSentiment,
)
from src.llm.provider import LLMProvider
from src.news.contracts import NewsItem

T = TypeVar("T", bound=BaseModel)


class StubLLM(LLMProvider):
    """Returns a pre-canned response. Records the last prompt for assertions."""

    def __init__(self, response: BaseModel) -> None:
        self._response = response
        self.last_prompt: str | None = None
        self.calls: int = 0

    async def complete(
        self,
        prompt: str,
        response_model: type[T],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> T:
        self.last_prompt = prompt
        self.calls += 1
        if not isinstance(self._response, response_model):
            raise TypeError(
                f"StubLLM was wired with {type(self._response).__name__} "
                f"but agent asked for {response_model.__name__}"
            )
        return self._response  # type: ignore[return-value]


def _run(coro):
    return asyncio.run(coro)


# ────────────────────────────── Contract validation ──────────────────────────────


class TestTechnicalOpinionContract:
    def test_valid(self) -> None:
        op = TechnicalOpinion(
            agent_name="TechnicalAnalyst",
            confidence=0.7,
            rationale="trend up, RSI 60",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            ticker="SBER",
            regime="bullish",
            horizon_bars=60,
            support=Decimal("295.5"),
            resistance=Decimal("315"),
            signals=["macd_bullish_cross"],
        )
        assert op.regime == "bullish"

    def test_rejects_confidence_above_one(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalOpinion(
                agent_name="x",
                confidence=1.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="SBER",
                regime="bullish",
                horizon_bars=10,
            )

    def test_rejects_invalid_regime(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalOpinion(
                agent_name="x",
                confidence=0.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="SBER",
                regime="WAT",  # type: ignore[arg-type]
                horizon_bars=10,
            )

    def test_rejects_lowercase_ticker(self) -> None:
        with pytest.raises(ValidationError):
            TechnicalOpinion(
                agent_name="x",
                confidence=0.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="sber",
                regime="neutral",
                horizon_bars=10,
            )


class TestNewsOpinionContract:
    def test_valid(self) -> None:
        op = NewsOpinion(
            agent_name="NewsAnalyst",
            confidence=0.6,
            rationale="ok",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            overall_sentiment="positive",
            urgency="medium",
            ticker_sentiments=[
                TickerSentiment(ticker="SBER", sentiment="positive", impact="high")
            ],
            key_themes=["earnings_beat"],
        )
        assert len(op.ticker_sentiments) == 1


# ────────────────────────────── TechnicalAnalyst ──────────────────────────────


def _features_frame(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = pd.Series(rng.normal(loc=300, scale=2, size=n).cumsum() / n + 300)
    return pd.DataFrame(
        {
            "close": close,
            "rsi": rng.uniform(30, 70, size=n),
            "macd_hist": rng.normal(0, 0.1, size=n),
            "atr": rng.uniform(0.05, 0.5, size=n),
        }
    )


class TestTechnicalAnalyst:
    def _opinion(self) -> TechnicalOpinion:
        return TechnicalOpinion(
            agent_name="TechnicalAnalyst",
            confidence=0.65,
            rationale="upward drift, MACD positive",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            ticker="SBER",
            regime="bullish",
            horizon_bars=60,
            signals=["macd_bullish_cross"],
        )

    def test_returns_opinion_and_calls_llm_once(self) -> None:
        stub = StubLLM(self._opinion())
        agent = TechnicalAnalyst(stub)
        out = _run(agent.analyze("SBER", _features_frame()))
        assert isinstance(out, TechnicalOpinion)
        assert out.ticker == "SBER"
        assert stub.calls == 1

    def test_prompt_contains_ticker_and_horizon(self) -> None:
        stub = StubLLM(self._opinion())
        agent = TechnicalAnalyst(stub, horizon_bars=42)
        _run(agent.analyze("GAZP", _features_frame()))
        assert stub.last_prompt is not None
        assert "GAZP" in stub.last_prompt
        assert "42" in stub.last_prompt

    def test_rejects_empty_features(self) -> None:
        stub = StubLLM(self._opinion())
        agent = TechnicalAnalyst(stub)
        with pytest.raises(ValueError):
            _run(agent.analyze("SBER", pd.DataFrame()))


# ────────────────────────────── NewsAnalyst ──────────────────────────────


def _news_batch() -> list[NewsItem]:
    base = datetime(2026, 4, 28, 10, tzinfo=UTC)
    items = []
    texts = [
        "Sber Q1: net profit +12 percent YoY",
        "CBR holds rate at 21 percent",
        "Gazprom dividends: zero, board recommends no payout",
    ]
    for i, t in enumerate(texts):
        items.append(
            NewsItem(
                channel="markettwits",
                message_id=1000 + i,
                posted_at=base.replace(minute=i * 5),
                text=t,
                fetched_at=base,
            )
        )
    return items


class TestNewsAnalyst:
    def _opinion(self) -> NewsOpinion:
        return NewsOpinion(
            agent_name="NewsAnalyst",
            confidence=0.55,
            rationale="mixed: SBER positive, GAZP negative on dividends",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            overall_sentiment="neutral",
            urgency="medium",
            ticker_sentiments=[
                TickerSentiment(ticker="SBER", sentiment="positive", impact="medium"),
                TickerSentiment(ticker="GAZP", sentiment="negative", impact="high"),
            ],
            key_themes=["earnings", "dividends"],
        )

    def test_returns_opinion(self) -> None:
        stub = StubLLM(self._opinion())
        agent = NewsAnalyst(stub, whitelist=frozenset({"SBER", "GAZP", "MOEX"}))
        out = _run(agent.analyze(_news_batch()))
        assert isinstance(out, NewsOpinion)
        assert {ts.ticker for ts in out.ticker_sentiments} == {"SBER", "GAZP"}

    def test_whitelist_appears_in_prompt(self) -> None:
        stub = StubLLM(self._opinion())
        wl = frozenset({"SBER", "MOEX"})
        agent = NewsAnalyst(stub, whitelist=wl)
        _run(agent.analyze(_news_batch()))
        assert stub.last_prompt is not None
        for t in wl:
            assert t in stub.last_prompt

    def test_news_sorted_newest_first(self) -> None:
        stub = StubLLM(self._opinion())
        agent = NewsAnalyst(stub, whitelist=frozenset({"SBER"}))
        _run(agent.analyze(_news_batch()))
        assert stub.last_prompt is not None
        # Last text in our batch was added at minute=10 — should appear before minute=0
        idx_last_added = stub.last_prompt.find("Gazprom dividends")
        idx_first_added = stub.last_prompt.find("Sber Q1")
        assert 0 <= idx_last_added < idx_first_added

    def test_rejects_empty_batch(self) -> None:
        stub = StubLLM(self._opinion())
        agent = NewsAnalyst(stub, whitelist=frozenset({"SBER"}))
        with pytest.raises(ValueError):
            _run(agent.analyze([]))

    def test_max_items_truncates(self) -> None:
        stub = StubLLM(self._opinion())
        agent = NewsAnalyst(stub, whitelist=frozenset({"SBER"}), max_items=2)
        _run(agent.analyze(_news_batch()))
        assert stub.last_prompt is not None
        # batch had 3 items; with max_items=2, only the 2 newest should be in the prompt
        assert "(2 items" in stub.last_prompt
        # Oldest item ("Sber Q1", minute=0) must be dropped
        assert "Sber Q1" not in stub.last_prompt
