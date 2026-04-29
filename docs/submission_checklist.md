# Pre-submission checklist — MOEX AI Hackathon 2026

**Цель:** отправить заявку **за 1 день до дедлайна** (Sat 9 May 18:00 MSK), чтобы оставить буфер на правки.
**Submission doc:** [`docs/application_v2.md`](application_v2.md) — финальная версия после Day 15.

---

## T-24h: технический freeze

- [ ] `pytest tests/` — все зелёные (target: ≥155/155)
- [ ] `mypy --strict src/` — no issues
- [ ] `ruff check src/ tests/` — All checks passed
- [ ] `git status` — рабочая копия чистая
- [ ] `git push origin main` — пуш прошёл, последний commit виден на GitHub
- [ ] `docker compose config --quiet` — синтаксис валиден
- [ ] `docker build -t moex-bot:final .` — образ собирается

## Reproducibility manifest

- [ ] `pyproject.toml` — все версии deps зафиксированы (`^X.Y` SemVer)
- [ ] `notes/llm_models.md` — pinned snapshots с датой и обоснованием
- [ ] `.env.example` — все переменные перечислены, без секретов
- [ ] Random seed фиксирован в `walk_forward` примерах
- [ ] OHLCV cache воспроизводим (детерминистичен по ISS endpoint)

## Документы для подачи

- [ ] [`docs/application_v2.md`](application_v2.md) — финальный текст заявки
- [ ] Архитектурная диаграмма читается без markdown-парсера (ASCII fallback)
- [ ] Baseline числа (`Sharpe 0.336 vs −1.005, p=0.491`) присутствуют
- [ ] План на 6 недель хакатона — есть
- [ ] Risk register — есть
- [ ] Контактный email указан

## Что показать жюри (демо)

- [ ] `pytest -v` running live → 155 зелёных
- [ ] `python -c "from src.orchestrator import build_graph; ..."` — LangGraph DAG строится
- [ ] Backtest comparison (BuyAndHold vs MACDRSI на 60 днях SBER) — running live через ISS API
- [ ] Risk Manager rejection demo: order на off-whitelist ticker → BLOCK с reason'ом
- [ ] (если успели) `docker compose up -d` → 6 контейнеров healthy, Grafana UI открывается

## Блокеры для submission (P0)

- [ ] HuggingFace token получен → `.env` обновлён
- [ ] Telegram api_id/api_hash — **fallback на fixtures работает** (это тоже валидный submit-state)
- [ ] TInvest sandbox token — gated на manual; demo идёт через MockBrokerGateway

## Послеподачи (Sprint 2 первые дни)

- [ ] Switch BrokerGateway → AlphaSandboxAdapter (Day 1 хакатона, 13 May)
- [ ] Daily walk-forward на свежих данных
- [ ] Iterate prompts (Manager, NewsAnalyst — наиболее cost-чувствительные)
- [ ] CVaR + correlation-aware portfolio VaR (приоритет 1 из roadmap'а)

---

## Submission flow

1. Залогиниться в личный кабинет хакатона
2. Прикрепить `docs/application_v2.md` (или скопировать в форму)
3. Указать GitHub repo URL: https://github.com/daniil2575/MOEX_hack
4. Подтвердить email
5. **Отправить за 24h до дедлайна**

## Если что-то ломается за 1 час до дедлайна

- ❌ Не пытаться чинить код — это P0-блокер на отправку
- ✅ Отправить **минимально жизнеспособную** заявку (текст + repo URL)
- ✅ После подачи — починить, опубликовать как hot-fix commit с явной ссылкой в финальной презентации
