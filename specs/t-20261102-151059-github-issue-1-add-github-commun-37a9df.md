---
id: t-20261102-151059-github-issue-1-add-github-commun-37a9df
title: Добавить раздел «GitHub» о коммуникации агентов в AGENTS.md
risk: low
auto_approve: true
deps: []
allowed_paths:
  - AGENTS.md
oracle_paths:
  - oracle/t-20261102-151059-github-issue-1-add-github-commun-37a9df/test_agents_md_github_section.py
gate_inputs: []
skills:
  - ~/.agents/skills/matt-writing-for-agents/SKILL.md
dod: "python3 -m pytest -q oracle/t-20261102-151059-github-issue-1-add-github-commun-37a9df/test_agents_md_github_section.py"
negative_control:
  corpus: oracle/negative/t-20261102-151059-github-issue-1-add-github-commun-37a9df/
---

## Intent

В `AGENTS.md` появляется раздел `## GitHub`, фиксирующий правила работы с
GitHub для агентов: issue — зеркало, доска — источник истины, вход через
`gh issue`, выход через `gh pr` и привязка PR к задаче доски (`stg board`,
`board pr <id> --pr <N>`). Критерий проверяется тестом
`tests/test_agents_md_github_section.py`, который ставится при approval и
worker'ом не редактируется.

## Given

- `AGENTS.md` в корне worktree содержит разделы `# Stigmergy — правила
  разработки`, `## Работа`, `## Приёмка`, `## Ветки` и не содержит раздела про
  GitHub.
- При approval в worktree появляется oracle-тест
  `tests/test_agents_md_github_section.py` (источник:
  `oracle/t-20261102-151059-github-issue-1-add-github-commun-37a9df/`), который
  читает `AGENTS.md` из корня репозитория и проверяет:
  1. раздел `## GitHub` существует ровно один раз;
  2. в его теле встречаются токены `gh issue`, `gh pr`, `stg board`,
     `MyDum-bsu/stigmergy`;
  3. в теле не меньше 4 строк списка, начинающихся с `- `;
  4. в теле (без учёта регистра) есть корень `зеркал` и корень `доск`;
  5. в теле нет заглушек `TBD` и `TODO`;
  6. заголовки `# Stigmergy`, `## Работа`, `## Приёмка`, `## Ветки` на месте.
- `uv run pytest -q` и `uv run ruff check .` настроены в `pyproject.toml`
  (`testpaths = ["tests"]`, line-length 120, python >= 3.12).

## When

Задача добавляет в `AGENTS.md` ровно один новый раздел `## GitHub` и ничего
больше не меняет.

## Then

- `uv run pytest -q tests/test_agents_md_github_section.py` завершается с кодом 0
  на ветке задачи и с ненулевым кодом на базе (до правки раздела нет).
- Раздел написан по-русски, в стиле файла, содержит вступление одной строкой и
  список из 4–7 пунктов; в пунктах названы: `gh issue` (вход и чтение задач),
  `gh pr` (выход: PR в `dev`), `stg board` (учёт) и `board pr <id> --pr <N>`
  (привязка PR к задаче), а также явное утверждение, что issue — зеркало, а
  доска — источник истины, со ссылкой на `MyDum-bsu/stigmergy`.
- `uv run pytest -q` зелёный, `uv run ruff check .` зелёный.
- Negative control: `git apply oracle/negative/<ID>/kit.patch` (заголовок
  `## GitHub` + `TBD`) даёт падение oracle-теста; после `git checkout -- AGENTS.md`
  рабочее состояние восстанавливается.

## Forbidden

- Менять, переставлять, переформатировать существующие разделы `AGENTS.md` и
  удалять из них строки.
- Писать раздел уровня `###` вместо `## GitHub` или добавлять второй раздел
  про GitHub.
- Править `tests/**`, `oracle/**`, `specs/**`, `prd/**`, `src/**`,
  `pyproject.toml`, `.agent.toml`.
- Вставлять заглушки (`TBD`, `TODO`, «здесь будет…») в раздел.
- Упоминать в разделе секреты, токены, содержимое `.env`/`credentials`.
- Копировать раздел в другие файлы за пределами `AGENTS.md`.
- Закрывать issue, пушить в `main`/`dev` или вызывать `stg board done` из
  задачи: это делает контур, а не worker.
