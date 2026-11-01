"""Herdr adapter: attach to a dedicated ``factory`` session, never restore labs.

Herdr is a terminal runtime, not the source of truth.  Its statuses are liveness
signals only; the verdict comes from the tree and the gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from stigmergy.runner.base import RunnerHandle

DEFAULT_SESSION = "factory"
ERROR_MARKERS = (
    "GoUsageLimitError",
    "usage limit exceeded",
    "Error: 401",
    "Error: 403",
    "Error: 429",
    "Error: 500",
    "Error: 502",
    "Error: 503",
)


class HerdrError(RuntimeError):
    pass


def detect_error(text: str) -> str:
    """The screen is not a verdict, but a provider error must fail the episode."""
    for marker in ERROR_MARKERS:
        if marker in text:
            return marker
    return ""


def binary() -> str:
    return shutil.which("herdr") or "herdr"


def _run(session: str, *args: str, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        [binary(), "--session", session, *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def _json(session: str, *args: str, timeout: int = 30) -> dict:
    code, out = _run(session, *args, timeout=timeout)
    if code != 0:
        raise HerdrError(out[:1000])
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise HerdrError(f"non-JSON herdr output: {out[:500]}") from exc


def workspaces(session: str = DEFAULT_SESSION) -> list[dict]:
    data = _json(session, "workspace", "list")
    return list((data.get("result") or {}).get("workspaces") or [])


def guard(session: str = DEFAULT_SESSION, prefix: str = "stg-") -> tuple[bool, str]:
    try:
        items = workspaces(session)
    except HerdrError as exc:
        return False, str(exc)
    foreign = []
    for item in items:
        label = str(item.get("label", ""))
        if label.startswith(prefix):
            continue
        # A fresh session starts with one empty home workspace ("~").
        if label == "~" and int(item.get("number", 0)) == 1:
            continue
        foreign.append(label)
    if foreign:
        return False, f"foreign workspaces in {session}: {foreign}"
    return True, f"{len(items)} workspace(s)"


def create_workspace(session: str, cwd: Path, label: str) -> dict:
    data = _json(
        session,
        "workspace",
        "create",
        "--cwd",
        str(cwd),
        "--label",
        label,
        "--no-focus",
    )
    return data.get("result") or {}


def start_agent(session: str, name: str, kind: str, pane: str) -> dict:
    data = _json(session, "agent", "start", name, "--kind", kind, "--pane", pane)
    return data.get("result") or {}


def prompt(session: str, target: str, text: str, timeout_ms: int = 1_800_000) -> dict:
    data = _json(
        session,
        "agent",
        "prompt",
        target,
        text,
        "--wait",
        "--timeout",
        str(timeout_ms),
        timeout=max(30, timeout_ms // 1000 + 30),
    )
    return data.get("result") or {}


def read(session: str, target: str, lines: int = 120) -> str:
    code, out = _run(session, "agent", "read", target, "--source", "recent-unwrapped", "--lines", str(lines))
    if code != 0:
        raise HerdrError(out[:1000])
    return out


def send_keys(session: str, target: str, *keys: str) -> dict:
    return _json(session, "agent", "send-keys", target, *keys).get("result") or {}


def close_workspace(session: str, workspace_id: str) -> dict:
    return _json(session, "workspace", "close", workspace_id).get("result") or {}


def own_workspaces(session: str = DEFAULT_SESSION, prefix: str = "stg-") -> list[dict]:
    return [item for item in workspaces(session) if str(item.get("label", "")).startswith(prefix)]


def cleanup(session: str = DEFAULT_SESSION, task: str | None = None) -> list[str]:
    closed: list[str] = []
    for item in own_workspaces(session):
        label = str(item.get("label", ""))
        if task and label != f"stg-{task}":
            continue
        close_workspace(session, str(item["workspace_id"]))
        closed.append(label)
    return closed


def status(session: str = DEFAULT_SESSION) -> dict:
    proc = subprocess.run(
        [binary(), "--session", session, "status"],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    text = (proc.stdout or proc.stderr).strip()
    return {"ok": proc.returncode == 0 and "status: running" in text, "text": text, "session": session}


def unit_text(session: str = DEFAULT_SESSION) -> str:
    herdr = binary()
    return f"""[Unit]
Description=stigmergy Herdr factory session ({session})
After=default.target

[Service]
Type=simple
Environment=TERM=xterm-256color
ExecStart=/usr/bin/script -qec 'stty rows 40 cols 120; exec {herdr} --session {session}' /dev/null
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""


def unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "stigmergy-herdr.service"


def install_service(session: str = DEFAULT_SESSION) -> Path:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(session), encoding="utf-8")
    return path


def reset_session(session: str = DEFAULT_SESSION, *, yes: bool = False) -> list[str]:
    """Archive Herdr state that could restore agents. Refuses without ``yes``."""
    if not yes:
        raise HerdrError("refusing to reset without --yes")
    base = Path.home() / ".config" / "herdr"
    moved: list[str] = []
    if not base.exists():
        return moved
    for path in sorted(base.rglob(f"*{session}*")):
        if path.is_file() and not path.name.endswith(".bak"):
            target = path.with_suffix(path.suffix + ".bak")
            path.rename(target)
            moved.append(str(target))
    return moved


class HerdrRunner:
    kind = "herdr"

    def __init__(self, session: str = DEFAULT_SESSION, agent: str = "pi", timeout_ms: int = 1_800_000):
        self.session = session
        self.agent = agent
        self.timeout_ms = timeout_ms

    def start(self, task_id: str, prompt_text: str, workspace: Path) -> RunnerHandle:
        ok, detail = guard(self.session)
        if not ok:
            raise HerdrError(f"herdr guard failed: {detail}")
        created = create_workspace(self.session, workspace, f"stg-{task_id}")
        pane = str((created.get("root_pane") or {}).get("pane_id", ""))
        name = f"stg-{task_id}".lower().replace("_", "-")[:32]
        start_agent(self.session, name, self.agent, pane)
        prompt(self.session, name, prompt_text, self.timeout_ms)
        handle = RunnerHandle(
            kind=self.kind,
            session=self.session,
            handle=name,
            pane=pane,
            workspace=str((created.get("workspace") or {}).get("workspace_id", "")),
        )
        marker = detect_error(self.read(handle))
        if marker:
            self.stop(handle)
            raise HerdrError(f"runner reported {marker}")
        return handle

    def status(self, handle: RunnerHandle) -> str:
        code, out = _run(self.session, "agent", "get", handle.handle)
        if code != 0:
            return "unknown"
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return "unknown"
        return str((data.get("result") or {}).get("agent", {}).get("agent_status", "unknown"))

    def read(self, handle: RunnerHandle, lines: int = 120) -> str:
        return read(self.session, handle.handle, lines)

    def stop(self, handle: RunnerHandle) -> None:
        try:
            send_keys(self.session, handle.handle, "ctrl+c")
        finally:
            if handle.workspace:
                close_workspace(self.session, handle.workspace)
