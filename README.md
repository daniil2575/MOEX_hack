# moex-bot

Мультиагентная LLM-система для автономной торговли на Московской бирже в рамках **MOEX AI Hackathon 2026** (13 мая — 30 июня 2026).

## Архитектура

Иерархическая система на LangGraph: Analyst team (News / Technical / Macro / Sentiment) → Bull/Bear debate subgraph → Trader → детерминированный Risk Manager → BrokerGateway → ALPHA sandbox.

Полная стратегия и обоснование решений — в [`../moex_ai_hackathon_full_strategy.pdf`](../moex_ai_hackathon_full_strategy.pdf).

## Стек

- **Оркестрация:** LangGraph
- **LLM:** Qwen3-32B-Instruct / DeepSeek V3.1 через OpenRouter (fallback — self-hosted Qwen3-32B AWQ в vLLM)
- **Structured output:** Instructor + Pydantic
- **Данные:** MOEX ISS + Algopack, Telegram (Telethon)
- **Хранение:** PostgreSQL 16 + Redis 7
- **Observability:** Langfuse + Prometheus + Grafana
- **Risk Manager:** чистый Python, TDD, никакого LLM в критическом пути
- **Python:** 3.11

## Быстрый старт (после Дня 3 спринта 1)

```bash
cp .env.example .env
# заполнить OPENROUTER_API_KEY, TELEGRAM_API_ID и т.д.
docker compose up -d
```

## Структура

```
src/
├── agents/       # LangGraph узлы (News/Tech/Macro Analyst, Bull/Bear, Trader)
├── data/         # MOEX ISS, Telegram parser, features, event calendar
├── execution/    # BrokerGateway + адаптеры (T-Invest, ALPHA, Mock)
├── llm/          # LLMProvider + OpenRouterAdapter / VllmLocalAdapter
└── risk/         # Детерминированный Risk Manager + правила
tests/            # pytest, snapshot-тесты промптов
prompts/          # Jinja-шаблоны промптов с версионированием
monitoring/       # Prometheus config, Grafana dashboards
notebooks/        # Pet-project, smoke-тесты, EDA
docs/             # Application draft, look-ahead guards, baseline results
scripts/          # backfill, одноразовые задачи
```

## Процесс

Команда из 3 человек: ML/LLM-инженер + Data/Backend + Quant. Планы спринтов — в [`../sprints/`](../sprints/).

## Лицензия

MIT
