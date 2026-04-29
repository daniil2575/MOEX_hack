"""Manager — aggregates the three analyst opinions into a `ManagerPlan`.

Routes to a deep-path LLM (configured by the orchestrator with the
`OPENROUTER_MODEL_DEEP` snapshot — Qwen3-235B-Thinking on the day this
file was written). Higher temperature is fine here: we want the manager
to weigh dissent and surface a thesis, not parrot the analysts.

The 3 inputs share a common base (`_OpinionBase`) so the manager can
treat them uniformly when summarising for the prompt.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.contracts import (
    FundamentalOpinion,
    ManagerPlan,
    NewsOpinion,
    TechnicalOpinion,
)
from src.llm.provider import LLMProvider

DEFAULT_TEMPERATURE = 0.4

PROMPT_TEMPLATE = """You are the portfolio manager. You receive structured opinions from three
specialist analysts and must produce a single ManagerPlan in JSON for the ticker
{ticker} at horizon up to ~30 days.

Inputs (each opinion is already validated structured JSON):

[Technical, agent={tech_agent}, confidence={tech_conf:.2f}]
- regime: {tech_regime}
- horizon_bars: {tech_horizon}
- support: {tech_support}, resistance: {tech_resistance}
- signals: {tech_signals}
- rationale: {tech_rationale}

[News, agent={news_agent}, confidence={news_conf:.2f}]
- overall_sentiment: {news_overall}, urgency: {news_urgency}
- ticker_sentiments (subset for this ticker): {news_ticker_sents}
- key_themes: {news_themes}
- rationale: {news_rationale}

[Fundamental, agent={fund_agent}, confidence={fund_conf:.2f}]
- rating: {fund_rating}, fair_value: {fund_fair_value}
- strengths: {fund_strengths}
- concerns: {fund_concerns}
- rationale: {fund_rationale}

Constraints:
- Output JSON must validate against the ManagerPlan schema.
- `agent_name` must be exactly "Manager".
- `produced_at` should equal {now_iso}.
- `recommendation` is one of: BUY, SELL, HOLD, AVOID.
- `size_hint_pct_nav` is a Decimal in [0, 0.05] (max position-size cap is 5% NAV).
- `conviction` is in [0, 1] and should weight analyst confidences AND their agreement.
- Set `dissent=true` if at least two analysts strongly point in opposing directions.
- `key_thesis` is the narrative — concise, no marketing language.
- `key_risks` is at most 5 short phrases.

Current UTC: {now_iso}
"""


class Manager:
    """Aggregator. The deep-path model is selected via the LLMProvider it gets."""

    name: str = "Manager"

    def __init__(self, llm: LLMProvider, *, temperature: float = DEFAULT_TEMPERATURE) -> None:
        self._llm = llm
        self._temperature = temperature

    async def synthesize(
        self,
        ticker: str,
        technical: TechnicalOpinion,
        news: NewsOpinion,
        fundamental: FundamentalOpinion,
        *,
        now: datetime | None = None,
    ) -> ManagerPlan:
        if technical.ticker != ticker or fundamental.ticker != ticker:
            raise ValueError(
                "ticker mismatch: technical/fundamental opinions must be for the same ticker"
            )
        prompt = self._build_prompt(ticker, technical, news, fundamental, now or datetime.now(UTC))
        return await self._llm.complete(
            prompt, response_model=ManagerPlan, temperature=self._temperature
        )

    @staticmethod
    def _build_prompt(
        ticker: str,
        tech: TechnicalOpinion,
        news: NewsOpinion,
        fund: FundamentalOpinion,
        now: datetime,
    ) -> str:
        ticker_sents = [
            f"{ts.ticker}={ts.sentiment}/{ts.impact}"
            for ts in news.ticker_sentiments
            if ts.ticker == ticker
        ]
        return PROMPT_TEMPLATE.format(
            ticker=ticker,
            tech_agent=tech.agent_name,
            tech_conf=tech.confidence,
            tech_regime=tech.regime,
            tech_horizon=tech.horizon_bars,
            tech_support=tech.support if tech.support is not None else "n/a",
            tech_resistance=tech.resistance if tech.resistance is not None else "n/a",
            tech_signals=tech.signals,
            tech_rationale=tech.rationale,
            news_agent=news.agent_name,
            news_conf=news.confidence,
            news_overall=news.overall_sentiment,
            news_urgency=news.urgency,
            news_ticker_sents=ticker_sents or ["(none specific to this ticker)"],
            news_themes=news.key_themes,
            news_rationale=news.rationale,
            fund_agent=fund.agent_name,
            fund_conf=fund.confidence,
            fund_rating=fund.rating,
            fund_fair_value=fund.fair_value if fund.fair_value is not None else "n/a",
            fund_strengths=fund.key_strengths,
            fund_concerns=fund.key_concerns,
            fund_rationale=fund.rationale,
            now_iso=now.isoformat(),
        )
