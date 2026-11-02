from __future__ import annotations

from pathlib import Path

from conftest import make_task_branch

from stigmergy.config import Config
from stigmergy.gate import gate_artifact, paths_allowed, run_gate
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


def test_paths_allowed_literal_brackets() -> None:
    """Пути Next.js с [gid]/[sid]/[aid] — литералы, не fnmatch-классы."""
    path = "tracker/web/app/student/[gid]/[sid]/[aid]/page.tsx"
    ok, bad = paths_allowed([path], [path])
    assert ok and bad == []


def test_sandbox_glitch_detector() -> None:
    from stigmergy.gate import _sandbox_glitch

    assert _sandbox_glitch("bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted")
    assert not _sandbox_glitch("assert 1 == 2")


def test_high_risk_gate_runs_formal_critic_and_pbt(repo: Path) -> None:
    import json
    import shutil

    from stigmergy import critic, formal

    config = Config.load(repo)
    if shutil.which("java") is None or formal.jar_path(config) is None:
        import pytest

        pytest.skip("java/tla2tools.jar not installed")
    model = Path(__file__).resolve().parents[1] / "src" / "stigmergy" / "formal"
    spec = Spec.from_text(
        f"""---
id: HR
risk: high
allowed_paths:
  - src.txt
  - work.txt
oracle_paths:
  - test_gate.py
gate_inputs: []
invariants:
  - done implies gate
formal:
  model: {model / 'TaskLifecycle.tla'}
  config: {model / 'TaskLifecycle.cfg'}
  mutant_model: {model / 'TaskLifecycleBroken.tla'}
  mutant_cfg: {model / 'TaskLifecycleBroken.cfg'}
properties:
  command: "true"
  seeds: 2
live_model:
  command: "true"
dod: python3 test_gate.py
negative_control:
  corpus: oracle/negative/T1/
---
high risk
""",
        "specs/HR.md",
    )
    assert not spec.validate(), spec.validate()
    report = critic.report_path(config, "HR")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"findings": []}), encoding="utf-8")
    head = make_task_branch(repo, "task/HR", {"work.txt": "work\n"})
    result = run_gate(config, spec, head, "dev", "hr1", use_sandbox=False)
    assert result.passed, (result.stderr, result.formal, result.properties)
    assert result.formal["critic"]["ok"]
    assert result.formal["task"]["ok"]
    assert result.formal["core"]["passed"]
    assert result.properties["properties"]["seeds"] == 2
    assert result.properties["live_model"]["ok"]
