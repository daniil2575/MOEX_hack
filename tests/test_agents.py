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
    FundamentalAnalyst,
    FundamentalOpinion,
    FundamentalSnapshot,
    Manager,
    ManagerPlan,
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


# ────────────────────────────── FundamentalAnalyst ──────────────────────────────


def _snapshot(ticker: str = "SBER") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker=ticker,
        as_of=datetime(2026, 4, 28, tzinfo=UTC),
        pe_ratio=Decimal("4.8"),
        pb_ratio=Decimal("1.1"),
        dividend_yield_pct=Decimal("11.2"),
        roe_pct=Decimal("24.1"),
        debt_to_equity=Decimal("0.8"),
        revenue_growth_yoy_pct=Decimal("8.4"),
        sector_pe_median=Decimal("5.5"),
    )


class TestFundamentalAnalyst:
    def _opinion(self, ticker: str = "SBER") -> FundamentalOpinion:
        return FundamentalOpinion(
            agent_name="FundamentalAnalyst",
            confidence=0.7,
            rationale="P/E below sector, ROE strong, yield 11%",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            ticker=ticker,
            rating="buy",
            fair_value=Decimal("365"),
            key_strengths=["high_roe", "below_sector_pe"],
            key_concerns=["macro_rate_risk"],
        )

    def test_returns_opinion(self) -> None:
        stub = StubLLM(self._opinion())
        agent = FundamentalAnalyst(stub)
        out = _run(agent.analyze(_snapshot()))
        assert isinstance(out, FundamentalOpinion)
        assert out.rating == "buy"
        assert stub.calls == 1

    def test_prompt_contains_ratios(self) -> None:
        stub = StubLLM(self._opinion())
        agent = FundamentalAnalyst(stub)
        _run(agent.analyze(_snapshot()))
        assert stub.last_prompt is not None
        # Spot-check: ratio values must appear so the LLM can ground its rating
        assert "4.8" in stub.last_prompt          # P/E
        assert "11.2" in stub.last_prompt         # dividend yield
        assert "24.1" in stub.last_prompt         # ROE
        assert "5.5" in stub.last_prompt          # sector P/E median

    def test_handles_missing_ratios(self) -> None:
        stub = StubLLM(self._opinion())
        agent = FundamentalAnalyst(stub)
        snap = FundamentalSnapshot(
            ticker="SBER",
            as_of=datetime(2026, 4, 28, tzinfo=UTC),
        )
        _run(agent.analyze(snap))
        assert stub.last_prompt is not None
        assert "n/a" in stub.last_prompt


class TestFundamentalContract:
    def test_rejects_negative_dividend_yield(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalSnapshot(
                ticker="SBER",
                as_of=datetime(2026, 4, 28, tzinfo=UTC),
                dividend_yield_pct=Decimal("-1"),
            )

    def test_rejects_invalid_rating(self) -> None:
        with pytest.raises(ValidationError):
            FundamentalOpinion(
                agent_name="x",
                confidence=0.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="SBER",
                rating="WAT",  # type: ignore[arg-type]
            )


# ────────────────────────────── Manager ──────────────────────────────


def _tech_op(ticker: str = "SBER") -> TechnicalOpinion:
    return TechnicalOpinion(
        agent_name="TechnicalAnalyst",
        confidence=0.6,
        rationale="trend up, MACD positive",
        produced_at=datetime(2026, 4, 28, tzinfo=UTC),
        ticker=ticker,
        regime="bullish",
        horizon_bars=60,
        signals=["macd_bullish_cross"],
    )


def _news_op() -> NewsOpinion:
    return NewsOpinion(
        agent_name="NewsAnalyst",
        confidence=0.55,
        rationale="positive earnings backdrop, mild policy concerns",
        produced_at=datetime(2026, 4, 28, tzinfo=UTC),
        overall_sentiment="positive",
        urgency="medium",
        ticker_sentiments=[
            TickerSentiment(ticker="SBER", sentiment="positive", impact="high"),
            TickerSentiment(ticker="GAZP", sentiment="negative", impact="medium"),
        ],
        key_themes=["earnings_beats", "rate_path"],
    )


def _fund_op(ticker: str = "SBER") -> FundamentalOpinion:
    return FundamentalOpinion(
        agent_name="FundamentalAnalyst",
        confidence=0.7,
        rationale="cheap on P/E, dividend solid",
        produced_at=datetime(2026, 4, 28, tzinfo=UTC),
        ticker=ticker,
        rating="buy",
        fair_value=Decimal("365"),
        key_strengths=["below_sector_pe"],
        key_concerns=["regulatory"],
    )


class TestManager:
    def _plan(self, ticker: str = "SBER") -> ManagerPlan:
        return ManagerPlan(
            agent_name="Manager",
            confidence=0.65,
            rationale="3 analysts agree on bullish",
            produced_at=datetime(2026, 4, 28, tzinfo=UTC),
            ticker=ticker,
            recommendation="BUY",
            conviction=0.7,
            size_hint_pct_nav=Decimal("0.03"),
            horizon_days=14,
            key_thesis="cheap, growing, technically bid",
            key_risks=["rate_volatility"],
            dissent=False,
        )

    def test_synthesize_calls_llm_with_deep_temperature(self) -> None:
        stub = StubLLM(self._plan())
        mgr = Manager(stub, temperature=0.4)
        out = _run(mgr.synthesize("SBER", _tech_op(), _news_op(), _fund_op()))
        assert isinstance(out, ManagerPlan)
        assert out.recommendation == "BUY"
        assert stub.calls == 1

    def test_prompt_includes_all_three_analyst_inputs(self) -> None:
        stub = StubLLM(self._plan())
        mgr = Manager(stub)
        _run(mgr.synthesize("SBER", _tech_op(), _news_op(), _fund_op()))
        assert stub.last_prompt is not None
        for fragment in (
            "TechnicalAnalyst",
            "NewsAnalyst",
            "FundamentalAnalyst",
            "macd_bullish_cross",
            "earnings_beats",
            "below_sector_pe",
        ):
            assert fragment in stub.last_prompt, f"missing fragment: {fragment}"

    def test_prompt_filters_news_to_target_ticker(self) -> None:
        stub = StubLLM(self._plan())
        mgr = Manager(stub)
        # News op has both SBER and GAZP; we ask about SBER only.
        _run(mgr.synthesize("SBER", _tech_op("SBER"), _news_op(), _fund_op("SBER")))
        assert stub.last_prompt is not None
        # The line that lists per-ticker sentiment for THIS ticker should mention SBER...
        assert "SBER=positive/high" in stub.last_prompt
        # ...but not surface GAZP's row in that same per-ticker list.
        assert "GAZP=negative/medium" not in stub.last_prompt

    def test_rejects_ticker_mismatch(self) -> None:
        stub = StubLLM(self._plan())
        mgr = Manager(stub)
        with pytest.raises(ValueError, match="ticker mismatch"):
            _run(
                mgr.synthesize(
                    "SBER",
                    _tech_op("GAZP"),  # mismatched
                    _news_op(),
                    _fund_op("SBER"),
                )
            )


class TestManagerPlanContract:
    def test_size_hint_capped_at_5pct(self) -> None:
        with pytest.raises(ValidationError):
            ManagerPlan(
                agent_name="Manager",
                confidence=0.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="SBER",
                recommendation="BUY",
                conviction=0.5,
                size_hint_pct_nav=Decimal("0.06"),  # over the 5% cap
                horizon_days=10,
                key_thesis="x",
            )

    def test_rejects_invalid_recommendation(self) -> None:
        with pytest.raises(ValidationError):
            ManagerPlan(
                agent_name="Manager",
                confidence=0.5,
                rationale="x",
                produced_at=datetime(2026, 4, 28, tzinfo=UTC),
                ticker="SBER",
                recommendation="WAT",  # type: ignore[arg-type]
                conviction=0.5,
                size_hint_pct_nav=Decimal("0.02"),
                horizon_days=10,
                key_thesis="x",
            )
