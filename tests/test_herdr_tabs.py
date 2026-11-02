from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from stigmergy import board as board_mod
from stigmergy import cli, episode, intake
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.runner import herdr_app

LONG = "t-20261102-162003-github-issue-3-herdr-tabs-читаем-50873d"
OTHER = "t-20261101-090000-github-issue-9-another-task-abcdef"
GHOST = "t-20260901-000000-github-issue-7-ghost-task-000000"


class FakeApp:
    """herdr-app process stand-in: spaces and tabs kept in memory."""

    def __init__(self, spaces: list[dict]):
        self.spaces_list = []
        for item in spaces:
            copy = dict(item)
            copy["tabs"] = [dict(tab) for tab in item.get("tabs", [])]
            self.spaces_list.append(copy)
        self.commands: list[tuple[str, dict]] = []
        self.dead: set[str] = set()

    def spaces(self, app: str | None = None) -> list[dict]:
        return self.spaces_list

    def get(self, terminal: str) -> dict:
        if terminal in self.dead:
            raise herdr_app.HerdrAppError(f"terminal {terminal} is gone")
        return {"status": {"state": "idle"}, "turn": 1}

    def do(self, app: str, command: str, **kwargs) -> dict:
        self.commands.append((command, kwargs))
        if command == "tab.new":
            tab = {
                "id": f"tab-{len(self.commands)}",
                "name": str(kwargs["name"]),
                "terminals": [f"term-{len(self.commands)}"],
            }
            for space in self.spaces_list:
                if space.get("name") == kwargs.get("space"):
                    space["tabs"].append(tab)
                    break
            return {"id": tab["id"], "terminal": tab["terminals"][0], "name": tab["name"]}
        return {"ok": True}

    def ensure_app(self, app: str | None = None, wait_seconds: int = 15) -> dict:
        return {"ok": True}

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


def tab(name: str, terminals=("alive",), **extra) -> dict:
    return {"id": f"id-{name}", "name": name, "terminals": list(terminals), **extra}


def space(name: str, *tabs) -> dict:
    return {"name": name, "id": f"space-{name}", "tabs": list(tabs)}


# ── marker and label ──────────────────────────────────────────────────────
def test_short_id_is_stable_hex() -> None:
    marker = herdr_app.short_id(LONG)
    assert marker == herdr_app.short_id(LONG)
    assert len(marker) == 6
    assert all(char in "0123456789abcdef" for char in marker)
    assert herdr_app.short_id(LONG, 10) != herdr_app.short_id(LONG)
    assert len(herdr_app.short_id(LONG, 10)) == 10


def test_label_carries_title_and_marker_without_the_slug() -> None:
    label = herdr_app.tab_label("Plan", "читаемые вкладки", LONG)
    assert label == f"Plan · читаемые вкладки [{herdr_app.short_id(LONG)}]"
    assert LONG not in label


def test_label_truncates_and_keeps_the_marker_last() -> None:
    marker = f"[{herdr_app.short_id(LONG)}]"
    label = herdr_app.tab_label("Worker", "я" * 300, LONG)
    assert len(label) <= herdr_app.MAX_TAB_LABEL
    assert label.endswith(marker)
    assert "…" in label


def test_label_survives_empty_title_and_a_task_slug_title() -> None:
    marker = f"[{herdr_app.short_id(LONG)}]"
    assert herdr_app.tab_label("Critic", "   ", LONG) == f"Critic · {marker}"
    slug_label = herdr_app.tab_label("Worker", LONG, LONG)
    assert "t-2026" not in slug_label
    assert slug_label.endswith(marker)
    assert len(slug_label) <= herdr_app.MAX_TAB_LABEL


def test_protected_tabs_and_managed_kinds() -> None:
    assert herdr_app.is_protected_tab("Lead")
    assert herdr_app.is_protected_tab("Board")
    assert herdr_app.is_protected_tab("Lead · architect")
    assert not herdr_app.is_protected_tab("Worker")
    assert herdr_app.managed_kind(herdr_app.tab_label("Plan", "x", LONG)) == "Plan"
    assert herdr_app.managed_kind(f"Plan · {LONG}") == "Plan"
    assert herdr_app.managed_kind(f"{LONG} · worker") == "Worker"
    assert herdr_app.managed_kind(f"stg-{LONG}") == "Worker"
    assert herdr_app.managed_kind("Lead") is None
    assert herdr_app.managed_kind("Board") is None
    assert herdr_app.managed_kind("just a tab") is None


# ── close by task ─────────────────────────────────────────────────────────
def test_close_task_tabs_closes_only_that_task(monkeypatch) -> None:
    owned = [
        herdr_app.tab_label("Plan", "задача", LONG),
        herdr_app.tab_label("Worker", "задача", LONG),
        herdr_app.tab_label("Critic", "задача", LONG),
        f"Plan · {LONG}",
        f"{LONG} · worker",
    ]
    kept = ["Lead", "Board", herdr_app.tab_label("Plan", "другая", OTHER)]
    app = install(monkeypatch, FakeApp([space("stigmergy", *[tab(name) for name in owned + kept])]))

    closed = herdr_app.close_task_tabs(herdr_app.DEFAULT_APP, LONG)

    assert set(closed) == set(owned)
    assert len(app.closed()) == len(owned)


def test_close_task_tabs_propagates_app_errors(monkeypatch) -> None:
    install(monkeypatch, FakeApp([space("stigmergy", tab(herdr_app.tab_label("Plan", "x", LONG)))]))

    def boom(app, command, **kwargs):
        raise herdr_app.HerdrAppError("tab.close failed")

    monkeypatch.setattr(herdr_app, "_do", boom)
    with pytest.raises(herdr_app.HerdrAppError):
        herdr_app.close_task_tabs(herdr_app.DEFAULT_APP, LONG)


# ── sweep ─────────────────────────────────────────────────────────────────
def test_cleanup_tabs_closes_terminal_and_dead_orphan_only(monkeypatch) -> None:
    finished = [herdr_app.tab_label("Plan", "готова", LONG)]
    live = herdr_app.tab_label("Worker", "живая", OTHER)
    orphan = herdr_app.tab_label("Critic", "осиротела", GHOST)
    app = install(
        monkeypatch,
        FakeApp(
            [
                space(
                    "stigmergy",
                    tab(finished[0], ("alive",)),
                    tab(live, ("alive",)),
                    tab(orphan, ("dead",)),
                    tab("Lead"),
                    tab("Board"),
                )
            ]
        ),
    )
    app.dead = {"dead"}

    closed = herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "done", OTHER: "claimed"})

    assert set(closed) == {finished[0], orphan}
    assert len(app.closed()) == 2


def test_cleanup_tabs_closes_stale_and_keeps_fresh(monkeypatch) -> None:
    stale = herdr_app.tab_label("Worker", "старая", GHOST)
    fresh = herdr_app.tab_label("Worker", "свежая", OTHER)
    app = install(
        monkeypatch,
        FakeApp(
            [
                space(
                    "stigmergy",
                    tab(stale, ("t-old",), created_at=1_000.0),
                    tab(fresh, ("t-new",), created_at=99_000.0),
                )
            ]
        ),
    )

    closed = herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, None, now=100_000.0, stale_after_s=3_600)

    assert closed == [stale]
    assert app.closed() == [f"id-{stale}"]


def test_cleanup_tabs_dry_run_reports_without_closing(monkeypatch) -> None:
    name = herdr_app.tab_label("Plan", "готова", LONG)
    app = install(monkeypatch, FakeApp([space("stigmergy", tab(name))]))

    names = herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "merged"}, dry_run=True)

    assert names == [name]
    assert app.closed() == []


def test_cleanup_tabs_propagates_errors(monkeypatch) -> None:
    def boom(app=None):
        raise herdr_app.HerdrAppError("herdr-app is not running")

    monkeypatch.setattr(herdr_app, "spaces", boom)
    with pytest.raises(herdr_app.HerdrAppError):
        herdr_app.cleanup_tabs(herdr_app.DEFAULT_APP, {LONG: "done"})


# ── single lead in the single project space ───────────────────────────────
def test_ensure_lead_tab_creates_once(monkeypatch) -> None:
    app = install(monkeypatch, FakeApp([space("stigmergy")]))
    folder = Path("/tmp/stigmergy")

    first = herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=folder)
    second = herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=folder)

    assert app.called("space.new") == []
    assert len(app.called("tab.new")) == 1
    assert first["created"] is True
    assert second["created"] is False
    assert [item["name"] for item in app.spaces_list[0]["tabs"]] == ["Lead"]


def test_ensure_lead_tab_closes_a_duplicate(monkeypatch) -> None:
    app = install(monkeypatch, FakeApp([space("stigmergy", tab("Lead"), tab("Lead"))]))

    result = herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=Path("/repo"))

    assert result["created"] is False
    assert app.closed() == ["id-Lead"]
    assert app.called("tab.new") == []


def test_ensure_lead_tab_propagates_errors(monkeypatch) -> None:
    def boom(app=None):
        raise herdr_app.HerdrAppError("herdr-app is not running")

    monkeypatch.setattr(herdr_app, "spaces", boom)
    with pytest.raises(herdr_app.HerdrAppError):
        herdr_app.ensure_lead_tab(app=herdr_app.DEFAULT_APP, space="stigmergy", folder=Path("/repo"))


# ── call sites ────────────────────────────────────────────────────────────
def test_runner_names_the_worker_tab_without_the_slug(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "ensure_app", lambda app, wait_seconds=15: {"ok": True})
    monkeypatch.setattr(
        herdr_app, "spaces", lambda app: [{"name": "stigmergy", "id": "sp0", "tabs": []}]
    )
    seen: dict[str, str] = {}

    def fake_tab(app, space, name, folder, agent, task, agent_args=None, argv=None):
        seen["name"] = name
        return {"space": space, "terminal": "t1"}

    monkeypatch.setattr(herdr_app, "create_tab", fake_tab)
    runner = herdr_app.HerdrAppRunner(
        space="stigmergy", space_folder=Path("/repo"), tab_title="читаемые вкладки"
    )
    runner.start(LONG, "prompt", Path("/repo/wt"), wait=False)

    assert seen["name"] == herdr_app.tab_label("Worker", "читаемые вкладки", LONG)
    assert LONG not in seen["name"]


def test_episode_finish_boundary_prints_one_line(repo: Path, monkeypatch, capsys) -> None:
    config = Config.load(repo)

    def boom(app, task_id):
        raise herdr_app.HerdrAppError("app is down")

    monkeypatch.setattr(herdr_app, "close_task_tabs", boom)
    episode._close_task_tabs(config, "T1")

    assert capsys.readouterr().out.strip() == "herdr: tabs not closed: app is down"


def test_approve_plan_closes_the_plan_tab(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app, "ensure_space", lambda app, name, folder: {"space": "sp0", "tabs": []}
    )
    monkeypatch.setattr(
        intake.herdr_app, "create_tab", lambda *args, **kwargs: {"space": "sp0", "terminal": "t-plan"}
    )
    task_id = intake.create_task(config, board, "Добавить виджет")["task"]
    intake.paths_for(config, task_id)["spec"].write_text(_draft_spec(task_id), encoding="utf-8")
    closed: list[str] = []
    monkeypatch.setattr(
        intake.herdr_app, "close_task_tabs", lambda app, task_id: closed.append(task_id) or []
    )

    intake.approve_plan(config, board, task_id)

    assert closed == [task_id]


def test_worker_done_closes_worker_tabs(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "fixture", spec_path="specs/T1.md")
    closed: list[str] = []
    monkeypatch.setattr(
        herdr_app, "close_task_tabs", lambda app, task_id: closed.append(task_id) or []
    )
    args = argparse.Namespace(board=str(repo), json=True, id="T1", agent="pi")

    assert cli.cmd_worker(args) == 0
    assert closed == ["T1"]


def test_space_ref_maps_a_name_to_the_id(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "spaces", lambda app: [{"id": "sp1", "name": "stigmergy"}])

    assert herdr_app._space_ref("herdr-app", "stigmergy") == "sp1"
    assert herdr_app._space_ref("herdr-app", "sp1") == "sp1"
    assert herdr_app._space_ref("herdr-app", "unknown") == "unknown"


def test_do_resolves_a_space_name_for_tab_new(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "spaces", lambda app: [{"id": "sp1", "name": "stigmergy"}])
    captured: dict[str, list[str]] = {}

    class Proc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return Proc()

    monkeypatch.setattr(herdr_app.subprocess, "run", fake_run)

    herdr_app._do(
        "herdr-app", "tab.new", name="Lead", space="stigmergy", folder="/tmp", argv=["pi"], task=""
    )

    argv = captured["argv"]
    assert argv[argv.index("--space") + 1] == "sp1"


def _draft_spec(task_id: str) -> str:
    return f"""---
id: {task_id}
title: Herdr tabs fixture
risk: low
deps: []
allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
gate_inputs: []
dod: python3 test_gate.py
---

## Intent
Fixture.
"""
