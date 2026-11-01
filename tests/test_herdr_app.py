from __future__ import annotations

import json

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
