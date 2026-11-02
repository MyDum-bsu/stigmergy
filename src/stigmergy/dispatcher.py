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

from stigmergy import board as board_mod
from stigmergy import judge as judge_mod
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
    if hc is None:
        sent, detail = herdr_app.send_paused(handle, message)
    else:
        code, out = hc("send", handle, message, "--if", "idle")
        sent, detail = code == 0, out[:300]
    return {"task": task_id, "sent": sent, "detail": detail, "lead": handle}


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



def _terminal_alive(handle: str) -> bool:
    try:
        data = herdr_app.get(handle)
    except Exception:
        return False
    status = data.get("status") or {}
    state = str(status.get("state") or "")
    return state not in {"exited", "failed", "dead"} and data.get("exit_code") is None


def worker_done_seq(board: Board, task_id: str) -> int:
    """Latest worker.done after the latest episode.start/answer, else 0."""
    start = answer = done = 0
    for event in board.read():
        attrs = event.get("attributes") or {}
        if attrs.get("task.id") != task_id:
            continue
        seq = int(event.get("seq", 0))
        action = event.get("action")
        if action == "episode.started":
            start = max(start, seq)
        elif action == "task.answered":
            answer = max(answer, seq)
        elif action == "worker.done":
            done = max(done, seq)
    return done if done > max(start, answer) else 0




def watch_all(
    projects: list[tuple[Config, Board]],
    *,
    app: str = DEFAULT_APP,
    interval: int = DEFAULT_INTERVAL,
    on_tick: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Global loop: one lock per project, one deterministic tick each."""
    handles = []
    try:
        for config, _board in projects:
            handles.append(lock(config))
        while True:
            for config, board in projects:
                result = tick(config, board, app=app)
                if on_tick:
                    on_tick({"project": config.name, **result})
            time.sleep(max(1, interval))
    finally:
        for handle in handles:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
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
    auto_judge = bool(dispatcher_cfg.get("auto_judge", False))
    max_retries = int(dispatcher_cfg.get("max_retries", 1)) if max_retries is None else max_retries
    start_fn = start or start_episode
    finish_fn = finish or _finish
    memory = state if state is not None else load_state(config)
    notified: dict[str, int] = dict(memory.get("notified") or {})
    finishing: dict[str, int] = dict(memory.get("finishing") or {})
    start_failed: dict[str, int] = dict(memory.get("start_failed") or {})
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
    if config.section("factory").get("auto_approve"):
        from stigmergy import intake

        auto_actions: list[dict[str, Any]] = []
        for task in snapshot.all():
            if task.status != "queued" or task.spec:
                continue
            try:
                verdict = intake.auto_approve_plan(config, board, task.id)
            except Exception as exc:
                actions.append(
                    {"action": "auto_approve_failed", "task": task.id, "detail": str(exc)[:500]}
                )
                continue
            if verdict.get("ok"):
                auto_actions.append(
                    {
                        "action": "auto_approve",
                        "task": task.id,
                        "policy": verdict.get("policy", ""),
                        "spec_sha": verdict.get("spec_sha", ""),
                    }
                )
        if auto_actions:
            actions.extend(auto_actions)
            snapshot = state_of(board, config.name)
    active = snapshot.current()
    blocked = snapshot.blocked()
    active_ids = {task.id for task in active}
    for task_id in list(finishing):
        if task_id not in active_ids:
            finishing.pop(task_id, None)
    known = {task.id: task for task in snapshot.all()}
    for task_id in list(notified):
        task = known.get(task_id)
        if task is None or task.status in {"done", "failed", "rejected"}:
            notified.pop(task_id, None)
    busy = [task for task in snapshot.all() if task.status in ACTIVE_STATIONS or task.status == "blocked"]
    max_retries = max(0, max_retries)

    for task in blocked:
        if notified.get(task.id) == task.last_seq:
            continue
        if auto_judge and task.risk != "high":
            decision = judge_mod.decide(config, task.question)
            if decision["outcome"] == "resolved":
                board_mod.answer(
                    board,
                    config,
                    task.id,
                    "judge",
                    decision["decision"],
                )
                handle = runner_handle(board, task.id)
                sent = False
                if handle:
                    sent, _detail = herdr_app.send_paused(
                        handle,
                        f"Судья: {decision['decision']}\n\nПродолжай.",
                    )
                actions.append(
                    {
                        "action": "judge_answer",
                        "task": task.id,
                        "decision": decision["decision"],
                        "sent": sent,
                    }
                )
                notified[task.id] = task.last_seq
                continue
        message = (
            f"Worker {task.id} blocked: {task.question}\n"
            f"Ответ: stg lead answer {task.id} --text \"...\""
        )
        result = notify_lead(board, task.id, message, hc=hc)
        actions.append({"action": "notify", **result})
        if result.get("sent"):
            notified[task.id] = task.last_seq

    for task in snapshot.all():
        if task.status != "queued" or task.retries < max_retries or not task.retries:
            continue
        if notified.get(task.id) == task.last_seq:
            continue
        message = (
            f"Task {task.id} exhausted retries ({task.retries}); gate/manual review needed.\n"
            f"  stg board show {task.id}"
        )
        result = notify_lead(board, task.id, message, hc=hc)
        actions.append({"action": "notify_exhausted", **result})
        if result.get("sent"):
            notified[task.id] = task.last_seq

    for task in active:
        if task.status != "episode":
            continue
        marker = worker_done_seq(board, task.id)
        if marker:
            if not auto_finish or finishing.get(task.id) == marker:
                continue
            result = finish_fn(config, task.id)
            actions.append(
                {
                    "action": "finish",
                    "task": task.id,
                    "detail": f"worker.done seq={marker}",
                    **result,
                }
            )
            if result.get("ok"):
                finishing[task.id] = marker
            else:
                finishing.pop(task.id, None)
                note = notify_lead(
                    board,
                    task.id,
                    f"Finish failed for {task.id}: {result.get('detail', '')}",
                    hc=hc,
                )
                actions.append({"action": "finish_failed", "task": task.id, **note})
            continue
        handle = task.runner_handle
        if not handle or _terminal_alive(handle):
            continue
        board.append(
            "episode.failed",
            {"kind": "agent", "name": "dispatcher"},
            {
                "project.name": config.name,
                "task.id": task.id,
                "agent.name": "dispatcher",
                "evidence": f"worker terminal lost: {handle}",
            },
            "worker terminal lost",
        )
        result = notify_lead(
            board,
            task.id,
            (
                f"Worker {task.id} died without worker.done (terminal {handle}). "
                "Task failed; retry after the cause is fixed."
            ),
            hc=hc,
        )
        actions.append(
            {
                "action": "worker_dead",
                "task": task.id,
                "terminal": handle,
                "notified": result.get("sent", False),
            }
        )

    if len(busy) < max(1, config.wip):
        ready = [
            task
            for task in snapshot.ready(wip=config.wip)
            if task.spec and task.retries < max_retries
        ]
        if ready:
            task = ready[0]
            if start_failed.get(task.id) == task.last_seq:
                ready = []
            else:
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
                    start_failed[task.id] = task.last_seq
                    actions.append(
                        {"action": "start_failed", "task": task.id, "detail": str(exc)[:500]}
                    )

    memory["notified"] = notified
    memory["finishing"] = finishing
    memory["start_failed"] = start_failed
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
