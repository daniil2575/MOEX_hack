"""Risk Manager rule tests — TDD red phase.

Stubs in `src/risk/rules.py` currently return APPROVE for all inputs, so every
test below that asserts a *rejection* will fail. This is intentional and gates
Day 5 (zelёные tests + sectors.py) per `sprints/sprint_1_prep/solo_plan.md`.

Coverage: 24 tests across 6 rules + 3 RiskManager integration tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.contracts import (
    MarketState,
    Portfolio,
    Position,
    RiskLimits,
    RiskVerdict,
)
from src.risk import (
    DrawdownKillSwitchRule,
    GrossExposureRule,
    PositionSizeRule,
    RiskManager,
    SectorExposureRule,
    TradingStatusRule,
    WhitelistRule,
    default_rules,
)


# ────────────────────────────── WhitelistRule ──────────────────────────────


class TestWhitelistRule:
    def test_allows_listed_ticker(self, market_all_trading, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="SBER")
        verdict = WhitelistRule().check(order, empty_portfolio, market_all_trading)
        assert verdict.approved is True
        assert verdict.rule == "WhitelistRule"

    def test_rejects_unlisted_ticker(self, market_all_trading, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="UNKNOWN")
        verdict = WhitelistRule().check(order, empty_portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.rule == "WhitelistRule"
        assert verdict.severity == "BLOCK"
        assert "UNKNOWN" in verdict.reason


# ────────────────────────────── TradingStatusRule ──────────────────────────────


class TestTradingStatusRule:
    def test_T_allows_market(self, market_factory, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="SBER", urgency="MARKET")
        verdict = TradingStatusRule().check(order, empty_portfolio, market_factory())
        assert verdict.approved is True

    def test_T_allows_limit(self, market_factory, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="SBER", urgency="LIMIT")
        verdict = TradingStatusRule().check(order, empty_portfolio, market_factory())
        assert verdict.approved is True

    def test_DA_rejects_market(self, market_factory, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="SBER", urgency="MARKET")
        market = market_factory({"SBER": "DA"})
        verdict = TradingStatusRule().check(order, empty_portfolio, market)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"
        assert "DA" in verdict.reason

    def test_DA_allows_limit(self, market_factory, empty_portfolio, buy_order_factory):
        order = buy_order_factory(ticker="SBER", urgency="LIMIT")
        market = market_factory({"SBER": "DA"})
        verdict = TradingStatusRule().check(order, empty_portfolio, market)
        assert verdict.approved is True

    def test_H_rejects_all(self, market_factory, empty_portfolio, buy_order_factory):
        for urgency in ("MARKET", "LIMIT"):
            order = buy_order_factory(ticker="SBER", urgency=urgency)
            market = market_factory({"SBER": "H"})
            verdict = TradingStatusRule().check(order, empty_portfolio, market)
            assert verdict.approved is False, f"H should reject urgency={urgency}"
            assert verdict.severity == "BLOCK"

    def test_U_rejects_all(self, market_factory, empty_portfolio, buy_order_factory):
        for urgency in ("MARKET", "LIMIT"):
            order = buy_order_factory(ticker="SBER", urgency=urgency)
            market = market_factory({"SBER": "U"})
            verdict = TradingStatusRule().check(order, empty_portfolio, market)
            assert verdict.approved is False, f"U should reject urgency={urgency}"
            assert verdict.severity == "BLOCK"


# ────────────────────────────── PositionSizeRule ──────────────────────────────


class TestPositionSizeRule:
    def test_within_limit_approved(
        self, limits, market_all_trading, empty_portfolio, buy_order_factory
    ):
        order = buy_order_factory(qty_pct_nav=Decimal("0.03"))  # 3%, limit 5%
        verdict = PositionSizeRule(limits).check(order, empty_portfolio, market_all_trading)
        assert verdict.approved is True

    def test_at_limit_approved(
        self, limits, market_all_trading, empty_portfolio, buy_order_factory
    ):
        order = buy_order_factory(qty_pct_nav=Decimal("0.05"))  # exactly 5%
        verdict = PositionSizeRule(limits).check(order, empty_portfolio, market_all_trading)
        assert verdict.approved is True

    def test_exceeds_limit_rejected(
        self, limits, market_all_trading, empty_portfolio, buy_order_factory
    ):
        order = buy_order_factory(qty_pct_nav=Decimal("0.07"))  # 7%, limit 5%
        verdict = PositionSizeRule(limits).check(order, empty_portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"
        assert "5" in verdict.reason or "0.05" in verdict.reason


# ────────────────────────────── SectorExposureRule ──────────────────────────────


class TestSectorExposureRule:
    def test_under_limit_approved(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        portfolio = portfolio_factory(
            sector_exposures={"Banking": Decimal("0.20")}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = SectorExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is True

    def test_at_limit_approved(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        portfolio = portfolio_factory(
            sector_exposures={"Banking": Decimal("0.25")}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))  # 25% + 5% = 30%
        verdict = SectorExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is True

    def test_over_limit_rejected(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        portfolio = portfolio_factory(
            sector_exposures={"Energy": Decimal("0.28")}
        )
        order = buy_order_factory(ticker="GAZP", qty_pct_nav=Decimal("0.05"))  # 28% + 5% = 33% > 30%
        verdict = SectorExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"
        assert "Energy" in verdict.reason


# ────────────────────────────── GrossExposureRule ──────────────────────────────


class TestGrossExposureRule:
    @staticmethod
    def _gross(positions: list[Position], nav: Decimal) -> dict:
        return {"positions": positions}

    def test_under_limit_approved(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        positions = [
            Position(
                ticker="SBER",
                qty=Decimal("100"),
                avg_price=Decimal("300"),
                market_value=Decimal("500000"),
            )
        ]
        portfolio = portfolio_factory(positions=positions)
        order = buy_order_factory(ticker="GAZP", qty_pct_nav=Decimal("0.05"))
        verdict = GrossExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is True

    def test_at_limit_approved(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        positions = [
            Position(
                ticker="SBER",
                qty=Decimal("3000"),
                avg_price=Decimal("300"),
                market_value=Decimal("950000"),
            )
        ]
        portfolio = portfolio_factory(positions=positions)
        order = buy_order_factory(ticker="GAZP", qty_pct_nav=Decimal("0.05"))  # 95% + 5% = 100%
        verdict = GrossExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is True

    def test_over_limit_rejected(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        positions = [
            Position(
                ticker="SBER",
                qty=Decimal("3000"),
                avg_price=Decimal("330"),
                market_value=Decimal("980000"),
            )
        ]
        portfolio = portfolio_factory(positions=positions)
        order = buy_order_factory(ticker="GAZP", qty_pct_nav=Decimal("0.05"))  # 98% + 5% = 103%
        verdict = GrossExposureRule(limits).check(order, portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"


# ────────────────────────────── DrawdownKillSwitchRule ──────────────────────────────


class TestDrawdownKillSwitchRule:
    def test_no_loss_approved(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        portfolio = portfolio_factory(daily_pnl_pct=Decimal("0.01"), intraday_peak=Decimal("0.01"))
        verdict = DrawdownKillSwitchRule(limits).check(
            buy_order_factory(), portfolio, market_all_trading
        )
        assert verdict.approved is True

    def test_warning_threshold_blocks_buy(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        # peak +2%, current -1.5% → DD from peak = -3.5% (between WARN and HALT)
        portfolio = portfolio_factory(
            daily_pnl_pct=Decimal("-0.015"),
            intraday_peak=Decimal("0.02"),
        )
        verdict = DrawdownKillSwitchRule(limits).check(
            buy_order_factory(), portfolio, market_all_trading
        )
        assert verdict.approved is False
        assert verdict.severity == "WARN"
        assert "drawdown" in verdict.reason.lower() or "dd" in verdict.reason.lower()

    def test_warning_threshold_allows_sell_for_derisking(
        self, limits, market_all_trading, portfolio_factory, sell_order_factory
    ):
        portfolio = portfolio_factory(
            daily_pnl_pct=Decimal("-0.015"),
            intraday_peak=Decimal("0.02"),
        )
        verdict = DrawdownKillSwitchRule(limits).check(
            sell_order_factory(), portfolio, market_all_trading
        )
        assert verdict.approved is True, "SELL must be allowed in WARN tier (de-risking)"

    def test_halt_threshold_blocks_buy(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        portfolio = portfolio_factory(
            daily_pnl_pct=Decimal("-0.06"),
            intraday_peak=Decimal("0"),
        )
        verdict = DrawdownKillSwitchRule(limits).check(
            buy_order_factory(), portfolio, market_all_trading
        )
        assert verdict.approved is False
        assert verdict.severity == "HALT"

    def test_halt_threshold_blocks_sell(
        self, limits, market_all_trading, portfolio_factory, sell_order_factory
    ):
        portfolio = portfolio_factory(
            daily_pnl_pct=Decimal("-0.06"),
            intraday_peak=Decimal("0"),
        )
        verdict = DrawdownKillSwitchRule(limits).check(
            sell_order_factory(), portfolio, market_all_trading
        )
        assert verdict.approved is False, "HALT blocks ALL orders, including SELL"
        assert verdict.severity == "HALT"


# ────────────────────────────── RiskManager integration ──────────────────────────────


class TestRiskManagerIntegration:
    def test_returns_first_block_in_fail_fast_order(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        # Unlisted + halted: WhitelistRule must fire first, not TradingStatusRule
        order = buy_order_factory(ticker="UNKNOWN", urgency="MARKET")
        market = market_factory({"UNKNOWN": "H"})  # type: ignore[dict-item]
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, empty_portfolio, market)
        assert verdict.approved is False
        assert verdict.rule == "WhitelistRule", "fail-fast: Whitelist must fire before TradingStatus"

    def test_runs_all_rules_when_approved(
        self, limits, market_all_trading, empty_portfolio, buy_order_factory
    ):
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.02"))
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, empty_portfolio, market_all_trading)
        assert verdict.approved is True
        assert verdict.rule == "ALL_PASSED"

    def test_short_circuits_on_first_block(
        self, limits, market_all_trading, portfolio_factory, buy_order_factory
    ):
        # Position-size violation must fire before sector check (rule #3 < rule #4)
        portfolio = portfolio_factory(
            sector_exposures={"Banking": Decimal("0.50")}  # already over sector cap
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.10"))  # also over pos cap
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.rule == "PositionSizeRule", (
            f"PositionSize (rule #3) must fire before Sector (rule #4); got {verdict.rule}"
        )


# ────────────────────────────── RiskVerdict semantics ──────────────────────────────


class TestRiskVerdictModel:
    def test_verdict_is_immutable(self):
        v = RiskVerdict(approved=True, rule="X", reason="ok", severity="INFO")
        with pytest.raises(Exception):  # Pydantic ValidationError on frozen
            v.approved = False  # type: ignore[misc]

    def test_verdict_rejects_unknown_severity(self):
        with pytest.raises(Exception):
            RiskVerdict(
                approved=False,
                rule="X",
                reason="bad",
                severity="WAT",  # type: ignore[arg-type]
            )
