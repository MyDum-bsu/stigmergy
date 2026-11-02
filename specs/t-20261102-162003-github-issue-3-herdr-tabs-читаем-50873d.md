---
id: t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d
title: Herdr tabs — читаемые имена, закрытие по событию задачи, безопасная уборка
risk: medium
auto_approve: false
deps: []
allowed_paths:
  - src/stigmergy/runner/herdr_app.py
  - src/stigmergy/runner/herdr.py
  - src/stigmergy/episode.py
  - src/stigmergy/intake.py
  - src/stigmergy/critic.py
  - src/stigmergy/lead.py
  - src/stigmergy/wave.py
  - src/stigmergy/dispatcher.py
  - src/stigmergy/cli.py
  - tests/**
oracle_paths:
  - oracle/t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d/test_herdr_tabs_oracle.py
gate_inputs:
  - pyproject.toml
invariants:
  - Lead и Board вкладки существуют в единственном числе и не закрываются ни одним путём уборки.
  - Space проекта один; повторный lead не создаёт второй space и вторую Lead-вкладку.
  - Вкладка закрывается только если её имя разобрано как Plan/Worker/Critic и сработало правило статуса или осиротелости.
  - Ошибка herdr-app пробрасывается как HerdrAppError, а не превращается в пустой результат.
dod: "uv run pytest -q oracle/t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d/test_herdr_tabs_oracle.py"
negative_control:
  corpus: oracle/negative/t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d/
---

## Intent

Вкладки Herdr в space проекта должны читаться человеком и умирать вместе с задачей.
Сейчас `HerdrAppRunner.start` называет вкладку `task_id` (длинный `t-...` slug),
`close_task_tabs` вызывается только на merge, уборка `cleanup` закрывает целые space
`stg-*`, а не вкладки, и не знает про Lead/Board. Нужно: label из title + короткий
стабильный маркер, закрытие Plan/worker/Critic по событию задачи, безопасный sweep
осиротевших и завершённых вкладок, ровно один Lead и один space.

## Given

- `src/stigmergy/runner/herdr_app.py` — адаптер `herdr-app`: `spaces()` (`herdr-app ls`),
  `_do(app, command, **kwargs)` (`herdr-app do`), `get(terminal)` (`hc get`),
  `ensure_space`, `create_space`, `create_tab`, `unique_name`, `close_task_tabs`,
  `cleanup`, `HerdrAppError`, `DEFAULT_APP = "herdr-app"`, `DEFAULT_AGENT = "pi"`.
- id задач вида `t-YYYYMMDD-HHMMSS-<slug>-<hash>`; статусы доски: `queued`, `claimed`,
  `blocked`, `done`, `merged`, `failed`, `cancelled`.
- Терминальный статус задачи: `done`, `merged`, `failed`, `cancelled`.
- `spaces()` может не отдавать `created_at` у вкладки — это допустимо.
- `Lead` и `Board` — вкладки пространства проекта, живут дольше любой задачи.

## When

1. Открывается Plan-, Worker- или Critic-вкладка для задачи.
2. Задача завершается (`stg episode finish`, `stg worker done`) или план одобрен
   (`stg plan approve`).
3. Человек или dispatcher запускает уборку вкладок.
4. Запускается `stg lead` при уже существующем space и Lead-вкладке.

## Then

В `src/stigmergy/runner/herdr_app.py` появляются (имена и сигнатуры — контракт,
oracle-тесты вызывают их напрямую):

```python
MAX_TAB_LABEL = 48
PROTECTED_TAB_PREFIXES = ("Lead", "Board")
TAB_KINDS = ("Plan", "Worker", "Critic")
TERMINAL_STATUSES = ("done", "merged", "failed", "cancelled")

def short_id(task_id: str, length: int = 6) -> str: ...
def tab_label(kind: str, title: str, task_id: str, max_len: int = MAX_TAB_LABEL) -> str: ...
def is_protected_tab(name: str) -> bool: ...
def managed_kind(name: str) -> str | None: ...
def ensure_lead_tab(app: str = DEFAULT_APP, space: str = "", folder: Path | None = None,
                    agent: str = DEFAULT_AGENT, task: str = "") -> dict: ...
def close_task_tabs(app: str = DEFAULT_APP, task_id: str = "") -> list[str]: ...
def cleanup_tabs(app: str = DEFAULT_APP, statuses: Mapping[str, str] | None = None, *,
                 now: float | None = None, stale_after_s: int = 6 * 3600,
                 dry_run: bool = False) -> list[str]: ...
```

Поведение:

1. `short_id` — `sha256(task_id.encode("utf-8")).hexdigest()[:length]`, строчные hex,
   детерминирован, при `length=6` даёт 6 символов.
2. `tab_label(kind, title, task_id)` → `"<kind> · <title> [<short>]"`:
   - из title вырезаются `task_id` и токены, начинающиеся с `t-` и содержащие 8 цифр даты;
   - пробелы схлопываются; пустой результат даёт `"<kind> · [<short>]"`;
   - результат не длиннее `max_len` символов, обрезка по символам с `…`, маркер
     `[<short>]` сохраняется целиком и всегда стоит в конце.
3. `is_protected_tab(name)` — ровно этот вид:

```python
def is_protected_tab(name: str) -> bool:
    """Lead and Board tabs outlive every task."""
    return name.startswith(PROTECTED_TAB_PREFIXES)
```

4. `managed_kind(name)` — `"Plan"`/`"Worker"`/`"Critic"` для имён вида `"<Kind> · ..."`,
   `"Worker"` для legacy `<task_id> · ...` и `stg-<task_id>`, иначе `None`.
   Маркер вкладки — завершающий `[xxxxxx]`, у legacy-имён маркера нет.
5. `ensure_lead_tab` возвращает `{"created": bool, "tab": <tab>}`: ищет вкладку с именем
   ровно `Lead` в space по имени; если есть — `created=False`, ничего не создаёт; если
   нет — создаёт одну вкладку через `create_tab`. `space.new` не вызывается никогда:
   space проекта уже существует (`ensure_space`).
6. `close_task_tabs(app, task_id, title="")` закрывает вкладки, у которых
   `managed_kind(name) is not None` и выполняется одно из:
   маркер равен `short_id(task_id)`, имя равно `f"<Kind> · {task_id}"`,
   `f"Plan · {task_id}"`/`f"Critic · {task_id}"`, имя начинается с `f"{task_id} ·"` или
   с `f"{PREFIX}{task_id}"`. `is_protected_tab(name)` проверяется первым и блокирует
   закрытие. Возвращает имена закрытых вкладок; закрытие — `_do(app, "tab.close",
   id=..., confirmed="true")`.
7. `cleanup_tabs` идёт по `spaces(app)` и закрывает вкладку только если:
   - `is_protected_tab(name)` — False (проверяется первым), и
   - `managed_kind(name)` не None, и
   - `statuses` содержит задачу с этим маркером (сопоставление по `short_id` ключа
     `statuses`) и её статус в `TERMINAL_STATUSES`; **или** задача не найдена и
     (все её терминалы отсутствуют или `get(terminal)` бросает `HerdrAppError`)
     **или** (`created_at` есть и `now - created_at >= stale_after_s`).
   `statuses=None` трактуется как пустое отображение. `now` по умолчанию —
   `time.time()`. `dry_run=True` возвращает имена, но не закрывает ничего.
   Возвращает имена закрытых (или отобранных) вкладок.
8. `HerdrAppError` из `spaces`/`_do`/`get` не глотается: `cleanup_tabs`,
   `close_task_tabs`, `ensure_lead_tab` пробрасывают её наружу.
9. Точки вызова:
   - `HerdrAppRunner.start` называет вкладку через `tab_label(kind, title, task_id)`
     (Plan — планировщик, Worker — воркер, Critic — критик); длинный `task_id` в имени
     вкладки не остаётся;
   - `stigmergy/episode.py` после успешного `finish_episode` и `stigmergy/ui`-точка
     `worker done` вызывают `close_task_tabs(app, task_id)`;
   - `stigmergy/intake.py::approve_plan` после успешного approve вызывает
     `close_task_tabs(app, task_id)`;
   - `stigmergy/lead.py` создаёт Lead через `ensure_lead_tab`, второй space не
     создаёт; уже существующая вторая Lead-вкладка закрывается как дубль.
   В этих точках `HerdrAppError` ловится на границе: печатается одна строка
   `herdr: tabs not closed: <reason>` и exit-код остаётся кодом основной операции.
10. CLI `stg app cleanup` получает `--dry-run` и передаёт в `cleanup_tabs` текущие
    статусы из доски; вывод — по одному имени в строке, `nothing to close` при пустом
    результате, ненулевой код и текст причины при `HerdrAppError`.
11. Собственные тесты воркера (`tests/**`) покрывают новый label, `close_task_tabs`,
    `cleanup_tabs` и `ensure_lead_tab`; существующие `tests/test_herdr.py` зелёные.

## Forbidden

- Править `oracle_paths` и файлы под `oracle/`; ослаблять oracle-тесты.
- Закрывать вкладку, имя которой не разобрано как Plan/Worker/Critic, либо чей путь
  ведёт к Lead/Board, либо которая принадлежит живой (не терминальной) задаче.
- Закрывать целые Herdr space (`space.close`) в рамках этой задачи как замену
  закрытию вкладок; `herdr.cleanup` (workspaces `stg-*`) не переиспользовать для вкладок.
- Создавать второй space проекта, `unique_name`-суффиксы вида `stigmergy-2` для Lead.
- Молчаливые `except: pass`, ретраи, фоллбэки «если herdr недоступен — вернуть пустой
  список», подмена ошибки пустым результатом.
- Менять публичные сигнатуры существующих `spaces`, `_do`, `get`, `create_space`,
  `create_tab`, `close_space`, `HerdrAppRunner`.
- Новые зависимости, изменения `pyproject.toml`, правки gate/merge/board-схемы.
- Правки вне `allowed_paths` (включая `.agent/`, `specs/`, `docs/`).
