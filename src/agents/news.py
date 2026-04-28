"""NewsAnalyst — distills a batch of news items into a `NewsOpinion`.

The agent receives `NewsItem`s (from `src.news.parser`) and a whitelist of
tickers we actually trade. We:
1. Sort items by `posted_at` desc and trim to the most recent `max_items`.
2. Render them as a numbered list with channel + timestamp + text.
3. Send to LLM with explicit per-ticker sentiment instructions, gated on
   the trading whitelist (no opinions on tickers we can't act on).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.contracts import NewsOpinion
from src.llm.provider import LLMProvider
from src.news.contracts import NewsItem

DEFAULT_MAX_ITEMS = 30

PROMPT_TEMPLATE = """You are a financial news analyst covering the Moscow Exchange (MOEX).
Read the news batch below and return a single NewsOpinion in JSON.

Constraints:
- Output JSON must validate against the NewsOpinion schema.
- `agent_name` must be exactly "NewsAnalyst".
- `produced_at` should match the current UTC timestamp passed below.
- `ticker_sentiments` may include only tickers from this trading whitelist:
  {whitelist}.
  Do NOT invent tickers or opinions on items unrelated to these names.
- `urgency` reflects whether the bot should react now (`high`) or watch
  passively (`low`). High urgency examples: regulator decisions, sudden
  rate moves, sanctions, major earnings surprises.
- `key_themes` is at most 10 short phrases.

Current UTC: {now_iso}
News batch ({n_items} items, newest first):
{news_block}
"""


class NewsAnalyst:
    name: str = "NewsAnalyst"

    def __init__(
        self,
        llm: LLMProvider,
        whitelist: frozenset[str],
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        self._llm = llm
        self._whitelist = whitelist
        self._max_items = max_items

    async def analyze(
        self,
        news_items: list[NewsItem],
        *,
        now: datetime | None = None,
    ) -> NewsOpinion:
        if not news_items:
            raise ValueError("news_items is empty")
        prompt = self._build_prompt(news_items, now=now or datetime.now(UTC))
        return await self._llm.complete(prompt, response_model=NewsOpinion)

    def _build_prompt(self, news_items: list[NewsItem], *, now: datetime) -> str:
        items = sorted(news_items, key=lambda n: n.posted_at, reverse=True)[: self._max_items]
        news_block = "\n".join(
            f"{i + 1}. [{item.channel} {item.posted_at.isoformat()}] {item.text}"
            for i, item in enumerate(items)
        )
        return PROMPT_TEMPLATE.format(
            whitelist=sorted(self._whitelist),
            now_iso=now.isoformat(),
            n_items=len(items),
            news_block=news_block,
        )
