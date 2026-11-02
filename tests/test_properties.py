from __future__ import annotations

from pathlib import Path

from stigmergy import properties
from stigmergy.config import Config
from stigmergy.spec import Spec


def _spec(properties_block: str, live_block: str = "") -> Spec:
    return Spec.from_text(
        f"""---
id: P1
risk: medium
allowed_paths:
  - src.txt
oracle_paths: []
dod: "true"
negative_control:
  corpus: oracle/negative/T1/
properties:
{properties_block}
{live_block}
---
body
""",
        "specs/P1.md",
    )


def test_properties_run_each_seed(repo: Path) -> None:
    spec = _spec(
        "  command: python3 -c 'import os; assert int(os.environ[\"STG_SEED\"]) >= 0'\n"
        "  seeds: 3",
        "live_model:\n  command: python3 -c 'import os; assert os.environ[\"STG_LIVE_MODEL\"] == \"1\"'",
    )
    data = properties.run(Config.load(repo), spec, "dev")
    assert data["ok"], data
    assert data["properties"]["seeds"] == 3
    assert len(data["properties"]["cases"]) == 3
    assert data["live_model"]["ok"]


def test_property_failure_stops_at_seed(repo: Path) -> None:
    spec = _spec(
        "  command: test \"$STG_SEED\" != \"2\"\n"
        "  seeds: 5",
    )
    data = properties.run(Config.load(repo), spec, "dev")
    assert not data["ok"]
    assert len(data["properties"]["cases"]) == 3
    assert data["properties"]["cases"][-1]["exit_code"] != 0


def test_no_properties_is_skipped(repo: Path) -> None:
    spec = _spec("  command: ''")
    data = properties.run(Config.load(repo), spec, "dev")
    assert data["ok"] and data["skipped"]
