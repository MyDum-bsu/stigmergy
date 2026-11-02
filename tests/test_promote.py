from __future__ import annotations

from pathlib import Path

from conftest import git, write

from stigmergy import promote
from stigmergy.config import Config


def test_promote_status_and_fast_forward(repo: Path) -> None:
    config = Config.load(repo)
    data = promote.status(config)
    assert data["ok"] and data["fast_forward"]
    assert data["dev_ahead"] >= 1
    applied = promote.apply(config)
    assert applied["applied"], applied
    assert git(repo, "rev-parse", "main").stdout.strip() == git(repo, "rev-parse", "dev").stdout.strip()


def test_promote_refuses_non_fast_forward(repo: Path) -> None:
    git(repo, "checkout", "main")
    write(repo / "main-only.txt", "main\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "main only")
    data = promote.apply(Config.load(repo))
    assert not data["applied"] and not data["fast_forward"]
