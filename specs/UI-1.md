---
id: UI-1
title: Herdr mod Mission Control
risk: medium
deps: []
allowed_paths:
  - mods/mission-control/**
oracle_paths: []
gate_inputs: []
dod: "test -f mods/mission-control/mod.json && test -f mods/mission-control/main.js && herdr-app check mods/mission-control && ! test -f stigmergy-kit"
negative_control:
  corpus: oracle/negative/UI-1/
---

## Intent
Сделать первый срез Mission Control как Herdr-мод в нативном приложении:
карточки агентов и пространств, статусы, счётчики, тёплый тёмный стеклянный
вид.

## What to do
Создай `mods/mission-control/`:

- `mod.json`: панель справа, title `Mission Control`, size около 380.
- `main.js`: панель на `gpui-kit` + модуль `herdr`.
- Скопируй `jsconfig.json` и `gpui-kit.d.ts` из
  `~/.config/herdr-app/mods/agents/` (это разрешённые файлы в mods/**).

Панель должна показывать:

1. Заголовок `Mission Control` и счётчики: working / blocked / done / idle.
2. Карточки агентов: имя, пространство, статус, длительность. Цвета:
   blocked — красный, working — синий/акцент, done — зелёный, idle — серый.
3. Карточки пространств: имя, папка, число терминалов.
4. Клик по карточке агента — `run("agent.focus", { terminal })`; по
   пространству — `run("space.select", { id })`.

Смотри примеры: `~/.config/herdr-app/mods/agents/main.js`,
`~/.config/herdr-app/mods/spaces/main.js`, API — `~/.config/herdr-app/AGENTS.md`
и `herdr.d.ts`. Стиль: тёмный тёплый фон, полупрозрачные карточки, мягкие
границы, скругления; без внешних зависимостей.

## Forbidden
Не менять другие моды, код stigmergy, `~/.config/herdr-app` (только читать).
