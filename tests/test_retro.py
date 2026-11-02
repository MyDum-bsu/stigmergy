from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import retro
from stigmergy.config import Config
from stigmergy.log import Board


def test_retro_collects_and_writes(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.block(board, config, "T1", "pi", "что делать?")
    data = retro.collect(config, board)
    assert data["blocked_questions"]
    assert "что делать?" in retro.render(data)
    path = retro.write(config, board)
    assert path.exists()
    assert "Retro" in path.read_text(encoding="utf-8")
