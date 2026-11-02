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
    argv = _aa_prefix() + _common(worktree, home, env)
    argv.append("--unshare-net")
    for path in oracle_paths:
        if path.exists():
            argv.extend(["--ro-bind", str(path), str(path)])
    argv.extend(["--", "bash", "-lc", command])
    return argv


def _aa_profile() -> str:
    """Herdr terminals are AppArmor 'unconfined'; userns needs the zcode profile.

    Probe in the caller, not via the caller's current profile: the tab is
    started later by Herdr and may have a different profile.
    """
    exe = shutil.which("aa-exec")
    if not exe:
        return ""
    probe = subprocess.run(
        [exe, "-p", "zcode", "--", "true"],
        capture_output=True,
        check=False,
    )
    return "zcode" if probe.returncode == 0 else ""


def _aa_prefix(profile: str | None = None) -> list[str]:
    name = profile if profile is not None else _aa_profile()
    return ["aa-exec", "-p", name, "--"] if name else []


def worker_argv(
    worktree: Path,
    root: Path,
    agent: str,
    agent_args: list[str],
    aa_profile: str | None = None,
) -> list[str]:
    """Filesystem sandbox for an agent that still needs the model network.

    Root is read-only; the worktree, the board and pi's auth/cache are the only
    writable mounts. Secrets, data/ and other home config are masked.
    """
    home = Path.home()
    argv = _aa_prefix(aa_profile) + [
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
    ]
    masked = [
        home / ".ssh",
        home / ".zcode",
        home / ".config",
        root / "data",
        root / "tracker" / "data",
    ]
    for path in masked:
        if path.exists():
            argv.extend(["--tmpfs", str(path)])
    writable = [
        worktree,
        root / ".agent",
        home / ".pi",
        home / ".cache",
    ]
    for path in writable:
        if path.exists():
            argv.extend(["--bind", str(path), str(path)])
    argv.extend(
        [
            "--chdir",
            str(worktree),
            "--die-with-parent",
            "--new-session",
            "--setenv",
            "HOME",
            str(home),
            "--setenv",
            "PATH",
            os.environ.get("PATH", "/usr/bin:/bin"),
            "--",
            agent,
            *agent_args,
        ]
    )
    return argv


def _profile_argv(
    worktree: Path,
    root: Path,
    writable: list[Path],
    agent: str,
    agent_args: list[str],
    aa_profile: str | None = None,
) -> list[str]:
    home = Path.home()
    argv = _aa_prefix(aa_profile) + [
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
    ]
    for path in (home / ".ssh", home / ".zcode", home / ".config", root / "data", root / "tracker" / "data"):
        if path.exists():
            argv.extend(["--tmpfs", str(path)])
    for path in [*writable, home / ".pi", home / ".cache"]:
        if path.exists():
            argv.extend(["--bind", str(path), str(path)])
    argv.extend(
        [
            "--chdir",
            str(worktree),
            "--die-with-parent",
            "--new-session",
            "--setenv",
            "HOME",
            str(home),
            "--setenv",
            "PATH",
            os.environ.get("PATH", "/usr/bin:/bin"),
            "--",
            agent,
            *agent_args,
        ]
    )
    return argv


def planner_argv(
    plan_root: Path,
    root: Path,
    agent: str,
    agent_args: list[str],
    aa_profile: str | None = None,
) -> list[str]:
    return _profile_argv(plan_root, root, [plan_root], agent, agent_args, aa_profile)


def lead_argv(
    root: Path,
    agent: str,
    agent_args: list[str],
    aa_profile: str | None = None,
) -> list[str]:
    return _profile_argv(
        root,
        root,
        [root / ".agent", root / ".factory", Path.home() / ".config" / "herdr-app"],
        agent,
        agent_args,
        aa_profile,
    )


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
