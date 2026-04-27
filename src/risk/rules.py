"""Risk Manager rules — TDD red-phase stubs.

All rules currently return APPROVE (no-op). Tests in `tests/test_risk_rules.py`
are intentionally red until `feat(risk): implement risk manager v1` lands.

Rule order (fail-fast, cheapest first):
    1. WhitelistRule
    2. TradingStatusRule
    3. PositionSizeRule
    4. SectorExposureRule
    5. GrossExposureRule
    6. DrawdownKillSwitchRule
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.contracts import (
    MarketState,
    Portfolio,
    ProposedOrder,
    RiskLimits,
    RiskVerdict,
)


class RiskRule(ABC):
    name: str

    @abstractmethod
    def check(
        self,
        order: ProposedOrder,
        portfolio: Portfolio,
        market: MarketState,
    ) -> RiskVerdict: ...


def _approve(rule: str) -> RiskVerdict:
    return RiskVerdict(approved=True, rule=rule, reason="stub: not implemented", severity="INFO")


class WhitelistRule(RiskRule):
    name = "WhitelistRule"

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


class TradingStatusRule(RiskRule):
    name = "TradingStatusRule"

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


class PositionSizeRule(RiskRule):
    name = "PositionSizeRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


class SectorExposureRule(RiskRule):
    name = "SectorExposureRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


class GrossExposureRule(RiskRule):
    name = "GrossExposureRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


class DrawdownKillSwitchRule(RiskRule):
    """Two-tier DD: WARN at -3% (blocks BUY, allows SELL), HALT at -5% (blocks all).

    DD measured from intraday peak (high-water-mark) via
    `portfolio.daily_pnl_pct - portfolio.daily_pnl_pct_intraday_peak`.
    """

    name = "DrawdownKillSwitchRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


def default_rules(limits: RiskLimits) -> list[RiskRule]:
    """Canonical rule order (fail-fast)."""
    return [
        WhitelistRule(),
        TradingStatusRule(),
        PositionSizeRule(limits),
        SectorExposureRule(limits),
        GrossExposureRule(limits),
        DrawdownKillSwitchRule(limits),
    ]
