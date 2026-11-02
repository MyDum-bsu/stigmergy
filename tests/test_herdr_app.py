from __future__ import annotations

import json
from pathlib import Path

from stigmergy.runner import herdr_app


def test_unique_name(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "spaces", lambda app: [{"name": "stg-S8a"}])
    assert herdr_app.unique_name("herdr-app", "stg-S8a") == "stg-S8a-2"
    assert herdr_app.unique_name("herdr-app", "stg-new") == "stg-new"


def test_do_builds_flags(monkeypatch) -> None:
    captured = {}

    class Proc:
        returncode = 0
        stdout = '{"space": "sp1", "terminal": "t1"}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return Proc()

    monkeypatch.setattr(herdr_app.subprocess, "run", fake_run)
    result = herdr_app._do(
        "herdr-app",
        "space.new",
        name="stg-X",
        folder="/tmp/x",
        argv=["pi"],
        task="do it",
    )
    argv = captured["argv"]
    assert result["space"] == "sp1"
    assert "--name" in argv and "stg-X" in argv
    assert json.loads(argv[argv.index("--argv") + 1]) == ["pi"]
    assert argv[argv.index("--task") + 1] == "do it"


def test_wait_ignores_early_idle(monkeypatch) -> None:
    states = iter(
        [
            {"status": {"state": "idle"}, "turn": 0},
            {"status": {"state": "working"}, "turn": 0},
            {"status": {"state": "idle"}, "turn": 1},
        ]
    )
    monkeypatch.setattr(herdr_app, "get", lambda terminal: next(states))
    monkeypatch.setattr(herdr_app, "read", lambda terminal, lines=120: "answer")
    monkeypatch.setattr(herdr_app.time, "sleep", lambda seconds: None)
    assert herdr_app.wait_until_settled("t1", 10) == "answer"


def test_detached_start_does_not_wait(monkeypatch) -> None:
    monkeypatch.setattr(
        herdr_app,
        "create_space",
        lambda app, name, folder, agent, task, agent_args=None: {"space": "sp1", "terminal": "t1"},
    )
    called = []
    monkeypatch.setattr(herdr_app, "wait_until_settled", lambda *a, **k: called.append(1))
    handle = herdr_app.HerdrAppRunner().start("T1", "prompt", Path("/tmp"), wait=False)
    assert handle.meta["space"] == "sp1"
    assert called == []


def test_cleanup_only_factory_spaces(monkeypatch) -> None:
    closed = []
    monkeypatch.setattr(
        herdr_app,
        "spaces",
        lambda app: [{"name": "stg-A", "id": "sp1"}, {"name": "home", "id": "sp2"}],
    )
    monkeypatch.setattr(herdr_app, "close_space", lambda space: closed.append(space))
    assert herdr_app.cleanup("herdr-app") == ["stg-A"]
    assert closed == ["sp1"]


def test_project_space_reuses_and_opens_tab(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "spaces", lambda app: [{"name": "optimization", "id": "sp0"}])
    monkeypatch.setattr(herdr_app, "ensure_app", lambda app: None)
    seen = {}

    def fake_tab(app, space, name, folder, agent, task, agent_args=None):
        seen.update(space=space, name=name, folder=str(folder))
        return {"space": space, "terminal": "t1"}

    monkeypatch.setattr(herdr_app, "create_tab", fake_tab)
    runner = herdr_app.HerdrAppRunner(
        space="optimization", tab_name="mo-a7j · HQ", space_folder=Path("/repo")
    )
    handle = runner.start("mo-a7j", "prompt", Path("/repo/.factory/worktrees/x"), wait=False)
    assert seen == {"space": "sp0", "name": "mo-a7j · HQ", "folder": "/repo/.factory/worktrees/x"}
    assert handle.meta["space"] == "sp0"


def test_project_space_is_created_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "spaces", lambda app: [])
    monkeypatch.setattr(herdr_app, "ensure_app", lambda app: None)
    calls = {}

    def fake_do(app, command, **kwargs):
        calls[command] = kwargs
        return {"space": "sp9"}

    monkeypatch.setattr(herdr_app, "_do", fake_do)
    monkeypatch.setattr(
        herdr_app,
        "create_tab",
        lambda app, space, name, folder, agent, task, agent_args=None: {"space": space, "terminal": "t1"},
    )
    runner = herdr_app.HerdrAppRunner(space="optimization", space_folder=Path("/repo"))
    handle = runner.start("mo-a7j", "prompt", Path("/repo/.factory/worktrees/x"), wait=False)
    assert calls["space.new"] == {"name": "optimization", "folder": "/repo"}
    assert handle.meta["space"] == "sp9"


def test_send_paused_accepts_done(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "get", lambda handle: {"status": {"state": "done"}})
    calls = []
    monkeypatch.setattr(herdr_app, "hc", lambda *args: (calls.append(args) or (0, "ok")))
    assert herdr_app.send_paused("t1", "hello") == (True, "ok")
    assert calls == [("send", "t1", "hello")]


def test_send_paused_refuses_working(monkeypatch) -> None:
    monkeypatch.setattr(herdr_app, "get", lambda handle: {"status": {"state": "working"}})
    calls = []
    monkeypatch.setattr(herdr_app, "hc", lambda *args: (calls.append(args) or (0, "ok")))
    assert herdr_app.send_paused("t1", "hello") == (False, "agent is working")
    assert calls == []
