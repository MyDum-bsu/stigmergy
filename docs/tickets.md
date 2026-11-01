# Stigmergy v1 — тикеты (tracer bullets)

Правило: каждый тикет замыкает один проверяемый срез. DoD — команда, а не
описание. Ветка на тикет — `feat/<id>-<slug>`; после зелёного DoD мерж в `dev`
через очередь (когда она появится) или вручную до неё.

## Статус (2026-11-01)

| Тикет | Статус | Чем подтверждён |
|---|---|---|
| S0 bootstrap | ✅ | 28 pytest, ruff clean |
| S1 board | ✅ | `tests/test_board.py`, `test_migrate.py` |
| S2 spec/claim/workspace | ✅ | `tests/test_spec.py`, `test_board.py` |
| S3 gate/control/sandbox | ✅ | `tests/test_gate.py`, `stg sandbox check` → ok |
| S4 integrate/merge | ✅ | `tests/test_integrate.py`, T5 clone ff |
| S5 episode + T5 | ✅ | T5 clone: `dev` → `a9f57f6`, events полной цепочкой |
| S6 Herdr | ✅ | сервис `factory` активен; реальный эпизод `H1` через `pi` (Go 3) до `merge.done`; конформанс `manual`/`herdr` — одна цепочка из 13 действий |
| S7 dash/registry | ✅ | `tests/test_dash.py`, HTTP `/api/state` |
| S8 Big Bang | ⚠️ | `migrate --check` 292 события; реальный перенос ждёт go-ahead |


## Граф

```
S0 bootstrap
 └─ S1 board
     ├─ S2 spec + claim + workspace
     │   └─ S3 gate + control + sandbox
     │       └─ S4 integrate + merge
     │           └─ S5 episode manual + T5 dogfood
     │               └─ S6 Herdr adapter + conformance
     ├─ S7 dash + registry
     └─ S8 Big Bang migration + docs   (после S1, S6, S7)
```

## S0 — Bootstrap пакета

**Цель:** репозиторий, пакет, CLI-скелет, лог событий, тесты.

**Файлы:** `pyproject.toml`, `src/stigmergy/{__init__,cli,log,model}.py`,
`tests/test_log.py`, `.gitignore`, `README.md`.

**DoD:**

```bash
uv run stg --help
uv run pytest -q
```

`stg --version` печатает версию; лог пишет событие с `seq`, `timeUnixNano`,
`eventId`, `flock`; повторный запуск не ломает монотонность.

**Risk:** low. **Deps:** нет.

## S1 — Доска `stg board`

**Цель:** все команды текущей доски под `stg board`; чтение/валидация legacy
лога; проекции.

**Файлы:** `src/stigmergy/{board,state,render,migrate}.py`,
`tests/test_board_compat.py`, `tests/fixtures/legacy/`.

**DoD:**

```bash
uv run pytest -q tests/test_board_compat.py
uv run stg migrate --check tests/fixtures/legacy
uv run stg board render --board tests/fixtures/legacy
```

На фикстуре из 291 события: `list/show/status` совпадают с выводом старого
`board` (нормализованный JSON), `render` даёт те же три проекции, `seq` не
переписан.

**Risk:** medium. **Deps:** S0.

## S2 — Спека, claim, workspace

**Цель:** decision procedure как файл; claim с guard'ами; planner; worktree.

**Файлы:** `src/stigmergy/{spec,planner,workspace}.py`,
`tests/test_spec.py`, `tests/test_claim.py`, `tests/fixtures/specs/`.

**DoD:**

```bash
uv run pytest -q tests/test_spec.py tests/test_claim.py
uv run stg spec validate tests/fixtures/specs/T5.md
```

Проверяется: невалидная спека отклоняется (нет DoD, абсолютный путь, нет
negative control для medium); claim блокируется при deps/WIP/пересечении
`allowed_paths`; `spec.sha` фиксируется; worktree создаётся от base и чист.

**Risk:** medium. **Deps:** S1.

## S3 — Гейт, негативный контроль, sandbox

**Цель:** DoD исполняет контур в gate-worktree; oracle из base; живость
доказана; evidence с хешами.

**Файлы:** `src/stigmergy/{gate,sandbox,artifacts}.py`,
`tests/test_gate.py`, `tests/test_sandbox.py`, `tests/fixtures/repo-gate/`.

**DoD:**

```bash
uv run pytest -q tests/test_gate.py tests/test_sandbox.py
uv run stg sandbox check --profile gate
```

На фикстурном репо: зелёный DoD → `gate.passed` + `gate.json`; красный →
`gate.failed`; патч, ломающий тест, → красный; no-op гейт (`assert True`) при
негативном корпусе → `control.failed`; oracle-файл, изменённый в эпизоде,
восстановлен из base (diff пуст); `~/.ssh` и `data/` не читаются; gate network
off.

**Risk:** high. **Deps:** S2.

## S4 — Интеграция и мерж

**Цель:** очередь мержа: rebase на `dev`, full gate, ff `dev`, конфликт →
requeue.

**Файлы:** `src/stigmergy/integrate.py`, `tests/test_integrate.py`,
`tests/fixtures/repo-integrate/`.

**DoD:**

```bash
uv run pytest -q tests/test_integrate.py
```

Фикстура: две task-ветки; первая мержится ff; вторая после rebase проходит
full gate и мержится; конфликтная → `integration.failed` + `task.requeued`;
`main` не изменился; worktree задачи убран.

**Risk:** high. **Deps:** S3.

## S5 — Эпизод `manual` и догфудинг T5

**Цель:** контур коммитит и снимает tree; полный цикл на реальной задаче
`T5-land`; первый мерж в `dev`.

**Файлы:** `src/stigmergy/{episode,runner/manual}.py`,
`specs/T5-land.md` в optimization, `tests/test_episode.py`.

**DoD:**

```bash
uv run pytest -q tests/test_episode.py
uv run stg run T5-land --runner manual --board /home/mydum/Desktop/projects/optimization
```

События: `claimed → workspace.created → episode.started → episode.finished →
gate.passed → control.passed → integration.passed → merge.done → task.done`;
`gate.json` с хешами; `dev` двигается ff; `views/` пересобраны; `main` не тронут.

**Risk:** medium. **Deps:** S4.

## S6 — Herdr-адаптер, systemd, конформанс

**Цель:** раннер Herdr с `pi` в отдельной сессии `factory`; guard; конформанс с
`manual`.

**Файлы:** `src/stigmergy/runner/{base,herdr}.py`,
`src/stigmergy/herdr_service.py`, `tests/test_runner_conformance.py`,
`docs/herdr.md`.

**DoD:**

```bash
uv run pytest -q tests/test_runner_conformance.py
uv run stg doctor herdr
systemctl --user status stigmergy-herdr.service
```

Сервис запущен, сессия `factory` без чужих workspace; `pi` распознан (в т.ч.
внутри bwrap через `HERDR_AGENT=pi`); синтетическая задача через `manual` и
`herdr` даёт одинаковую последовательность станций; `blocked` → событие и
уведомление; stop гасит панель; повторный старт не восстанавливает агентов.

**Risk:** high. **Deps:** S5.

## S7 — Дашборд, реестр, `status --all`

**Цель:** `stg dash` из событий; реестр проектов; `mo-swarm` переписан.

**Файлы:** `src/stigmergy/{dash,registry}.py`, `tests/test_dash.py`,
`bin/mo-swarm` (замена).

**DoD:**

```bash
uv run pytest -q tests/test_dash.py
uv run stg dash --port 8787 &
curl -s http://127.0.0.1:8787/api/state | head
```

Панели: очередь, активный эпизод, гейт, очередь мержа, бюджет, лента. В
`src/stigmergy/dash.py` нет `sqlite3` ZCode и `bd`; `stg status --all` читает
два фикстурных проекта из реестра.

**Risk:** low. **Deps:** S1 (можно параллельно с S2–S6).

## S8 — Big Bang: миграция, доки, установка

**Цель:** перенести реальный `.agent`, обновить `AGENTS.md`, убрать `board`,
установить `stg`, зафиксировать runbook.

**Файлы:** `optimization/AGENTS.md`, `optimization/.gitignore`,
`docs/runbook.md`, `docs/migration.md`.

**DoD:**

```bash
uv run stg migrate --check --from /home/mydum/src/optimization/.agent
uv run stg migrate --from /home/mydum/src/optimization/.agent \
  --to /home/mydum/Desktop/projects/optimization/.agent
cd /home/mydum/Desktop/projects/optimization && stg doctor && stg board render
```

291 событие провалидировано, `board.migrated` записан; `AGENTS.md` ссылается
только на `stg`; `board` не в PATH; `stg doctor` зелёный; T5 уже в `dev`;
отчёт с числами.

**Risk:** high. **Deps:** S1, S6, S7.

## Парковка (v1.1+)

- WIP 2–3 и параллельные эпизоды.
- Экспорт событий в git-ref / межмашинный синк.
- Telegram-уведомления через `notify`-адаптер.
- Полная автономия `stg run` без ручного старта.
- Легальная правка oracle отдельной задачей.
- `mo-hud` на `stg status --json`.
- `stg promote` `dev → main`.
