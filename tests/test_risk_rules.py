"""Risk Manager rule tests — TDD red phase.

Stubs in `src/risk/rules.py` currently return APPROVE for all inputs, so every
test below that asserts a *rejection* will fail. This is intentional and gates
the green-phase implementation per `sprints/sprint_1_prep/solo_plan.md`.

Coverage: 8 rules (Whitelist, TradingStatus, PositionSize, Liquidity,
SectorExposure, GrossExposure, DrawdownKillSwitch, VaR) + RiskManager
integration + RiskVerdict semantics.
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
    LiquidityRule,
    PositionSizeRule,
    RiskManager,
    SectorExposureRule,
    TradingStatusRule,
    VaRRule,
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


# ────────────────────────────── LiquidityRule ──────────────────────────────


class TestLiquidityRule:
    """order_value / ADV ≤ max_order_pct_adv (default 5%).

    NAV=1_000_000, default ADV=1_000_000_000 → 5% of ADV = 50_000_000 ₽.
    A 5% NAV order = 50_000 ₽ → 0.005% of ADV → trivially under cap.
    To stress the rule we shrink ADV per ticker.
    """

    def test_within_limit_approved(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        # 2% NAV = 20_000 ₽; ADV=1_000_000 → 2% of ADV (≤5%)
        market = market_factory(adv_overrides={"SBER": Decimal("1000000")})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.02"))
        verdict = LiquidityRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is True

    def test_at_limit_approved(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        # 5% NAV = 50_000 ₽; ADV=1_000_000 → exactly 5% of ADV
        market = market_factory(adv_overrides={"SBER": Decimal("1000000")})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = LiquidityRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is True

    def test_over_limit_rejected(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        # 5% NAV = 50_000 ₽; ADV=500_000 → 10% of ADV > 5% cap
        market = market_factory(adv_overrides={"SBER": Decimal("500000")})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = LiquidityRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"
        assert "adv" in verdict.reason.lower() or "liquidity" in verdict.reason.lower()

    def test_missing_adv_rejected(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        market = market_factory(adv_missing={"SBER"})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.02"))
        verdict = LiquidityRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is False, "missing ADV → cannot price slippage → reject"
        assert verdict.severity == "BLOCK"


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


# ────────────────────────────── VaRRule ──────────────────────────────


class TestVaRRule:
    """Historical 1-day 95% VaR on the simulated post-trade portfolio.

    With `returns_with_tail(tail_loss)`, historical 95% VaR for a single
    fully-allocated ticker equals |tail_loss|. We size the position so the
    weighted post-trade VaR straddles `max_var_pct_nav` (default 2%).
    """

    def test_under_limit_approved(
        self,
        limits,
        market_factory,
        empty_portfolio,
        buy_order_factory,
        returns_with_tail,
    ):
        # 5% position × 20% tail loss → contributes 1% VaR (< 2% cap)
        market = market_factory(
            returns_overrides={"SBER": returns_with_tail(Decimal("-0.20"))}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = VaRRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is True

    def test_at_limit_approved(
        self,
        limits,
        market_factory,
        empty_portfolio,
        buy_order_factory,
        returns_with_tail,
    ):
        # 5% position × 40% tail loss → contributes 2% VaR (= 2% cap)
        market = market_factory(
            returns_overrides={"SBER": returns_with_tail(Decimal("-0.40"))}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = VaRRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is True

    def test_over_limit_rejected(
        self,
        limits,
        market_factory,
        empty_portfolio,
        buy_order_factory,
        returns_with_tail,
    ):
        # 5% position × 50% tail loss → contributes 2.5% VaR (> 2% cap)
        market = market_factory(
            returns_overrides={"SBER": returns_with_tail(Decimal("-0.50"))}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        verdict = VaRRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is False
        assert verdict.severity == "BLOCK"
        assert "var" in verdict.reason.lower()

    def test_missing_returns_rejected(
        self, limits, market_factory, empty_portfolio, buy_order_factory
    ):
        market = market_factory(returns_missing={"SBER"})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.02"))
        verdict = VaRRule(limits).check(order, empty_portfolio, market)
        assert verdict.approved is False, "missing returns → cannot estimate VaR → reject"
        assert verdict.severity == "BLOCK"

    def test_post_trade_simulation_includes_new_order(
        self,
        limits,
        market_factory,
        portfolio_factory,
        buy_order_factory,
        returns_with_tail,
    ):
        """VaR is measured on PRE+POST composition, not the existing portfolio alone.

        Existing portfolio has zero-vol exposure (no VaR). The new order
        targets a high-tail-loss ticker; if the rule used the pre-trade
        portfolio it would approve. It must reject.
        """
        existing = [
            Position(
                ticker="MOEX",  # zero-vol from default returns
                qty=Decimal("1000"),
                avg_price=Decimal("100"),
                market_value=Decimal("100000"),
            )
        ]
        portfolio = portfolio_factory(positions=existing, cash=Decimal("900000"))
        market = market_factory(
            returns_overrides={"GAZP": returns_with_tail(Decimal("-0.50"))}
        )
        order = buy_order_factory(ticker="GAZP", qty_pct_nav=Decimal("0.05"))
        verdict = VaRRule(limits).check(order, portfolio, market)
        assert verdict.approved is False, "post-trade VaR must include the new order"


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
        # Position-size (#3) must fire before Sector (#5)
        portfolio = portfolio_factory(
            sector_exposures={"Banking": Decimal("0.50")}  # already over sector cap
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.10"))  # also over pos cap
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, portfolio, market_all_trading)
        assert verdict.approved is False
        assert verdict.rule == "PositionSizeRule", (
            f"PositionSize (rule #3) must fire before Sector (rule #5); got {verdict.rule}"
        )

    def test_liquidity_fires_before_sector(
        self, limits, market_factory, portfolio_factory, buy_order_factory
    ):
        # Liquidity (#4) must fire before Sector (#5)
        portfolio = portfolio_factory(
            sector_exposures={"Banking": Decimal("0.50")}  # already over sector cap
        )
        # 5% NAV = 50_000 ₽; ADV=100_000 → 50% of ADV ≫ 5% cap
        market = market_factory(adv_overrides={"SBER": Decimal("100000")})
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, portfolio, market)
        assert verdict.approved is False
        assert verdict.rule == "LiquidityRule", (
            f"Liquidity (rule #4) must fire before Sector (rule #5); got {verdict.rule}"
        )

    def test_var_runs_last(
        self,
        limits,
        market_factory,
        empty_portfolio,
        buy_order_factory,
        returns_with_tail,
    ):
        # All cheap rules pass; only VaR rejects → confirms VaR is reachable as #8.
        market = market_factory(
            returns_overrides={"SBER": returns_with_tail(Decimal("-0.50"))}
        )
        order = buy_order_factory(ticker="SBER", qty_pct_nav=Decimal("0.05"))
        manager = RiskManager(default_rules(limits))
        verdict = manager.evaluate(order, empty_portfolio, market)
        assert verdict.approved is False
        assert verdict.rule == "VaRRule", (
            f"VaR (rule #8) is the only block here; got {verdict.rule}"
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
