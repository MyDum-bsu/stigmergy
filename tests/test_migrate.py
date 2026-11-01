from __future__ import annotations

from pathlib import Path

from stigmergy.log import Board
from stigmergy.migrate import check, run


def _legacy(root: Path) -> Board:
    board = Board(root)
    board.append(
        "task.created",
        {"kind": "agent", "name": "triage"},
        {"project.name": "legacy", "task.id": "T1", "task.title": "legacy", "task.sha": "abc"},
        "create",
    )
    board.append(
        "task.claimed",
        {"kind": "agent", "name": "impl"},
        {"project.name": "legacy", "task.id": "T1", "agent.name": "impl"},
        "claim",
    )
    board.append(
        "task.done",
        {"kind": "agent", "name": "impl"},
        {"project.name": "legacy", "task.id": "T1", "evidence": "done", "vcs.commit": "abc"},
        "done",
    )
    return board


def test_check_valid(tmp_path: Path) -> None:
    _legacy(tmp_path)
    report = check(tmp_path)
    assert report["ok"], report["errors"]
    assert report["count"] == 3
    assert report["tasks"] == 1


def test_run_copies_and_appends_migration(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _legacy(src)
    report = run(src, dst, "legacy")
    assert report["ok"]
    events = Board(dst).read()
    assert len(events) == 4
    assert events[-1]["action"] == "board.migrated"
    assert events[-1]["attributes"]["source.count"] == 3
    assert (dst / ".agent" / "views" / "Backlog.md").exists()
    assert check(dst)["ok"]
