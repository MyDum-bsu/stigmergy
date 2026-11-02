from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stigmergy import board as board_mod
from stigmergy import dispatcher
from stigmergy.config import Config
from stigmergy.log import Board


def _config(repo: Path):
    config = Config.load(repo)
    return config


def test_tick_starts_spec_task(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = _config(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    monkeypatch.setattr(dispatcher.herdr_app, "status", lambda app: {"ok": True})
    calls = []

    def fake_start(*args, **kwargs):
        calls.append((args, kwargs))
        return (
            SimpleNamespace(episode="ep1", runner_handle="t1", runner_space="sp0"),
            "prompt",
        )

    result = dispatcher.tick(
        config,
        board,
        start=fake_start,
        auto_finish=False,
        state={},
    )
    assert result["ok"]
    assert result["actions"][0]["action"] == "start"
    assert result["actions"][0]["task"] == "T1"
    assert calls and calls[0][0][2] == "T1"


def test_tick_notifies_lead_once(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = _config(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.block(board, config, "T1", "pi", "куда деплоить?")
    board.append(
        "lead.started",
        {"kind": "agent", "name": "lead"},
        {"project.name": "fixture", "lead.handle": "t-lead"},
    )
    monkeypatch.setattr(dispatcher.herdr_app, "status", lambda app: {"ok": True})
    sent = []

    def fake_hc(*args):
        sent.append(args)
        return 0, "ok"

    state = {}
    first = dispatcher.tick(config, board, hc=fake_hc, auto_finish=False, state=state)
    assert first["actions"][0]["action"] == "notify"
    assert sent and sent[0][0] == "send"
    assert state["notified"]["T1"] == 2
    second = dispatcher.tick(config, board, hc=fake_hc, auto_finish=False, state=state)
    assert second["actions"] == []


def test_tick_finishes_settled_worker(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = _config(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.started",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "runner.handle": "t1"},
    )
    board.append(
        "worker.done",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1"},
    )
    monkeypatch.setattr(dispatcher.herdr_app, "status", lambda app: {"ok": True})
    seen = []

    def fake_finish(config, task_id):
        seen.append(task_id)
        return {"task": task_id, "ok": True}

    result = dispatcher.tick(
        config,
        board,
        finish=fake_finish,
        auto_finish=True,
        state={},
    )
    assert result["actions"][0]["action"] == "finish"
    assert seen == ["T1"]
    again = dispatcher.tick(config, board, finish=fake_finish, auto_finish=True, state=result["state"])
    assert again["actions"] == []
    assert seen == ["T1"]
