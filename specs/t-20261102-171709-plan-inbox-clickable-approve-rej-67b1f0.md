---
id: t-20261102-171709-plan-inbox-clickable-approve-rej-67b1f0
title: Clickable approve/reject в plan inbox для normal и high lane
risk: medium
auto_approve: false
deps: []
allowed_paths:
  - src/stigmergy/planinbox.py
  - src/stigmergy/plan*.py
  - src/stigmergy/cli.py
  - src/stigmergy/dash.py
  - tests/test_plan*.py
  - docs/runbook.md
oracle_paths:
  - oracle/t-20261102-171709-plan-inbox-clickable-approve-rej-67b1f0/test_plan_inbox_actions.py
gate_inputs: []
invariants:
  - Одно человеческое действие даёт не больше одного события доски.
  - Токен действия привязан к plan_id и digest спеки; чужой или подделанный токен не меняет состояние.
  - Отклонённый/подделанный запрос не вызывает apply.
  - После approve или reject повторный клик отвечает 409 и не применяет действие.
  - Fast lane и уже решённые планы не показывают кнопок.
skills:
  - ~/.agents/skills/workflow-worker/SKILL.md
dod: "uv run pytest -q oracle/t-20261102-171709-plan-inbox-clickable-approve-rej-67b1f0"
negative_control:
  corpus: oracle/negative/t-20261102-171709-plan-inbox-clickable-approve-rej-67b1f0/
---

## Intent

Человек утверждает normal/high-risk план кликом на странице плана, которую
открывает `stg plan serve <ID> --open`, вместо набора `stg plan approve <ID>`.
Клик и CLI идут через один и тот же путь применения: тот же валидатор спеки,
тот же коммит в `dev` worktree, то же событие доски — с отличием `via=inbox`
в событии, чтобы аудит видел человеческое действие.

## Given

- Существующие `stg plan approve <ID>` / `stg plan serve <ID> --open` и рендер
  HTML-артефакта плана; `stg plan auto <ID>` для fast lane.
- Новый модуль `src/stigmergy/planinbox.py` (stdlib, без зависимостей) с публичным
  контрактом — единственная точка, которую проверяет oracle:

  ```python
  PLAN_ACTIONS: tuple[str, str] = ("approve", "reject")

  def action_token(plan_id: str, spec_sha: str, secret: str) -> str: ...

  def actions_html(
      plan_id: str, *, spec_sha: str, secret: str, lane: str, state: str
  ) -> str: ...

  def handle_action(
      plan_id: str,
      action: str,
      *,
      token: str,
      spec_sha: str,
      secret: str,
      state: str,
      apply: Callable[[str], None],
  ) -> tuple[int, str]: ...
  ```

- `lane` ∈ `{"normal", "high", "fast"}`, `state` ∈ `{"pending", "approved", "rejected"}`.
- `action_token` — детерминированный HMAC-SHA256 hex от `plan_id` и `spec_sha`
  с ключом `secret`.
- `actions_html` возвращает HTML-фрагмент с двумя `POST`-формами на
  `/plan/<plan_id>/action/approve` и `/plan/<plan_id>/action/reject`, каждая с
  hidden-полем `token` = `action_token(plan_id, spec_sha, secret)`.
- `handle_action` — чистый обработчик: возвращает `(status, body)` и вызывает
  `apply(action)` максимум один раз.

## When

- Рендер/серв страницы плана для `lane in {"normal", "high"}` и `state == "pending"`.
- HTTP `POST` на `/plan/<plan_id>/action/<approve|reject>` с `token`.
- Ручной запуск `stg plan approve`/`reject` (старый путь) — поведение не меняется.

## Then

1. `actions_html(..., lane="normal" | "high", state="pending")` содержит обе формы,
   `method="post"`, оба action-URL и токен ровно дважды; `lane="fast"` или
   `state in {"approved", "rejected"}` → пустая строка `""`.
2. `handle_action` с валидным токеном и `state="pending"` → `200` и ровно один
   вызов `apply(action)` с `"approve"` или `"reject"`; тело содержит итоговое состояние.
3. Подделанный токен, токен другого плана, токен от другого `spec_sha` → `403`,
   `apply` не вызывается. Проверка токена идёт до проверки состояния: подделанный
   токен на уже решённом плане тоже даёт `403`, а не `409` и не утечку состояния.
4. `state != "pending"` при валидном токене → `409`, `apply` не вызывается.
5. `action` вне `PLAN_ACTIONS` → `400`, `apply` не вызывается.
6. Неизвестный `plan_id` → `404` на уровне HTTP-обвязки, событий доски не появляется.
7. HTTP-обвязка: сервер слушает `127.0.0.1`, принимает только `POST` на путь
   действия, отклоняет чужой `Host`, сериализует применение блокировкой, токен не
   пишет в лог. Применение действия — тот же код, что у `stg plan approve/reject`.
8. High risk: approve без зелёного preflight (formal + mutant + critic + negative
   control) → `409` с перечнем недостающего, состояние плана не меняется.
9. Событие доски для действия из страницы содержит `via=inbox` и человеческий
   `actor`; повторный клик второго события не создаёт.

## Forbidden

- Менять `oracle_paths`, `stg plan auto`, policy fast lane и схему событий доски.
- Делать approve доступным агенту: новый CLI-флаг обхода токена, `--force`,
  переменная окружения «approve без токена», скрытый ретрай или фоллбэк, при
  котором отсутствующий токен считается валидным.
- Отдавать страницу действия по `GET` с изменением состояния (GET только читает).
- Слушать `0.0.0.0`, добавлять внешнюю авторизацию, зависимости вне stdlib.
- Глотать ошибки применения: сбой коммита спеки → код 5xx и причина в теле,
  без «approved» в ответе.
- Править файлы вне `allowed_paths` (включая `tests/` сверх `tests/test_plan*.py`).
