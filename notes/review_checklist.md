# Self-review checklist

Перед каждым `git push origin main`.

## Code quality
- [ ] `pytest` зелёный (или новые тесты — *intentionally red* в TDD-фазе, отмечено в commit message)
- [ ] `ruff check .` без ошибок
- [ ] `ruff format --check .` чистый (или auto-applied)
- [ ] `mypy --strict src tests` чистый
- [ ] Нет `print()` / `pdb.set_trace()` / `breakpoint()` в production-коде
- [ ] Нет TODO без issue-ссылки или дедлайна

## Financial correctness
- [ ] **`Decimal` для всех денежных величин** (NAV, цены, qty, %, commission, slippage). Float — табу.
- [ ] Все Pydantic-модели с деньгами имеют `model_config = ConfigDict(frozen=True, extra="forbid")`
- [ ] Округления используют `Decimal.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)`, не дефолтное float-rounding
- [ ] Любой timestamp — timezone-aware (UTC или MSK с явным tz-info)

## Security
- [ ] Нет hardcoded API-ключей / токенов / паролей (даже в тестах — используем `pytest.MonkeyPatch` или `.env.test`)
- [ ] Нет URL'ов с inline credentials (`https://user:pass@...`)
- [ ] `.gitignore` покрывает все локальные `.env*` (кроме `.env.example`)
- [ ] Логи не пишут чувствительные поля (PII, tokens, raw orders)

## Architecture
- [ ] Все ABC имеют ≥1 теста на контракт (хотя бы smoke)
- [ ] Pydantic-контракты живут только в `src/contracts/`, нигде не дублируются
- [ ] LangGraph-узлы не пишут в БД напрямую — только через persistence-слой
- [ ] Risk Manager — детерминирован, без внешних вызовов

## Reproducibility
- [ ] Pinned LLM snapshots (`OPENROUTER_MODEL_*` без «latest»)
- [ ] `poetry lock` обновлён, если менялись deps
- [ ] Сиды зафиксированы для backtest (numpy + python `random`)

## Process
- [ ] Commit message по conventional commits (`feat(risk): ...`, `test(risk): ...`, `fix(...)`)
- [ ] Один логический change per commit
- [ ] `daily_log.md` обновлён, если день закрыт
- [ ] Если красные тесты — это TDD red-phase: пометить `WIP` в commit body или явно `test(risk): add failing tests for ...`
