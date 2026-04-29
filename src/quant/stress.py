"""Historical stress-testing (Aladdin-inspired).

Replays a portfolio's exposures against a fixed set of crisis scenarios.
Output is a Decimal projected P&L (% of NAV) per scenario. Used by Risk
Manager v2 to flag fragile allocations alongside the daily VaR check.

Each scenario is a per-ticker daily-return path over the crisis window.
On `stress_test_portfolio()`:
    pnl_pct = sum over positions of (position_weight * compounded_return_for_ticker)
where compounded_return = product(1 + r_t for r_t in scenario.returns[ticker]) - 1.

Tickers without scenario data contribute zero (we don't know what they
did during 2008, so we don't punish or reward them — explicit and audit-friendly).

Skeleton scenarios ship with `returns={}` (no historical paths populated yet).
Day-of-walk-forward (Day 14) populates them from MOEX historical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.contracts import Portfolio


@dataclass(frozen=True)
class StressScenario:
    """A historical crisis window expressed as per-ticker daily return paths."""

    name: str
    start: date
    end: date
    description: str
    returns: dict[str, list[Decimal]] = field(default_factory=dict)


SCENARIOS: dict[str, StressScenario] = {
    "crisis_2008": StressScenario(
        name="crisis_2008",
        start=date(2008, 9, 15),  # Lehman collapse
        end=date(2008, 10, 31),
        description="Global financial crisis — Lehman fallout, RTS -70% peak-to-trough",
    ),
    "ruble_2014": StressScenario(
        name="ruble_2014",
        start=date(2014, 12, 1),
        end=date(2014, 12, 19),
        description="Ruble collapse + CBR emergency 17% rate hike (Dec 16, 2014)",
    ),
    "feb_2022": StressScenario(
        name="feb_2022",
        start=date(2022, 2, 21),
        end=date(2022, 2, 25),  # MOEX closed Feb 28 - Mar 23
        description="Geopolitical shock — MOEX -33% on Feb 24, then trading halt",
    ),
    "dec_2024_mini": StressScenario(
        name="dec_2024_mini",
        start=date(2024, 12, 17),
        end=date(2024, 12, 20),
        description="CBR keeps rate at 21% surprise → IMOEX +5% rally (long-tail upside test)",
    ),
}


def stress_test_portfolio(
    portfolio: Portfolio,
    scenario: StressScenario,
) -> Decimal:
    """Project portfolio P&L (fraction of NAV) under a historical scenario.

    Tickers missing from `scenario.returns` contribute zero. NAV ≤ 0 raises
    (we never want a stress test of a degenerate portfolio).
    """
    if portfolio.nav <= 0:
        raise ValueError("portfolio.nav must be positive for stress test")

    total: Decimal = Decimal("0")
    for pos in portfolio.positions:
        path = scenario.returns.get(pos.ticker)
        if not path:
            continue
        weight = pos.market_value / portfolio.nav
        compounded = _compound(path)
        total += weight * compounded
    return total


def _compound(returns: list[Decimal]) -> Decimal:
    """Geometric compounding: product(1 + r) - 1."""
    result = Decimal("1")
    for r in returns:
        result *= Decimal("1") + r
    return result - Decimal("1")
