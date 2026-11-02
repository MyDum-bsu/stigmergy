"""Visual acceptance adapter: a command owns the browser/computer session.

The factory does not embed a browser. It runs the configured acceptance command
with the target in ``STG_VISUAL_TARGET`` and the evidence directory in
``STG_VISUAL_OUT``; the command returns non-zero on a failed visual verdict.
Dry-run prints the plan and never launches the computer.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from stigmergy.config import Config


def check(
    config: Config,
    target: str,
    *,
    run_now: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
    command = str(config.section("visual").get("command") or "").strip()
    if not command:
        return {
            "ok": False,
            "detail": "no [visual].command configured",
            "target": target,
            "dry_run": not run_now,
        }
    out = config.artifacts_root / "visual" / "latest"
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["STG_VISUAL_TARGET"] = target
    env["STG_VISUAL_OUT"] = str(out)
    if not run_now:
        return {
            "ok": True,
            "dry_run": True,
            "target": target,
            "command": command,
            "out": str(out),
        }
    wait = int(timeout or config.section("visual").get("timeout_seconds", 120))
    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=str(config.root),
            env=env,
            text=True,
            capture_output=True,
            timeout=wait,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "target": target, "detail": "visual timeout", "out": str(out)}
    return {
        "ok": proc.returncode == 0,
        "target": target,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-1000:],
        "stderr": (proc.stderr or "")[-1000:],
        "out": str(out),
    }


def evidence(config: Config) -> list[Path]:
    root = config.artifacts_root / "visual"
    return sorted(root.glob("**/*")) if root.exists() else []
