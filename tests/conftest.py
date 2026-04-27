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


DEFAULT_ADV: Decimal = Decimal("1000000000")  # 1B RUB — generous, all liquidity tests pass by default
DEFAULT_RETURNS_252D: list[Decimal] = [Decimal("0")] * 252  # zero-vol → zero VaR


def _market(
    whitelist: frozenset[str],
    sector_map: dict[str, str],
    status_overrides: dict[str, TradingStatus] | None = None,
    adv_overrides: dict[str, Decimal] | None = None,
    adv_missing: set[str] | None = None,
    returns_overrides: dict[str, list[Decimal]] | None = None,
    returns_missing: set[str] | None = None,
) -> MarketState:
    statuses: dict[str, TradingStatus] = {t: "T" for t in whitelist}
    if status_overrides:
        statuses.update(status_overrides)

    adv: dict[str, Decimal] = {t: DEFAULT_ADV for t in whitelist}
    if adv_overrides:
        adv.update(adv_overrides)
    if adv_missing:
        for t in adv_missing:
            adv.pop(t, None)

    returns: dict[str, list[Decimal]] = {t: list(DEFAULT_RETURNS_252D) for t in whitelist}
    if returns_overrides:
        returns.update(returns_overrides)
    if returns_missing:
        for t in returns_missing:
            returns.pop(t, None)

    return MarketState(
        trading_status=statuses,
        sector_map=sector_map,
        whitelist=whitelist,
        adv=adv,
        returns_252d=returns,
    )


@pytest.fixture
def market_all_trading(whitelist: frozenset[str], sector_map: dict[str, str]) -> MarketState:
    return _market(whitelist, sector_map)


@pytest.fixture
def market_factory(whitelist: frozenset[str], sector_map: dict[str, str]):
    def _factory(
        status_overrides: dict[str, TradingStatus] | None = None,
        *,
        adv_overrides: dict[str, Decimal] | None = None,
        adv_missing: set[str] | None = None,
        returns_overrides: dict[str, list[Decimal]] | None = None,
        returns_missing: set[str] | None = None,
    ) -> MarketState:
        return _market(
            whitelist,
            sector_map,
            status_overrides,
            adv_overrides,
            adv_missing,
            returns_overrides,
            returns_missing,
        )

    return _factory


@pytest.fixture
def returns_with_tail():
    """Generate 252 daily returns with a controlled left tail (for VaR testing).

    Produces returns where the worst 5% (~13 worst days) are at `tail_loss`,
    rest are zero. Historical 1-day 95% VaR = `abs(tail_loss)`.
    """

    def _factory(tail_loss: Decimal) -> list[Decimal]:
        n_tail = 13  # ~5% of 252
        returns = [tail_loss] * n_tail + [Decimal("0")] * (252 - n_tail)
        return returns

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
