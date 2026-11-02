from __future__ import annotations

import json
from pathlib import Path

from stigmergy import critic
from stigmergy.config import Config


def _report(root: Path, findings: list[dict]) -> None:
    p = root / ".factory" / "critic" / "T1.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"findings": findings}), encoding="utf-8")


def test_critic_missing_blocks(repo: Path) -> None:
    assert not critic.evaluate(Config.load(repo), "T1")["ok"]


def test_critic_low_catalog_passes(repo: Path) -> None:
    _report(repo, [{"kind": "style", "frequency": 2, "harm": 2, "evidence": "x"}])
    assert critic.evaluate(Config.load(repo), "T1")["ok"]


def test_critic_high_blocks(repo: Path) -> None:
    _report(repo, [{"kind": "data", "frequency": 2, "harm": 3, "evidence": "x"}])
    data = critic.evaluate(Config.load(repo), "T1")
    assert not data["ok"] and data["blocking"]
