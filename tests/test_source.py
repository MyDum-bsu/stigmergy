from __future__ import annotations

from pathlib import Path

from stigmergy import source
from stigmergy.config import Config
from stigmergy.log import Board


def _trigger(trigger_id: str = "chat:1", actor: str = "alice") -> source.Trigger:
    return source.Trigger(
        source="chat",
        trigger_id=trigger_id,
        thread="chat:room-1",
        actor=actor,
        title="Fix a typo",
        text="Please fix the typo in README.",
    )


def test_observe_records_without_task(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    data = source.ingest(config, board, _trigger(), accept_mode="observe", start_planner=False)
    assert data["decision"] == "observed" and not data["task"]
    assert [e["action"] for e in board.read()] == ["source.trigger"]


def test_auto_creates_task_and_mandate(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    data = source.ingest(config, board, _trigger("chat:2"), accept_mode="auto", start_planner=False)
    assert data["decision"] == "accepted" and data["task"]
    actions = [e["action"] for e in board.read()]
    assert actions.count("source.trigger") == 1
    assert actions.count("mandate.granted") == 1
    duplicate = source.ingest(config, board, _trigger("chat:2"), accept_mode="auto", start_planner=False)
    assert duplicate["decision"] == "duplicate"
    assert [e["action"] for e in board.read()].count("mandate.granted") == 1


def test_actor_gate(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    data = source.ingest(
        config,
        board,
        _trigger("chat:3", actor="mallory"),
        accept_mode="auto",
        allowed_actors=("alice",),
        start_planner=False,
    )
    assert data["decision"] == "not_admitted" and not data["task"]
