from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import mirror
from stigmergy.config import Config
from stigmergy.log import Board


def test_github_payloads(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    items = mirror.payloads(config, board)
    assert items and items[0]["task"] == "T1"
    assert "stg:T1" in items[0]["labels"]
