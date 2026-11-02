from __future__ import annotations

from pathlib import Path

from stigmergy import usage
from stigmergy.config import Config
from stigmergy.log import Board


def test_usage_totals(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    usage.record(
        config,
        board,
        task_id="T1",
        stage="check",
        prompt_tokens=10,
        completion_tokens=5,
        duration_ms=100,
        cost_usd="0.25",
    )
    usage.record(
        config,
        board,
        task_id="T1",
        stage="check",
        prompt_tokens=2,
        completion_tokens=1,
        duration_ms=50,
        cost_usd="0.05",
    )
    data = usage.totals(board)
    assert data == {"calls": 2, "prompt_tokens": 12, "completion_tokens": 6, "duration_ms": 150, "cost_usd": "3/10"}
