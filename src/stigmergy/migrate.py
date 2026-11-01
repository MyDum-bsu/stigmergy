"""Legacy board migration: validate, copy, rebuild projections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stigmergy.log import Board, sha256_file
from stigmergy.model import ProjectState
from stigmergy.render import render

REQUIRED_ACTIONS = {
    "task.created",
    "task.proposed",
    "task.approved",
    "task.rejected",
    "task.claimed",
    "task.heartbeat",
    "task.blocked",
    "task.answered",
    "task.done",
    "task.failed",
    "task.note",
    "task.pr",
    "message.sent",
}


def _agent_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.name == ".agent":
        return path
    if (path / ".agent").exists():
        return path / ".agent"
    return path


def check(path: str | Path) -> dict[str, Any]:
    agent = _agent_dir(Path(path))
    errors: list[str] = []
    events_path = agent / "events.jsonl"
    if not events_path.exists():
        return {"ok": False, "errors": [f"events.jsonl not found in {agent}"], "count": 0}
    events: list[dict[str, Any]] = []
    with events_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: {exc}")
                continue
            events.append(event)
    last_seq = 0
    actions: dict[str, int] = {}
    tasks: set[str] = set()
    for event in events:
        seq = event.get("seq")
        if not isinstance(seq, int):
            errors.append("event without integer seq")
            continue
        if seq <= last_seq:
            errors.append(f"seq not increasing: {seq} after {last_seq}")
        last_seq = seq
        if event.get("schema") != "stigmergy/v1":
            errors.append(f"unexpected schema at seq {seq}: {event.get('schema')}")
        action = event.get("action")
        if not action:
            errors.append(f"event without action at seq {seq}")
            continue
        actions[action] = actions.get(action, 0) + 1
        if not isinstance(event.get("actor"), dict):
            errors.append(f"event without actor at seq {seq}")
        attrs = event.get("attributes")
        if not isinstance(attrs, dict):
            errors.append(f"event without attributes at seq {seq}")
            continue
        task_id = attrs.get("task.id")
        if task_id:
            tasks.add(str(task_id))
    return {
        "ok": not errors,
        "errors": errors,
        "count": len(events),
        "last_seq": last_seq,
        "tasks": len(tasks),
        "actions": dict(sorted(actions.items())),
        "sha256": sha256_file(events_path),
        "path": str(events_path),
    }


def run(
    src: str | Path,
    dst_repo: str | Path,
    project: str = "",
    *,
    force: bool = False,
) -> dict[str, Any]:
    report = check(src)
    if not report["ok"]:
        raise RuntimeError("legacy log is not valid: " + "; ".join(report["errors"][:5]))
    src_events = _agent_dir(Path(src)) / "events.jsonl"
    dst = Board(dst_repo)
    dst.ensure()
    if dst.events_path.exists() and dst.events_path.stat().st_size and not force:
        raise RuntimeError(f"destination already has events: {dst.events_path}")
    dst.events_path.write_bytes(src_events.read_bytes())
    dst.append(
        "board.migrated",
        {"kind": "human", "name": "stg"},
        {
            "project.name": project or dst.root.name,
            "source.path": str(src_events),
            "source.count": report["count"],
            "source.sha256": report["sha256"],
        },
        "legacy board migrated",
    )
    state = ProjectState.from_events(dst.read(), project=project or dst.root.name)
    render(dst.views_dir, state)
    return {
        "ok": True,
        "source": str(src_events),
        "destination": str(dst.events_path),
        "count": report["count"],
        "last_seq": report["last_seq"],
        "tasks": report["tasks"],
        "actions": report["actions"],
    }
