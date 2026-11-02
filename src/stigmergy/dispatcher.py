"""Event-driven dispatcher: a deterministic loop around the board.

It is deliberately not an LLM: it starts approved tasks, notices a settled
worker, runs the contour finish, and pings the lead about blocked tasks. LLM
decisions stay in the lead/judge tabs, where they can be inspected.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.episode import start_episode, state_of
from stigmergy.lead import runner_handle
from stigmergy.log import Board
from stigmergy.model import ACTIVE_STATIONS
from stigmergy.runner import herdr_app

DEFAULT_APP = "herdr-app"
DEFAULT_INTERVAL = 5


def _state_path(config: Config) -> Path:
    return config.root / ".factory" / "dispatcher.json"


def load_state(config: Config) -> dict[str, Any]:
    path = _state_path(config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(config: Config, data: dict[str, Any]) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lock(config: Config):
    """Single dispatcher per project; returns an open lock handle."""
    path = config.root / ".factory" / "dispatcher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("another dispatcher is already running") from exc
    return handle


def lead_handle(board: Board) -> str:
    for event in reversed(board.read()):
        if event.get("action") != "lead.started":
            continue
        handle = str((event.get("attributes") or {}).get("lead.handle", "") or "")
        if handle:
            return handle
    return ""


def notify_lead(
    board: Board,
    task_id: str,
    message: str,
    *,
    hc: Callable[..., tuple[int, str]] | None = None,
) -> dict[str, Any]:
    handle = lead_handle(board)
    if not handle:
        return {"task": task_id, "sent": False, "detail": "lead tab is not running"}
    send = hc or herdr_app.hc
    code, out = send("send", handle, message, "--if", "idle")
    return {"task": task_id, "sent": code == 0, "detail": out[:300], "lead": handle}


def _finish(config: Config, task_id: str) -> dict[str, Any]:
    stg = shutil.which("stg") or "stg"
    proc = subprocess.run(
        [stg, "episode", "finish", task_id, "--auto"],
        cwd=str(config.root),
        text=True,
        capture_output=True,
        check=False,
        timeout=int(config.section("gate").get("timeout_seconds", 1800)) + 120,
    )
    return {
        "task": task_id,
        "ok": proc.returncode == 0,
        "detail": (proc.stdout or proc.stderr).strip()[-2000:],
    }


def _worker_ready(handle: str) -> tuple[bool, str]:
    try:
        data = herdr_app.get(handle)
    except Exception as exc:
        return False, str(exc)[:300]
    status = data.get("status") or {}
    state = str(status.get("state") or "")
    turn = int(data.get("turn") or 0)
    return state in {"idle", "done"} and turn > 0, f"{state}/turn={turn}"


def tick(
    config: Config,
    board: Board,
    *,
    app: str = DEFAULT_APP,
    auto_finish: bool | None = None,
    max_retries: int | None = None,
    start: Callable[..., Any] | None = None,
    finish: Callable[[Config, str], dict[str, Any]] | None = None,
    hc: Callable[..., tuple[int, str]] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One deterministic pass. Returns what changed, without running forever."""
    dispatcher_cfg = config.section("dispatcher")
    auto_finish = bool(dispatcher_cfg.get("auto_finish", True)) if auto_finish is None else auto_finish
    max_retries = int(dispatcher_cfg.get("max_retries", 1)) if max_retries is None else max_retries
    start_fn = start or start_episode
    finish_fn = finish or _finish
    memory = state if state is not None else load_state(config)
    notified: dict[str, int] = dict(memory.get("notified") or {})
    actions: list[dict[str, Any]] = []

    app_status = herdr_app.status(app)
    if not app_status.get("ok"):
        return {
            "ok": False,
            "detail": f"Herdr app is not ready: {app_status.get('error', '')}",
            "actions": [],
            "state": memory,
        }

    snapshot = state_of(board, config.name)
    active = snapshot.current()
    blocked = snapshot.blocked()
    busy = [task for task in snapshot.all() if task.status in ACTIVE_STATIONS or task.status == "blocked"]
    max_retries = max(0, max_retries)

    for task in blocked:
        if notified.get(task.id) == task.last_seq:
            continue
        message = (
            f"Worker {task.id} blocked: {task.question}\n"
            f"Ответ: stg lead answer {task.id} --text \"...\""
        )
        result = notify_lead(board, task.id, message, hc=hc)
        actions.append({"action": "notify", **result})
        if result.get("sent"):
            notified[task.id] = task.last_seq

    for task in active:
        if task.status != "episode" or not auto_finish:
            continue
        handle = runner_handle(board, task.id)
        if not handle:
            continue
        ready, detail = _worker_ready(handle)
        if not ready:
            continue
        actions.append({"action": "finish", "task": task.id, "detail": detail, **finish_fn(config, task.id)})

    if len(busy) < max(1, config.wip):
        ready = [
            task
            for task in snapshot.ready(wip=config.wip)
            if task.spec and task.retries < max_retries
        ]
        if ready:
            task = ready[0]
            try:
                result, _prompt = start_fn(
                    config,
                    board,
                    task.id,
                    "dispatcher",
                    str(config.runner.get("kind", "herdr-app")),
                    wait_runner=False,
                    tab_name=f"{task.id} · {task.title}",
                )
                actions.append(
                    {
                        "action": "start",
                        "task": task.id,
                        "episode": result.episode,
                        "terminal": result.runner_handle,
                        "space": result.runner_space,
                    }
                )
            except Exception as exc:
                actions.append({"action": "start_failed", "task": task.id, "detail": str(exc)[:500]})

    memory["notified"] = notified
    memory["last_tick"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_state(config, memory)
    return {
        "ok": True,
        "actions": actions,
        "active": [task.id for task in active],
        "blocked": [task.id for task in blocked],
        "queued": len(snapshot.ready(wip=max(1, config.wip))),
        "state": memory,
    }


def watch(
    config: Config,
    board: Board,
    *,
    app: str = DEFAULT_APP,
    interval: int | None = None,
    auto_finish: bool | None = None,
    max_retries: int | None = None,
    on_tick: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Run ticks until interrupted; one dispatcher per project via flock."""
    interval = int(interval or config.section("dispatcher").get("interval_seconds", DEFAULT_INTERVAL))
    handle = lock(config)
    try:
        while True:
            result = tick(
                config,
                board,
                app=app,
                auto_finish=auto_finish,
                max_retries=max_retries,
            )
            if on_tick:
                on_tick(result)
            time.sleep(max(1, interval))
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
