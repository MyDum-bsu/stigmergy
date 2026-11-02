"""Factory metrics and actor audit from the append-only board."""

from __future__ import annotations

from collections import Counter
from typing import Any

from stigmergy import usage as usage_mod
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def anonymous(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events that cannot be attributed to an actor or project."""
    out = []
    for event in events:
        actor = event.get("actor") or {}
        attrs = event.get("attributes") or {}
        name = str(actor.get("name") or "")
        project = str(attrs.get("project.name") or "")
        if name and project:
            continue
        out.append(
            {
                "seq": event.get("seq"),
                "action": event.get("action"),
                "actor": name or None,
                "project": project or None,
            }
        )
    return out


def snapshot(config: Config, board: Board) -> dict[str, Any]:
    events = board.read()
    state = ProjectState.from_events(events, project=config.name)
    tasks = state.all()
    actions = Counter(str(event.get("action", "")) for event in events)
    statuses = Counter(task.status for task in tasks)
    queued_spec = sum(1 for task in tasks if task.status == "queued" and task.spec)
    queued_no_spec = sum(1 for task in tasks if task.status == "queued" and not task.spec)
    human_answers = sum(
        1
        for event in events
        if event.get("action") == "task.answered"
        and str((event.get("attributes") or {}).get("answered.by") or "") == "human"
    )
    lead_answers = sum(
        1
        for event in events
        if event.get("action") == "task.answered"
        and str((event.get("attributes") or {}).get("answered.by") or "") == "lead"
    )
    return {
        "project": config.name,
        "events": len(events),
        "tasks": len(tasks),
        "status": dict(statuses),
        "queued_with_spec": queued_spec,
        "queued_without_spec": queued_no_spec,
        "gate_failed": actions.get("gate.failed", 0),
        "control_failed": actions.get("control.failed", 0),
        "gate_passed": actions.get("gate.passed", 0),
        "worker_done": actions.get("worker.done", 0),
        "plan_approved": actions.get("plan.approved", 0),
        "human_answers": human_answers,
        "lead_answers": lead_answers,
        "retries": sum(task.retries for task in tasks),
        "anonymous": anonymous(events),
        "usage": usage_mod.totals(board),
        "actions": dict(actions.most_common()),
    }


def text(data: dict[str, Any]) -> str:
    return (
        f"{data['project']}: tasks={data['tasks']} events={data['events']} "
        f"queued(spec/no)={data['queued_with_spec']}/{data['queued_without_spec']} "
        f"gate(fail/pass)={data['gate_failed']}/{data['gate_passed']} "
        f"control_failed={data['control_failed']} retries={data['retries']} "
        f"human/lead answers={data['human_answers']}/{data['lead_answers']} "
        f"anonymous={len(data['anonymous'])}"
    )
