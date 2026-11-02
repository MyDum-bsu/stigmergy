# Stigmergy — правила разработки

Этот репозиторий разрабатывается через собственный контур: `stg` — доска,
спека, gate, merge. Человек утверждает только normal/high-risk план; fast
lane для мелких обратимых правок проходит policy-approve.

## Работа

- `stg doctor` — окружение; `stg status` — доска.
- `stg task --quick "<идея>"` — мелкая правка; `stg task "<идея>"` — обычная.
- `stg plan show <ID>` / `stg plan serve <ID> --open` — посмотреть план.
- `stg plan approve <ID>` — только человек, normal/high-risk.
- `stg lead` — вкладка Lead в space `stigmergy`; worker'ы открываются в нём же.
- `stg dispatcher --watch` — один dispatcher на проект, не запускать два.
- Worker блокируется через `stg board block`; завершает `stg worker done`.
  Не вызывай `stg board done` сам.
- Gate — вердикт. Не правь `oracle_paths`; не мержи `main` вручную.

## Приёмка

```bash
uv run pytest -q
uv run ruff check .
```

Для high-risk — `formal` + mutant + critic report + PBT/live-model. Для
medium/high обязателен negative control.

## Ветки

Рабочая ветка — `dev`; `main` только через `stg promote --apply` после
человеческого go-ahead. Feature-ветка живёт до merge в `dev`.

## GitHub

GitHub (`MyDum-bsu/stigmergy`) — внешний слой коммуникации: issue — зеркало,
источник истины — доска.

- Вход: issue с меткой `stigmergy`; `stg github sync --apply` импортирует его в
  request/task, комментарии issue попадают в board как `github.comment.in`.
  `gh issue view <N>` / `gh issue list` — только чтение внешнего слоя.
- Выход: `stg github pr <id> --push` или `gh pr create --base dev`; PR
  привязывается к задаче через `stg board pr <id> --url <ссылка>`.
- Учёт: `stg board list|show <id>|status`; issue не является вторым трекером,
  его состояние не заменяет событие доски.
- Ревью и комментарии: `stg github comment <id> --text ...` или `gh pr comment`;
  обсуждение ведёт доска, issue — уведомление.
- Закрытие: `worker done` → gate → merge; issue закрывает контур после
  `task.done`, не worker.
