from __future__ import annotations

from pathlib import Path

import pytest

from stigmergy import board as board_mod
from stigmergy import lead
from stigmergy.config import Config
from stigmergy.log import Board, BoardError
from stigmergy.model import ProjectState


def _state(board: Board) -> ProjectState:
    return ProjectState.from_events(board.read(), project="fixture")


def test_lead_can_answer_worker_question(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.block(board, config, "T1", "pi", "which branch?")
    event = board_mod.answer(board, config, "T1", "lead", "use dev")
    assert event["actor"]["name"] == "lead"
    assert _state(board).task("T1").status == "queued"


def test_lead_cannot_answer_high_risk(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "task.claimed",
        {"kind": "agent", "name": "pi"},
        {"project.name": config.name, "task.id": "T1", "agent.name": "pi", "risk": "high"},
    )
    board_mod.block(board, config, "T1", "pi", "merge?")
    with pytest.raises(BoardError, match="high-risk"):
        board_mod.answer(board, config, "T1", "lead", "yes")


def test_inbox_and_answer_resume_worker(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.started",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "runner.handle": "t1"},
    )
    board_mod.block(board, config, "T1", "pi", "which branch?")
    calls = []
    monkeypatch.setattr(
        lead.herdr_app,
        "send_paused",
        lambda handle, text: (calls.append(("send", handle, text)) or (True, "sent")),
    )
    items = lead.inbox(board, config)
    assert len(items) == 1
    assert items[0]["id"] == "T1"
    assert items[0]["title"] == "T1 gate fixture"
    assert items[0]["risk"] == _state(board).task("T1").risk
    assert items[0]["question"] == "which branch?"
    assert items[0]["terminal"] == "t1"
    data = lead.answer(config, board, "T1", "use dev")
    assert data["sent"] is True
    assert calls[0] == ("send", "t1", "Лид: use dev\n\nПродолжай работу по спеке.")
    assert _state(board).task("T1").status == "episode"


def test_start_lead_reuses_and_creates_tab(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        lead.herdr_app,
        "ensure_space",
        lambda app, name, folder: {"space": "sp0", "tabs": []},
    )
    seen = {}

    def fake_tab(app, space, name, folder, agent, task, agent_args=None, argv=None):
        seen.update(space=space, name=name, agent=agent, agent_args=agent_args)
        return {"space": space, "tab": "tb0", "terminal": "t1"}

    monkeypatch.setattr(lead.herdr_app, "create_tab", fake_tab)
    data = lead.start_lead(config, board)
    assert data == {"space": "sp0", "tab": "tb0", "terminal": "t1", "created": True}
    assert seen["space"] == config.space
    assert seen["name"] == lead.LEAD_TAB
    assert seen["agent_args"] == ["--exclude-tools", "edit,write"]
    assert "lead.started" in [event["action"] for event in board.read()]


def test_lead_startup_does_not_scan_board(repo: Path) -> None:
    config = Config.load(repo)
    text = lead.lead_prompt(config, "fixture")
    assert "Startup rule: do nothing" in text
    assert "Do not scan the board" in text
