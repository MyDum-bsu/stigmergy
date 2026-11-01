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

## 8. Диагностика

| Симптом | Что проверить |
|---|---|
| `NO_TASK` | deps, WIP, пересечение `allowed_paths`, `paused` |
| `control=dead` | DoD зелёный на заведомо плохом патче — критерий мёртв |
| `allowed_paths` 126 | diff эпизода выходит за `allowed_paths` |
| `spec changed after claim` | спека правилась после claim — новая задача |
| `herdr guard failed` | в сессии `factory` чужие workspace — `reset-session` |
| `GoUsageLimitError` | квота провайдера; эпизод падает, не мержится |
| `database is locked` (board) | второй писатель; `flock` ждёт, проверь долгий процесс |

## 9. Безопасность

- `main` не пишется фабрикой; мерж только в `base` (`dev`), fast-forward.
- `data/`, `tracker/data/`, `$HOME`, SSH и креды не видны в episode/gate.
- Gate network off; episode network — только провайдер/прокси.
- Деструктивные команды — только человек; `board answer --by human`.
