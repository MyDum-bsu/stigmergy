"""Git workspace helpers: one task, one branch, one worktree."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from stigmergy.config import Config
from stigmergy.model import Task


class WorkspaceError(RuntimeError):
    pass


def git(repo: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise WorkspaceError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def rev_parse(repo: str | Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).stdout.strip()


def tree_of(repo: str | Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", f"{ref}^{{tree}}").stdout.strip()


def branch_exists(repo: str | Path, branch: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def worktree_exists(repo: str | Path, path: Path) -> bool:
    proc = git(repo, "worktree", "list", "--porcelain", check=False)
    target = str(path.resolve())
    return f"worktree {target}" in proc.stdout


@dataclass
class Worktree:
    path: Path
    branch: str
    base: str


def create_task_worktree(config: Config, task: Task, base: str | None = None) -> Worktree:
    root = config.root
    base = base or task.base or config.base
    branch = task.branch or f"task/{task.id}-{task.sha or 'work'}"
    path = config.workspace_root / f"{task.id}-{task.sha or 'work'}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_exists(root, path):
        return Worktree(path=path, branch=branch, base=base)
    if branch_exists(root, branch):
        git(root, "worktree", "add", str(path), branch)
    else:
        git(root, "worktree", "add", "-b", branch, str(path), base)
    return Worktree(path=path, branch=branch, base=base)


def commit_all(path: str | Path, message: str) -> tuple[str, bool]:
    """Commit every change in the worktree. Returns (commit, created)."""
    repo = Path(path)
    status = git(repo, "status", "--porcelain").stdout.strip()
    if status:
        git(repo, "add", "-A")
        git(repo, "commit", "-m", message)
        return rev_parse(repo, "HEAD"), True
    return rev_parse(repo, "HEAD"), False


def remove_worktree(root: str | Path, path: str | Path) -> None:
    git(root, "worktree", "remove", "--force", str(path), check=False)
    git(root, "worktree", "prune", check=False)


def is_clean(path: str | Path) -> bool:
    return not git(path, "status", "--porcelain").stdout.strip()


def current_branch(path: str | Path) -> str:
    proc = git(path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return proc.stdout.strip()
