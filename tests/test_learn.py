from __future__ import annotations

from pathlib import Path

from stigmergy import learn
from stigmergy.config import Config
from stigmergy.log import Board


def test_learn_writes_proposals(repo: Path) -> None:
    path = learn.propose(Config.load(repo), Board(repo), days=7)
    text = path.read_text(encoding="utf-8")
    assert "Retro" in text and "Guardrail proposals" in text
