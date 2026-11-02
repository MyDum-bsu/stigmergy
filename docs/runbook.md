# Runbook

## 1. Установка

```bash
cd ~/Desktop/projects/stigmergy
uv tool install --editable .
stg --version
```

Проверка окружения в проекте:

```bash
cd <repo>
stg doctor
```

`bwrap`, `systemd --user`, `herdr`, `pi` — опциональные для `doctor`, но
обязательные для соответствующих профилей.

## 2. Новый проект

```bash
cd <repo>
stg init                 # .agent/, .agent.toml, specs/, .factory/, .gitignore
stg project add <name>   # глобальный реестр ~/.config/stigmergy/projects.toml
```

В `.agent.toml` задаются `base` (по умолчанию `dev`), `wip`, гейт и раннер.
Секреты и `data/` в репозиторий не попадают — их маскирует sandbox-профиль.

## 3. Спека

```bash
stg spec new T1 --title "..."     # шаблон specs/T1.md
$EDITOR specs/T1.md               # risk, allowed_paths, oracle_paths, dod, negative_control
stg spec validate specs/T1.md --base dev
```

Правила: `dod` — одна неинтерактивная команда; `oracle_paths` — то, что
определяет критерий; `negative_control.corpus` обязателен для medium/high.
Спека коммитится в `base` до постановки задачи: гейт читает её из `base`, а не
из рабочего дерева.

## 4. Задача и ручной эпизод

```bash
stg board add T1 --spec specs/T1.md
stg run T1 --runner manual        # печатает промпт и workspace
# ... работа в workspace ...
stg episode finish T1 --auto      # контур коммитит, гейтит, интегрирует, мержит
```

`--auto` делает `gate → control → integration → merge`; high-risk останавливается
на `blocked` и ждёт `stg board answer`.

## 5. Автоматический прогон (без агента)

```bash
stg run T1 --runner noop --auto --no-sandbox
```

Полезен для догфудинга и проверки контура: контур берёт HEAD ветки задачи,
исполняет DoD, прогоняет негативный контроль и мержит.

## 6. Herdr как раннер

Один раз:

```bash
stg herdr install-service --enable    # systemd --user, сессия factory
stg herdr doctor                      # server running
stg herdr guard                       # только stg-* workspace + пустой "~"
```

Фабрика **не поднимает** Herdr из шелла агента: сессия `factory` живёт в
systemd, фабрика только аттачится. `herdr` внутри сессии запускает `pi`;
провайдер — `opencode-go` / `deepseek-v4.1-flash`.

Workspace эпизода **остаётся открытым** (`runner.keep_workspace = true`), чтобы
процесс было видно:

```bash
herdr --session factory     # панели stg-<ID>
stg herdr list              # label/id/status
stg herdr cleanup           # закрыть все stg-* после просмотра
stg herdr cleanup --task ID # только одну
```

Важно: у OpenCode Go три ключа. `pi auth` должен указывать на **третий**
(`opencode-go-chat-3` из `~/.zcode/v2/provider_config.json`), иначе эпизод
получает `429 GoUsageLimitError`. Ключ не печатать и не коммитить; проверка
живого вызова:

```bash
pi -p "Reply exactly: pi-ok" --model opencode-go/deepseek-v4.1-flash --no-session --thinking off
```

Если провайдер вернул ошибку (429/401/5xx), адаптер читает экран и валит
эпизод, а не считает `done` вердиктом. Проверка:

```bash
stg herdr reset-session --yes         # архивирует состояние сессии factory
```

## 7. Дашборд

```bash
stg dash --port 8788 --open
```

Читает только события и артефакты; ZCode sqlite и `bd` не используются.
Реестр проектов — `~/.config/stigmergy/projects.toml`.

## 8. Свойства, live-model и high-risk

Спека может добавить проверки, которые исполняет контур:

```yaml
properties:
  command: "python3 -m pytest tests/property -q"
  seeds: 32
live_model:
  command: "python3 tests/live_model.py"
```

`properties` запускается на каждом seed (`STG_SEED`) в одноразовом worktree;
`live_model` — один раз с `STG_LIVE_MODEL=1`. Для `risk: high` нужен хотя бы
один из блоков; гейт исполняет formal + critic + эти проверки и не мержит
high-risk без human answer.

```bash
stg pbt <ID>                 # прогон вручную, вне гейта
stg verify <ID>              # TLA+ core + per-task модель
```

## 9. Модели и бенчмарки

Маршруты задаются в `.agent.toml`; ядро не угадывает модель:

```toml
[models]
default = "provider/base"
worker = "provider/fast"
planner = "provider/reasoning"
critic = "provider/other"
lead = "provider/reasoning"
bench_command = "my-model-cli --model {model} --prompt-file {prompt_file}"
```

```bash
stg model list
stg model route --stage worker
stg model bench --cases evals/cases.jsonl --model provider/fast
```

Бенчмарк-команда получает `STG_MODEL`, `STG_PROMPT_FILE`, `STG_EXPECTED`;
`expected` из JSONL проверяется как подстрока. Отчёт пишется в
`.factory/benchmarks/`.

## 10. Регулярные задания

```bash
stg schedule install --enable
stg schedule status
```

`stigmergy-learn.timer` — еженедельный `stg learn --days 7`;
`stigmergy-persona.timer` — ежедневный ingest
`.factory/persona/inbox.jsonl` (формат JSONL: `question`, `decision`, `quote`,
`source`, `date`). Повторный ingest идемпотентен; digest —
`persona/<date>.md`.

## 11. Promotion в main

```bash
stg promote                    # dry-run: fast-forward, dev_ahead, dirty
stg promote --apply            # только человек, только fast-forward
```

`--apply` требует human token и отказывается при грязном дереве,
non-fast-forward или `main`, занятом в другом worktree. `main` не трогается
фабрикой автоматически.

## 12. Внешние адаптеры

```toml
[notify]
telegram_token_env = "STG_TELEGRAM_TOKEN"
telegram_chat_id = ""
webhook_url = ""

[visual]
command = "my-visual-acceptance --target {target}"  # получает STG_VISUAL_TARGET
```

```bash
stg notify --text "gate failed"          # dry-run, без сети
stg notify --text "gate failed" --send   # человек; реальный Telegram/webhook
stg visual check --target http://127.0.0.1:3000
stg visual check --target http://127.0.0.1:3000 --run  # человек
```

Токен Telegram берётся из env, не из репозитория. `mirror github --apply`
также требует human token; без него — только dry-run payloads.

## 13. GitHub как канал связи

```toml
[github]
repo = ""                 # пусто → gh repo view (origin)
label = "stigmergy"       # какие issues импортировать
```

```bash
stg github status
stg github sync                    # dry-run: import + comments
stg github sync --apply             # человек: импорт issues + push комментариев
stg github sync --apply --no-push   # только импорт
stg github comment <ID> --text "..."
stg github pr <ID> --push
stg github checks <ID>
```

Issue с меткой `stigmergy` становится request/task; `stg:<ID>` в labels или
`github.issue.linked` связывает issue с задачей. Комментарии issue пишутся в
board как `github.comment.in`; `task.note`/`task.answered` после link уходят
в issue при `--push`. `task.pr` хранит PR URL, `checks` читает CI, но вердикт
по-прежнему даёт gate, не GitHub. Все write-операции требуют human token.

## 14. Диагностика

| Симптом | Что проверить |
|---|---|
| `NO_TASK` | deps, WIP, пересечение `allowed_paths`, `paused` |
| `control=dead` | DoD зелёный на заведомо плохом патче — критерий мёртв |
| `allowed_paths` 126 | diff эпизода выходит за `allowed_paths` |
| `spec changed after claim` | спека правилась после claim — новая задача |
| `herdr guard failed` | в сессии `factory` чужие workspace — `reset-session` |
| `GoUsageLimitError` | квота провайдера; эпизод падает, не мержится |
| `database is locked` (board) | второй писатель; `flock` ждёт, проверь долгий процесс |

## 15. Безопасность

- `main` не пишется фабрикой; мерж только в `base` (`dev`), fast-forward.
- `data/`, `tracker/data/`, `$HOME`, SSH и креды не видны в episode/gate.
- Gate network off; episode network — только провайдер/прокси.
- Деструктивные команды — только человек; `board answer --by human`.
