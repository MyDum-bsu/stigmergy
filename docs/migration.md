# Big Bang migration

Цель: заменить `stigmergy-kit/bin/board` на `stg` без переписывания событий.

## Условия (проверены)

- `stg` реализует все команды доски: add/propose/approve/reject/next/claim/
  heartbeat/block/answer/done/fail/note/ask/list/show/log/status/render/pr.
- Схема `stigmergy/v1` совместима; новые actions аддитивны.
- `stg migrate --check` проходит на реальном логе.

Текущий реальный лог (2026-11-01):

```
count=292  tasks=105  last_seq=292
sha256=c9966dcef03f04d35728323fc1eb6086d824d20861d5a52c2551a75c990a90cf
path=/home/mydum/src/optimization/.agent/events.jsonl
```

## Шаги

1. Бэкап:

```bash
cp -a /home/mydum/src/optimization/.agent /home/mydum/Desktop/projects/optimization/.agent.bak-$(date +%Y%m%d)
```

2. Проверка:

```bash
stg migrate --check /home/mydum/src/optimization/.agent
```

3. Перенос в главный чекаут (канонический `.agent`):

```bash
stg migrate \
  --from /home/mydum/src/optimization/.agent \
  --to /home/mydum/Desktop/projects/optimization \
  --project optimization
```

`migrate` копирует события, добавляет `board.migrated` с числом и sha256
источника, пересобирает `views/`.

4. Проверка:

```bash
cd /home/mydum/Desktop/projects/optimization
stg doctor
stg board list
stg board render
stg status
```

5. Обновить `AGENTS.md` (раздел «Доска задач») на `stg`; убрать путь
   `stigmergy-kit/PROTOCOL.md` и команды `board`. Сделать это отдельной задачей
   на `dev`, а не прямым коммитом в `main`.

6. Убрать `board` из PATH/доков. Старый kit в
   `~/.zcode/workspace/draft-.../stigmergy-kit` не удалять — архив.

7. Догфудинг T5:

```bash
stg board add T5-land --spec specs/T5-land.md \
  --sha fbe810a335bd5562 --branch task/T5-fbe810 --priority 1
stg run T5-land --runner noop --auto --no-sandbox
```

Спека T5 и негативный корпус должны быть закоммичены в `dev` до запуска.

## Откат

События не переписываются; откат безопасен:

```bash
rm -rf /home/mydum/Desktop/projects/optimization/.agent
mv /home/mydum/Desktop/projects/optimization/.agent.bak-YYYYMMDD \
   /home/mydum/Desktop/projects/optimization/.agent
# вернуть board из архива kit в PATH
```

## Что остаётся за человеком

- `approve`/`reject`/`answer` — только `--by human`.
- High-risk merge — `stg board answer` перед `stg merge`.
- `main` — только человек, после приёмки.
