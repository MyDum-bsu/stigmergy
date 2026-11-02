"""Oracle: Herdr tabs — readable labels, lifecycle close, safe cleanup.

This file is the criterion, not a suggestion: it is restored from the base
before the gate, so editing it inside the task worktree changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stigmergy.runner import herdr_app

LONG = "t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d"
OTHER = "t-20261101-090000-github-issue-9-another-task-abcdef"
GHOST = "t-20260901-000000-github-issue-7-ghost-task-000000"
FOREIGN = "t-20250101-000000-foreign-agent-thing-111111"


class FakeApp:
    """Stands in for the herdr-app process: spaces and tabs live in memory."""

    def __init__(self, spaces):
        self.spaces_list = []
        for space in spaces:
            copy = dict(space)
            copy["tabs"] = [dict(tab) for tab in space.get("tabs", [])]
            self.spaces_list.append(copy)
        self.commands: list[tuple[str, dict]] = []
        self.dead: set[str] = set()

    # ── module-level replacements ──────────────────────────────────────────
    def spaces(self, app=None):
        return self.spaces_list

    def get(self, terminal):
        if terminal in self.dead:
            raise herdr_app.HerdrAppError(f"terminal {terminal} is gone")
        return {"status": {"state": "idle"}, "turn": 1}

    def do(self, app, command, **kwargs):
        self.commands.append((command, kwargs))
        if command == "tab.new":
            name = str(kwargs["name"])
            tab = {
                "id": f"tab-{len(self.commands)}",
                "name": name,
                "terminals": [f"term-{len(self.commands)}"],
            }
            for space in self.spaces_list:
                if space.get("name") == kwargs.get("space"):
                    space["tabs"].append(tab)
                    break
            return {"id": tab["id"], "terminal": tab["terminals"][0], "name": name}
        return {"ok": True}

    def ensure_app(self, app=None, wait_seconds=15):
        return {"ok": True}

    # ── assertions helpers ────────────────────────────────────────────────
    def closed(self) -> list[str]:
        return [str(kwargs.get("id", "")) for command, kwargs in self.commands if command == "tab.close"]

    def called(self, command: str) -> list[dict]:
        return [kwargs for name, kwargs in self.commands if name == command]


def install(monkeypatch, app: FakeApp) -> FakeApp:
    monkeypatch.setattr(herdr_app, "spaces", app.spaces)
    monkeypatch.setattr(herdr_app, "get", app.get)
    monkeypatch.setattr(herdr_app, "_do", app.do)
    monkeypatch.setattr(herdr_app, "ensure_app", app.ensure_app)
    return app


def tab(name: str, terminals=("alive",)) -> dict:
    return {"id": f"id-{name}", "name": name, "terminals": list(terminals)}


def space(name: str, *tabs) -> dict:
    return {"name": name, "id": f"space-{name}", "tabs": list(tabs)}


# ── labels ────────────────────────────────────────────────────────────────
def test_short_id_is_short_stable_and_distinct() -> None:
    first = herdr_app.short_id(LONG)
    assert first == herdr_app.short_id(LONG)
    assert len(first) == 6
    assert all(char in "0123456789abcdef" for char in first)
    assert herdr_app.short_id(OTHER) != first
    assert herdr_app.short_id(GHOST) != first


def test_label_is_readable_and_carries_the_marker() -> None:
    marker = f"[{herdr_app.short_id(LONG)}]"
    label = herdr_app.tab_label("Plan", "читаемые имена вкладок и автоуборка", LONG)
    assert label.startswith("Plan · ")
    assert "читаемые имена" in label
    assert LONG not in label
    assert "t-2026" not in label
    assert marker in label
    assert len(label) <= herdr_app.MAX_TAB_LABEL


def test_label_truncates_a_long_title_and_keeps_the_marker() -> None:
    marker = f"[{herdr_app.short_id(LONG)}]"
    label = herdr_app.tab_label("Worker", "я" * 300, LONG)
    assert len(label) <= herdr_app.MAX_TAB_LABEL
    assert marker in label
    assert "…" in label


def test_label_drops_the_task_slug_used_as_a_title() -> None:
    label = herdr_app.tab_label("Worker", LONG, LONG)
    assert LONG not in label
    assert "t-2026" not in label
    assert len(label) <= herdr_app.MAX_TAB_LABEL


def test_label_survives_an_empty_title_and_an_inner_separator() -> None:
    marker = f"[{herdr_app.short_id(LONG)}]"
    empty = herdr_app.tab_label("Critic", "   ", LONG)
    assert empty.startswith("Critic · ")
    assert marker in empty
    dotted = herdr_app.tab_label("Plan", "a · b · c", LONG)
    assert dotted.startswith("Plan · ")
    assert marker in dotted


# ── lifecycle close ───────────────────────────────────────────────────────
def test_close_task_tabs_closes_only_the_finished_task(monkeypatch) -> None:
    owned = [
        herdr_app.tab_label("Plan", "читаемые вкладки", LONG),
        herdr_app.tab_label("Worker", "читаемые вкладки", LONG),
        herdr_app.tab_label("Critic", "читаемые вкладки", LONG),
        f"Plan · {LONG}",  # name written before this change
        f"{LONG} · worker",  # name written before this change
    ]
    kept = [
        "Lead",
        "Board",
        herdr_app.tab_label("Plan", "другая задача", OTHER),
    ]
    app = install(monkeypatch, FakeApp([space("stigmergy", *[tab(name) for name in owned + kept])]))

    closed = herdr_app.close_task_tabs(app=herdr_app.DEFAULT_APP, task_id=LONG)

    assert set(closed) == set(owned)
    assert "Lead" not in closed
    assert "Board" not in closed
    assert herdr_app.tab_label("Plan", "другая задача", OTHER) not in closed
    assert len(app.closed()) == len(closed)


# ── cleanup sweep ─────────────────────────────────────────────────────────
def test_cleanup_closes_terminal_and_dead_orphans_only(monkeypatch) -> None:
    finished = [
        herdr_app.tab_label("Plan", "законченная задача", LONG),
        herdr_app.tab_label("Worker", "законченная задача", LONG),
    ]
    live = [herdr_app.tab_label("Worker", "живая задача", OTHER)]
    orphan = [herdr_app.tab_label("Plan", "осиротевшая вкладка", GHOST)]
    foreign_live = [herdr_app.tab_label("Critic", "чужой живой агент", FOREIGN)]
    protected = ["Lead", "Board", f"Lead · {herdr_app.tab_label('Plan', 'з', LONG)}"]

    app = install(
        monkeypatch,
        FakeApp(
            [
                space(
                    "stigmergy",
                    *[tab(name, ("alive",)) for name in finished + live + foreign_live],
                    tab(orphan[0], ("dead",)),
                    *[tab(name, ("alive",)) for name in protected],
                )
            ]
        ),
    )
    app.dead = {"dead"}

    closed = herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "done", OTHER: "claimed"})

    assert set(closed) == set(finished) | set(orphan)
    assert len(app.closed()) == len(closed)


def test_cleanup_keeps_a_live_orphan_and_closes_a_stale_one(monkeypatch) -> None:
    stale = herdr_app.tab_label("Worker", "старая осиротевшая", GHOST)
    fresh = herdr_app.tab_label("Worker", "свежая осиротевшая", FOREIGN)
    old = {"id": "id-old", "name": stale, "terminals": ["t-old"], "created_at": 1_000.0}
    new = {"id": "id-new", "name": fresh, "terminals": ["t-new"], "created_at": 99_000.0}
    app = install(monkeypatch, FakeApp([space("stigmergy", old, new)]))

    closed = herdr_app.cleanup_tabs(
        herdr_app.DEFAULT_APP,
        {},
        now=100_000.0,
        stale_after_s=3_600,
    )

    assert set(closed) == {stale}
    assert app.closed() == ["id-old"]


def test_cleanup_dry_run_reports_without_closing(monkeypatch) -> None:
    finished = [herdr_app.tab_label("Plan", "законченная задача", LONG)]
    app = install(monkeypatch, FakeApp([space("stigmergy", *[tab(name) for name in finished])]))

    names = herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "merged"}, dry_run=True)

    assert set(names) == set(finished)
    assert app.closed() == []


def test_cleanup_does_not_swallow_app_errors(monkeypatch) -> None:
    def boom(app=None):
        raise herdr_app.HerdrAppError("herdr-app is not running")

    monkeypatch.setattr(herdr_app, "spaces", boom)

    with pytest.raises(herdr_app.HerdrAppError):
        herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "done"})


# ── one lead, one space ───────────────────────────────────────────────────
def test_lead_tab_and_space_are_created_once(monkeypatch) -> None:
    app = install(monkeypatch, FakeApp([space("stigmergy")]))
    folder = Path("/tmp/stigmergy")

    first = herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=folder)
    second = herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=folder)

    assert app.called("space.new") == []
    assert len(app.called("tab.new")) == 1
    assert first.get("created") is True
    assert second.get("created") is False
    lead_tabs = [item for item in app.spaces_list[0]["tabs"] if item["name"] == "Lead"]
    assert len(lead_tabs) == 1
