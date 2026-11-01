"""Merge queue: rebase onto the base branch, run the full gate, fast-forward."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.gate import GateResult, run_gate
from stigmergy.spec import Spec
from stigmergy.workspace import (
    current_branch,
    git,
    is_clean,
    remove_worktree,
    rev_parse,
    tree_of,
    worktree_exists,
)


class IntegrationError(RuntimeError):
    pass


@dataclass
class IntegrationResult:
    ok: bool
    base: str
    commit: str
    tree: str
    detail: str = ""
    artifact: Path = Path()
    gate: GateResult | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "base": self.base,
            "commit": self.commit,
            "tree": self.tree,
            "detail": self.detail,
            "artifact": str(self.artifact),
            "gate": self.gate.as_dict() if self.gate else None,
        }


def _integration_worktree(config: Config) -> tuple[Path, bool]:
    """Return (path, detached). The worktree is checked out at ``base``."""
    base = config.base
    path = config.integration_root
    path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_exists(config.root, path):
        branch = current_branch(path)
        if branch == base and is_clean(path):
            return path, False
        remove_worktree(config.root, path)
    proc = git(config.root, "worktree", "add", str(path), base, check=False)
    if proc.returncode == 0:
        return path, False
    git(config.root, "worktree", "add", "--detach", str(path), base, check=False)
    return path, True


def _rebase(config: Config, task_wt: Path, base: str) -> tuple[bool, str]:
    if not is_clean(task_wt):
        return False, "task worktree is dirty"
    proc = git(task_wt, "rebase", base, check=False)
    if proc.returncode == 0:
        return True, ""
    git(task_wt, "rebase", "--abort", check=False)
    return False, (proc.stderr or proc.stdout).strip()[:2000]


def ff_base(config: Config, commit: str) -> tuple[bool, str]:
    """Fast-forward the base branch to ``commit`` in the integration worktree."""
    int_wt, detached = _integration_worktree(config)
    proc = git(int_wt, "merge", "--ff-only", commit, check=False)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:2000]
    if detached:
        git(config.root, "update-ref", f"refs/heads/{config.base}", rev_parse(int_wt, "HEAD"))
    return True, ""


def integrate(
    config: Config,
    spec: Spec,
    task_wt: Path,
    base: str,
    episode: str,
    *,
    use_sandbox: bool | None = None,
    do_merge: bool = True,
) -> IntegrationResult:
    ok, detail = _rebase(config, task_wt, base)
    if not ok:
        return IntegrationResult(ok=False, base=base, commit="", tree="", detail=detail)
    commit = rev_parse(task_wt, "HEAD")
    tree = tree_of(task_wt, "HEAD")
    gate = run_gate(config, spec, commit, base, f"{episode}-integration", use_sandbox=use_sandbox)
    artifact = gate.artifact_dir / "gate.json"
    if not gate.passed:
        return IntegrationResult(
            ok=False,
            base=base,
            commit=commit,
            tree=tree,
            detail=f"integration gate failed: exit={gate.exit_code} control={gate.control.get('result')}",
            artifact=artifact,
            gate=gate,
        )
    int_wt, detached = _integration_worktree(config)
    if not do_merge:
        return IntegrationResult(
            ok=True,
            base=base,
            commit=commit,
            tree=tree,
            detail="gated, awaiting merge",
            artifact=artifact,
            gate=gate,
        )
    proc = git(int_wt, "merge", "--ff-only", commit, check=False)
    if proc.returncode != 0:
        return IntegrationResult(
            ok=False,
            base=base,
            commit=commit,
            tree=tree,
            detail=f"ff merge failed: {proc.stderr.strip()[:1000]}",
            artifact=artifact,
            gate=gate,
        )
    new_base = rev_parse(int_wt, "HEAD")
    if detached:
        git(config.root, "update-ref", f"refs/heads/{config.base}", new_base)
    return IntegrationResult(
        ok=True,
        base=base,
        commit=new_base,
        tree=tree_of(int_wt, "HEAD"),
        detail="fast-forward",
        artifact=artifact,
        gate=gate,
    )


def write_integration_artifact(config: Config, episode: str, result: IntegrationResult) -> Path:
    path = config.artifacts_root / "_integration" / f"{episode}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
