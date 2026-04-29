"""E2E orchestrator tests — full LangGraph DAG with stubbed LLMs.

The DAG is the integration boundary: every component contract has unit
tests; this file verifies they wire together without exception and that
the conditional routing (risk-rejected → skip execute) actually fires.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

import numpy as np
import pandas as pd
from pydantic import BaseModel

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
    Trader,
)
from src.contracts.risk import (
    MarketState,
    Portfolio,
    RiskLimits,
    TradingStatus,
)
from src.execution.gateway import MockBrokerGateway
from src.llm.provider import LLMProvider
from src.news.contracts import NewsItem
from src.orchestrator import build_graph
from src.risk.manager import RiskManager
from src.risk.rules import default_rules

T = TypeVar("T", bound=BaseModel)


class StubLLM(LLMProvider):
    """Returns a different canned response per response_model class."""

    def __init__(self, responses: dict[type, BaseModel]) -> None:
        self._responses = responses

    async def complete(
        self,
        prompt: str,
        response_model: type[T],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> T:
        try:
            return self._responses[response_model]  # type: ignore[return-value]
        except KeyError as e:
            raise AssertionError(
                f"StubLLM has no canned response for {response_model.__name__}"
            ) from e


def _features() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 60
    return pd.DataFrame(
        {
            "close": pd.Series(rng.normal(300, 1, n).cumsum() / n + 300),
            "rsi": rng.uniform(30, 70, n),
            "macd_hist": rng.normal(0, 0.1, n),
            "atr": rng.uniform(2.5, 3.5, n),
        }
    )


def _news_items() -> list[NewsItem]:
    base = datetime(2026, 4, 29, 10, tzinfo=UTC)
    return [
        NewsItem(
            channel="markettwits",
            message_id=1,
            posted_at=base,
            text="Sber Q1: net profit +12 percent YoY",
            fetched_at=base,
        ),
    ]


def _snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        ticker="SBER",
        as_of=datetime(2026, 4, 29, tzinfo=UTC),
        pe_ratio=Decimal("4.8"),
        roe_pct=Decimal("24"),
        dividend_yield_pct=Decimal("11.2"),
    )


def _portfolio() -> Portfolio:
    return Portfolio(
        nav=Decimal("1000000"),
        cash=Decimal("1000000"),
        positions=[],
        daily_pnl_pct=Decimal("0"),
        daily_pnl_pct_intraday_peak=Decimal("0"),
        sector_exposures={},
    )


def _market() -> MarketState:
    whitelist = frozenset({"SBER", "GAZP"})
    statuses: dict[str, TradingStatus] = dict.fromkeys(whitelist, "T")
    return MarketState(
        trading_status=statuses,
        sector_map={"SBER": "Banking", "GAZP": "Energy"},
        whitelist=whitelist,
        adv={"SBER": Decimal("1000000000"), "GAZP": Decimal("1000000000")},
        returns_252d={"SBER": [Decimal("0")] * 252, "GAZP": [Decimal("0")] * 252},
    )


def _stub_responses(*, recommendation: str = "BUY") -> dict[type, BaseModel]:
    now = datetime(2026, 4, 29, tzinfo=UTC)
    return {
        TechnicalOpinion: TechnicalOpinion(
            agent_name="TechnicalAnalyst",
            confidence=0.65,
            rationale="bullish",
            produced_at=now,
            ticker="SBER",
            regime="bullish",
            horizon_bars=60,
            signals=["macd_bullish_cross"],
        ),
        NewsOpinion: NewsOpinion(
            agent_name="NewsAnalyst",
            confidence=0.6,
            rationale="positive earnings",
            produced_at=now,
            overall_sentiment="positive",
            urgency="medium",
            ticker_sentiments=[
                TickerSentiment(ticker="SBER", sentiment="positive", impact="high")
            ],
            key_themes=["earnings"],
        ),
        FundamentalOpinion: FundamentalOpinion(
            agent_name="FundamentalAnalyst",
            confidence=0.7,
            rationale="cheap on P/E",
            produced_at=now,
            ticker="SBER",
            rating="buy",
            fair_value=Decimal("365"),
        ),
        ManagerPlan: ManagerPlan(
            agent_name="Manager",
            confidence=0.7,
            rationale="3 analysts agree",
            produced_at=now,
            ticker="SBER",
            recommendation=recommendation,  # type: ignore[arg-type]
            conviction=0.7,
            size_hint_pct_nav=Decimal("0.03"),
            horizon_days=14,
            key_thesis="cheap, growing, technically bid",
        ),
    }


def _build_pipeline(
    *,
    responses: dict[type, BaseModel],
    quotes: dict[str, Decimal] | None = None,
):
    llm = StubLLM(responses)
    return build_graph(
        technical=TechnicalAnalyst(llm),
        news=NewsAnalyst(llm, whitelist=frozenset({"SBER", "GAZP"})),
        fundamental=FundamentalAnalyst(llm),
        manager=Manager(llm),
        trader=Trader(),
        risk=RiskManager(default_rules(RiskLimits())),
        broker=MockBrokerGateway(quotes=quotes or {"SBER": Decimal("300")}),
    )


def _initial_state() -> dict:
    return {
        "ticker": "SBER",
        "features": _features(),
        "news_items": _news_items(),
        "fundamental_snapshot": _snapshot(),
        "portfolio": _portfolio(),
        "market": _market(),
        "current_price": Decimal("300"),
        "atr": Decimal("3"),
    }


# ────────────────────────────── Happy path ──────────────────────────────


class TestE2EHappyPath:
    def test_full_pipeline_runs_and_executes(self) -> None:
        graph = _build_pipeline(responses=_stub_responses(recommendation="BUY"))
        out = asyncio.run(graph.ainvoke(_initial_state()))
        # Every node populated its output
        assert out["technical_opinion"].regime == "bullish"
        assert out["news_opinion"].overall_sentiment == "positive"
        assert out["fundamental_opinion"].rating == "buy"
        assert out["plan"].recommendation == "BUY"
        assert out["decision"].action == "BUY"
        assert out["proposed_order"].action == "BUY"
        assert out["risk_verdict"].approved is True
        assert out["risk_verdict"].rule == "ALL_PASSED"
        # Broker actually filled the order
        assert out["order_state"].status == "FILLED"
        assert len(out["fills"]) >= 1

    def test_hold_recommendation_short_circuits_to_skip(self) -> None:
        graph = _build_pipeline(responses=_stub_responses(recommendation="HOLD"))
        out = asyncio.run(graph.ainvoke(_initial_state()))
        assert out["decision"].action == "HOLD"
        # No order placed → no proposed_order key, no order_state, no fills
        assert "proposed_order" not in out
        assert out["risk_verdict"].rule == "HOLD"
        assert "order_state" not in out
        assert "fills" not in out


# ────────────────────────────── Risk-reject route ──────────────────────────────


class TestE2ERiskReject:
    def test_unknown_ticker_blocks_at_risk_and_skips_execute(self) -> None:
        # Manager recommends BUY but on a ticker NOT in market.whitelist → Whitelist rule rejects
        responses = _stub_responses(recommendation="BUY")
        # Override the manager plan to recommend an off-whitelist ticker.
        responses[ManagerPlan] = ManagerPlan(
            agent_name="Manager",
            confidence=0.7,
            rationale="x",
            produced_at=datetime(2026, 4, 29, tzinfo=UTC),
            ticker="SBER",  # Manager keeps SBER, but we'll restrict the market whitelist
            recommendation="BUY",
            conviction=0.7,
            size_hint_pct_nav=Decimal("0.03"),
            horizon_days=14,
            key_thesis="x",
        )
        graph = _build_pipeline(responses=responses)
        # Patch market state to drop SBER from the whitelist
        state = _initial_state()
        market = state["market"]
        narrowed = MarketState(
            trading_status=market.trading_status,
            sector_map=market.sector_map,
            whitelist=frozenset(),  # empty → SBER not whitelisted
            adv=market.adv,
            returns_252d=market.returns_252d,
        )
        state["market"] = narrowed

        out = asyncio.run(graph.ainvoke(state))
        assert out["risk_verdict"].approved is False
        assert out["risk_verdict"].rule == "WhitelistRule"
        assert "order_state" not in out  # execute branch skipped
        assert "fills" not in out

    def test_position_size_over_cap_routes_to_skip(self) -> None:
        # Manager hints 5% (at cap) but trader will produce qty_pct_nav=0.05.
        # Make Manager recommend more by setting size_hint to the max allowed (0.05)
        # AND patch the limits to a tighter cap so PositionSizeRule fires.
        responses = _stub_responses(recommendation="BUY")
        responses[ManagerPlan] = ManagerPlan(
            agent_name="Manager",
            confidence=0.7,
            rationale="x",
            produced_at=datetime(2026, 4, 29, tzinfo=UTC),
            ticker="SBER",
            recommendation="BUY",
            conviction=0.7,
            size_hint_pct_nav=Decimal("0.05"),  # at the cap
            horizon_days=14,
            key_thesis="x",
        )
        # Build pipeline with a tighter risk limit (max_position_pct_nav=0.02)
        llm = StubLLM(responses)
        graph = build_graph(
            technical=TechnicalAnalyst(llm),
            news=NewsAnalyst(llm, whitelist=frozenset({"SBER", "GAZP"})),
            fundamental=FundamentalAnalyst(llm),
            manager=Manager(llm),
            trader=Trader(),
            risk=RiskManager(default_rules(RiskLimits(max_position_pct_nav=Decimal("0.02")))),
            broker=MockBrokerGateway(quotes={"SBER": Decimal("300")}),
        )
        out = asyncio.run(graph.ainvoke(_initial_state()))
        assert out["risk_verdict"].approved is False
        assert out["risk_verdict"].rule == "PositionSizeRule"
        assert "order_state" not in out
