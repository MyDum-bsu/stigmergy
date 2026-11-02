from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import metrics
from stigmergy.config import Config
from stigmergy.log import Board


def test_metrics_counts_and_anonymous(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.worker_done(board, config, "T1", "pi")
    board.append("orphan.event", {}, {})
    data = metrics.snapshot(config, board)
    assert data["tasks"] == 1
    assert data["worker_done"] == 1
    assert data["queued_with_spec"] == 1
    assert data["anonymous"]
    assert "anonymous" in metrics.text(data)
