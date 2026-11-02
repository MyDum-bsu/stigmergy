from __future__ import annotations

from pathlib import Path

from stigmergy import mutation
from stigmergy.config import Config


def test_mutation_harness(repo: Path) -> None:
    config = Config.load(repo)
    data = mutation.run(config, "dev", ["false"])
    assert data["ok"] and data["killed"] == ["false"]
    data = mutation.run(config, "dev", ["true"])
    assert not data["ok"] and data["survivors"] == ["true"]
