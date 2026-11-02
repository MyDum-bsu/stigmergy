"""The gate: execute the decision procedure in a pristine, anchored worktree."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from stigmergy import sandbox
from stigmergy.config import Config
from stigmergy.log import sha256_file
from stigmergy.spec import Spec
from stigmergy.workspace import git, remove_worktree, worktree_exists


class GateError(RuntimeError):
    pass


@dataclass
class GateResult:
    task: str
    episode: str
    base: str
    commit: str
    tree: str
    oracle_sha: str
    command: str
    exit_code: int
    duration_ms: int
    control: dict[str, Any] = field(default_factory=dict)
    artifact_dir: Path = Path()
    stdout: str = ""
    stderr: str = ""
    passed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "stigmergy/gate/v1",
            "task": self.task,
            "episode": self.episode,
            "base": self.base,
            "commit": self.commit,
            "tree": self.tree,
            "oracle_sha": self.oracle_sha,
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "control": self.control,
            "artifact": str(self.artifact_dir),
            "stdout_sha256": hashlib.sha256(self.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr.encode()).hexdigest(),
            "passed": self.passed,
        }


def _ls_tree(repo: Path, rev: str, paths: list[str]) -> list[tuple[str, str]]:
    if not paths:
        return []
    proc = git(repo, "ls-tree", "-r", rev, "--", *paths, check=False)
    if proc.returncode != 0:
        raise GateError(proc.stderr.strip())
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            out.append((path, parts[2]))
    return out


def oracle_digest(repo: Path, rev: str, paths: list[str]) -> str:
    entries = _ls_tree(repo, rev, paths)
    payload = "\n".join(f"{path}:{sha}" for path, sha in sorted(entries))
    return hashlib.sha256(payload.encode()).hexdigest()


def _existing(repo: Path, base: str, paths: list[str]) -> list[str]:
    return [path for path in paths if _ls_tree(repo, base, [path])]


def _restore(repo: Path, wt: Path, base: str, paths: list[str]) -> None:
    if not paths:
        return
    proc = git(wt, "checkout", base, "--", *paths, check=False)
    if proc.returncode != 0:
        raise GateError(f"restore from {base} failed: {proc.stderr.strip()}")
    diff = git(wt, "diff", "--quiet", base, "--", *paths, check=False)
    if diff.returncode != 0:
        raise GateError("oracle/gate inputs still differ from base after restore")


def _matched_paths(wt: Path, patterns: list[str]) -> list[Path]:
    matched: list[Path] = []
    for pattern in patterns:
        direct = wt / pattern
        if direct.exists():
            matched.append(direct)
            continue
        matched.extend(sorted(wt.glob(pattern)))
    return matched


def _env(config: Config, home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = sandbox.default_env(config.gate.get("env") or {})
    env["HOME"] = str(home)
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _run(
    wt: Path,
    command: str,
    env: dict[str, str],
    timeout: int,
    *,
    use_sandbox: bool,
    oracle_paths: list[Path],
) -> tuple[int, str, str, int]:
    start = time.monotonic()
    argv: list[str]
    if use_sandbox:
        if not sandbox.bwrap_available():
            raise GateError("bwrap requested but not found")
        home = Path(env["HOME"])
        argv = sandbox.gate_argv(wt, oracle_paths, command, env, home)
        proc = subprocess.run(
            argv,
            cwd=str(wt),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    else:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(wt),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    duration = int((time.monotonic() - start) * 1000)
    return proc.returncode, proc.stdout, proc.stderr, duration


def _control(
    config: Config,
    spec: Spec,
    commit: str,
    base: str,
    episode: str,
    command: str,
    env: dict[str, str],
    timeout: int,
    *,
    use_sandbox: bool,
) -> dict[str, Any]:
    corpus_rel = spec.negative_corpus
    if not corpus_rel:
        return {"result": "absent", "cases": 0}
    listing = git(config.root, "ls-tree", "-r", "--name-only", base, "--", corpus_rel, check=False)
    if listing.returncode != 0:
        return {"result": "error", "cases": 0, "detail": f"corpus not in {base}: {corpus_rel}"}
    names = [line for line in listing.stdout.splitlines() if line.endswith(".patch")]
    if not names:
        return {"result": "absent", "cases": 0}
    patches: list[tuple[str, Path]] = []
    patch_dir = config.artifacts_root / spec.id / episode
    patch_dir.mkdir(parents=True, exist_ok=True)
    for idx, name in enumerate(names):
        show = git(config.root, "show", f"{base}:{name}", check=False)
        if show.returncode != 0:
            return {"result": "error", "cases": 0, "detail": f"cannot read {name} at {base}"}
        patch_path = patch_dir / f"control-{idx}.patch"
        patch_path.write_text(show.stdout, encoding="utf-8")
        patches.append((name, patch_path))
    details: list[dict[str, Any]] = []
    dead = False
    for idx, (name, patch) in enumerate(patches):
        wt = config.gate_root / f"{spec.id}-{episode}-control-{idx}"
        if worktree_exists(config.root, wt):
            remove_worktree(config.root, wt)
        git(config.root, "worktree", "add", "--detach", str(wt), commit)
        try:
            restore_paths = _existing(config.root, base, spec.oracle_paths)
            missing = set(spec.oracle_paths) - set(restore_paths)
            if missing:
                raise GateError(f"oracle paths missing at {base}: {sorted(missing)}")
            restore_paths += _existing(config.root, base, spec.gate_inputs)
            _restore(config.root, wt, base, restore_paths)
            apply = git(wt, "apply", "--whitespace=nowarn", str(patch), check=False)
            if apply.returncode != 0:
                details.append(
                    {"patch": Path(name).name, "applied": False, "detail": apply.stderr.strip()[:300]}
                )
                continue
            code, out, err, _ = _run(
                wt,
                command,
                env,
                timeout,
                use_sandbox=use_sandbox,
                oracle_paths=_matched_paths(wt, spec.oracle_paths),
            )
            details.append(
                {
                    "patch": Path(name).name,
                    "applied": True,
                    "exit_code": code,
                    "stdout_tail": out[-300:],
                    "stderr_tail": err[-300:],
                }
            )
            if code == 0:
                dead = True
        finally:
            remove_worktree(config.root, wt)
    if dead:
        result = "dead"
    elif any(not d.get("applied") for d in details):
        result = "error"
    else:
        result = "proven"
    return {"result": result, "cases": len(patches), "details": details}


def diff_paths(repo: Path, base: str, commit: str) -> list[str]:
    merge_base = git(repo, "merge-base", base, commit, check=False)
    if merge_base.returncode != 0:
        raise GateError(merge_base.stderr.strip())
    fork = merge_base.stdout.strip()
    proc = git(repo, "diff", "--name-only", f"{fork}..{commit}", check=False)
    if proc.returncode != 0:
        raise GateError(proc.stderr.strip())
    return [line for line in proc.stdout.splitlines() if line]


def paths_allowed(paths: list[str], patterns: list[str]) -> tuple[bool, list[str]]:
    if not patterns:
        return True, []
    bad: list[str] = []
    for path in paths:
        if any(
            path == pattern
            or fnmatch(path, pattern)
            or (pattern.endswith("/**") and path.startswith(pattern[:-3] + "/"))
            for pattern in patterns
        ):
            continue
        bad.append(path)
    return not bad, bad


def run_gate(
    config: Config,
    spec: Spec,
    commit: str,
    base: str,
    episode: str,
    *,
    use_sandbox: bool | None = None,
) -> GateResult:
    if use_sandbox is None:
        use_sandbox = bool(config.sandbox.get("engine") == "bwrap" and sandbox.bwrap_available())
    root = config.root
    ok_paths, violations = paths_allowed(diff_paths(root, base, commit), spec.allowed_paths)
    if not ok_paths:
        artifact_dir = config.artifacts_root / spec.id / episode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        message = "paths outside allowed_paths: " + ", ".join(violations[:20])
        result = GateResult(
            task=spec.id,
            episode=episode,
            base=base,
            commit=commit,
            tree=git(root, "rev-parse", f"{commit}^{{tree}}").stdout.strip(),
            oracle_sha=oracle_digest(root, base, _existing(root, base, spec.oracle_paths)),
            command="allowed_paths",
            exit_code=126,
            duration_ms=0,
            control={"result": "skipped"},
            artifact_dir=artifact_dir,
            stderr=message,
            passed=False,
        )
        (artifact_dir / "gate.json").write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result
    wt = config.gate_root / f"{spec.id}-{episode}"
    if worktree_exists(root, wt):
        remove_worktree(root, wt)
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "--detach", str(wt), commit)
    artifact_dir = config.artifacts_root / spec.id / episode
    artifact_dir.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="stg-home-", dir=str(artifact_dir)))
    try:
        restore_paths = _existing(root, base, spec.oracle_paths)
        missing = set(spec.oracle_paths) - set(restore_paths)
        if missing:
            raise GateError(f"oracle paths missing at {base}: {sorted(missing)}")
        restore_paths += _existing(root, base, spec.gate_inputs)
        _restore(root, wt, base, restore_paths)
        oracle_sha = oracle_digest(root, base, restore_paths)
        command = spec.dod or str(config.gate.get("default_dod") or "")
        if not command:
            raise GateError("no dod and no gate.default_dod")
        timeout = int(config.gate.get("timeout_seconds", 1800))
        env = _env(config, home)
        oracle_paths = _matched_paths(wt, spec.oracle_paths)
        try:
            code, stdout, stderr, duration = _run(
                wt,
                command,
                env,
                timeout,
                use_sandbox=use_sandbox,
                oracle_paths=oracle_paths,
            )
        except subprocess.TimeoutExpired as exc:
            code, stdout, stderr, duration = 124, str(exc.stdout or ""), "timeout", timeout * 1000
        (artifact_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (artifact_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        control = _control(
            config,
            spec,
            commit,
            base,
            episode,
            command,
            env,
            timeout,
            use_sandbox=use_sandbox,
        )
        tree = git(wt, "rev-parse", "HEAD^{tree}").stdout.strip()
        passed = code == 0 and (
            control["result"] == "proven"
            or (spec.risk == "low" and control["result"] == "absent")
        )
        result = GateResult(
            task=spec.id,
            episode=episode,
            base=base,
            commit=commit,
            tree=tree,
            oracle_sha=oracle_sha,
            command=command,
            exit_code=code,
            duration_ms=duration,
            control=control,
            artifact_dir=artifact_dir,
            stdout=stdout,
            stderr=stderr,
            passed=passed,
        )
        (artifact_dir / "gate.json").write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        remove_worktree(root, wt)


def gate_artifact(config: Config, task_id: str, episode: str) -> dict[str, Any]:
    path = config.artifacts_root / task_id / episode / "gate.json"
    if not path.exists():
        raise GateError(f"gate artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_hashes(result: GateResult) -> dict[str, str]:
    return {
        "stdout": sha256_file(result.artifact_dir / "stdout.log"),
        "stderr": sha256_file(result.artifact_dir / "stderr.log"),
        "gate": sha256_file(result.artifact_dir / "gate.json"),
    }
