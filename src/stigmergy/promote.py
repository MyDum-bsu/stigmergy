"""Promote the base branch into protected main.

This is deliberately a separate command with its own human gate: the factory
can finish `dev`, but only a human can move `main`. The default is a dry run;
``--apply`` is refused for non-fast-forward or dirty trees.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from stigmergy.config import Config


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return (proc.stdout or proc.stderr).strip()


def _branch(config: Config) -> str:
    protected = config.protected
    if not protected:
        raise ValueError("project has no protected branch")
    return str(protected[0])


def status(config: Config) -> dict[str, Any]:
    target = _branch(config)
    base = config.base
    main_sha = _git(config.root, "rev-parse", "--verify", target)
    dev_sha = _git(config.root, "rev-parse", "--verify", base)
    if not main_sha or not dev_sha:
        return {"ok": False, "target": target, "base": base, "detail": "branch missing"}
    ancestor = subprocess.run(
        ["git", "-C", str(config.root), "merge-base", "--is-ancestor", target, base],
        check=False,
        capture_output=True,
    ).returncode == 0
    dirty = bool(_git(config.root, "status", "--porcelain"))
    ahead = _git(config.root, "rev-list", "--count", f"{target}..{base}")
    behind = _git(config.root, "rev-list", "--count", f"{base}..{target}")
    return {
        "ok": ancestor and not dirty,
        "target": target,
        "base": base,
        "main": main_sha,
        "dev": dev_sha,
        "fast_forward": ancestor,
        "dev_ahead": int(ahead or 0),
        "main_ahead": int(behind or 0),
        "dirty": dirty,
        "detail": "" if ancestor and not dirty else (
            "main has commits not in dev; merge/rebase first"
            if not ancestor
            else "working tree is dirty"
        ),
    }


def apply(config: Config) -> dict[str, Any]:
    data = status(config)
    if not data["ok"]:
        return {**data, "applied": False}
    root = config.root
    current = _git(root, "branch", "--show-current")
    if current == data["target"]:
        proc = subprocess.run(
            ["git", "-C", str(root), "merge", "--ff-only", data["base"]],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return {**data, "applied": False, "detail": (proc.stderr or proc.stdout).strip()[:1000]}
        after = _git(root, "rev-parse", "HEAD")
    else:
        # Do not update a branch checked out in another worktree.
        worktrees = _git(root, "worktree", "list", "--porcelain")
        for line in worktrees.splitlines():
            if line == f"branch refs/heads/{data['target']}":
                return {
                    **data,
                    "applied": False,
                    "detail": f"{data['target']} is checked out in another worktree",
                }
        proc = subprocess.run(
            ["git", "-C", str(root), "update-ref", f"refs/heads/{data['target']}", data["dev"]],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return {**data, "applied": False, "detail": (proc.stderr or proc.stdout).strip()[:1000]}
        after = data["dev"]
    return {**data, "applied": True, "after": after, "detail": "fast-forward"}
