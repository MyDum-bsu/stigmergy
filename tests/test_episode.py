from __future__ import annotations

from pathlib import Path

from conftest import git, make_task_branch

from stigmergy import board as board_mod
from stigmergy.config import Config
from stigmergy.episode import finish_episode, start_episode
from stigmergy.log import Board
from stigmergy.model import ProjectState, task_sha


def _add_and_branch(repo: Path) -> tuple[Board, Config, str]:
    board = Board(repo)
    config = Config.load(repo)
    task = board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md", agent="a")
    branch = f"task/T1-{task.sha}"
    make_task_branch(repo, branch, {"work.txt": "work\n"})
    return board, config, branch


def test_end_to_end_noop(repo: Path) -> None:
    board, config, branch = _add_and_branch(repo)
    before = git(repo, "rev-parse", "dev").stdout.strip()
    result, prompt = start_episode(config, board, "T1", "agent-a", "manual")
    assert "T1" in prompt and str(repo) in prompt
    finished = finish_episode(config, board, "T1", "agent-a", noop=True, auto=True, use_sandbox=False)
    assert finished.merged, finished.detail
    assert finished.gate and finished.gate.passed
    assert finished.gate.control["result"] == "proven"

    state = ProjectState.from_events(board.read(), project="fixture")
    assert state.task("T1").status == "done"
    after = git(repo, "rev-parse", "dev").stdout.strip()
    assert before != after
    assert git(repo, "show", "dev:work.txt").stdout.strip() == "work"
    assert git(repo, "rev-parse", "main").stdout.strip() == git(repo, "rev-parse", "main").stdout.strip()

    actions = [e["action"] for e in board.read()]
    for expected in (
        "task.created",
        "task.claimed",
        "workspace.created",
        "episode.started",
        "episode.finished",
        "gate.started",
        "gate.passed",
        "control.passed",
        "integration.started",
        "integration.passed",
        "merge.done",
        "task.done",
        "workspace.removed",
    ):
        assert expected in actions, expected
    assert (board.views_dir / "Worklog.md").read_text(encoding="utf-8").count("T1") >= 1


def test_runner_field_does_not_change_stations(repo: Path) -> None:
    board, config, _branch = _add_and_branch(repo)
    start_episode(config, board, "T1", "agent-a", "manual")
    finish_episode(config, board, "T1", "agent-a", noop=True, auto=True, use_sandbox=False)
    events = board.read()
    started = [e for e in events if e["action"] == "episode.started"][0]
    assert started["attributes"]["runner.kind"] == "manual"
    assert [e["action"] for e in events if e["action"] in {"gate.passed", "merge.done"}] == [
        "gate.passed",
        "merge.done",
    ]


def test_sha_is_content_hash() -> None:
    assert task_sha("T1", "t", [], "true") == task_sha("T1", "t", [], "true")
    assert task_sha("T1", "t", [], "true") != task_sha("T1", "t", [], "false")
