# stigmergy

Универсальный контур тёмной фабрики: append-only лог событий, машина состояний
над короткими эпизодами, исполняемая приёмка с якорным и живым оракулом, очередь
интеграции и мержа. Ядро не знает имён раннеров: Herdr, pi, ручной запуск —
адаптеры на краю.

Пакет `stigmergy`, CLI `stg`, Python 3.12 stdlib, без runtime-зависимостей.

## Документы

- [`docs/spec.md`](docs/spec.md) — спецификация v1: домен, события, станции,
  гейт, права, раннеры, миграция, приёмка.
- [`docs/tickets.md`](docs/tickets.md) — трассер-тикеты S0–S8 с DoD.
- [`docs/runbook.md`](docs/runbook.md) — установка, задачи, Herdr, dash,
  диагностика.
- [`docs/migration.md`](docs/migration.md) — Big Bang-перенос доски.

## Состояние (2026-11-01)

Реализованы S0–S7; S8 подготовлен, реальный перенос `.agent` ждёт явного
go-ahead.

Проверено в этом окружении:

- `uv run pytest -q` — 28 passed; `uv run ruff check .` — clean.
- T5 end-to-end на клоне `optimization`: `stg run T5-land --runner noop --auto
  --no-sandbox` → `gate.passed`, `control.proven`, `integration.passed`,
  `merge.done`; `dev` fast-forward на `a9f57f6`, `.beads` не в дереве,
  bd-блока в `AGENTS.md` нет.
- `stg sandbox check` — bwrap-канарейка `ok`.
- Herdr: systemd-сессия `factory` запущена; `pi` с ключом OpenCode Go 3
  (`opencode-go-chat-3`) прошёл реальные эпизоды `S8a` (конфиг + скилл) и
  `S8b2` (AGENTS.md на `stg`); `S8b` — пример плохого критерия: агент
  заблокировался, гейт покраснел, DoD исправлен в `S8b2`. Workspace эпизода
  остаётся открытым (`stg herdr list`, `herdr --session factory`).
- Реальные мержи в `dev`: T5 `a8b2cd1`, S8a `892e241`, S8b2 `00e46b5`;
  `main` не тронут (`069c3af`).
- `stg migrate --check /home/mydum/src/optimization/.agent` — 292 события,
  105 задач, схема валидна.

Не проверено: реальный T5-мерж в `optimization/dev` и переписывание
`AGENTS.md` на `stg` — ждут явного go-ahead.

## Быстрый старт

```bash
uv tool install --editable .
cd <repo> && stg init && stg doctor
stg spec new T1 && stg spec validate specs/T1.md --base dev
stg board add T1 --spec specs/T1.md
stg run T1 --runner manual
stg episode finish T1 --auto
```
