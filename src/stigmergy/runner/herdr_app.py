"""Herdr desktop app adapter.

`herdr-app` is the native window; `hc` (herdr-core) runs the terminals.  This
adapter creates a visible space per task and drives the agent through `hc`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from stigmergy.runner.base import RunnerHandle

DEFAULT_APP = "herdr-app"
DEFAULT_AGENT = "pi"
PREFIX = "stg-"


class HerdrAppError(RuntimeError):
    pass


def binary(app: str = DEFAULT_APP) -> str:
    return shutil.which(app) or app


def _run(app: str, *args: str, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        [binary(app), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def _json(app: str, *args: str, timeout: int = 30) -> dict:
    code, out = _run(app, *args, timeout=timeout)
    if code != 0:
        raise HerdrAppError(out[:1000])
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise HerdrAppError(f"non-JSON herdr-app output: {out[:500]}") from exc


def status(app: str = DEFAULT_APP) -> dict:
    try:
        data = _json(app, "status")
        return {"ok": not data.get("errors"), "status": data, "app": app}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "app": app}


def ensure_app(app: str = DEFAULT_APP, wait_seconds: int = 15) -> dict:
    state = status(app)
    if state["ok"]:
        return state
    try:
        subprocess.Popen([binary(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HerdrAppError(f"cannot start {app}: {exc}") from exc
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(0.5)
        state = status(app)
        if state["ok"]:
            return state
    raise HerdrAppError(f"{app} did not become ready")


def spaces(app: str = DEFAULT_APP) -> list[dict]:
    data = _json(app, "ls")
    return list(data.get("spaces") or [])


def _do(app: str, command: str, **kwargs) -> dict:
    argv = [binary(app), "do", command]
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            value = json.dumps(value)
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    proc = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=60)
    out = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0:
        raise HerdrAppError(out[:1000])
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise HerdrAppError(f"non-JSON herdr-app do output: {out[:500]}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise HerdrAppError(str(data["error"]))
    return data


def unique_name(app: str, base: str) -> str:
    names = {str(space.get("name", "")) for space in spaces(app)}
    if base not in names:
        return base
    for idx in range(2, 100):
        candidate = f"{base}-{idx}"
        if candidate not in names:
            return candidate
    return f"{base}-{int(time.time())}"


def create_space(
    app: str,
    name: str,
    folder: Path,
    agent: str,
    task: str,
    agent_args: list[str] | None = None,
) -> dict:
    ensure_app(app)
    return _do(
        app,
        "space.new",
        name=unique_name(app, name),
        folder=str(folder),
        argv=[agent, *(agent_args or [])],
        task=task,
    )


def find_space(app: str, name: str) -> dict | None:
    for space in spaces(app):
        if str(space.get("name", "")) == name:
            return space
    return None


def ensure_space(app: str, name: str, folder: Path) -> dict:
    """Проектный space (папка репозитория), без агента: задачи — вкладки."""
    ensure_app(app)
    space = find_space(app, name)
    if space is not None:
        return space
    return _do(app, "space.new", name=name, folder=str(folder))


def create_tab(
    app: str,
    space: str,
    name: str,
    folder: Path,
    agent: str,
    task: str,
    agent_args: list[str] | None = None,
) -> dict:
    ensure_app(app)
    return _do(
        app,
        "tab.new",
        name=name,
        space=space,
        folder=str(folder),
        argv=[agent, *(agent_args or [])],
        task=task,
    )


def hc(*args: str, timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        ["hc", *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def hc_json(*args: str, timeout: int = 30) -> dict:
    code, out = hc(*args, "--json", timeout=timeout)
    if code != 0:
        raise HerdrAppError(out[:1000])
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise HerdrAppError(f"non-JSON hc output: {out[:500]}") from exc


def get(terminal: str) -> dict:
    return hc_json("get", terminal)


def read(terminal: str, lines: int = 120) -> str:
    code, out = hc("read", terminal, "--lines", str(lines), timeout=30)
    if code != 0:
        raise HerdrAppError(out[:1000])
    return out


def wait(terminal: str, timeout_s: int = 180) -> dict:
    return hc_json("wait", terminal, "--timeout", str(timeout_s), timeout=timeout_s + 20)


def kill(terminal: str) -> dict:
    return hc_json("kill", terminal)


def close_space(space_id: str) -> dict:
    try:
        return _do(DEFAULT_APP, "space.close", id=space_id, confirmed="true")
    except HerdrAppError:
        return {"ok": False}


def cleanup(app: str = DEFAULT_APP, task: str | None = None) -> list[str]:
    closed: list[str] = []
    for space in spaces(app):
        name = str(space.get("name", ""))
        if not name.startswith(PREFIX):
            continue
        if task and name != f"{PREFIX}{task}":
            continue
        close_space(str(space.get("id", "")))
        closed.append(name)
    return closed


def wait_until_settled(terminal: str, deadline_s: int = 1800) -> str:
    """Wait for the agent's first turn to finish.

    ``hc wait`` can report ``idle`` before the agent starts its turn (turn 0);
    ``hc get`` is authoritative: ``status.state == working`` then idle/done.
    """
    deadline = time.monotonic() + deadline_s
    saw_work = False
    while time.monotonic() < deadline:
        try:
            data = get(terminal)
        except HerdrAppError:
            return read(terminal)
        status = data.get("status") or {}
        state = str(status.get("state") or "")
        turn = int(data.get("turn") or 0)
        if state == "working":
            saw_work = True
        elif state == "blocked":
            raise HerdrAppError("agent blocked:\n" + read(terminal))
        elif state in {"idle", "done"} and (saw_work or turn > 0):
            return read(terminal)
        if data.get("exit_code") is not None:
            if data.get("exit_code") not in (0, None):
                raise HerdrAppError("agent exited with " + str(data.get("exit_code")))
            return read(terminal)
        time.sleep(2)
    raise HerdrAppError("agent wait deadline exceeded")


class HerdrAppRunner:
    kind = "herdr-app"

    def __init__(
        self,
        app: str = DEFAULT_APP,
        agent: str = DEFAULT_AGENT,
        timeout_s: int = 1800,
        space: str | None = None,
        tab_name: str | None = None,
        space_folder: Path | None = None,
        agent_args: list[str] | None = None,
    ):
        self.app = app
        self.agent = agent
        self.timeout_s = timeout_s
        self.space = space
        self.tab_name = tab_name
        self.space_folder = space_folder
        self.agent_args = list(agent_args or [])

    def start(self, task_id: str, prompt: str, workspace: Path, wait: bool = True) -> RunnerHandle:
        if self.space:
            project_space = ensure_space(
                self.app, self.space, self.space_folder or workspace
            )
            space = str(project_space.get("space") or project_space.get("id") or "")
            created = create_tab(
                self.app,
                space,
                self.tab_name or task_id,
                workspace,
                self.agent,
                prompt,
                agent_args=self.agent_args,
            )
        else:
            created = create_space(
                self.app,
                f"{PREFIX}{task_id}",
                workspace,
                self.agent,
                prompt,
                agent_args=self.agent_args,
            )
            space = str(created.get("space", ""))
        terminal = str(created.get("terminal", ""))
        if not space or not terminal:
            raise HerdrAppError(f"space.new/tab.new returned no ids: {created}")
        if wait:
            wait_until_settled(terminal, self.timeout_s)
        return RunnerHandle(
            kind=self.kind,
            session=self.app,
            handle=terminal,
            pane="",
            workspace=str(workspace),
            meta={"space": space, "terminal": terminal},
        )

    def status(self, handle: RunnerHandle) -> str:
        try:
            data = get(handle.handle)
        except HerdrAppError:
            return "unknown"
        return str(data.get("status") or data.get("state") or "unknown")

    def read(self, handle: RunnerHandle, lines: int = 120) -> str:
        return read(handle.handle, lines)

    def stop(self, handle: RunnerHandle) -> None:
        try:
            kill(handle.handle)
        finally:
            space = handle.meta.get("space")
            if space:
                close_space(space)
