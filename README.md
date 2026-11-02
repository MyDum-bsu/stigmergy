# stigmergy

Универсальный контур тёмной фабрики: append-only лог событий, машина состояний
над короткими эпизодами, исполняемая приёмка с якорным и живым оракулом, очередь
интеграции и мержа. Ядро не знает имён раннеров: Herdr, pi, ручной запуск —
адаптеры на краю.

Пакет `stigmergy`, CLI `stg`, Python 3.12 stdlib, без runtime-зависимостей.

stigmergy разрабатывается через self-host в space `stigmergy`.

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
stg bootstrap --name myproj              # init + Lead tab (no manual commands)
stg task --quick "мелкая правка"          # compact fast-lane spec
stg plan list
stg plan show <ID>
stg plan preflight <ID>                # oracle/corpus проверка до approve
stg plan render <ID>                    # HTML-артефакт плана
stg plan approve <ID>                   # human: commit spec в dev + attach
stg plan auto <ID>                      # policy fast lane, no token
stg verify                              # TLA+ lifecycle model + live invariants
stg dispatcher --once                   # один тик
stg dispatcher --watch                  # демон: старт/финиш/уведомления
stg dispatcher --all --once             # один тик по registry
stg judge search "куда деплоить"
stg judge decide "куда деплоить?"
stg judge eval
stg judge import --file decisions/nightly.jsonl
stg usage add --task <ID> --stage check --prompt-tokens 100
stg learn --days 7
stg persona ingest --file .factory/persona/inbox.jsonl
stg schedule install --enable            # weekly learn + nightly persona timers
stg model list                           # stage → model routing
stg model route --stage worker
stg model bench --cases evals/cases.jsonl --model <model>
stg pbt <ID>                             # property seeds + live-model probe
stg promote                              # dry-run dev → main (human --apply)
stg notify --text "gate failed"          # dry-run; --send is human-only
stg visual check --target http://...     # dry-run; --run is human-only
stg feed --file .factory/inbox.jsonl
stg source status                        # triggers / mandates
stg github status                        # repo + linked issues
stg github sync                          # dry-run issue/comment sync
stg github sync --apply                  # human: import issues + push comments
stg github comment <ID> --text "..."     # human: comment on linked issue
stg github pr <ID> --push                # human: open PR from task branch
stg github checks <ID>
stg mutation <ID>
stg mirror github
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

## Состояние (2026-11-02)

Реализованы S0–S7, P0 dark factory, M1 trust baseline и M2–M5:
intake, plan approval + HTML artifact, dispatcher, lead-канал, judge/decisions,
metrics/audit, formal TLA+/TLC (core + per-task mutant), auto-judge, enforced
critic, PBT/live-model checks, usage/cost, feed, plan UI, mirror adapter,
stage routing and a benchmark harness. Weekly learn and nightly persona are
installed as user systemd timers on this machine.

Проверено в этом окружении:

- `uv run pytest -q` — 143 passed; `uv run ruff check .` — clean.
- T5 end-to-end на клоне `optimization`: `stg run T5-land --runner noop --auto
  --no-sandbox` → `gate.passed`, `control.proven`, `integration.passed`,
  `merge.done`; `dev` fast-forward на `a9f57f6`, `.beads` не в дереве,
  bd-блока в `AGENTS.md` нет.
- High-risk live fixture: `formal` core/task PASS, mutant rejected, critic
  report clean, properties 3/3 seeds, live-model PASS, negative control
  proven; задача остановлена на `task.blocked` «High-risk merge HR».
- Real PBT on `optimization`: `mo_grader.scoring.compute` — 50 seeds × 500
  cases, 25 000 проверок инвариантов балла (`0 ≤ score ≤ weight`,
  `Σ tasks == total`, `total ≤ hw_max`).
- `stg sandbox check` — bwrap-канарейка `ok`.
- Herdr: systemd-сессия `factory` запущена; `pi` с ключом OpenCode Go 3
  (`opencode-go-chat-3`) прошёл реальные эпизоды `S8a` (конфиг + скилл) и
  `S8b2` (AGENTS.md на `stg`); `S8b` — пример плохого критерия: агент
  заблокировался, гейт покраснел, DoD исправлен в `S8b2`. Workspace эпизода
  остаётся открытым (`stg herdr list`, `herdr --session factory`).
- `optimization/main` fast-forward до `59f6f67` (22 коммита): factory docs/
  specs/decisions, дедлайны hw10–19, tracker UI fix; `make test` — 809
  passed, 1 skipped, `make lint` — clean.
- `stg notify` / `stg visual` — dry-run adapters; real `--send`/`--run` требуют
  human token. GitHub mirror `--apply` — human token, реального создания
  issues не было.
- GitHub communication: `stg github sync` (dry-run) / `--apply` импортирует
  issues с меткой `stigmergy`, связывает их с задачами, переносит комментарии
  в board и обратно; `stg github pr/checks` — PR и CI-статусы. Board остаётся
  source of truth.
- `stg migrate --check /home/mydum/src/optimization/.agent` — 292 события,
  105 задач, схема валидна.
- timers: `stigmergy-learn.timer` → Mon 09:00, `stigmergy-persona.timer` →
  03:30 daily; both `active`.

Внешние действия (Telegram/cloud, visual `--run`, GitHub issue apply) в этом
прогоне не выполнялись — только dry-run adapters; для них нужен явный
go-ahead владельца.

## Быстрый старт

```bash
uv tool install --editable .
cd <repo> && stg init && stg doctor
stg spec new T1 && stg spec validate specs/T1.md --base dev
stg board add T1 --spec specs/T1.md
stg run T1 --runner manual
stg episode finish T1 --auto
```
