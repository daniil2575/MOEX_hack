# Заявка на MOEX AI Hackathon 2026 — v1 (черновик)

**Статус:** черновик к Day 8 пре-хакатонной подготовки. Финал — к Day 16 (Sat May 9).
**Подача:** через личный кабинет хакатона до 10 мая 2026.

---

## 1. Команда

- **Название:** *moex-bot*
- **Состав:** соло-участник
  - **Даниил Садчиков** — ML/LLM-инженер, тимлид. Профиль: применение LLM в продуктовых задачах, multi-agent системы, Pydantic-контракты, Python/Rust бэкенд

> Изначально команда состояла из 3 человек (ML/Lead + Data/Backend + Quant). По непредвиденным обстоятельствам коллеги выбыли до старта; **scope сохранён в полном объёме** — все компоненты из исходной стратегии реализуются одним участником.

## 2. Идея и гипотеза

Multi-agent LLM-система для алгоритмической торговли акциями MOEX, строящая решения на координации специализированных аналитиков (Technical / News / Fundamental → Manager → Trader → RiskManager). Гипотеза: при правильной декомпозиции и **детерминированном risk-gate** между LLM-выводом и брокером, LLM-агенты могут устойчиво превосходить пассивный buy-and-hold IMOEX по риск-скорректированной доходности на горизонте недель-месяца.

## 3. Архитектура (на момент подачи)

```
┌────────────────────────────────────────────────────────────────────┐
│                           LangGraph Orchestrator                   │
│                                                                    │
│   ┌──────────┐    ┌──────────────┐    ┌──────────────────┐         │
│   │ Manager  │ ←→ │ TechAnalyst  │    │ NewsAnalyst       │        │
│   │ (deep)   │    │ FundAnalyst  │    │ (Telegram/RSS)    │        │
│   └────┬─────┘    └──────┬───────┘    └─────────┬─────────┘        │
│        │                 │                      │                  │
│        ↓                 ↓                      ↓                  │
│   ┌────────────────────────────────────────────────┐               │
│   │     Trader → ProposedOrder (Pydantic)          │               │
│   └──────────────────┬─────────────────────────────┘               │
│                      ↓                                             │
│   ┌──────────────────────────────────────────────────┐             │
│   │  RiskManager — 8 fail-fast rules (deterministic) │             │
│   │  Whitelist → TradingStatus → PositionSize →      │             │
│   │  Liquidity → Sector → Gross → Drawdown → VaR     │             │
│   └──────────────────┬───────────────────────────────┘             │
│                      ↓ (verdict.approved=True)                     │
│   ┌──────────────────────────────────────────────────┐             │
│   │  BrokerGateway (TInvest sandbox / Alpha API)     │             │
│   └──────────────────────────────────────────────────┘             │
└────────────────────────────────────────────────────────────────────┘
```

## 4. Технический стек

| Слой | Технологии |
|---|---|
| LLM | OpenRouter — Qwen3-32B-Instruct (fast), Qwen3-235B-A22B-Thinking (deep), DeepSeek V3.1 (fallback). Pinned snapshots |
| Structured output | Instructor + Pydantic (frozen, extra=forbid, Decimal для денег) |
| Orchestration | LangGraph |
| Backend | Python 3.11, SQLAlchemy 2 (async + asyncpg), Alembic, Pydantic |
| Хранилище | PostgreSQL 16 (5 таблиц: instruments / decisions / orders / fills / equity) |
| Очередь / cache | Redis 7 (AOF) |
| Observability | Langfuse 2 + Prometheus + Grafana |
| Данные | MOEX ISS API (OHLCV 1m/15m/1h), Algopack (доп. агрегаты), Telegram Telethon (новости) |
| Брокер | TInvest sandbox (paper) до 13 мая → Alpha sandbox в хакатоне |
| Инфра | Docker Compose (6 сервисов с healthchecks), multi-stage Dockerfile |
| CI/CD | ruff + mypy --strict + pytest (38 тестов risk + 14 features = 52 на момент подачи) |

## 5. Risk Manager — особенности

- **8 правил fail-fast:** Whitelist, TradingStatus (T/DA/H/U), PositionSize (≤5% NAV), **Liquidity** (order/ADV ≤5%, missing data → reject), Sector (≤30% NAV per industry), Gross (≤100%), Drawdown (DD-from-peak: WARN -3% → BUY blocked / SELL allowed; HALT -5% → all blocked), **VaR** (historical 1d 95% на симулированном post-trade портфеле, missing returns → reject)
- **Aladdin-вдохновлённое расширение:** Liquidity и VaR-rules + 4 исторических stress-сценария (2008 Lehman, 2014 ruble/CBR-17%, 2022 Feb, 2024 Dec CBR-rally). Reverse stress + correlation-aware VaR — Sprint 2
- **TDD:** все правила покрыты red→green-фазой (38/38), `mypy --strict` чистый

## 6. Reproducibility manifest

- **LLM:** pinned snapshots, не «latest» (`qwen3-32b-instruct-2507`, `qwen3-235b-a22b-thinking-2507`, `deepseek-chat-v3.1`). Дата pinning и процедура обновления через PR — в `notes/llm_models.md`
- **Deps:** Poetry lock, Python 3.11
- **Random seed:** фиксирован для всех симуляций
- **Data:** OHLCV-cache + полный лог `decisions/orders/fills` в Postgres → walk-forward воспроизводим бит-в-бит

## 7. План на хакатон (May 13 → Jun 30)

| Период | Фокус |
|---|---|
| Week 1 | Switch на Alpha sandbox token, daily walk-forward на свежих данных, итерации prompt-ов агентов |
| Week 2-3 | Расширение whitelist по результатам, добавление CVaR + correlation-aware portfolio VaR в Risk Manager |
| Week 4 | Stress-testing на исторических сценариях, reverse stress |
| Week 5 | Reproducibility manifest финал, презентация |
| Week 6 | Submission, defence, доработки по фидбеку жюри |

## 8. Метрики оценки результатов

- **Sharpe / Sortino** — risk-adjusted return
- **Max Drawdown** (peak-to-trough)
- **Hit rate** (% прибыльных сделок) и **profit factor**
- **Comparison** vs buy-and-hold IMOEX (с p-value)
- **Cost** per LLM-decision (≤$0.05 deep-path, ≤$0.005 fast-path)

## 9. Риски и их митигация

| Риск | Триггер | План |
|---|---|---|
| Algopack API не выдают вовремя | нет ключа к Day 8 | Pipeline идёт на ISS only, фичи Algopack позже |
| Telegram API заблокирован | нет `api_id/api_hash` | Static news fixtures (50 сообщений), parser после kick-off |
| LLM cost overrun | OpenRouter spend >$30/неделю | Switch Manager на fast-path, кэш LLM-вызовов, batch |
| Burnout | 3 дня <8ч продуктивных | Принудительный выходной + retro в `daily_log` |
| Late submission | заявка не готова к Sat May 9 18:00 MSK | **БЛОКЕР P0** — отбрасываем всё остальное, отправляем минимально жизнеспособную заявку |

## 10. Что готово к моменту подачи (план Day 16)

- ✅ Working e2e pipeline (data → features → agents → risk → execution paper)
- ✅ Risk Manager 8 правил, TDD, зелёный
- ✅ 4 stress-scenario skeleton + walk-forward harness
- ✅ Buy-and-hold IMOEX benchmark с p-value
- ✅ Reproducibility manifest (pinned LLM, deps lock, seed)
- ✅ Telegram parser (либо static fixtures fallback)
- ✅ Langfuse + Grafana дашборды
- ✅ TInvest sandbox адаптер живой
- ✅ Baseline MACD+RSI стратегия (буст-сравнение)

---

**Контакт:** solodimkinalidi@gmail.com
