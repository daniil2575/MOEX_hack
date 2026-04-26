# LLM Models — Reproducibility Manifest

**Pinned snapshots**, не «latest». Используются в `.env.example` как hard requirement.
Дата pinning: **2026-04-26**.

## Tier 1 — Fast path (single-asset signal, news intake)

| Variable | Snapshot | Provider | Cost (input/output, $/1M tok) | Context | Notes |
|---|---|---|---|---|---|
| `OPENROUTER_MODEL_FAST` | `qwen/qwen3-32b-instruct-2507` | OpenRouter | ~0.1 / ~0.3 | 32K | Default для Analysts (Technical, News, Fundamental) |

## Tier 2 — Deep path (Manager + complex reasoning)

| Variable | Snapshot | Provider | Cost (input/output, $/1M tok) | Context |
|---|---|---|---|---|
| `OPENROUTER_MODEL_DEEP` | `qwen/qwen3-235b-a22b-thinking-2507` | OpenRouter | ~0.5 / ~1.5 | 64K |

Используется Manager-агентом и для разрешения конфликтов между Analysts.

## Tier 3 — Fallback (если основной провайдер падает)

| Variable | Snapshot | Provider | Notes |
|---|---|---|---|
| `OPENROUTER_MODEL_FALLBACK` | `deepseek/deepseek-chat-v3.1` | OpenRouter | Активируется при `LLMProviderError` после retries; альтернативный провайдер сети для отказоустойчивости |

## Why not "latest"

- **Reproducibility** — тестовые прогоны и live должны использовать **тот же** weights snapshot. «latest» меняется без уведомления → walk-forward результаты несравнимы.
- **Knowledge cutoff control** — pinned snapshot имеет известный cutoff (важно для look-ahead bias guards: см. `notes/look_ahead_guards.md` от Quant).
- **LLM training data leak protection** — фиксируем известный `training_cutoff_date`, не пускаем модель смотреть на котировки после этой даты.

## Update procedure

Менять снапшоты можно **только** через PR с обоснованием:
1. Причина смены (cost, новые capabilities, deprecation старого snapshot)
2. Новый walk-forward прогон на baseline (sprint 2 Day 1) — результаты в `docs/baseline_results.md`
3. Обновление этого файла + `.env.example`

Не править live во время хакатонной сессии.
