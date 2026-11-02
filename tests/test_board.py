from __future__ import annotations

from pathlib import Path

import pytest

from stigmergy import board as board_mod
from stigmergy.config import Config
from stigmergy.log import Board, BoardError
from stigmergy.model import ProjectState


def _state(board: Board) -> ProjectState:
    return ProjectState.from_events(board.read(), project="fixture")


def test_add_claim_block_answer_done(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    task = board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md", agent="t")
    assert task.title == "T1 gate fixture"
    assert _state(board).task("T1").status == "queued"
    assert _state(board).task("T1").spec_sha

    board_mod.claim(board, config, "T1", "agent-a")
    assert _state(board).task("T1").status == "claimed"
    assert _state(board).task("T1").agent == "agent-a"

    board_mod.block(board, config, "T1", "agent-a", "which branch?")
    assert _state(board).task("T1").status == "blocked"
    board_mod.answer(board, config, "T1", "human", "use dev")
    assert _state(board).task("T1").status == "queued"

    board_mod.done(board, config, "T1", "agent-a", no_commit=True, evidence="checked")
    assert _state(board).task("T1").status == "done"
    board_mod.render_views(board, config)
    for name in ("Current.md", "Backlog.md", "Worklog.md"):
        assert (board.views_dir / name).exists()


def test_attach_spec_to_existing_task(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "No spec yet")
    board_mod.attach_spec(board, config, "T1", "specs/T1.md")
    task = _state(board).task("T1")
    assert task.spec == "specs/T1.md"
    assert task.spec_sha
    assert task.status == "queued"


def test_human_only_approve(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.propose_task(board, config, "T2", "proposal")
    with pytest.raises(BoardError):
        board_mod.approve(board, config, "T2", "agent")
    board_mod.approve(board, config, "T2", "human")
    assert _state(board).task("T2").status == "queued"


def test_next_respects_deps_and_wip(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.add_task(board, config, "T2", "", spec_path="specs/T1.md", deps=["T1"])
    # T2's spec id is T1; the task id is separate, that is allowed by the board.
    task = board_mod.next_task(board, config, "agent-a")
    assert task is not None and task.id == "T1"
    assert board_mod.next_task(board, config, "agent-b") is None  # WIP=1
    board_mod.done(board, config, "T1", "agent-a", no_commit=True, evidence="ok")
    task2 = board_mod.next_task(board, config, "agent-b")
    assert task2 is not None and task2.id == "T2"


def test_lead_answer_keeps_open_episode(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.started",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "runner.handle": "t1"},
    )
    board_mod.block(board, config, "T1", "pi", "question")
    board_mod.answer(board, config, "T1", "lead", "answer")
    assert _state(board).task("T1").status == "episode"


def test_worker_done_is_a_marker(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    event = board_mod.worker_done(board, config, "T1", "pi")
    assert event["action"] == "worker.done"
    assert _state(board).task("T1").status == "queued"


def test_done_with_commit_requires_gate(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    with pytest.raises(BoardError, match="gate.passed"):
        board_mod.done(board, config, "T1", "pi", commit="deadbeef", evidence="trust me")


def test_answer_after_failed_gate_is_not_integrated(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.started",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "runner.handle": "t1"},
    )
    board.append(
        "episode.finished",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "vcs.commit": "c", "vcs.tree": "t"},
    )
    board.append(
        "task.answered",
        {"kind": "human", "name": "human"},
        {"project.name": "fixture", "task.id": "T1", "answer": "retry", "answered.by": "human"},
    )
    assert _state(board).task("T1").status != "integrated"
