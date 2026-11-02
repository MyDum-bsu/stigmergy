"""Herdr desktop app adapter.

`herdr-app` is the native window; `hc` (herdr-core) runs the terminals.  This
adapter creates a visible space per task and drives the agent through `hc`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

from stigmergy.runner.base import RunnerHandle

DEFAULT_APP = "herdr-app"
DEFAULT_AGENT = "pi"
PREFIX = "stg-"

MAX_TAB_LABEL = 48
PROTECTED_TAB_PREFIXES = ("Lead", "Board")
TAB_KINDS = ("Plan", "Worker", "Critic")
TERMINAL_STATUSES = ("done", "merged", "failed", "cancelled")
LEAD_TAB_NAME = "Lead"
TAB_SEPARATOR = " · "

_MARKER = re.compile(r"\[([0-9a-f]+)\]$")
_DATE_TOKEN = re.compile(r"t-\d{8}")


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


def _space_ref(app: str, value: object) -> str:
    """``tab.new`` addresses a space by id; callers may also pass the space name."""
    text = str(value)
    known = spaces(app)
    for space in known:
        if str(space.get("id", "")) == text:
            return text
    for space in known:
        if str(space.get("name", "")) == text:
            return str(space.get("id") or text)
    return text


def _do(app: str, command: str, **kwargs) -> dict:
    if command == "tab.new" and kwargs.get("space"):
        kwargs["space"] = _space_ref(app, kwargs["space"])
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
    argv: list[str] | None = None,
) -> dict:
    ensure_app(app)
    return _do(
        app,
        "tab.new",
        name=name,
        space=space,
        folder=str(folder),
        argv=argv or [agent, *(agent_args or [])],
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


def short_id(task_id: str, length: int = 6) -> str:
    """Stable short marker for a task id: same id, same marker, every run."""
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:length]


def _clean_title(title: str, task_id: str) -> str:
    text = str(title or "")
    if task_id:
        text = text.replace(task_id, " ")
    kept = [token for token in text.split() if not _DATE_TOKEN.search(token)]
    return " ".join(" ".join(kept).split())


def tab_label(kind: str, title: str, task_id: str, max_len: int = MAX_TAB_LABEL) -> str:
    """Readable tab name: kind, human title, stable marker; marker always last."""
    marker = f"[{short_id(task_id)}]"
    head = f"{kind}{TAB_SEPARATOR}"
    clean = _clean_title(title, task_id)
    if not clean:
        return f"{head}{marker}"
    label = f"{head}{clean} {marker}"
    if len(label) <= max_len:
        return label
    room = max_len - len(head) - len(marker) - 2
    if room < 1:
        return f"{head}{marker}"
    return f"{head}{clean[:room]}… {marker}"


def is_protected_tab(name: str) -> bool:
    """Lead and Board tabs outlive every task."""
    return name.startswith(PROTECTED_TAB_PREFIXES)


def tab_marker(name: str) -> str | None:
    """Trailing ``[xxxxxx]`` marker of a managed tab, if it carries one."""
    match = _MARKER.search(str(name or ""))
    return match.group(1) if match else None


def managed_kind(name: str) -> str | None:
    """Kind of a managed tab, or None when the name is not ours to close."""
    value = str(name or "")
    if not value or is_protected_tab(value):
        return None
    head, sep, _rest = value.partition(TAB_SEPARATOR)
    if sep:
        if head in TAB_KINDS:
            return head
        return "Worker"
    if value.startswith(PREFIX):
        return "Worker"
    return None


def _tab_terminals(tab: dict) -> list[str]:
    terminals: list[str] = []
    for item in tab.get("terminals") or []:
        value = str(item.get("terminal") or item.get("id") or "") if isinstance(item, dict) else str(item)
        if value:
            terminals.append(value)
    return terminals


def _terminal_gone(terminal: str) -> bool:
    try:
        get(terminal)
    except HerdrAppError:
        return True
    return False


def _close_tab(app: str, tab: dict) -> None:
    _do(app, "tab.close", id=str(tab.get("id", "")), confirmed="true")


def ensure_lead_tab(
    app: str = DEFAULT_APP,
    space: str = "",
    folder: Path | None = None,
    agent: str = DEFAULT_AGENT,
    task: str = "",
    *,
    agent_args: list[str] | None = None,
    argv: list[str] | None = None,
) -> dict:
    """Exactly one Lead tab in the existing project space; never a second space."""
    root = Path(folder) if folder is not None else Path.cwd()
    if not space:
        for candidate in spaces(app):
            if str(candidate.get("folder", "")) == str(root):
                space = str(candidate.get("name", ""))
                break
        if not space:
            raise HerdrAppError(f"no herdr space for {root}")
    project_space = ensure_space(app, space, root)
    space_id = str(project_space.get("space") or project_space.get("id") or "")
    if not space_id:
        raise HerdrAppError(f"herdr space {space!r} has no id")
    leads = [
        tab for tab in (project_space.get("tabs") or []) if str(tab.get("name", "")) == LEAD_TAB_NAME
    ]
    if leads:
        for duplicate in leads[1:]:
            _close_tab(app, duplicate)
        return {"created": False, "tab": leads[0]}
    created = create_tab(
        app,
        space,
        LEAD_TAB_NAME,
        root,
        agent,
        task,
        agent_args=agent_args,
        argv=argv,
    )
    return {"created": True, "tab": created}


def close_task_tabs(
    app: str = DEFAULT_APP,
    task_id: str = "",
    title: str = "",
    *,
    dry_run: bool = False,
) -> list[str]:
    """Close the Plan, Worker and Critic tabs that belong to one task."""
    if not task_id:
        return []
    marker = short_id(task_id)
    legacy_names = {f"{kind}{TAB_SEPARATOR}{task_id}" for kind in TAB_KINDS}
    prefixes = (f"{task_id} ·", f"{PREFIX}{task_id}")
    closed: list[str] = []
    for space in spaces(app):
        for tab in space.get("tabs") or []:
            name = str(tab.get("name", ""))
            if is_protected_tab(name):
                continue
            if managed_kind(name) is None:
                continue
            if not (
                tab_marker(name) == marker
                or name in legacy_names
                or name.startswith(prefixes)
            ):
                continue
            if not dry_run:
                _close_tab(app, tab)
            closed.append(name)
    return closed


def cleanup_tabs(
    app: str = DEFAULT_APP,
    statuses: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
    stale_after_s: int = 6 * 3600,
    dry_run: bool = False,
) -> list[str]:
    """Sweep managed tabs of finished tasks and of dead or stale orphans."""
    known = {short_id(task_id): str(status) for task_id, status in (statuses or {}).items()}
    moment = time.time() if now is None else now
    closed: list[str] = []
    for space in spaces(app):
        for tab in space.get("tabs") or []:
            name = str(tab.get("name", ""))
            if is_protected_tab(name):
                continue
            if managed_kind(name) is None:
                continue
            marker = tab_marker(name)
            if marker is not None and marker in known:
                doomed = known[marker] in TERMINAL_STATUSES
            else:
                terminals = _tab_terminals(tab)
                created_at = tab.get("created_at")
                stale = created_at is not None and moment - float(created_at) >= stale_after_s
                doomed = not terminals or all(_terminal_gone(item) for item in terminals) or stale
            if not doomed:
                continue
            if not dry_run:
                _close_tab(app, tab)
            closed.append(name)
    return closed


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


def send_paused(handle: str, text: str) -> tuple[bool, str]:
    """Type into a terminal only when its agent is not working.

    ``done`` is a normal pi state after a turn; ``hc send --if idle`` rejects
    it, so check the state ourselves and then send without the filter.
    """
    try:
        data = get(handle)
    except Exception as exc:
        return False, str(exc)[:300]
    state = str((data.get("status") or {}).get("state") or "")
    if state == "working":
        return False, "agent is working"
    code, out = hc("send", handle, text)
    return code == 0, out[:300]


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
        argv: list[str] | None = None,
        tab_kind: str = "Worker",
        tab_title: str = "",
    ):
        self.app = app
        self.agent = agent
        self.timeout_s = timeout_s
        self.space = space
        self.tab_name = tab_name
        self.tab_kind = tab_kind
        self.tab_title = tab_title
        self.space_folder = space_folder
        self.agent_args = list(agent_args or [])
        self.argv = list(argv or [])

    def start(self, task_id: str, prompt: str, workspace: Path, wait: bool = True) -> RunnerHandle:
        if self.space:
            project_space = ensure_space(
                self.app, self.space, self.space_folder or workspace
            )
            space = str(project_space.get("space") or project_space.get("id") or "")
            created = create_tab(
                self.app,
                space,
                self.tab_name or tab_label(self.tab_kind, self.tab_title, task_id),
                workspace,
                self.agent,
                prompt,
                agent_args=self.agent_args,
                argv=self.argv or None,
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
