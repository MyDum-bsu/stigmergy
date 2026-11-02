from __future__ import annotations

import json
from pathlib import Path

from stigmergy import bench, routing
from stigmergy.config import Config


def test_routing_stage_default_and_runner_fallback(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["models"] = {"default": "base/model", "critic": "critic/model"}
    config.raw["runner"] = {"critic_model": "old/critic", "model": "old/worker"}
    assert routing.choose(config, "critic") == "critic/model"
    assert routing.choose(config, "worker") == "base/model"
    config.raw["models"] = {}
    assert routing.choose(config, "critic") == "old/critic"
    assert routing.choose(config, "worker") == "old/worker"
    assert routing.args(config, "worker", ["--exclude-tools", "x"]) == [
        "--exclude-tools",
        "x",
        "--model",
        "old/worker",
    ]


def test_benchmark_harness(repo: Path, tmp_path: Path) -> None:
    cases = tmp_path / "cases.jsonl"
    rows = [
        {"prompt": "one", "expected": "model-a"},
        {"prompt": "two", "expected": "model-a"},
    ]
    cases.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    data = bench.evaluate(
        Config.load(repo),
        cases,
        "model-a",
        command="python3 -c 'import os; print(os.environ[\"STG_MODEL\"])'",
    )
    assert data["ok"] and data["passed"] == 2 and data["score"] == 1.0
    assert Path(data["artifact"]).exists()
    bad = bench.evaluate(
        Config.load(repo),
        cases,
        "model-a",
        command="python3 -c 'print(\"wrong\")'",
    )
    assert not bad["ok"] and bad["passed"] == 0
