"""Environment readiness checks for ``stg doctor``."""

from __future__ import annotations

import shutil
import subprocess

from stigmergy import sandbox
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.registry import load as registry_load


def _cmd(args: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()[:300]


def checks(config: Config, board: Board | None = None) -> list[dict]:
    root = config.root
    out: list[dict] = []

    def add(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
        out.append({"name": name, "ok": ok, "detail": detail, "required": required})

    add("git", (root / ".git").exists(), str(root))
    add(".agent", (root / ".agent").exists(), str(root / ".agent"))
    add(".agent.toml", (root / ".agent.toml").exists(), str(root / ".agent.toml"), required=False)
    add("specs/", (root / "specs").is_dir(), str(root / "specs"), required=False)
    add("bwrap", sandbox.bwrap_available(), shutil.which("bwrap") or "not found", required=False)
    ok, detail = _cmd(["systemctl", "--user", "is-system-running"])
    add("systemd --user", ok or detail == "degraded", detail, required=False)
    add("herdr", shutil.which("herdr") is not None, shutil.which("herdr") or "not found", required=False)
    runner_kind = str(config.runner.get("kind", "manual"))
    if runner_kind == "herdr-app":
        from stigmergy.runner import herdr_app

        app = str(config.runner.get("app", herdr_app.DEFAULT_APP))
        state = herdr_app.status(app)
        add("runner", state["ok"], app if state["ok"] else str(state.get("error", app)))
    elif runner_kind == "herdr":
        add("runner", True, runner_kind)
        from stigmergy.runner import herdr as herdr_mod

        state = herdr_mod.status(str(config.runner.get("session", "factory")))
        detail = state["text"].splitlines()[-1] if state["text"] else ""
        add("herdr server", state["ok"], detail)
    else:
        add("runner", runner_kind == "manual", runner_kind)
    registered = {item["name"] for item in registry_load()}
    add("registry", config.name in registered, f"{config.name} in {len(registered)} project(s)", required=False)
    return out


def summary(items: list[dict]) -> dict:
    failed = [item for item in items if not item["ok"] and item["required"]]
    return {"ok": not failed, "failed": [item["name"] for item in failed], "checks": items}
