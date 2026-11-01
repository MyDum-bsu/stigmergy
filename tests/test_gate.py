from __future__ import annotations

from pathlib import Path

from conftest import make_task_branch

from stigmergy.config import Config
from stigmergy.gate import gate_artifact, run_gate
from stigmergy.spec import Spec


def test_gate_passes_and_control_proven(repo: Path) -> None:
    spec = Spec.from_git(repo, "dev", "specs/T1.md")
    branch = f"task/T1-{spec.id}"
    head = make_task_branch(repo, branch, {"work.txt": "work\n"})
    result = run_gate(Config.load(repo), spec, head, "dev", "ep1", use_sandbox=False)
    assert result.passed
    assert result.exit_code == 0
    assert result.control["result"] == "proven"
    assert (result.artifact_dir / "gate.json").exists()
    data = gate_artifact(Config.load(repo), "T1", "ep1")
    assert data["schema"] == "stigmergy/gate/v1"
    assert data["control"]["result"] == "proven"
    assert data["oracle_sha"]


def test_gate_restores_oracle_and_fails(repo: Path) -> None:
    spec = Spec.from_git(repo, "dev", "specs/T1.md")
    branch = "task/T1-tamper"
    head = make_task_branch(
        repo,
        branch,
        {"src.txt": "bad\n", "test_gate.py": "print('tampered')\nassert True\n"},
    )
    result = run_gate(Config.load(repo), spec, head, "dev", "ep2", use_sandbox=False)
    assert not result.passed
    assert result.exit_code != 0
    assert "gate-ok" not in result.stdout


def test_paths_outside_allowed_fail(repo: Path) -> None:
    spec = Spec.from_text(
        """---
id: T3
risk: low
allowed_paths:
  - work.txt
oracle_paths: []
dod: "true"
---
only work.txt
""",
        "specs/T3.md",
    )
    head = make_task_branch(repo, "task/T3-paths", {"work.txt": "work\n", "extra.txt": "extra\n"})
    result = run_gate(Config.load(repo), spec, head, "dev", "ep4", use_sandbox=False)
    assert not result.passed
    assert result.exit_code == 126
    assert "extra.txt" in result.stderr


def test_dead_gate_is_detected(repo: Path) -> None:
    spec = Spec.from_text(
        """---
id: T2
risk: low
allowed_paths:
  - src.txt
  - work.txt
oracle_paths:
  - test_gate.py
dod: "true"
negative_control:
  corpus: oracle/negative/T1/
---
noop
""",
        "specs/T2.md",
    )
    head = make_task_branch(repo, "task/T2-noop", {"work.txt": "work\n"})
    result = run_gate(Config.load(repo), spec, head, "dev", "ep3", use_sandbox=False)
    assert result.exit_code == 0
    assert result.control["result"] == "dead"
    assert not result.passed
