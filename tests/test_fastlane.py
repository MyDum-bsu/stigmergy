from __future__ import annotations

from pathlib import Path

from stigmergy import intake, policy
from stigmergy.config import Config
from stigmergy.log import Board


def _draft_spec(repo: Path, config: Config, board: Board, *, auto: bool = True, idea: str = "fix a typo") -> str:
    data = intake.create_task(config, board, idea, start_planner=False)
    task_id = data["task"]
    spec = intake.paths_for(config, task_id)["spec"]
    spec.write_text(
        f"""---
id: {task_id}
title: fix a typo
risk: low
auto_approve: {str(auto).lower()}
allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
gate_inputs: []
dod: python3 test_gate.py
---
one file
""",
        encoding="utf-8",
    )
    return task_id


def test_config_space_defaults_to_project_name(repo: Path) -> None:
    config = Config.load(repo)
    assert config.space == "fixture"
    config.raw["runner"] = {"space": "custom"}
    assert config.space == "custom"


def test_policy_fast_lane(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["factory"] = {"auto_approve": True}
    board = Board(repo)
    task_id = _draft_spec(repo, config, board)
    data = intake.auto_approve_plan(config, board, task_id)
    assert data["ok"], data
    assert data["approval"] == "policy"
    assert data["verdict"]["policy"] == policy.POLICY


def test_policy_requires_opt_in_and_flag(repo: Path) -> None:
    config = Config.load(repo)
    board = Board(repo)
    task_id = _draft_spec(repo, config, board)
    data = intake.auto_approve_plan(config, board, task_id)
    assert not data["ok"]
    config.raw["factory"] = {"auto_approve": True}
    task_id = _draft_spec(repo, config, board, auto=False, idea="fix another typo")
    data = intake.auto_approve_plan(config, board, task_id)
    assert not data["ok"]


def test_preflight_rejects_missing_oracle(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["factory"] = {"auto_approve": True}
    board = Board(repo)
    task_id = _draft_spec(repo, config, board, idea="missing oracle")
    spec = intake.paths_for(config, task_id)["spec"]
    text = spec.read_text().replace("  - test_gate.py", "  - tests/missing_oracle.py")
    spec.write_text(text, encoding="utf-8")
    preflight = intake.preflight_draft(config, task_id)
    assert not preflight["ok"]
    assert any("oracle path" in error for error in preflight["errors"])
    assert not intake.auto_approve_plan(config, board, task_id)["ok"]
