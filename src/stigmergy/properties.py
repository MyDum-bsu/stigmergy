"""Property-based and live-model checks.

The property command is run once per deterministic seed (``STG_SEED``), so a
test suite can use the seed to generate its inputs. The live-model command is
run once against a fresh worktree. Both are optional for low/medium tasks and
mandatory for high-risk specs; the gate treats a failure as a failed verdict.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from stigmergy import sandbox
from stigmergy.config import Config
from stigmergy.spec import Spec
from stigmergy.workspace import git, remove_worktree


class PropertyError(RuntimeError):
    pass


def _command(block: dict[str, Any], key: str = "command") -> str:
    return str(block.get(key) or "").strip()


def _run(
    path: Path,
    command: str,
    env: dict[str, str],
    timeout: int,
    *,
    use_sandbox: bool,
    home: Path | None = None,
) -> tuple[int, str, str]:
    if use_sandbox:
        if not sandbox.bwrap_available():
            raise PropertyError("bwrap requested but not found")
        sandbox_home = home or Path(tempfile.mkdtemp(prefix="stg-property-home-"))
        argv = sandbox.gate_argv(path, [], command, env, sandbox_home)
        proc = subprocess.run(
            argv,
            cwd=str(path),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    else:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(path),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _tail(text: str, limit: int = 500) -> str:
    return text[-limit:]


def run(
    config: Config,
    spec: Spec,
    commit: str,
    *,
    use_sandbox: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Run all seed properties and the live-model probe on ``commit``."""
    properties = spec.properties
    live = spec.live_model
    property_command = _command(properties)
    live_command = _command(live)
    if not property_command and not live_command:
        return {
            "ok": True,
            "skipped": True,
            "detail": "no properties or live_model configured",
            "properties": None,
            "live_model": None,
        }
    path = config.root / ".factory" / "properties" / f"{spec.id}-{int(time.time())}"
    path.parent.mkdir(parents=True, exist_ok=True)
    add = git(config.root, "worktree", "add", "--detach", str(path), commit, check=False)
    if add.returncode != 0:
        return {
            "ok": False,
            "skipped": False,
            "detail": (add.stderr or add.stdout).strip()[:500],
            "properties": None,
            "live_model": None,
        }
    env = sandbox.default_env(
        {
            "HOME": os.environ.get("HOME", str(Path.home())),
            "STG_SEED": "0",
            "STG_PROPERTY_SEED": "0",
            "STG_TASK": spec.id,
            "STG_COMMIT": commit,
        }
    )
    home = Path(tempfile.mkdtemp(prefix="stg-property-home-", dir=str(path.parent)))
    property_result: dict[str, Any] | None = None
    live_result: dict[str, Any] | None = None
    try:
        if property_command:
            seeds = max(1, min(1000, int(properties.get("seeds", 1) or 1)))
            seed_timeout = int(timeout or properties.get("timeout_seconds", 120) or 120)
            cases: list[dict[str, Any]] = []
            for seed in range(seeds):
                seed_env = dict(env)
                seed_env["STG_SEED"] = str(seed)
                seed_env["STG_PROPERTY_SEED"] = str(seed)
                try:
                    code, out, err = _run(
                        path,
                        property_command,
                        seed_env,
                        seed_timeout,
                        use_sandbox=use_sandbox,
                        home=home,
                    )
                except subprocess.TimeoutExpired:
                    code, out, err = 124, "", "property timeout"
                cases.append(
                    {
                        "seed": seed,
                        "exit_code": code,
                        "stdout": _tail(out),
                        "stderr": _tail(err),
                    }
                )
                if code != 0:
                    break
            property_result = {
                "ok": all(case["exit_code"] == 0 for case in cases),
                "command": property_command,
                "seeds": seeds,
                "cases": cases,
            }
        if live_command:
            live_timeout = int(timeout or live.get("timeout_seconds", 300) or 300)
            live_env = dict(env)
            live_env["STG_LIVE_MODEL"] = "1"
            try:
                code, out, err = _run(
                    path,
                    live_command,
                    live_env,
                    live_timeout,
                    use_sandbox=use_sandbox,
                    home=home,
                )
            except subprocess.TimeoutExpired:
                code, out, err = 124, "", "live-model timeout"
            live_result = {
                "ok": code == 0,
                "command": live_command,
                "exit_code": code,
                "stdout": _tail(out),
                "stderr": _tail(err),
            }
    finally:
        remove_worktree(config.root, path)
    ok = bool(
        (property_result is None or property_result["ok"])
        and (live_result is None or live_result["ok"])
    )
    return {
        "ok": ok,
        "skipped": False,
        "detail": "" if ok else "property/live-model check failed",
        "properties": property_result,
        "live_model": live_result,
    }


def text(data: dict[str, Any]) -> str:
    if data.get("skipped"):
        return "pbt: SKIP (no properties/live_model)"
    prop = data.get("properties") or {}
    live = data.get("live_model") or {}
    return (
        f"pbt: {'PASS' if data.get('ok') else 'FAIL'} "
        f"seeds={prop.get('seeds', 0)} live_model={'ok' if live.get('ok') else 'fail' if live else 'off'}"
    )
