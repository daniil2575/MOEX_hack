# Заявка на MOEX AI Hackathon 2026 — v2 (с baseline-замерами)

**Статус:** v2 после Day 15 пре-хакатонной подготовки. Финал — к Day 16 (Sat May 9).
**Подача:** через личный кабинет хакатона до 10 мая 2026.

> v2 отличается от v1 наличием реальных baseline-замеров на 60 днях SBER + результатами walk-forward harness и look-ahead guards.

---

## 1. Команда

- **Название:** *moex-bot*
- **Состав:** соло-участник
  - **Даниил Садчиков** — ML/LLM-инженер, тимлид

> Изначально команда состояла из 3 человек. По непредвиденным обстоятельствам коллеги выбыли до старта; **scope сохранён в полном объёме** — все компоненты из исходной стратегии реализуются одним участником.

## 2. Идея и гипотеза

Multi-agent LLM-система для алгоритмической торговли акциями MOEX, строящая решения на координации специализированных аналитиков (Technical / News / Fundamental → Manager → Trader → RiskManager). Гипотеза: при правильной декомпозиции и **детерминированном risk-gate** между LLM-выводом и брокером, LLM-агенты могут устойчиво превосходить пассивный buy-and-hold IMOEX по риск-скорректированной доходности на горизонте недель–месяца.

## 3. Архитектура (на момент подачи v2)

```
┌──────────────────────────────────────────────────────────────────────┐
│                       LangGraph Orchestrator (DAG)                   │
│                                                                      │
│   Technical → News → Fundamental → Manager → Trader → Risk → Broker  │
│       │         │         │            │         │       │      │    │
│   features  Telegram   ratios       deep-path  ATR-rules 8 fail BrokerGW │
│   (RSI/MACD  (fixtures   (P/E,     (Qwen3-235B   v1     fast         │
│   /ATR)     fallback)   div_yield)  Thinking)            rules)      │
│                                                                      │
│   ↓ conditional edge after Risk: rejected → END (skip Broker)        │
└──────────────────────────────────────────────────────────────────────┘
```

## 4. Технический стек

| Слой | Технологии |
|---|---|
| LLM | OpenRouter — Qwen3-32B-Instruct (fast), Qwen3-235B-A22B-Thinking (deep), DeepSeek V3.1 (fallback). Pinned snapshots |
| Structured output | Instructor + Pydantic (frozen, extra=forbid, Decimal для денег) |
| Orchestration | LangGraph 0.2 (StateGraph, conditional edges) |
| Backend | Python 3.11, SQLAlchemy 2 (async + asyncpg), Alembic, Pydantic |
| Хранилище | PostgreSQL 16 (5 таблиц: instruments / decisions / orders / fills / equity) |
| Очередь / cache | Redis 7 (AOF) |
| Observability | Langfuse 2 + Prometheus + Grafana |
| Данные | MOEX ISS API (OHLCV 1m/15m/1h), Algopack (доп. агрегаты), Telegram Telethon (новости + fixtures fallback) |
| Брокер | TInvest sandbox (paper) до 13 мая → Alpha sandbox в хакатоне; MockBrokerGateway для тестов |
| Инфра | Docker Compose (6 сервисов с healthchecks), multi-stage Dockerfile (316 МБ) |
| CI/CD | ruff + mypy --strict + pytest (155 тестов на момент v2) |

## 5. Risk Manager — особенности

8 правил fail-fast в каноническом порядке (cheapest first):
1. **WhitelistRule** — set lookup
2. **TradingStatusRule** — T (всё) / DA (только LIMIT) / H/U (блок)
3. **PositionSizeRule** — ≤5% NAV
4. **LiquidityRule** (Aladdin-вдохновение) — `order_value / ADV ≤ 5%`, missing data → reject
5. **SectorExposureRule** — ≤30% per industry
6. **GrossExposureRule** — sum |positions| / NAV ≤ 100%
7. **DrawdownKillSwitchRule** — DD-from-peak: WARN -3% (BUY blocked / SELL allowed), HALT -5% (all blocked)
8. **VaRRule** (Aladdin-вдохновение) — historical 1d 95% VaR на симулированном **post-trade** портфеле, missing returns → reject

Plus: 4 исторических stress-сценария (`src/quant/stress.py`): 2008 Lehman, 2014 ruble/CBR-17%, 2022 Feb, 2024 Dec CBR-rally — replay-ом весят compounded_return × position_weight.

**TDD:** все правила покрыты red→green фазой, **38/38 risk + 26 quant + 91 другое = 155/155** зелёных. `mypy --strict` чистый на 41 файле.

## 6. Walk-forward harness + look-ahead guards

`src/quant/walk_forward.py` — single-ticker, long-only paper-backtester со строгим no-look-ahead контрактом. Strategy Protocol — стратегия видит `features.iloc[: t+1]` (G1), fills на OPEN бара t+1 со slippage в bps (G4). Возвращает `BacktestResult` с equity curve + headline metrics.

**5 look-ahead guards** (`src/quant/look_ahead.py`):
- G1 frame_no_future — нет строки в `frame.index` > `as_of`
- G2 disjoint_windows — train/test не пересекаются
- G3 indicator_warmup_nan — первые N-1 значений N-периодного индикатора = NaN
- G4 fill_after_decision — fill минимум через 1 бар после decision'а
- G5 news_no_future — `posted_at <= as_of` для всех NewsItem

Все guards — runtime-assertions с `LookAheadError`. Backtest падает громко, если кто-то случайно подсунул future bar.

## 7. Baseline backtest — реальные числа

Walk-forward backtest на **60 днях SBER (1h bars, 881 bar after MACD/RSI warm-up)** через MOEX ISS API:

| Метрика | BuyAndHold (benchmark) | MACDRSI (active) |
|---|---|---|
| Cumulative return | **+2.95%** | **−0.30%** |
| Sharpe (ann.) | 0.336 | −1.005 |
| Sortino | 0.506 | −1.399 |
| Max Drawdown | 2.59% | 0.32% |
| Hit rate | n/a (no closes) | 22.50% (40 trades) |

**Welch t-test на bar-returns:** t = −0.688, **p = 0.491** — разница не статистически значима.

**Интерпретация:** наивный MACD+RSI без LLM-overlay не бьёт buy-and-hold на 60 днях SBER, но и не проигрывает значимо (p > 0.4). Это honest baseline — multi-agent system нужно показать значимое преимущество **именно** над этим уровнем, а не над «случайной стратегией». MDD у MACDRSI на порядок ниже buy-and-hold (0.32% vs 2.59%) — компенсация низкой доходности дисциплиной выхода.

**Цель Sprint 2 (хакатон):** LLM-multi-agent overlay должен дать Sharpe > 0.5 на скользящем окне с p-value < 0.05 vs тот же buy-and-hold.

## 8. Reproducibility manifest

- **LLM:** pinned snapshots (`qwen3-32b-instruct-2507`, `qwen3-235b-a22b-thinking-2507`, `deepseek-chat-v3.1`). Дата pinning — `notes/llm_models.md`. Update procedure через PR.
- **Deps:** Poetry lock, Python 3.11
- **Random seed:** фиксирован для всех симуляций (`np.random.default_rng(0)` в синтетических harness'ах; live backtest детерминистичен по def fetch_candles)
- **Data:** OHLCV-cache в `data/cache/`, полный лог `decisions/orders/fills` в Postgres → walk-forward воспроизводим бит-в-бит
- **Look-ahead:** 5 guards в `src/quant/look_ahead.py`, runtime-assertions, fail-loud на любую попытку использовать future data

## 9. Метрики оценки результатов

- **Sharpe / Sortino** — risk-adjusted return
- **Max Drawdown** (peak-to-trough)
- **Hit rate** (% прибыльных сделок) и **profit factor**
- **Comparison vs buy-and-hold IMOEX** через Welch t-test (manual, scipy-free) с p-value
- **Cost** per LLM-decision (≤$0.05 deep-path, ≤$0.005 fast-path)

## 10. План на хакатон (May 13 → Jun 30)

| Период | Фокус |
|---|---|
| Week 1 | Switch на Alpha sandbox token, daily walk-forward на свежих данных, итерации prompt-ов агентов |
| Week 2-3 | Расширение whitelist по результатам, добавление **CVaR + correlation-aware portfolio VaR** в Risk Manager (приоритет 1 из roadmap'а) |
| Week 4 | Stress-testing на исторических сценариях (populate `scenario.returns` из MOEX historical), reverse stress |
| Week 5 | Reproducibility manifest финал, презентация |
| Week 6 | Submission, defence, доработки по фидбеку жюри |

## 11. Риски и митигация

| Риск | Триггер | План |
|---|---|---|
| Algopack API не выдают вовремя | нет ключа к Day 8 | Pipeline на ISS only (✅ работает), Algopack-фичи позже |
| Telegram API заблокирован | нет `api_id/api_hash` | **Mitigated:** static fixtures (38 messages, 6 channels) в `data/fixtures/news/`, parser-factory автоматически переключается |
| LLM cost overrun | OpenRouter spend >$30/неделю | Switch Manager на fast-path, кэш LLM-вызовов, batch |
| Burnout | 3 дня <8ч продуктивных | Принудительный выходной + retro в `daily_log` |
| Late submission | заявка не готова к Sat May 9 18:00 MSK | **БЛОКЕР P0** — отбрасываем всё остальное, отправляем минимально жизнеспособную заявку |

## 12. Что готово к моменту подачи (план Day 16)

- ✅ Working e2e pipeline (data → features → agents → risk → execution paper) — **LangGraph DAG зелёный, E2E test проходит**
- ✅ Risk Manager 8 правил, TDD, зелёный (38/38)
- ✅ 4 stress-scenario skeleton + walk-forward harness с 5 look-ahead guards
- ✅ Buy-and-hold benchmark + Welch t-test, **реальные числа на 60 днях SBER**
- ✅ Reproducibility manifest (pinned LLM, deps lock, seed)
- ✅ Telegram parser (live + fixtures fallback) — pipeline идёт независимо от наличия api_id
- ✅ TInvest sandbox адаптер skeleton (gated на token)
- ⏳ Langfuse + Grafana дашборды — поднять при получении локального docker stack (Day 16)

---

**Контакт:** solodimkinalidi@gmail.com
