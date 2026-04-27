"""Risk Manager rules — TDD red-phase stubs.

All rules currently return APPROVE (no-op). Tests in `tests/test_risk_rules.py`
are intentionally red until `feat(risk): implement risk manager v1` lands.

Rule order (fail-fast, cheapest first; LiquidityRule and VaRRule are
Aladdin-inspired additions for slippage and correlation-risk control):
    1. WhitelistRule          — set lookup
    2. TradingStatusRule      — dict lookup
    3. PositionSizeRule       — single compare
    4. LiquidityRule          — order_value / ADV ≤ 5%
    5. SectorExposureRule     — sector aggregation
    6. GrossExposureRule      — sum of |positions|
    7. DrawdownKillSwitchRule — DD-from-peak two-tier
    8. VaRRule                — historical VaR on simulated post-trade portfolio
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


class LiquidityRule(RiskRule):
    """Order value as fraction of average daily volume must be ≤ `max_order_pct_adv`.

    Missing ADV in `MarketState.adv` for the ticker → reject (cannot price slippage).
    """

    name = "LiquidityRule"

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


class VaRRule(RiskRule):
    """Historical Value-at-Risk on the simulated post-trade portfolio.

    Computes 1-day (1 - alpha) VaR from `MarketState.returns_252d` weighted by
    the post-trade portfolio composition. Rejects if VaR > `max_var_pct_nav`.

    Missing returns history → reject (cannot estimate risk).
    """

    name = "VaRRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        return _approve(self.name)


def default_rules(limits: RiskLimits) -> list[RiskRule]:
    """Canonical rule order (fail-fast, cheapest first; VaR last as it's most expensive)."""
    return [
        WhitelistRule(),
        TradingStatusRule(),
        PositionSizeRule(limits),
        LiquidityRule(limits),
        SectorExposureRule(limits),
        GrossExposureRule(limits),
        DrawdownKillSwitchRule(limits),
        VaRRule(limits),
    ]
