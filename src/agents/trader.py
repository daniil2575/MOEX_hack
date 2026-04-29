"""Trader — deterministic v1 bridge from `ManagerPlan` to `TraderDecision`.

Why deterministic instead of LLM-driven: a v1 Trader doing fixed ATR-based
stops costs $0/decision and is fully testable. Once walk-forward shows the
fixed-rule baseline, an LLM Trader (v2) can be A/B'd against it under the
same plan input. Until then there's no reason to spend deep-path tokens
on a step that doesn't add information.

Stop / target derivation:
- stop_loss_pct  = `stop_atr_mult` * atr / current_price
- take_profit_pct = `take_atr_mult` * atr / current_price
- time_stop_bars  = `plan.horizon_days` * `bars_per_day`

`HOLD` and `AVOID` recommendations short-circuit to a HOLD decision with
zero qty (Risk Manager will see qty=0 and approve trivially).

Clamps: stop in [0.005, 0.20], take in [0.005, 1.0], time_stop in [1, 200] —
matches `TraderDecision` validation bounds, so we never construct an invalid
contract regardless of upstream noise.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from src.agents.contracts import ManagerPlan
from src.contracts.trader import TraderDecision

DEFAULT_BARS_PER_DAY = 6  # 1h bars * 6 ≈ trading day
DEFAULT_STOP_ATR_MULT = Decimal("2")
DEFAULT_TAKE_ATR_MULT = Decimal("3")
DEFAULT_FALLBACK_STOP_PCT = Decimal("0.02")  # 2% if ATR is unavailable


class Trader:
    """Translate a ManagerPlan into an executable TraderDecision."""

    name: str = "Trader"

    def __init__(
        self,
        *,
        bars_per_day: int = DEFAULT_BARS_PER_DAY,
        stop_atr_mult: Decimal = DEFAULT_STOP_ATR_MULT,
        take_atr_mult: Decimal = DEFAULT_TAKE_ATR_MULT,
        fallback_stop_pct: Decimal = DEFAULT_FALLBACK_STOP_PCT,
    ) -> None:
        self._bars_per_day = bars_per_day
        self._stop_mult = stop_atr_mult
        self._take_mult = take_atr_mult
        self._fallback_stop = fallback_stop_pct

    def decide(
        self,
        plan: ManagerPlan,
        *,
        current_price: Decimal,
        atr: Decimal | None = None,
    ) -> TraderDecision:
        if current_price <= 0:
            raise ValueError("current_price must be positive")

        if plan.recommendation in ("HOLD", "AVOID"):
            return TraderDecision(
                ticker=plan.ticker,
                action="HOLD",
                qty_pct_nav=Decimal("0"),
                stop_loss_pct=Decimal("0.005"),  # min allowed by contract; HOLD ignores it
                take_profit_pct=None,
                time_stop_bars=max(1, plan.horizon_days * self._bars_per_day),
                confidence=plan.conviction,
                rationale=f"HOLD per Manager: {plan.key_thesis[:200]}",
                urgency="LIMIT",
            )

        action: Literal["BUY", "SELL"] = "BUY" if plan.recommendation == "BUY" else "SELL"

        atr_pct = (atr / current_price) if (atr is not None and atr > 0) else self._fallback_stop
        stop_loss_pct = _clamp(self._stop_mult * atr_pct, lo=Decimal("0.005"), hi=Decimal("0.20"))
        take_profit_pct = _clamp(self._take_mult * atr_pct, lo=Decimal("0.005"), hi=Decimal("1.0"))
        time_stop_bars = max(1, min(200, plan.horizon_days * self._bars_per_day))

        # v1: always LIMIT — keeps slippage bounded and matches MockBrokerGateway
        # zero-slippage path. v2 may upgrade to MARKET when plan.dissent is False
        # and recent volatility is low.
        urgency: Literal["MARKET", "LIMIT"] = "LIMIT"

        return TraderDecision(
            ticker=plan.ticker,
            action=action,
            qty_pct_nav=plan.size_hint_pct_nav,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            time_stop_bars=time_stop_bars,
            confidence=plan.conviction,
            rationale=plan.key_thesis[:2000],
            urgency=urgency,
        )


def _clamp(v: Decimal, *, lo: Decimal, hi: Decimal) -> Decimal:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v
