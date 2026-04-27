"""Shared fixtures for risk-rule tests.

Convention: portfolio NAV = 1_000_000 ₽; all percentages expressed as fractions.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.contracts import (
    MarketState,
    Portfolio,
    Position,
    ProposedOrder,
    RiskLimits,
    TradingStatus,
)

NAV: Decimal = Decimal("1000000")


@pytest.fixture
def whitelist() -> frozenset[str]:
    return frozenset({"SBER", "GAZP", "LKOH", "GMKN", "YNDX", "MGNT", "MTSS", "MOEX"})


@pytest.fixture
def sector_map() -> dict[str, str]:
    return {
        "SBER": "Banking",
        "GAZP": "Energy",
        "LKOH": "Energy",
        "GMKN": "Metals",
        "YNDX": "Tech",
        "MGNT": "Retail",
        "MTSS": "Telecom",
        "MOEX": "Financial",
    }


def _market(
    whitelist: frozenset[str],
    sector_map: dict[str, str],
    overrides: dict[str, TradingStatus] | None = None,
) -> MarketState:
    statuses: dict[str, TradingStatus] = {t: "T" for t in whitelist}
    if overrides:
        statuses.update(overrides)
    return MarketState(trading_status=statuses, sector_map=sector_map, whitelist=whitelist)


@pytest.fixture
def market_all_trading(whitelist: frozenset[str], sector_map: dict[str, str]) -> MarketState:
    return _market(whitelist, sector_map)


@pytest.fixture
def market_factory(whitelist: frozenset[str], sector_map: dict[str, str]):
    def _factory(overrides: dict[str, TradingStatus] | None = None) -> MarketState:
        return _market(whitelist, sector_map, overrides)

    return _factory


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits()


@pytest.fixture
def empty_portfolio() -> Portfolio:
    return Portfolio(
        nav=NAV,
        cash=NAV,
        positions=[],
        daily_pnl_pct=Decimal("0"),
        daily_pnl_pct_intraday_peak=Decimal("0"),
        sector_exposures={},
    )


@pytest.fixture
def portfolio_factory():
    def _factory(
        *,
        nav: Decimal = NAV,
        cash: Decimal | None = None,
        positions: list[Position] | None = None,
        daily_pnl_pct: Decimal = Decimal("0"),
        intraday_peak: Decimal = Decimal("0"),
        sector_exposures: dict[str, Decimal] | None = None,
    ) -> Portfolio:
        return Portfolio(
            nav=nav,
            cash=cash if cash is not None else nav,
            positions=positions or [],
            daily_pnl_pct=daily_pnl_pct,
            daily_pnl_pct_intraday_peak=intraday_peak,
            sector_exposures=sector_exposures or {},
        )

    return _factory


@pytest.fixture
def buy_order_factory():
    def _factory(
        ticker: str = "SBER",
        qty_pct_nav: Decimal = Decimal("0.02"),
        urgency: str = "LIMIT",
    ) -> ProposedOrder:
        return ProposedOrder(
            ticker=ticker,
            action="BUY",
            qty_pct_nav=qty_pct_nav,
            urgency=urgency,  # type: ignore[arg-type]
        )

    return _factory


@pytest.fixture
def sell_order_factory():
    def _factory(
        ticker: str = "SBER",
        qty_pct_nav: Decimal = Decimal("0.02"),
        urgency: str = "LIMIT",
    ) -> ProposedOrder:
        return ProposedOrder(
            ticker=ticker,
            action="SELL",
            qty_pct_nav=qty_pct_nav,
            urgency=urgency,  # type: ignore[arg-type]
        )

    return _factory
