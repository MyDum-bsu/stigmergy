from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SPEC_T1 = """---
id: T1
title: T1 gate fixture
risk: medium
deps: []
allowed_paths:
  - src.txt
  - work.txt
oracle_paths:
  - test_gate.py
gate_inputs: []
dod: python3 test_gate.py
negative_control:
  corpus: oracle/negative/T1/
budget:
  wall_seconds: 60
---

## Intent
Add work.txt without touching the gate.

## Given
dev has a test that rejects src.txt == bad.

## When
The task branch adds work.txt.

## Then
python3 test_gate.py exits zero.
"""

PATCH_BAD = """diff --git a/src.txt b/src.txt
--- a/src.txt
+++ b/src.txt
@@ -1 +1 @@
-ok
+bad
"""

AGENT_TOML = """[project]
name = "fixture"
base = "dev"
protected = ["main"]
wip = 1

[gate]
timeout_seconds = 60
network = false

[sandbox]
engine = "bwrap"
gate_network = "none"

[runner]
kind = "manual"
agent = "pi"
sandbox = false
"""


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr or proc.stdout}")
    return proc


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "fixture@example.com")
    git(root, "config", "user.name", "Fixture")
    write(root / ".gitignore", ".agent/\n.factory/\n")
    write(root / ".agent.toml", AGENT_TOML)
    write(root / "src.txt", "ok\n")
    write(
        root / "test_gate.py",
        "from pathlib import Path\n"
        "assert Path('src.txt').read_text().strip() != 'bad'\n"
        "print('gate-ok')\n",
    )
    git(root, "add", "-A")
    git(root, "commit", "-m", "init")
    git(root, "checkout", "-b", "dev")
    write(root / "specs" / "T1.md", SPEC_T1)
    write(root / "oracle" / "negative" / "T1" / "bad.patch", PATCH_BAD)
    git(root, "add", "-A")
    git(root, "commit", "-m", "spec")
    git(root, "checkout", "main")
    return root


def make_task_branch(root: Path, branch: str, changes: dict[str, str], message: str = "work") -> str:
    git(root, "checkout", "-b", branch, "dev")
    for rel, text in changes.items():
        write(root / rel, text)
    git(root, "add", "-A")
    git(root, "commit", "-m", message)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "checkout", "main")
    return head
