from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import intake, planinbox, planui
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState

SPEC = """---
id: T1
title: plan page fixture
risk: medium
allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
dod: python3 test_gate.py
negative_control:
  corpus: oracle/negative/T1/
---
Plan body.
"""


def _plan(repo: Path) -> tuple[Config, Board]:
    board = Board(repo)
    config = Config.load(repo)
    spec = repo / "specs" / "T1.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(SPEC, encoding="utf-8")
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    return config, board


def test_review_html_offers_both_actions(repo: Path) -> None:
    config, board = _plan(repo)
    page = planui.review_html(config, board, "T1", "page-key", secret="signing-key")
    assert "/plan/T1/action/approve" in page
    assert "/plan/T1/action/reject" in page
    assert "page-key" in page  # the key rides on the submit URL
    assert "signing-key" not in page  # the HMAC key never reaches the page


def test_review_html_and_reject(repo: Path) -> None:
    config, board = _plan(repo)
    intake.reject_plan(config, board, "T1", "not now")
    page = planui.review_html(config, board, "T1", "page-key", secret="signing-key")
    assert "/action/approve" not in page
    assert "rejected" in page
    assert ProjectState.from_events(board.read()).task("T1").status == "rejected"


def test_review_html_without_a_draft_spec_has_no_actions(repo: Path) -> None:
    config = Config.load(repo)
    board = Board(repo)
    task_id = intake.create_task(config, board, "no draft spec yet", start_planner=False)["task"]
    page = planui.review_html(config, board, task_id, "page-key", secret="signing-key")
    assert "/action/" not in page
    assert "has not written a draft spec" in page
    assert planinbox.plan_state(config, board, task_id) == "pending"
    assert planinbox.spec_sha(config, task_id) == ""
