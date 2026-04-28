"""TechnicalAnalyst — turns OHLCV + indicator frame into a `TechnicalOpinion`.

The agent itself is thin: it (1) summarizes the recent state of the
indicators into a compact text snapshot the LLM can reason over, (2)
issues a single `LLMProvider.complete()` call asking for a TechnicalOpinion.

Why pre-summarize: dumping 26000 bars across 5 columns into a prompt is
wasteful and noisy. The summary keeps the latest N bars verbatim plus
the trend of each indicator over a longer window, which is what an
analyst would actually look at.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.agents.contracts import TechnicalOpinion
from src.llm.provider import LLMProvider

DEFAULT_TAIL_BARS = 30
DEFAULT_HORIZON_BARS = 60

PROMPT_TEMPLATE = """You are a senior technical analyst on the Moscow Exchange (MOEX).
Analyze the following indicator snapshot for {ticker} and return a single
TechnicalOpinion in JSON. Be direct and quantitative — no marketing language.

Constraints:
- Output JSON must validate against the TechnicalOpinion schema.
- `regime` is your assessment of the next {horizon} bars.
- `signals` is a short list of named patterns/triggers you actually observe.
  Examples: "rsi_oversold_divergence", "macd_bullish_cross", "atr_expansion".
- `support`/`resistance` are price levels in RUB (Decimal). If unsure, leave null.
- `agent_name` must be exactly "TechnicalAnalyst".
- `produced_at` should be the current UTC timestamp passed below.

Snapshot (most recent {tail} bars):
{tail_table}

Indicator trend over the last {tail} bars:
- close: first={first_close}, last={last_close}, pct_change={pct_change:.4f}
- rsi: first={first_rsi}, last={last_rsi}
- macd_hist: first={first_macd_hist}, last={last_macd_hist}
- atr: first={first_atr}, last={last_atr}

Current UTC: {now_iso}
"""


class TechnicalAnalyst:
    """Async wrapper around `LLMProvider` producing `TechnicalOpinion`."""

    name: str = "TechnicalAnalyst"

    def __init__(
        self,
        llm: LLMProvider,
        *,
        tail_bars: int = DEFAULT_TAIL_BARS,
        horizon_bars: int = DEFAULT_HORIZON_BARS,
    ) -> None:
        self._llm = llm
        self._tail_bars = tail_bars
        self._horizon_bars = horizon_bars

    async def analyze(
        self,
        ticker: str,
        features: pd.DataFrame,
        *,
        now: datetime | None = None,
    ) -> TechnicalOpinion:
        if features.empty:
            raise ValueError("features frame is empty")
        prompt = self._build_prompt(ticker, features, now=now or datetime.now(UTC))
        return await self._llm.complete(prompt, response_model=TechnicalOpinion)

    def _build_prompt(self, ticker: str, features: pd.DataFrame, *, now: datetime) -> str:
        tail = features.tail(self._tail_bars)
        if tail.empty:
            raise ValueError("tail is empty after .tail() — check tail_bars vs frame length")

        cols = [c for c in ("close", "rsi", "macd_hist", "atr") if c in tail.columns]
        tail_table = tail[cols].round(4).to_string()

        first = tail.iloc[0]
        last = tail.iloc[-1]
        pct_change = float((last["close"] - first["close"]) / first["close"]) if "close" in tail.columns else 0.0

        return PROMPT_TEMPLATE.format(
            ticker=ticker,
            horizon=self._horizon_bars,
            tail=len(tail),
            tail_table=tail_table,
            first_close=_fmt(first.get("close")),
            last_close=_fmt(last.get("close")),
            pct_change=pct_change,
            first_rsi=_fmt(first.get("rsi")),
            last_rsi=_fmt(last.get("rsi")),
            first_macd_hist=_fmt(first.get("macd_hist")),
            last_macd_hist=_fmt(last.get("macd_hist")),
            first_atr=_fmt(first.get("atr")),
            last_atr=_fmt(last.get("atr")),
            now_iso=now.isoformat(),
        )


def _fmt(v: object) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.4f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(v)
