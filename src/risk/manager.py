"""Risk Manager — orchestrates rule evaluation in fail-fast order."""

from __future__ import annotations

from src.contracts import (
    MarketState,
    Portfolio,
    ProposedOrder,
    RiskVerdict,
)
from src.risk.rules import RiskRule


class RiskManager:
    """Evaluates a `ProposedOrder` against a list of `RiskRule`s in order.

    Returns the first non-approving verdict, or a synthetic ALL_PASSED verdict
    if every rule approves.
    """

    def __init__(self, rules: list[RiskRule]) -> None:
        self._rules = rules

    def evaluate(
        self,
        order: ProposedOrder,
        portfolio: Portfolio,
        market: MarketState,
    ) -> RiskVerdict:
        for rule in self._rules:
            verdict = rule.check(order, portfolio, market)
            if not verdict.approved:
                return verdict
        return RiskVerdict(
            approved=True,
            rule="ALL_PASSED",
            reason="all rules passed",
            severity="INFO",
        )
