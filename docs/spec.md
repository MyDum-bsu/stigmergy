# Stigmergy v1 — спецификация

Статус: draft на согласование. Дата: 2026-11-01.
Источник решений: гриллинг с владельцем (сессия ZCode), урок «Dark factory AI
agent» (LearnHarness), ресерч polomodov / Абдуллин / Ваковский / теория
стигмергии.

## 0. Резюме

`stigmergy` — универсальный контур тёмной фабрики: append-only лог событий,
машина состояний над короткими эпизодами, исполняемая приёмка с якорным и живым
оракулом, очередь интеграции и мержа. Ядро не знает имён раннеров и продуктов:
Herdr, pi, ручной запуск — адаптеры на краю. Первый полигон — `optimization`;
первый реальный мерж — T5.

Продукт: отдельный репозиторий `~/Desktop/projects/stigmergy`, пакет
`stigmergy`, CLI `stg`, Python 3.12 stdlib, без runtime-зависимостей.

## 1. Проблема

В `optimization` уже есть доска (291 событие), worktree на задачу, `make test` /
`make lint`, CI и эвалы. Но нет центра:

- `board done --evidence` принимает **текст от агента**, контур DoD не исполняет;
- `specs/` пуст — decision procedure ни одной задачи не существует;
- пять worktree в `~/src/*` впереди `dev` на 1–22 коммита (у T6 23 грязных
  файла), ни одна задача не слита — интеграционной станции нет;
- kit доски лежит в `~/.zcode/workspace/draft-.../stigmergy-kit`, вне git;
- привязки: `bench/pilot.py` знает `~/.zcode/cli/zcode-headless.cjs`,
  `AGENTS.md` больше не предписывает внешний worktree-менеджер; HUD читает sqlite ZCode и `bd`.

Урок «Dark factory»: тёмная фабрика — контур, где человек задаёт критерий, но не
выносит вердикт; вход — decision procedure; оракул якорный и живой; ущерб
ограничен правами и обратимостью; фабрика — машина состояний над эпизодами;
инструменты — на краю.

## 2. Цели и не-цели

Цели v1:

1. Провести реальную задачу от очереди до `dev` без ручного вердикта.
2. Держать состояние вне модели: любой раннер продолжает задачу с того же места.
3. Исполнять DoD контуром и писать evidence, которое агент не может подделать.
4. Гарантировать якорь (критерий не правится эпизодом) и живость (гейт умеет
   падать) оракула.
5. Ограничить ущерб правами (bwrap) и обратимостью (worktree, merge queue,
   `main` не пишется).
6. Портируемость: одна установка, per-repo конфиг, ноль имён продуктов в ядре.
7. Доказать сменяемость раннера: один эпизод через `manual` и `pi/Herdr` даёт
   эквивалентные события.

Не-цели v1: межмашинный синк событий, центральный сервер, авто-разрешение
конфликтов, маршрутизация моделей, Windows, Telegram-бот (адаптер позже),
замена CI (CI остаётся, может вызывать `stg gate`).

## 3. Принципы

1. **Событие — единственный state.** Проекции (`views/`, dash) пересобираемы.
2. **Человек на критерии, не на вердикте.** Утверждение спеки и high-risk —
   человек; вердикт «готово» — гейт.
3. **Якорь + живость.** Критерий и его носитель восстанавливаются из base;
   негативный корпус доказывает, что гейт падает.
4. **Ущерб — правами и обратимостью.** bwrap-профиль, allowlist, `main`
   защищён, мерж только в `dev`.
5. **Инструменты на краю.** Раннер, workspace, sandbox, notifier — адаптеры.
6. **Короткие эпизоды, состояние вне модели.** Эпизод можно прервать и
   продолжить.
7. **Детерминированный лог, вероятностные агенты.** Рой не является
   источником истины.
8. **Один писатель на задачу.** Claim + lease + отдельный worktree.

## 4. Домен и язык

| Термин | Значение |
|---|---|
| Проект | git-репозиторий с `.agent/` и `.agent.toml` |
| Задача | единица работы: id, title, spec, deps, priority, risk, status |
| Спека | decision procedure: frontmatter + Given/When/Then; неизменна в эпизоде |
| Claim | lease на задачу; ветка `task/<id>-<sha>` |
| Workspace | git worktree задачи под `.factory/worktrees/` |
| Эпизод | один прогон агента: base, prompt, runner handle, артефакты |
| Гейт | исполнение DoD в чистом gate-worktree с oracle из base; `gate.json` |
| Оракул | тесты, эталоны, фикстуры, конфиги — то, что определяет критерий |
| Негативный контроль | заведомо плохие артефакты, на которых гейт обязан краснеть |
| Интеграция | rebase на `dev` + полный гейт на собранном дереве |
| Мерж | fast-forward `dev`; `main` не трогается |
| Evidence | артефакты гейта/интеграции + событие с хешами |
| Контур | CLI `stg`, машина состояний без демона |
| Раннер | адаптер эпизода: `manual`, `herdr` |
| Workspace provider | адаптер worktree: `git`, `herdr worktree` |
| Notifier | адаптер внимания человека: `dash`, `herdr`, позже Telegram |

## 5. Архитектура

```
Уровень 0  ~/.agents/RULES.md            глобальные правила и запреты
Уровень 1  <repo>/AGENTS.md + docs/      проектные правила
Уровень 2  specs/<ID>.md                 decision procedure задачи
Уровень 3  .agent/events.jsonl           координация: события, claim, evidence
Уровень 4  контур stg                    станции, guard'ы, gate, merge queue
Уровень 5  адаптеры                      runner / workspace / sandbox / notify
```

Компоненты пакета:

```
stigmergy/
  pyproject.toml            console script stg = stigmergy.cli:main
  src/stigmergy/
    cli.py                  argparse, подкоманды
    log.py                  append-only JSONL, flock, seq, eventId
    model.py                Task, Spec, Claim, Episode, Gate, Station
    state.py                проекции состояния из событий
    spec.py                 парсер/валидатор спеки, canonical hash
    workspace.py            git worktree provider
    runner/                 base.py, manual.py, herdr.py
    sandbox.py              bwrap-профили episode/gate, canary
    gate.py                 gate-worktree, oracle restore, negative control
    integrate.py            merge queue, rebase, ff dev
    planner.py              DAG, priority, WIP, конфликты путей
    dash.py                 stdlib HTTP + HTML, только события/артефакты
    doctor.py               проверка окружения и адаптеров
    migrate.py              валидация legacy-лога, перенос .agent
  tests/
  docs/
```

## 6. События

Один лог `.agent/events.jsonl`, схема `stigmergy/v1` остаётся. Новые actions
аддитивны; старые читатели их игнорируют. Один писатель — `stg` под
`flock(.agent/lock)`.

Базовые поля (как в текущей доске): `schema`, `seq`, `timeUnixNano`,
`observedTimeUnixNano`, `traceId`, `spanId`, `parentSpanId`, `severityText`,
`action`, `actor{kind,name}`, `attributes`, `body`.

Добавляется `eventId` (uuid4) для будущего экспорта/импорта; у старых событий
его нет — читатель синтезирует стабильный id из `schema:seq:traceId`.

Новые actions:

| Action | Когда |
|---|---|
| `spec.created` | спека создана и провалидирована |
| `spec.approved` | человек утвердил спеку (criterion) |
| `spec.rejected` | человек отклонил |
| `workspace.created` / `workspace.removed` | worktree задачи |
| `episode.started` / `episode.heartbeat` / `episode.finished` / `episode.failed` / `episode.stopped` | прогон агента |
| `gate.started` / `gate.passed` / `gate.failed` | DoD в gate-worktree |
| `control.passed` / `control.failed` | негативный корпус |
| `integration.started` / `integration.passed` / `integration.failed` | rebase + full gate |
| `merge.done` / `merge.reverted` | ff `dev` |
| `task.requeued` | красный гейт/конфликт, назад в очередь |
| `budget.exceeded` | лимит времени/токенов |
| `factory.paused` / `factory.resumed` | kill switch |
| `board.migrated` | перенос legacy-лога |

Обязательные attributes по станциям:

- claim: `task.id`, `task.sha`, `spec.sha`, `agent.name`, `lease.until`,
  `vcs.base`, `vcs.branch`, `paths.allowed`.
- workspace: `workspace.path`, `vcs.branch`, `vcs.base`.
- episode: `episode.id`, `runner.kind`, `runner.handle`, `sandbox.profile`,
  `prompt.sha`, `budget.*`.
- gate: `gate.command`, `gate.exit_code`, `gate.duration_ms`,
  `gate.artifact`, `gate.stdout_sha256`, `gate.stderr_sha256`,
  `oracle.sha`, `control.result`, `vcs.commit`, `vcs.tree`.
- integration/merge: `vcs.base_before`, `vcs.base_after`, `vcs.commit`,
  `vcs.tree`, `integration.artifact`.

Инварианты: `seq` строго растёт; `timeUnixNano = max(now, last+1)`; `traceId =
sha256(project + ":" + task_id)[:16]`; `task.sha` меняется при изменении
смысла задачи; `spec.sha` фиксируется на claim.

## 7. Станции и guard'ы

```
proposed --approve--> queued
queued --claim--> claimed
claimed --workspace--> workspace
workspace --episode.start--> episode
episode --episode.finish--> gate
gate --gate.passed--> integration
gate --gate.failed--> queued (requeue) | blocked (2-й провал) | failed
integration --integration.passed--> merge
integration --integration.failed--> queued (конфликт) | blocked
merge --merge.done--> done
любая --block--> blocked --answer--> queued
любая --pause--> paused --resume--> queued
```

| Станция | Guard |
|---|---|
| claim | deps done; WIP < limit; `allowed_paths` не пересекаются с активными; spec valid; spec.sha зафиксирован; budget есть |
| workspace | ветка `task/<id>-<sha>` создана от `vcs.base`; worktree чист; путь свободен |
| episode.start | sandbox готов; runner готов; prompt собран; бюджет выставлен |
| episode.finish | коммит/дерево снято контуром; workspace не пуст либо `episode.empty` |
| gate | commit существует; oracle diff пуст; gate inputs из base; negative control прогнан; DoD exit 0 |
| integration | gate green; rebase чист; full gate на rebased tree green |
| merge | `dev` fast-forward возможен; risk high требует `spec.approved` человека; `main` не тронут |
| done | артефакты записаны, хеши совпадают, worktree убран |

Повторный прогон станции идемпотентен: если артефакт с теми же хешами уже есть,
он переиспользуется; события не дублируются (кроме heartbeat).

## 8. Спека задачи

`specs/<ID>.md`:

```markdown
---
id: T5
title: Похоронить beads и оставить только доску
risk: low
deps: []
allowed_paths:
  - AGENTS.md
  - .gitignore
  - .beads/**
oracle_paths:
  - tests/**
  - Makefile
  - pyproject.toml
  - uv.lock
gate_inputs:
  - Makefile
  - pyproject.toml
  - uv.lock
  - pytest.ini
dod: bash -lc 'make test && make lint && ! git ls-files .beads | grep -q . && ! grep -q "Beads Issue Tracker" AGENTS.md'
negative_control:
  corpus: oracle/negative/t5/
budget:
  wall_seconds: 1800
  tokens: 120000
---

## Intent
Убрать beads из git и из AGENTS.md; доска `.agent/` остаётся единственным
трекером.

## Given
`dev` содержит bd-блок в `AGENTS.md` и `.beads` в индексе.

## When
Контур применяет ветку T5 и запускает DoD.

## Then
`make test`, `make lint` зелёные; `.beads` не в индексе; bd-блока в AGENTS.md
нет.

## Forbidden
Не удалять локальную Dolt-базу владельца; не трогать `tracker/data/`.
```

Правила валидации `stg spec validate`:

- `id` совпадает с именем файла; `risk ∈ {low, medium, high}`;
- `allowed_paths` непуст, без абсолютных путей и `..`;
- `dod` непуст и не содержит интерактивных команд;
- `oracle_paths` и `gate_inputs` существуют в base;
- `negative_control.corpus` существует для `risk >= medium`;
- `spec.sha = sha256(canonical(frontmatter) + "\n" + body)`.

Изменение oracle — отдельная задача с человеческим `spec.approved`. Если эпизод
меняет `oracle_paths`, гейт всё равно восстановит их из base; такие изменения
попадут в diff, но не в вердикт. Легальная правка критерия = новый base.

## 9. Гейт

Алгоритм `stg gate run <task>`:

1. Взять `C` (commit эпизода) и `B` (base, `dev` на claim).
2. Посчитать `oracle.sha` по `oracle_paths`/`gate_inputs` на `B`.
3. Создать gate-worktree на `C` в `.factory/gate/<task>-<episode>` — вне
   workspace агента.
4. Восстановить oracle и gate inputs из `B`: `git checkout B -- <paths>`;
   проверить `git diff B -- <paths>` пуст; смонтировать ro.
5. Применить sandbox-профиль `gate` (network off, `$HOME` tmpfs, `data/` и
   креды не видны).
6. Запустить `dod` через `bash -lc` с таймаутом, санитизированным env, записать
   stdout/stderr, exit code, длительность.
7. Негативный контроль: для каждого патча из `corpus` — отдельный worktree,
   применить патч, запустить `dod`, ожидать non-zero. Любой зелёный → гейт
   мёртв (`control.failed`). Кеш по `(dod, oracle.sha, env.sha, corpus.sha)`.
8. Записать `gate.json` и логи в `.factory/artifacts/<task>/<episode>/`;
   `sha256` каждого файла; событие `gate.passed|failed`.

`gate.json`:

```json
{
  "schema": "stigmergy/gate/v1",
  "task": "T5",
  "episode": "ep_...",
  "base": "<sha>",
  "commit": "<sha>",
  "tree": "<sha>",
  "oracle_sha": "<sha256>",
  "command": "bash -lc '...'",
  "exit_code": 0,
  "duration_ms": 12345,
  "stdout": {"path": "stdout.log", "sha256": "..."},
  "stderr": {"path": "stderr.log", "sha256": "..."},
  "control": {"result": "passed", "cases": 3, "corpus_sha": "..."},
  "env": {"python": "3.12", "uv": "...", "ci": "1"}
}
```

Провал: `task.requeued` с артефактом и счётчиком; второй провал той же приёмки
— `blocked` (правило loop-gate: не ретраить одно и то же). Оракул, который
никогда не падал, не считается проверенным: `control.result=absent` запрещает
мерж для `risk >= medium`.

## 10. Права (bwrap)

Два профиля:

| Профиль | root | workspace | oracle | $HOME / data / creds | network |
|---|---|---|---|---|---|
| episode | ro | rw | ro | скрыты (tmpfs) | только модель/прокси |
| gate | ro | rw (oracle ro) | ro | скрыты | off |

Детали:

- `bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --tmpfs $HOME
  --die-with-parent --new-session --clearenv`.
- workspace — единственный rw-каталог; `.git` ro, кроме
  `.git/worktrees/<task>` (минимум для чтения/диффа).
- `data/`, `tracker/data/`, `~/.ssh`, `~/.config`, `~/.zcode` не монтируются.
- gate: `unshare-net`, `dod` обязан быть офлайн; если тесту нужен network —
  отдельный `risk` и явное поле спеки.
- episode: сеть только к провайдеру модели; при наличии прокси — `HTTPS_PROXY`
  и allowlist домена. Секреты провайдера остаются у раннера, не в workspace.
- `stg sandbox check` — канарейка: `~/.ssh` не читается, `data/` отсутствует,
  workspace пишется, oracle ro, network off (gate).
- Herdr + bwrap: `HERDR_AGENT=pi` помечает обёрнутый процесс, чтобы Herdr
  распознал агента; это проверяется спайком (см. риски). Если не сработает —
  эпизод идёт через `manual`, Herdr остаётся кокпитом без права вердикта.

## 11. Раннеры

Интерфейс:

```
start(task, spec, workspace, prompt) -> handle
status(handle) -> running | blocked | done | error | unknown
read(handle, lines) -> text
prompt(handle, text) -> ok
stop(handle) -> ok
normalize(handle) -> {tokens, cost, duration, exit_code}
```

`manual`: печатает промпт и workspace, ждёт `stg episode finish <task>`; любой
харнесс (ZCode desktop, pi, Herdr) может выполнить работу. Это дефолт для
отладки и первый адаптер.

`herdr`:

- systemd `--user` юнит `stigmergy-herdr.service` с `ExecStart=herdr --session
  factory`; установка — `stg herdr install-service` (печатает юнит; включает
  только по `--yes`).
- Фабрика **не поднимает** Herdr из шелла агента (урок OOM: восстановление
  сессии запустило 7 `pi` и убило память). Только attach к сервису.
- Guard: `herdr --session factory workspace list`; если есть чужие workspace
  (не `stg-*`) — отказ. `stg herdr reset` архивирует session-файл сессии.
- Flow: `workspace create --cwd <workspace> --label stg-<task> --no-focus` →
  `agent start <name> --kind pi --pane <id>` → `agent prompt ... --wait` →
  `agent get/read` → статус Herdr используется только как живость/UX.
- `blocked` от Herdr → `episode.blocked` + уведомление человеку; ответ только
  через `stg board answer`.
- Stop: `agent send-keys ctrl+c`, `pane close`, `workspace close`.
- `unknown`/таймаут не означает «готово»; вердикт даёт только дерево + гейт.
- Провайдер: `opencode-go` / `deepseek-v4.1-flash` через `pi`, без смены
  моделей в v1.

Конформанс: один синтетический эпизод прогоняется через `manual` и `herdr`;
сравниваются последовательности actions и поля evidence (без
runner-специфичных). Это доказательство сменяемости.

## 12. Интеграция и мерж

Очередь мержа, один writer:

1. `integration.started`: интеграционный worktree `.factory/integration` на
   `dev`.
2. `git rebase dev <task-commit>`; конфликт → `integration.failed` +
   артефакт, `task.requeued`; повтор → `blocked`.
3. Полный гейт на rebased tree (тот же алгоритм, oracle из нового `dev`).
4. `merge.done`: `git merge --ff-only <rebased>` в интеграционном worktree;
   `dev` двигается только fast-forward.
5. `done`: evidence, удаление worktree задачи, ветка остаётся до мержа/удаления
   по политике; `main` не трогается.

High-risk: перед `merge` требуется `spec.approved` человека (событие
`task.blocked` с вопросом «мержить?» → `board answer --by human`).

## 13. Планировщик

`stg next`:

- status `queued`, deps `done`, spec valid, WIP < `wip`, budget есть;
- `allowed_paths` не пересекаются с активными claim/workspace;
- порядок: priority asc, затем seq создания;
- атомарный claim + lease 30 мин (`heartbeat` продлевает);
- нет задачи — `NO_TASK`, не изобретать работу.

WIP v1 = 1; после зелёного цикла — 2–3. Бюджет: wall/tokens на эпизод;
превышение → `budget.exceeded`, эпизод гасится, задача возвращается.

## 14. Наблюдаемость

- Проекции: `views/Current.md`, `Backlog.md`, `Worklog.md` — из событий, не
  руками.
- `stg status`, `stg log`, `stg show`, `stg status --all` по реестру
  `~/.config/stigmergy/projects.toml`.
- `stg dash`: stdlib HTTP+HTML на 127.0.0.1:8787, панели очередь / активный
  эпизод / гейт / очередь мержа / бюджет / лента. Только события и артефакты;
  **никакого sqlite ZCode и `bd`**.
- `mo-swarm` переписывается на `stg dash`; `mo-hud` позже читает
  `stg status --json`.

## 15. Конфиг

`<repo>/.agent.toml`:

```toml
[project]
name = "optimization"
base = "dev"
protected = ["main"]
wip = 1

[workspace]
provider = "git"
root = ".factory/worktrees"

[gate]
default_dod = "make test"
timeout_seconds = 1800
network = false

[sandbox]
engine = "bwrap"
episode_network = "proxy"
gate_network = "none"
mask = ["$HOME", "data", "tracker/data", ".ssh"]

[runner]
kind = "herdr"
session = "factory"
agent = "pi"
sandbox = true

[risk]
low = "auto"
medium = "auto"
high = "human"
```

Реестр `~/.config/stigmergy/projects.toml`:

```toml
[[project]]
name = "optimization"
root = "/home/mydum/Desktop/projects/optimization"
board = ".agent"
```

Приоритет правил: спека → `AGENTS.md` → `~/.agents/RULES.md`. В `.agent.toml`
только механизм, не правила.

## 16. Миграция Big Bang

Условия, без которых Big Bang запрещён:

1. `stg` реализует все команды, которые сегодня использует доска:
   `add/propose/approve/reject/next/claim/heartbeat/block/answer/done/fail/
   pr/note/ask/list/show/log/status/render`.
2. Схема событий совместима; `stg migrate --check` валидирует 291 событие
   (seq, поля, actions) и сравнивает `list/show/status` с текущим `board` на
   выборке задач.
3. `stg board render` даёт те же три проекции.

Шаги:

1. Создать репозиторий `~/Desktop/projects/stigmergy`, пакет, CLI, тесты.
2. `stg migrate --from ~/src/optimization/.agent --to
   ~/Desktop/projects/optimization/.agent`: копия лога, `board.migrated` с
   хешем источника; старый каталог остаётся как backup.
3. `stg doctor` и `stg board render` в главном чекауте optimization.
4. Установить `stg` (`uv tool install`), убрать `board` из PATH/доков,
   обновить `AGENTS.md` (раздел «Доска задач») на `stg`.
5. Догфудинг T5 (см. приёмку).
6. Старый kit в draft-workspace не удалять; пометить как legacy в отчёте.

Откат: вернуть старый `board` и `.agent` из backup; события не переписывались,
поэтому откат безопасен.

## 17. Приёмка v1

A. `stg doctor` зелёный на optimization: git, bwrap, systemd, Herdr-сессия,
   провайдер `pi`, реестр.

B. T5 end-to-end (реальный мерж):

- задача `T5-land` создана из ветки `task/T5-fbe810` (1 коммит, `done`);
- `stg next` клеймит её, workspace создан от `dev`;
- эпизод (manual или pi) не меняет дерево либо вносит правку; контур коммитит
  и снимает `commit`/`tree`;
- гейт в gate-worktree: `make test && make lint && ! git ls-files .beads |
  grep -q . && ! grep -q "Beads Issue Tracker" AGENTS.md` → exit 0;
- негативный контроль: патч, возвращающий `.beads` или bd-блок, гейт краснеет;
- интеграция: rebase на `dev`, full gate, ff `dev`;
- события всех станций, `gate.json` с хешами, `views/` пересобраны, `stg dash`
  показывает прогон.

C. Конформанс: синтетическая задача (например, `hello()` + тест) через
   `manual` и `herdr/pi` даёт одинаковую последовательность станций и
   эквивалентный evidence (runner-поля исключены).

D. Чистота ядра: тест `test_no_tool_names` — в `src/stigmergy/` вне
   `runner/` и `workspace/` нет строк `zcode|orca|herdr|pi` (кроме докстрингов
   адаптеров).

E. Sandbox-канарейка: `~/.ssh` и `data/` не читаются, workspace пишется,
   oracle ro, gate network off.

## 18. Риски и открытые вопросы

| Риск | Митигация |
|---|---|
| Herdr восстанавливает сохранённую сессию и запускает N агентов (OOM 01.11: 7 `pi`) | отдельная сессия `factory` в systemd, guard на чужие workspace, лимит панелей = WIP, не стартовать из шелла агента |
| Herdr не распознаёт `pi` внутри bwrap | `HERDR_AGENT=pi`; спайк; fallback — `manual` эпизод, Herdr только кокпит |
| `pi` не отдаёт usage/токены | бюджет по wall time + артефакты; токены — best effort |
| Полный `make test` долгий | таймаут, кеш по хешам, позже селективный прогон |
| Легальная правка oracle | отдельная задача с human approve; иначе гейт восстановит base |
| Конфликт rebase | `integration.failed` + requeue; повтор → block |
| Big Bang ломает текущий поток | условия §16, `migrate --check`, backup `.agent` |
| bwrap и `.git` worktree | `.git` ro, `.git/worktrees/<task>` rw; спайк |
| Дашборд без auth | bind 127.0.0.1, без внешнего доступа |

Открытые вопросы для спайков: Herdr session storage для `--session factory`;
`HERDR_AGENT` + bwrap; `pi --mode json` usage; `.git` ro при `pi`-тулах.

## 19. Вне скоупа v1

Межмашинный синк, центральный сервер, Telegram, авто-разрешение конфликтов,
маршрутизация моделей, Windows/macOS, замена CI, `stg promote` в `main`,
автоматическое изменение oracle.

## 20. Решения (журнал)

1. Продукт — отдельный пакет, не в монорепо.
2. Автономия: человек на критерии и high-risk; low/medium авто до `dev`.
3. Состояние — локальный лог на репо + реестр проектов.
4. Оракул — gate-worktree + restore из base + hash + негативный корпус.
5. Интеграция — очередь мержа: rebase → full gate → ff `dev`.
6. Спека — markdown+frontmatter, DoD-команда + negative control.
7. Планировщик — DAG + приоритет + WIP + конфликты путей.
8. Эпизод завершает контур (коммит + tree).
9. Схема — один лог, аддитивные actions.
10. WIP 1, затем 2–3.
11. Дашборд — переписать `mo-swarm` на события.
12. Догфудинг — T5 первым.
13. Права — bwrap-профиль.
14. Раннер — Herdr в systemd-сессии `factory`, внутри `pi`; ZCode headless не
    нужен.
15. Имя — `stigmergy` / `stg`; стек — Python 3.12 stdlib.
16. v1 DoD — T5 end-to-end + конформанс.

## 21. Статус реализации v0.1 (2026-11-01)

Реализовано в `src/stigmergy/`: лог с flock/seq/eventId, проекции, доска,
спеки, planner, worktree, gate + негативный контроль, bwrap-профили, очередь
интеграции, episode manual/noop, Herdr-адаптер + systemd-юнит, dash, registry,
doctor, migrate.

Уточнения, принятые при реализации:

- `allowed_paths` проверяются гейтом: diff эпизода от merge-base до commit
  обязан укладываться в шаблоны; иначе `exit 126` до запуска DoD.
- Oracle и негативный корпус читаются из `base` через git, а не из рабочего
  дерева: главный чекаут может стоять на `main`.
- Herdr-статусы (`done`) не считаются вердиктом; экран читается после промпта,
  `429/401/403/5xx` валят эпизод.
- `herdr status` и `doctor` используют `--session factory`; guard допускает
  один пустой home-workspace `~`.
- `stg dash` по умолчанию на 8787; при живом `mo-swarm` использовать
  `--port 8788`.

Проверено: 29 pytest, ruff clean, T5 end-to-end на клоне optimization
(`a9f57f6`), bwrap-канарейка, `migrate --check` реального лога (292 события,
105 задач). Herdr-конформанс: на двух одинаковых фикстурах `manual` и `herdr`
дали одинаковую цепочку из 13 действий; `pi` использовал ключ OpenCode Go 3
(`opencode-go-chat-3`), эпизод `H1` дошёл до `merge.done`, workspace закрыт.
Не проверено: реальный T5-мерж в `optimization/dev` и обновление `AGENTS.md`.

