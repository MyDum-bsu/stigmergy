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

## P0: идея → принятая задача

```bash
stg task "добавить HQ-сканы в трекер"   # request + task + Plan tab
stg plan list
stg plan show <ID>
stg plan render <ID>                    # HTML-артефакт плана
stg plan approve <ID>                   # commit spec в dev + attach к task
stg verify                              # TLA+ lifecycle model + live invariants
stg dispatcher --once                   # один тик
stg dispatcher --watch                  # демон: старт/финиш/уведомления
stg dispatcher --all --once             # один тик по registry
stg judge search "куда деплоить"
stg judge add "куда деплоить?" --decision "только через поезд" \
  --quote "не выкатываем без гейта" --source decisions/runbook.md
stg metrics                             # human touches, gate failures, anonymous
stg board audit                         # события без actor/project
stg retro --days 7 --write              # weekly lessons report
stg critique <ID>                       # независимый critic, другой model
```

Инварианты P0:

- `stg task` не создаёт ветку/воркtree — только request, доску и Plan-вкладку.
- `stg plan approve` — единственный человеческий шаг: спеку валидирует и
  коммитит в `dev` worktree, задача становится runnable.
- `dispatcher` — детерминированный цикл, не LLM: стартует задачи со спекой,
  финишит заснувшего worker'а, пишет lead'у про `task.blocked`, соблюдает WIP.
- `stg judge` не выдумывает: ищет решения с цитатой/источником/датой; пусто —
  эскалация человеку.
- `stg lead` — человек говорит только с lead-вкладкой; worker'ы блокируются
  через `stg board block`, без AskUserQuestion.

## Состояние (2026-11-01)

Реализованы S0–S7 и P0 dark factory: intake, plan approval + HTML artifact,
dispatcher, lead-канал, judge/decisions, metrics/audit, weekly retro, critic
tab, source idempotency. Formal TLA+/TLC, auto-judge, enforced critic,
proactive watchers, Telegram/GitHub and cost telemetry — следующие слои.

Проверено в этом окружении:

- `uv run pytest -q` — 77 passed; `uv run ruff check .` — clean.
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
