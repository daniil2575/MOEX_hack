"""State carried through the LangGraph DAG.

Each node reads what it needs from the state and writes its own outputs.
Updates are LangGraph-style partial dicts — return only the keys you change.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

import pandas as pd

from src.agents.contracts import (
    FundamentalOpinion,
    FundamentalSnapshot,
    ManagerPlan,
    NewsOpinion,
    TechnicalOpinion,
)
from src.contracts.risk import (
    MarketState,
    Portfolio,
    ProposedOrder,
    RiskVerdict,
)
from src.contracts.trader import TraderDecision
from src.execution.contracts import BrokerFill, OrderState
from src.news.contracts import NewsItem


class TickState(TypedDict, total=False):
    # Inputs (set before invoke)
    ticker: str
    features: pd.DataFrame
    news_items: list[NewsItem]
    fundamental_snapshot: FundamentalSnapshot
    portfolio: Portfolio
    market: MarketState
    current_price: Decimal
    atr: Decimal | None

    # Per-node outputs (filled as the graph runs)
    technical_opinion: TechnicalOpinion
    news_opinion: NewsOpinion
    fundamental_opinion: FundamentalOpinion
    plan: ManagerPlan
    decision: TraderDecision
    proposed_order: ProposedOrder
    risk_verdict: RiskVerdict
    order_state: OrderState
    fills: list[BrokerFill]
