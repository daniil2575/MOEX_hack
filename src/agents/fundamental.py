"""FundamentalAnalyst — ratios in, FundamentalOpinion out.

Inputs are a fully-populated `FundamentalSnapshot` (the data-layer fetch
of P/E, P/B, dividend yield, ROE, etc.). The agent does not call ISS or
Algopack itself — that's the orchestrator's responsibility, so the agent
stays trivially testable with a stubbed snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.agents.contracts import FundamentalOpinion, FundamentalSnapshot
from src.llm.provider import LLMProvider

PROMPT_TEMPLATE = """You are an equity research analyst covering MOEX-listed companies.
Evaluate the fundamental snapshot below and return a single FundamentalOpinion in JSON.

Constraints:
- Output JSON must validate against the FundamentalOpinion schema.
- `agent_name` must be exactly "FundamentalAnalyst".
- `produced_at` should equal the current UTC timestamp passed below.
- `rating` is one of: strong_buy, buy, hold, sell, strong_sell.
- `fair_value` (RUB) is your DCF/multiples-based estimate; null if not estimable.
- `key_strengths` and `key_concerns` are short phrases (max 5 each), grounded in
  the numbers below — do NOT invent metrics that are not provided.
- Compare key ratios against `sector_pe_median` when present.

Snapshot:
- ticker:                {ticker}
- as_of:                 {as_of}
- P/E:                   {pe}
- P/B:                   {pb}
- Dividend yield (%):    {dy}
- ROE (%):               {roe}
- Debt/Equity:           {de}
- Revenue growth YoY (%):{rg}
- Sector P/E median:     {sector_pe}

Current UTC: {now_iso}
"""


class FundamentalAnalyst:
    """Async wrapper around `LLMProvider` producing `FundamentalOpinion`."""

    name: str = "FundamentalAnalyst"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyze(
        self,
        snapshot: FundamentalSnapshot,
        *,
        now: datetime | None = None,
    ) -> FundamentalOpinion:
        prompt = self._build_prompt(snapshot, now or datetime.now(UTC))
        return await self._llm.complete(prompt, response_model=FundamentalOpinion)

    @staticmethod
    def _build_prompt(s: FundamentalSnapshot, now: datetime) -> str:
        return PROMPT_TEMPLATE.format(
            ticker=s.ticker,
            as_of=s.as_of.isoformat(),
            pe=_fmt(s.pe_ratio),
            pb=_fmt(s.pb_ratio),
            dy=_fmt(s.dividend_yield_pct),
            roe=_fmt(s.roe_pct),
            de=_fmt(s.debt_to_equity),
            rg=_fmt(s.revenue_growth_yoy_pct),
            sector_pe=_fmt(s.sector_pe_median),
            now_iso=now.isoformat(),
        )


def _fmt(v: Decimal | None) -> str:
    return "n/a" if v is None else str(v)
