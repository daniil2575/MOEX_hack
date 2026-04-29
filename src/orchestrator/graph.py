"""LangGraph DAG: per-tick trading pipeline.

Flow:
        analysts (parallel: technical, news, fundamental)
             ↓
        manager → trader → risk → [route] → execute / END

`risk` short-circuits the graph: if the verdict is not approved, we skip
`execute` and end. Approved verdicts proceed to the broker.

The graph is built once (`build_graph(...)`) and reused across ticks —
state is per-invocation. Nodes are pure async functions over `TickState`.

LangGraph note: each node returns a *partial* dict. We never mutate the
incoming state in place; the graph runtime merges the return value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from langgraph.graph import END, StateGraph

from src.agents import (
    FundamentalAnalyst,
    Manager,
    NewsAnalyst,
    TechnicalAnalyst,
    Trader,
)
from src.contracts.risk import ProposedOrder, RiskVerdict
from src.execution.contracts import BrokerOrder
from src.execution.gateway import BrokerGateway
from src.orchestrator.state import TickState
from src.risk.manager import RiskManager


def build_graph(
    *,
    technical: TechnicalAnalyst,
    news: NewsAnalyst,
    fundamental: FundamentalAnalyst,
    manager: Manager,
    trader: Trader,
    risk: RiskManager,
    broker: BrokerGateway,
) -> Any:
    """Wire the pipeline. The compiled graph is `await`-able via `.ainvoke()`.

    Return type is `Any` because LangGraph's `CompiledStateGraph` generic
    parameters change across minor versions; downstream callers only need
    `.ainvoke(state)`.
    """

    async def n_technical(state: TickState) -> dict[str, Any]:
        op = await technical.analyze(state["ticker"], state["features"])
        return {"technical_opinion": op}

    async def n_news(state: TickState) -> dict[str, Any]:
        op = await news.analyze(state["news_items"])
        return {"news_opinion": op}

    async def n_fundamental(state: TickState) -> dict[str, Any]:
        op = await fundamental.analyze(state["fundamental_snapshot"])
        return {"fundamental_opinion": op}

    async def n_manager(state: TickState) -> dict[str, Any]:
        plan = await manager.synthesize(
            state["ticker"],
            state["technical_opinion"],
            state["news_opinion"],
            state["fundamental_opinion"],
        )
        return {"plan": plan}

    async def n_trader(state: TickState) -> dict[str, Any]:
        decision = trader.decide(
            state["plan"],
            current_price=state["current_price"],
            atr=state.get("atr"),
        )
        proposed = ProposedOrder(
            ticker=decision.ticker,
            action="BUY" if decision.action == "BUY" else "SELL",
            qty_pct_nav=decision.qty_pct_nav,
            urgency=decision.urgency,
        ) if decision.action != "HOLD" else None

        out: dict[str, Any] = {"decision": decision}
        if proposed is not None:
            out["proposed_order"] = proposed
        return out

    async def n_risk(state: TickState) -> dict[str, Any]:
        proposed = state.get("proposed_order")
        if proposed is None:
            # HOLD path — synthesize a trivially-approved verdict for trace symmetry.
            verdict = RiskVerdict(
                approved=True,
                rule="HOLD",
                reason="Trader emitted HOLD; no order to evaluate",
                severity="INFO",
            )
            return {"risk_verdict": verdict}
        return {"risk_verdict": risk.evaluate(proposed, state["portfolio"], state["market"])}

    async def n_execute(state: TickState) -> dict[str, Any]:
        proposed = state["proposed_order"]
        decision = state["decision"]
        # Convert percentage size into absolute qty using current price.
        notional = state["portfolio"].nav * proposed.qty_pct_nav
        qty = (notional / state["current_price"]).quantize(Decimal("0.00000001"))
        broker_order = BrokerOrder(
            ticker=proposed.ticker,
            action=proposed.action,
            qty=qty,
            limit_price=state["current_price"] if decision.urgency == "LIMIT" else None,
            urgency=decision.urgency,
        )
        order_state = await broker.place_order(broker_order)
        fills = await broker.drain_fills(broker_order.client_order_id)
        return {"order_state": order_state, "fills": fills}

    def route_after_risk(state: TickState) -> str:
        verdict = state.get("risk_verdict")
        proposed = state.get("proposed_order")
        if verdict is None or not verdict.approved or proposed is None:
            return "skip"
        return "execute"

    g: StateGraph[TickState] = StateGraph(TickState)
    g.add_node("technical", n_technical)
    g.add_node("news", n_news)
    g.add_node("fundamental", n_fundamental)
    g.add_node("manager", n_manager)
    g.add_node("trader", n_trader)
    g.add_node("risk", n_risk)
    g.add_node("execute", n_execute)

    # Fan out from START into the 3 analysts (parallel) → join at manager
    g.set_entry_point("technical")
    g.add_edge("technical", "news")
    g.add_edge("news", "fundamental")
    g.add_edge("fundamental", "manager")
    g.add_edge("manager", "trader")
    g.add_edge("trader", "risk")
    g.add_conditional_edges(
        "risk",
        route_after_risk,
        {"execute": "execute", "skip": END},
    )
    g.add_edge("execute", END)

    return g.compile()


def initial_state_now() -> datetime:
    """Helper: current UTC, factored out for tests that need a deterministic stamp."""
    return datetime.now(UTC)
