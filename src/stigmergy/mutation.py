"""Mutation harness: each command mutates a throwaway worktree and must fail."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from stigmergy.config import Config
from stigmergy.workspace import git, remove_worktree


def run(config: Config, commit: str, commands: list[str], *, timeout: int = 120) -> dict[str, Any]:
    if not commands:
        return {"ok": False, "detail": "no mutation commands configured", "survivors": []}
    path = config.root / ".factory" / "mutation" / f"m-{int(time.time())}"
    path.parent.mkdir(parents=True, exist_ok=True)
    add = git(config.root, "worktree", "add", "--detach", str(path), commit, check=False)
    if add.returncode != 0:
        return {"ok": False, "detail": (add.stderr or add.stdout).strip()[:500], "survivors": []}
    survivors: list[str] = []
    killed: list[str] = []
    try:
        for command in commands:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=path,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            if proc.returncode == 0:
                survivors.append(command)
            else:
                killed.append(command)
    finally:
        remove_worktree(config.root, path)
    return {
        "ok": not survivors,
        "survivors": survivors,
        "killed": killed,
        "commit": commit,
    }
