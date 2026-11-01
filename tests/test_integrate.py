from __future__ import annotations

from pathlib import Path

from conftest import git, make_task_branch, write

from stigmergy.config import Config
from stigmergy.integrate import integrate
from stigmergy.model import Task
from stigmergy.spec import Spec
from stigmergy.workspace import create_task_worktree


def _task(branch: str, sha: str) -> Task:
    return Task(id="T1", title="t", sha=sha, spec="specs/T1.md", branch=branch, base="dev")


def test_integrate_fast_forward(repo: Path) -> None:
    spec = Spec.from_git(repo, "dev", "specs/T1.md")
    branch = "task/T1-int"
    head = make_task_branch(repo, branch, {"work.txt": "work\n"})
    config = Config.load(repo)
    wt = create_task_worktree(config, _task(branch, head[:12]))
    result = integrate(config, spec, wt.path, "dev", "ep-int", use_sandbox=False)
    assert result.ok, result.detail
    assert git(repo, "show", "dev:work.txt").stdout.strip() == "work"


def test_integrate_conflict_requeues(repo: Path) -> None:
    spec = Spec.from_git(repo, "dev", "specs/T1.md")
    branch = "task/T1-conflict"
    make_task_branch(repo, branch, {"src.txt": "task\n"})
    git(repo, "checkout", "dev")
    write(repo / "src.txt", "dev\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "dev change")
    git(repo, "checkout", "main")
    config = Config.load(repo)
    wt = create_task_worktree(config, _task(branch, "conflict"))
    result = integrate(config, spec, wt.path, "dev", "ep-conflict", use_sandbox=False)
    assert not result.ok
    assert result.detail
