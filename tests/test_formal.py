from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stigmergy import board as board_mod
from stigmergy import formal
from stigmergy.config import Config
from stigmergy.log import Board


def test_live_invariants() -> None:
    from stigmergy.model import ProjectState

    assert ProjectState is not None


def test_live_violations(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "task.done",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "vcs.commit": "abc"},
    )
    violations = formal.live_violations(config, board)
    assert any("T1" in item for item in violations)


def test_tlc_model_and_mutant(repo: Path) -> None:
    if shutil.which("java") is None:
        pytest.skip("java not installed")
    config = Config.load(repo)
    if formal.jar_path(config) is None:
        pytest.skip("tla2tools.jar not installed")
    data = formal.verify_core(config, Board(repo))
    assert data["model"]["ok"], data["model"]["output"][-1000:]
    assert data["mutant_rejected"], data["mutant"]["output"][-1000:]
    assert data["passed"], data
