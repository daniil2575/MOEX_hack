# Quant reading log — спринт 1, день 1 (24 апреля 2026)

Конспект ключевых секций стратегического PDF глазами Quant/финансиста. Фокус — на решениях, которые я должен либо имплементировать сам, либо отстаивать на защите.

---

## Секция 02 — Архитектурное ядро

### Ключевые решения

- **Иерархия, не плоский дебат.** Manager → Analysts/Workers. Координация в плоской схеме пожирает токенов больше самой аналитики.
- **Risk Manager как tool, а не как LLM-агент.** В диаграмме графа Risk Manager — детерминированный узел, следующий за Trader. Это прямо моя зона.
- **Conditional edge после Risk:** `approved → execute, else → END`. Это контракт, под который я пишу `evaluate() → RiskVerdict{APPROVE|MODIFY|REJECT}`.
- **Structured output через Instructor + Pydantic.** `TraderDecision` приходит ко мне уже типизированным. Мои `ProposedOrder` / `RiskVerdict` должны лежать в том же Pydantic-стиле с `Decimal` для денег.

### Риски / вопросы для команды

- В графе LangGraph есть поле `state.trader_decision` — мне нужно знать, каким `qty_pct_nav` там приходит (0–10% по PDF) и есть ли `sector` в decision или вычисляю сам. Это тема синка вт 28 апреля с Человеком 1.
- State → Risk → Execute — вопрос, кто преобразует `TraderDecision` в `ProposedOrder` (qty в штуках, price в рублях). Наверное я же в `RiskManager.evaluate()`, но надо зафиксировать.
- Memory layer и reflection — nice-to-have, вне моей зоны в спринте 1.

---

## Секция 05 — Risk Manager как детерминированный барьер

Самая критичная для меня секция. Senior-подход (тип C) — детерминированный Python-барьер + дешёвая LLM **только** для объяснений отказов.

### Почему LLM-Risk-Manager — сломанная архитектура

1. **Narrative plausibility** — LLM оценивает не риск, а убедительность аргумента Trader-агента.
2. **RLHF-смещение к compliance** — модель специально учат соглашаться с обоснованными просьбами.
3. **Prompt injection.** Trader может вписать «специальная ситуация, лимиты не применять» — LLM примет.
4. **Недетерминизм.** Один и тот же ордер получает разные вердикты.
5. **Невозможность аудита.** Жюри не поверит, что отказ был корректным.

Это формулировка для защиты. Ответ на вопрос «почему не LLM-риск?» должен быть ровно таким.

### 6 правил спринта 1 (из моей задачи) vs полный список из PDF

| Правило из 03_quant.md | Правило из PDF секции 05 | Коммент |
|---|---|---|
| PositionSizeRule (max 10% NAV) | Есть | 1:1 |
| SectorExposureRule (max 30%) | Есть (25–30%) | беру 30% |
| TradingStatusRule (DA/H/U) | Есть | критичный, редкий у конкурентов |
| DrawdownKillSwitchRule (-3%) | Двухпороговый: -3% only-close, -5% full stop | **расширяю до двух порогов** |
| GrossExposureRule (≤1×) | Есть | шортов нет в хакатоне, сводится к «не больше cash» |
| WhitelistRule (IMOEX-15) | Есть | маппинг в sectors.py |

Из PDF есть ещё **CVaR-budget, Liquidity (5% ADV), RateLimit (≤5/мин), Fat-finger (±2% от last)** — формально они вне scope спринта 1, но я их учитываю в архитектуре базового класса `RiskRule`, чтобы в спринте 2 подключать без рефакторинга.

### Порядок проверки (fail-fast)

PDF явно не задаёт, но «самая дешёвая — первой»:
1. Whitelist (set-lookup)
2. TradingStatus (dict-lookup)
3. PositionSize (одна арифметика)
4. SectorExposure (требует агрегации позиций)
5. GrossExposure (итерация по позициям)
6. DrawdownKillSwitch (требует daily P&L из портфеля)

### Что брать в позицию sizing

- **Half-Kelly с hard-cap 10% NAV.** Full Kelly катастрофичен при шумной оценке edge у LLM.
- **Volatility targeting** — целевая волатильность портфеля ~12% годовых, если рынок спокойный — увеличиваем, если волатильный — урезаем. В спринте 1 не делаю, но фиксирую как следующий шаг.
- **Stop-loss = 2·ATR**, time-stop = N часовых баров (например 24 = 1 торговый день). Time-stop ключевой: LLM-агент может «забыть» открытую позицию.

### Fallback

LLM упал → **НЕ ретраим бесконечно**. Переходим в rule-based baseline: новые позиции не открываем, stop-loss и time-stop продолжают работать. Кэш последнего валидного решения в Redis — страховка от единичного glitch.

---

## Секция 06 — Данные, фичи, промпт-дизайн

Это в основном зона Человека 1 (промпты) и Человека 2 (фичи), но мне это важно для двух вещей: **формирования входа в Trader** и **интеграции LightGBM-сигнала**.

### Правила, которые мне нужны

- **Гибрид числа + семантический ярлык + z-score.** `rsi_14: 72 (overbought, z+1.8)` — не просто 72.
- **Дискретизация в категории.** RSI<30 → oversold и т.д. LLM обучены на тексте, категория активирует правильные паттерны.
- **Мультитаймфреймовая иерархия.** trend_1d → trend_4h → trend_1h → trend_15m.
- **Компактный YAML, не JSON.** Экономия 30–50% токенов.

### Microstructure-фичи из Algopack (когда активируется)

- **OBI (Order Book Imbalance)** — `(Vbid − Vask) / (Vbid + Vask)`. >0.3 buy-pressure, <−0.3 sell-pressure. Предсказывает 1–5 мин.
- **VPIN > 0.4 = toxic flow** — hard stop, не открываем позиции. Может быть ещё одно правило Risk Manager в спринте 2.
- **TradeStats** — buy-initiated vs sell-initiated через Lee-Ready/tick rule.

### LightGBM-сигнал (мой опциональный таск день 8)

- Target: бинарный `price_up_4h` (вырастет ли за 4 часа более чем на 0.5%).
- Walk-forward 2022–2024 train / 2025 val.
- Критерий успеха: **F1 > 0.55** на валидации. Это и попадает в промпт Trader как `ml_signal_p_up: 0.63`.
- Если не успеваю — НЕ критично, переносим в спринт 2. Важнее довести Risk Manager и baseline до зелёных тестов.

### Антипаттерны промптов (чтобы не ткнуть Человека 1 лицом)

- Сырые list-of-list (LLM плохо работает с числовыми последовательностями).
- `temperature > 0` — ломает воспроизводимость.
- Одинаковый промпт для всех тикеров без per-ticker z-score.
- Сырые новости целиком (нужны агрегаты).

---

## Секция 08 — Бэктестинг, воспроизводимость, детерминизм

Это **квант-секция защиты**. Половина моей работы — не «красивые цифры», а методологическая чистота.

### Две большие ошибки, убивающие бэктесты

1. **Look-ahead bias** — revised vs first-release, close-price leak, dividend adjustment leak, **LLM training data leak** (Glasserman & Lin, arXiv 2309.17322). Мой отдельный документ `docs/look_ahead_guards.md` на день 7.
2. **Overfitting / data snooping** — из 1000 стратегий ~50 получат «значимый» alpha при p<0.05 случайно. Walk-forward + честный OOS + фиксированный seed + sensitivity analysis.

### Walk-forward, который я делаю день 6

- Rolling (не anchored) — из-за non-stationarity.
- Train 180 дней, test 30 дней, step 30 дней.
- **Purge** 1–5 дней между train и test — защита от leak через rolling features.
- Fold-метрики: mean ± std ± min/max по Sharpe/MDD/hit-rate. Не просто «средний Sharpe».

### Что симулировать

| Компонент | Значение для MOEX |
|---|---|
| Комиссия MOEX | ~0.02% (2 bp) |
| Комиссия брокера | 0.03–0.05% |
| **Round-trip минимум** | **0.05%** |
| Slippage на blue-chip | 0.05% на сторону = 0.1% round-trip |
| LLM latency (simple agent) | 2–10 сек |
| Partial fills | Для ~100k ₽ и blue-chip считать полными |
| Queue position для limit | Исполнение только когда цена пересекла уровень (pessimistic) |

### Мета-метрики

- **Целевой Sharpe хакатона: 1.0–1.5.** Sharpe 3+ в бэктесте — red flag p-hacking.
- **MDD** — worst experience, показывается на графике equity curve.
- **Calmar = annual_return / MDD**, >1 — хорошо.
- **CVaR(95%)** — среднее убытка в худших 5% случаев. Честнее, чем VaR.
- **Turnover** — высокий + умеренный Sharpe = комиссии съедают alpha.
- **Обязательное сравнение с buy-and-hold IMOEX.** Без бенчмарка цифры ничего не значат.

### Reproducibility manifest

Должен быть в `docs/` к концу спринта 2. Состав:
- `git_commit`, `docker_image_digest`, `requirements_hash`
- `llm_models` (pinned snapshots, не «последний Qwen»)
- `data_snapshot` (даты pull'ов ISS / Algopack / Telegram)
- `prompts_version`
- `seeds` (python_random, numpy_random, llm_seed)
- `llm_cache_digest`

Критерий: `docker compose up && make run-backtest` даёт **идентичные** цифры на любой машине.

### Что я говорю жюри (почти дословно из PDF)

> Трёхуровневая валидация: walk-forward с purge и полной симуляцией комиссий/slippage; параллельный paper trading; live-прогон в ALPHA. Sharpe по fold'ам 1.2 ± 0.3, MDD ≤ 6%. Про look-ahead bias LLM знаем (Glasserman & Lin), используем модели с knowledge cutoff до периода тестирования + ticker anonymization. Reproducibility manifest с git SHA, Docker digest, LLM cache hash.

---

## Pre-hackathon preparation — Level 3 (моя зона)

Релевантные пункты:

1. **Baseline без LLM (MACD+RSI).** Я делаю в день 5. Walk-forward 2022–2024 на SBER, получаю baseline Sharpe для честного сравнения с LLM-системой.
2. **LightGBM-сигнал за 2022–2024.** День 8, опциональный. Сохранить `.pkl`, подключить в промпт Trader.
3. **Тесты для Risk Manager (TDD).** День 2 — красные тесты до имплементации. Это главный артефакт для жюри: «мы покрыли 100% детерминированной логики тестами».

---

## Итог — что меняется в моём плане после чтения

### Подтверждается as-is

- 6 правил Risk Manager, Pydantic-модели с Decimal, TDD в день 2.
- MACD+RSI baseline в день 5 + walk-forward в день 6.
- `docs/look_ahead_guards.md` в день 7 с 5 пунктами защит (из PDF секция 08).

### Расширения/правки к исходному плану 03_quant.md

- **DrawdownKillSwitch делаю двухпороговый** (−3% only-close, −5% full stop), как в PDF секция 05.
- **Базовый класс `RiskRule`** сразу рассчитан на расширение до CVaR/Liquidity/RateLimit/FatFinger в спринте 2 — в спринте 1 имплементирую только 6, но API одинаковый.
- **В sectors.py добавляю ещё тикеры из PDF секции 05**: BSPB (банки), FIVE, OZON (ритейл), HEAD, ASTR (IT), UPRO, IRAO (энергетика). Это не ломает whitelist, просто полный маппинг.
- **В walk-forward обязательно добавить buy-and-hold IMOEX baseline** для сравнения в `docs/baseline_results.md` — без бенчмарка цифры не убеждают.
- **Для схемы Человека 2 заготовил 5 вопросов** (см. 03_quant.md 4.2) + уточнил, что по PDF в `fills` точно нужен `commission` с разделением MOEX/брокер — спросить, будет ли одна колонка или две.

### Вопросы команде (на завтрашний sync)

1. **Человеку 1:** какая финальная Pydantic-схема `TraderDecision`? Достаточно ли `{ticker, action, qty_pct_nav, stop_loss, time_stop_bars}` или что-то ещё? Решаем вт 28 апр.
2. **Человеку 2:** в `fills.commission DECIMAL(10,4)` — одно поле или две колонки (MOEX + broker)? Для MDD-анализа лучше разделение. Решаем пн 27 апр.
3. **Оба:** соглашаемся ли мы на **pinned model snapshots** (`qwen3-32b-instruct-2507`, не «последний Qwen»), и фиксируем это в `.env.example` как жёсткое требование?

### Риски, которые я беру на учёт

- **LLM training data leak** в бэктестах 2022–2025. Смягчается: (а) baseline MACD+RSI полностью без LLM, (б) live-forward testing в ALPHA — главная защита, (в) ticker anonymization как опциональная проверка.
- **Pandas-ta в Python 3.11** — возможна несовместимость. Fallback — TA-Lib (требует apt install, Человек 2 в Dockerfile).
- **Walk-forward длительный** — если >4 часов, урезаем до 3 тикеров / 2 лет.
