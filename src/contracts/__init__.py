"""Shared Pydantic contracts between agents, risk manager and execution.

Single source of truth — no duplicated models in submodules.
"""

from src.contracts.risk import (
    MarketState,
    Portfolio,
    Position,
    ProposedOrder,
    RiskLimits,
    RiskVerdict,
    Severity,
    TradingStatus,
)
from src.contracts.trader import TraderDecision

__all__ = [
    "MarketState",
    "Portfolio",
    "Position",
    "ProposedOrder",
    "RiskLimits",
    "RiskVerdict",
    "Severity",
    "TraderDecision",
    "TradingStatus",
]
