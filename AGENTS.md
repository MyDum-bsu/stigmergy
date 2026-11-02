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
