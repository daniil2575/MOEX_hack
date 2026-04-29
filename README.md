# moex-bot

Мультиагентная LLM-система для автономной торговли на Московской бирже в рамках **MOEX AI Hackathon 2026** (13 мая — 30 июня 2026).

> **Статус (Day 16 пре-хакатонной подготовки):** 155/155 тестов зелёные, `mypy --strict` чистый на 43 файлах, 8-rule Risk Manager TDD, walk-forward harness с 5 look-ahead guards, baseline на 60 днях SBER замерен.
> Полная заявка на хакатон — [`docs/application_v2.md`](docs/application_v2.md). Submission checklist — [`docs/submission_checklist.md`](docs/submission_checklist.md).

## Архитектура

LangGraph DAG: `Technical → News → Fundamental → Manager → Trader → Risk → [conditional] → Broker / END`. Conditional edge после Risk Manager: rejected verdict → END (skip broker). Полная стратегия — в [`../moex_ai_hackathon_full_strategy.pdf`](../moex_ai_hackathon_full_strategy.pdf).

## Стек

- **Оркестрация:** LangGraph 0.2 (StateGraph + conditional edges)
- **LLM:** OpenRouter — Qwen3-32B-Instruct (fast), Qwen3-235B-A22B-Thinking (deep), DeepSeek V3.1 (fallback). **Pinned snapshots** — см. [`notes/llm_models.md`](notes/llm_models.md)
- **Structured output:** Instructor + Pydantic (frozen, `extra=forbid`, Decimal для денег)
- **Данные:** MOEX ISS API (1m/15m/1h OHLCV), Algopack, Telegram (Telethon + fixtures fallback)
- **Хранение:** PostgreSQL 16 (5 таблиц через SQLAlchemy 2 + Alembic) + Redis 7
- **Observability:** Langfuse 2 + Prometheus + Grafana (provisioned dashboard + alerts)
- **Risk Manager:** чистый Python, **TDD, 8 fail-fast правил, никакого LLM в критическом пути**
- **Python:** 3.11

## Быстрый старт

```bash
# 1. Поднять стек (6 сервисов)
cp .env.example .env                 # заполнить OPENROUTER_API_KEY и т.д.
docker compose up -d                 # postgres / redis / langfuse / prometheus / grafana / app

# 2. Установить deps локально для разработки и backtest'ов
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .                     # ставит из pyproject.toml

# 3. Прогнать БД-миграции
DATABASE_URL=postgresql+asyncpg://bot:bot@localhost:5433/bot \
  alembic upgrade head

# 4. Тесты
pytest tests/ -v                     # 155 зелёных
mypy --strict src/                   # no issues
ruff check src/ tests/               # All checks passed

# 5. Live SBER backtest (60 дней через ISS API)
python -m src.scripts.backtest_baseline    # см. ниже / docs/application_v2.md
```

UI:
- Langfuse: http://localhost:3000
- Grafana: http://localhost:3001 (admin / admin) — dashboard `moex-bot — overview` provisioned
- Prometheus: http://localhost:9090 — alerts через `monitoring/prometheus/alerts.yml`

## Структура

```
src/
├── agents/         # TechnicalAnalyst, NewsAnalyst, FundamentalAnalyst, Manager, Trader
├── contracts/      # Pydantic-контракты (TraderDecision, Portfolio, RiskVerdict, ProposedOrder...)
├── data/           # MOEX ISS client + technical features (RSI/MACD/ATR/volume_profile)
├── db/             # SQLAlchemy 2 models + async session
├── execution/      # BrokerGateway ABC + MockBrokerGateway + TInvestSandboxAdapter (skeleton)
├── llm/            # LLMProvider + OpenRouterAdapter (Instructor + tenacity)
├── news/           # NewsItem contract + TelethonParser + FixturesParser + factory
├── orchestrator/   # LangGraph DAG (TickState + build_graph)
├── quant/          # walk_forward, look_ahead guards, metrics, stress, strategies, compare
└── risk/           # 8-rule Risk Manager + sectors map (43 IMOEX tickers)
tests/              # 155 tests across all modules
alembic/            # async Alembic migrations
monitoring/
├── prometheus.yml + prometheus/alerts.yml
└── grafana/{provisioning,dashboards}/
data/fixtures/news/ # 6 channel fixtures (~38 сообщений) для offline-mode
docs/               # application_v1.md, application_v2.md, submission_checklist.md
notes/              # llm_models.md (reproducibility), review_checklist.md
sprints/            # daily_log.md, solo_plan.md
```

## Reproducibility

- LLM snapshots **pinned** (`qwen3-32b-instruct-2507`, `qwen3-235b-a22b-thinking-2507`, `deepseek-chat-v3.1`) с датой pinning в `notes/llm_models.md` — никаких "latest"
- Random seed фиксирован для всех симуляций
- 5 look-ahead guards в [`src/quant/look_ahead.py`](src/quant/look_ahead.py) как runtime assertions — backtest падает громко на любую попытку использовать future data

## Процесс

Изначально — команда из 3 человек (ML/LLM-инженер + Data/Backend + Quant). На Day 4 пре-хакатонной подготовки два участника выбыли по независящим обстоятельствам; **scope сохранён в полном объёме, ведётся соло**. Daily log — в [`../sprints/daily_log.md`](../sprints/daily_log.md), план — [`../sprints/sprint_1_prep/solo_plan.md`](../sprints/sprint_1_prep/solo_plan.md).

## Лицензия

MIT
