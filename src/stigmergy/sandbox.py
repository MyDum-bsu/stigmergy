"""bubblewrap profiles for episodes and gates.

The gate profile is the security boundary for the verdict: read-only root, only
the gate worktree writable, oracle paths re-bound read-only, network off.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def _env_args(env: dict[str, str]) -> list[str]:
    args: list[str] = []
    for key, value in sorted(env.items()):
        args.extend(["--setenv", key, str(value)])
    return args


def _common(worktree: Path, home: Path, env: dict[str, str]) -> list[str]:
    return [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        str(home),
        "--bind",
        str(worktree),
        str(worktree),
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        *_env_args(env),
    ]


def gate_argv(
    worktree: Path,
    oracle_paths: list[Path],
    command: str,
    env: dict[str, str],
    home: Path,
) -> list[str]:
    argv = _common(worktree, home, env)
    argv.append("--unshare-net")
    for path in oracle_paths:
        if path.exists():
            argv.extend(["--ro-bind", str(path), str(path)])
    argv.extend(["--", "bash", "-lc", command])
    return argv


def episode_argv(
    worktree: Path,
    repo_git_dir: Path | None,
    command: list[str],
    env: dict[str, str],
    home: Path,
) -> list[str]:
    argv = _common(worktree, home, env)
    if repo_git_dir and repo_git_dir.exists():
        argv.extend(["--ro-bind", str(repo_git_dir), str(repo_git_dir)])
    argv.extend(["--", *command])
    return argv


def canary_script(worktree: Path, forbidden: list[Path]) -> str:
    checks = [
        "set -eu",
        f"test -w {worktree}",
        f"echo canary > {worktree}/.stg-canary",
        f"rm -f {worktree}/.stg-canary",
    ]
    for path in forbidden:
        checks.append(f"if test -e {path}; then echo 'visible: {path}' >&2; exit 42; fi")
    checks.append("echo ok")
    return "\n".join(checks)


def run_canary(worktree: Path, forbidden: list[Path], home: Path, env: dict[str, str]) -> tuple[bool, str]:
    if not bwrap_available():
        return False, "bwrap not found"
    argv = _common(worktree, home, env)
    argv.extend(["--unshare-net", "--", "bash", "-lc", canary_script(worktree, forbidden)])
    proc = subprocess.run(argv, text=True, capture_output=True, check=False)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def default_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "CI": "1",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": "/tmp",
    }
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
