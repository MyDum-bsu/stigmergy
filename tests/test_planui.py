from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import intake, planui
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def test_review_html_and_reject(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    page = planui.review_html(config, "T1", "secret")
    assert "Approve" in page and "Reject" in page and "secret" in page
    intake.reject_plan(config, board, "T1", "not now")
    assert ProjectState.from_events(board.read()).task("T1").status == "rejected"
