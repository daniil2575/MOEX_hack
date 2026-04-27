"""Risk Manager rules — green phase.

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
from decimal import Decimal

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


def _approve(rule: str, reason: str = "ok") -> RiskVerdict:
    return RiskVerdict(approved=True, rule=rule, reason=reason, severity="INFO")


class WhitelistRule(RiskRule):
    name = "WhitelistRule"

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        if order.ticker not in market.whitelist:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"ticker {order.ticker} not in whitelist",
                severity="BLOCK",
            )
        return _approve(self.name)


class TradingStatusRule(RiskRule):
    """T allows everything; DA allows LIMIT only; H/U block all."""

    name = "TradingStatusRule"

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        status = market.trading_status.get(order.ticker)
        if status is None:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"no trading status for {order.ticker}",
                severity="BLOCK",
            )
        if status == "T":
            return _approve(self.name)
        if status == "DA" and order.urgency == "LIMIT":
            return _approve(self.name)
        return RiskVerdict(
            approved=False,
            rule=self.name,
            reason=f"trading status {status} blocks {order.urgency} on {order.ticker}",
            severity="BLOCK",
        )


class PositionSizeRule(RiskRule):
    name = "PositionSizeRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        if order.qty_pct_nav > self._limits.max_position_pct_nav:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"order size {order.qty_pct_nav} exceeds max_position_pct_nav "
                    f"{self._limits.max_position_pct_nav}"
                ),
                severity="BLOCK",
            )
        return _approve(self.name)


class LiquidityRule(RiskRule):
    """Order value as fraction of average daily volume must be ≤ `max_order_pct_adv`.

    Missing ADV in `MarketState.adv` for the ticker → reject (cannot price slippage).
    """

    name = "LiquidityRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        adv = market.adv.get(order.ticker)
        if adv is None:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"no ADV/liquidity data for {order.ticker}",
                severity="BLOCK",
            )
        if adv <= 0:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"non-positive ADV for {order.ticker}",
                severity="BLOCK",
            )
        order_value = order.qty_pct_nav * portfolio.nav
        adv_pct = order_value / adv
        if adv_pct > self._limits.max_order_pct_adv:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"order is {adv_pct:.4f} of ADV, exceeds liquidity cap "
                    f"{self._limits.max_order_pct_adv}"
                ),
                severity="BLOCK",
            )
        return _approve(self.name)


class SectorExposureRule(RiskRule):
    """Post-trade sector exposure must stay within `max_sector_pct_nav`.

    SELL reduces exposure → always approve at this rule (de-risking).
    """

    name = "SectorExposureRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        if order.action == "SELL":
            return _approve(self.name)
        sector = market.sector_map.get(order.ticker)
        if sector is None:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"no sector mapping for {order.ticker}",
                severity="BLOCK",
            )
        current = portfolio.sector_exposures.get(sector, Decimal("0"))
        post_trade = current + order.qty_pct_nav
        if post_trade > self._limits.max_sector_pct_nav:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"sector {sector} exposure {post_trade} would exceed cap "
                    f"{self._limits.max_sector_pct_nav}"
                ),
                severity="BLOCK",
            )
        return _approve(self.name)


class GrossExposureRule(RiskRule):
    """Sum of |position market values| / NAV + new order ≤ `max_gross_pct_nav`.

    SELL is treated as de-risking → approve.
    """

    name = "GrossExposureRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        if order.action == "SELL":
            return _approve(self.name)
        gross_value = sum(
            (abs(p.market_value) for p in portfolio.positions),
            start=Decimal("0"),
        )
        gross_pct = gross_value / portfolio.nav
        post_trade = gross_pct + order.qty_pct_nav
        if post_trade > self._limits.max_gross_pct_nav:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"gross exposure {post_trade} would exceed cap "
                    f"{self._limits.max_gross_pct_nav}"
                ),
                severity="BLOCK",
            )
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
        dd = portfolio.daily_pnl_pct - portfolio.daily_pnl_pct_intraday_peak
        if dd <= self._limits.dd_halt_pct:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=f"drawdown from peak {dd} hit HALT threshold {self._limits.dd_halt_pct}",
                severity="HALT",
            )
        if dd <= self._limits.dd_warning_pct:
            if order.action == "SELL":
                return _approve(self.name, reason="WARN tier — SELL allowed for de-risking")
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"drawdown from peak {dd} hit WARN threshold "
                    f"{self._limits.dd_warning_pct}; BUY blocked"
                ),
                severity="WARN",
            )
        return _approve(self.name)


class VaRRule(RiskRule):
    """Historical Value-at-Risk on the simulated post-trade portfolio.

    Computes 1-day (1 - alpha) VaR from `MarketState.returns_252d` weighted by
    the post-trade portfolio composition. Rejects if VaR > `max_var_pct_nav`.

    Missing returns history → reject (cannot estimate risk).
    SELL is treated as de-risking → approve without computation.
    """

    name = "VaRRule"

    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def check(self, order: ProposedOrder, portfolio: Portfolio, market: MarketState) -> RiskVerdict:
        if order.action == "SELL":
            return _approve(self.name)

        # Build post-trade weights for risky positions (cash contributes zero return).
        weights: dict[str, Decimal] = {}
        for pos in portfolio.positions:
            w = pos.market_value / portfolio.nav
            weights[pos.ticker] = weights.get(pos.ticker, Decimal("0")) + w
        weights[order.ticker] = weights.get(order.ticker, Decimal("0")) + order.qty_pct_nav

        # Reject if any held/traded ticker lacks returns history.
        for ticker in weights:
            if ticker not in market.returns_252d:
                return RiskVerdict(
                    approved=False,
                    rule=self.name,
                    reason=f"no returns history for {ticker}; cannot compute VaR",
                    severity="BLOCK",
                )

        n = min(len(market.returns_252d[t]) for t in weights)
        if n == 0:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason="empty returns history; cannot compute VaR",
                severity="BLOCK",
            )

        # Weighted daily portfolio returns over the common window.
        weighted: list[Decimal] = []
        for i in range(n):
            day_return = sum(
                (weights[t] * market.returns_252d[t][i] for t in weights),
                start=Decimal("0"),
            )
            weighted.append(day_return)

        # Historical alpha-quantile (lower-tail), conservative floor index.
        weighted.sort()
        idx = int(self._limits.var_alpha * Decimal(n))
        if idx >= n:
            idx = n - 1
        var = abs(weighted[idx])

        if var > self._limits.max_var_pct_nav:
            return RiskVerdict(
                approved=False,
                rule=self.name,
                reason=(
                    f"post-trade VaR {var} exceeds cap {self._limits.max_var_pct_nav}"
                ),
                severity="BLOCK",
            )
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
