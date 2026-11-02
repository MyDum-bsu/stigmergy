"""Source/Trigger/Thread intake primitives.

This is the first general-purpose layer above the board: a source produces an
immutable trigger, a trigger belongs to a thread, and a policy decides whether
it is observed or accepted. The board remains the source of truth; the layer
does not know GitHub or Feishu names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState

POLICY_VERSION = "source-v1"


@dataclass(frozen=True)
class Trigger:
    source: str
    trigger_id: str
    thread: str
    actor: str
    text: str
    title: str = ""
    kind: str = "message"
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _seen(board: Board) -> set[str]:
    out: set[str] = set()
    for event in board.read():
        if event.get("action") != "source.trigger":
            continue
        attrs = event.get("attributes") or {}
        trigger_id = str(attrs.get("trigger.id") or "")
        if trigger_id:
            out.add(trigger_id)
    return out


def _decision(
    trigger: Trigger,
    *,
    accept_mode: str,
    allowed_actors: tuple[str, ...],
) -> str:
    if accept_mode not in {"observe", "auto"}:
        raise ValueError(f"unknown accept mode: {accept_mode}")
    if allowed_actors and trigger.actor not in allowed_actors:
        return "not_admitted"
    if accept_mode == "observe":
        return "observed"
    return "accepted"


def ingest(
    config: Config,
    board: Board,
    trigger: Trigger,
    *,
    accept_mode: str = "observe",
    allowed_actors: tuple[str, ...] = (),
    start_planner: bool = True,
) -> dict[str, Any]:
    """Record one trigger and accept it only when the policy allows."""
    if not trigger.trigger_id or not trigger.thread or not trigger.source:
        raise ValueError("trigger.source, trigger.thread and trigger.trigger_id are required")
    if trigger.trigger_id in _seen(board):
        return {
            "ok": True,
            "decision": "duplicate",
            "duplicate": True,
            "task": "",
            "trigger": trigger.trigger_id,
        }
    decision = _decision(
        trigger,
        accept_mode=accept_mode,
        allowed_actors=allowed_actors,
    )
    attrs = {
        "project.name": config.name,
        "source.name": trigger.source,
        "trigger.id": trigger.trigger_id,
        "thread.id": trigger.thread,
        "trigger.kind": trigger.kind,
        "trigger.actor": trigger.actor,
        "trigger.url": trigger.url,
        "policy.version": POLICY_VERSION,
        "decision": decision,
    }
    if decision != "accepted":
        board.append(
            "source.trigger",
            {"kind": "agent", "name": "source"},
            attrs,
            trigger.text[:500],
        )
        return {
            "ok": True,
            "decision": decision,
            "duplicate": False,
            "task": "",
            "trigger": trigger.trigger_id,
        }

    from stigmergy import intake

    result = intake.create_task(
        config,
        board,
        trigger.text,
        title=trigger.title or None,
        source=trigger.source,
        source_id=trigger.trigger_id,
        start_planner=start_planner,
    )
    task_id = str(result["task"])
    attrs["task.id"] = task_id
    board.append(
        "source.trigger",
        {"kind": "agent", "name": "source"},
        attrs,
        trigger.text[:500],
    )
    if not result.get("duplicate"):
        board.append(
            "mandate.granted",
            {"kind": "agent", "name": "policy"},
            {
                "project.name": config.name,
                "task.id": task_id,
                "mandate.id": f"m-{trigger.trigger_id}",
                "mandate.source": trigger.source,
                "mandate.thread": trigger.thread,
                "mandate.trigger": trigger.trigger_id,
                "mandate.actor": trigger.actor,
                "policy.version": POLICY_VERSION,
                "accept.mode": accept_mode,
            },
            f"mandate {task_id}",
        )
    return {
        "ok": True,
        "decision": decision,
        "duplicate": bool(result.get("duplicate")),
        "task": task_id,
        "trigger": trigger.trigger_id,
    }


def status(board: Board) -> dict[str, Any]:
    state = ProjectState.from_events(board.read())
    triggers = []
    mandates = []
    for event in board.read():
        if event.get("action") == "source.trigger":
            triggers.append(event)
        elif event.get("action") == "mandate.granted":
            mandates.append(event)
    return {
        "tasks": len(state.tasks),
        "triggers": len(triggers),
        "mandates": len(mandates),
        "decisions": {
            str((event.get("attributes") or {}).get("decision")): sum(
                1
                for item in triggers
                if (item.get("attributes") or {}).get("decision")
                == (event.get("attributes") or {}).get("decision")
            )
            for event in triggers
        },
    }
