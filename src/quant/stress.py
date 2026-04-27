"""Historical stress-testing scaffolding (Aladdin-inspired).

Replays a portfolio's exposures against a fixed set of crisis scenarios. Output
is a dict of `scenario_name -> projected_pnl_pct`. Used to flag fragile
allocations before the Risk Manager's daily VaR check kicks in.

Scenarios are defined as per-ticker daily-return paths over the crisis window.
The skeleton ships with empty paths — populated from MOEX historical data on
Day 5+ via `data/loaders` (out of scope for the red phase).

NOTE: All four scenarios are intentionally stubbed (`returns={}`,
`stress_test_portfolio` raises NotImplementedError). Green-phase work fills in
the historical paths and the projection math.
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
    """Project portfolio P&L (% NAV) under a historical scenario.

    Returns the cumulative P&L over the scenario window, computed as the
    weighted sum of per-ticker compounded returns × position weight.

    Raises:
        NotImplementedError: green-phase work — see Day 6 of solo_plan.md.
    """
    raise NotImplementedError("stress_test_portfolio is a red-phase stub")
