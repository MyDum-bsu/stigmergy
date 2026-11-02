---
id: t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d
created: 2026-11-02T16:20:03+0300
source: github
source_id: MyDum-bsu/stigmergy#3
trust: untrusted
---

# Raw request

GitHub issue #3: Herdr tabs: читаемые имена и автоматическая уборка

Сейчас вкладки названы длинным task id/кодом, скапливаются, Lead/Board теряются, активные задачи не видны одновременно.

Нужно:
- читаемый label из title (без длинного t-... slug), короткий стабильный идентификатор;
- Plan/worker/Critic вкладки закрывать после завершения/approve, не только после merge;
- cleanup старых завершённых/осиротевших Plan/worker вкладок, не трогая Lead и Board;
- не создавать второй Lead/space.

Результат: код + тесты; Herdr остаётся, board source of truth.

https://github.com/MyDum-bsu/stigmergy/issues/3

This request came from GitHub; the issue is a mirror, the board is the source of truth.
