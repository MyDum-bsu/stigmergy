"""Board commands: the coordination surface."""

from __future__ import annotations

import time
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board, BoardError
from stigmergy.model import (
    DONE,
    QUEUED,
    ProjectState,
    Task,
    task_sha,
)
from stigmergy.render import render
from stigmergy.spec import SpecError, load_for

LEASE_SECONDS = 30 * 60


def _attrs(project: str, task_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {"project.name": project, "task.id": task_id}
    out.update(extra or {})
    return out


def _actor(name: str, kind: str = "agent") -> dict[str, str]:
    return {"kind": kind, "name": name}


def add_task(
    board: Board,
    config: Config,
    task_id: str,
    title: str,
    *,
    priority: int = 2,
    deps: list[str] | None = None,
    spec_path: str = "",
    risk: str = "low",
    branch: str = "",
    sha: str = "",
    labels: dict[str, str] | None = None,
    agent: str = "stg",
) -> Task:
    state = ProjectState.from_events(board.read(), project=config.name)
    if task_id in state.tasks:
        raise BoardError(f"task already exists: {task_id}")
    deps = deps or []
    dod = ""
    spec_sha = ""
    allowed: list[str] = []
    if spec_path:
        spec = load_for(config.root, config.base, spec_path)
        errors = spec.validate()
        if errors:
            raise SpecError("; ".join(errors))
        risk = spec.risk
        allowed = spec.allowed_paths
        dod = spec.dod
        spec_sha = spec.sha
        if not title:
            title = spec.title or task_id
        deps = deps or spec.deps
    sha = sha or task_sha(task_id, title, deps, dod)
    branch = branch or f"task/{task_id}-{sha}"
    board.append(
        "task.created",
        _actor(agent),
        _attrs(
            config.name,
            task_id,
            {
                "task.title": title,
                "task.priority": priority,
                "task.deps": deps,
                "task.sha": sha,
                "task.dod": dod,
                "task.labels": labels or {},
                "spec.path": spec_path,
                "spec.sha": spec_sha,
                "risk": risk,
                "paths.allowed": allowed,
                "vcs.base": config.base,
                "vcs.branch": branch,
            },
        ),
        f"create {task_id}",
    )
    render(board.views_dir, ProjectState.from_events(board.read(), project=config.name))
    return Task(id=task_id, title=title, sha=sha, spec=spec_path, spec_sha=spec_sha)


def propose_task(board: Board, config: Config, task_id: str, title: str, **kwargs: Any) -> dict:
    state = ProjectState.from_events(board.read(), project=config.name)
    if task_id in state.tasks:
        raise BoardError(f"task already exists: {task_id}")
    attrs = _attrs(
        config.name,
        task_id,
        {
            "task.title": title,
            "task.priority": kwargs.get("priority", 2),
            "task.deps": kwargs.get("deps", []),
            "task.sha": kwargs.get("sha", task_sha(task_id, title, [], "")),
            "spec.path": kwargs.get("spec_path", ""),
            "risk": kwargs.get("risk", "low"),
            "paths.allowed": [],
        },
    )
    return board.append("task.proposed", _actor(kwargs.get("agent", "triage")), attrs, f"propose {task_id}")


def attach_spec(
    board: Board,
    config: Config,
    task_id: str,
    spec_path: str,
    agent: str = "architect",
) -> dict:
    """Attach a spec to a queued task without inventing a duplicate task."""
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    base = task.base or config.base
    spec = load_for(config.root, base, spec_path)
    errors = spec.validate_against_repo(config.root, base)
    if errors:
        raise SpecError("; ".join(errors))
    return board.append(
        "spec.attached",
        _actor(agent),
        _attrs(
            config.name,
            task_id,
            {
                "spec.path": spec_path,
                "spec.sha": spec.sha,
                "risk": spec.risk,
                "paths.allowed": spec.allowed_paths,
                "spec.deps": spec.deps,
            },
        ),
        f"attach spec {task_id}",
    )


def approve(board: Board, config: Config, task_id: str, by: str) -> dict:
    if by != "human":
        raise BoardError("approve is human-only: pass --by human")
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    if task.status != "proposed":
        raise BoardError(f"task {task_id} is {task.status}, not proposed")
    return board.append(
        "task.approved",
        _actor("human", "human"),
        _attrs(config.name, task_id, {"spec.sha": task.spec_sha}),
        f"approve {task_id}",
    )


def reject(board: Board, config: Config, task_id: str, by: str, reason: str = "") -> dict:
    if by != "human":
        raise BoardError("reject is human-only: pass --by human")
    return board.append(
        "task.rejected",
        _actor("human", "human"),
        _attrs(config.name, task_id, {"answer": reason}),
        f"reject {task_id}",
    )


def claim(
    board: Board,
    config: Config,
    task_id: str,
    agent: str,
    *,
    lease_seconds: int = LEASE_SECONDS,
) -> dict:
    with board.locked():
        state = ProjectState.from_events(board.read(), project=config.name)
        task = state.task(task_id)
        if task.status != QUEUED:
            raise BoardError(f"task {task_id} is {task.status}, not queued")
        if any(state.tasks.get(dep) is None or state.tasks[dep].status != DONE for dep in task.deps):
            raise BoardError(f"dependencies not done: {task.deps}")
        return board._append_locked(
            "task.claimed",
            _actor(agent),
            _attrs(
                config.name,
                task_id,
                {
                    "agent.name": agent,
                    "lease.until": time.time_ns() + lease_seconds * 1_000_000_000,
                    "task.sha": task.sha,
                    "spec.sha": task.spec_sha,
                    "vcs.base": task.base or config.base,
                    "vcs.branch": task.branch or f"task/{task.id}-{task.sha}",
                    "risk": task.risk,
                    "paths.allowed": task.allowed_paths,
                },
            ),
            f"claim {task_id}",
        )


def next_task(
    board: Board,
    config: Config,
    agent: str,
    *,
    lease_seconds: int = LEASE_SECONDS,
) -> Task | None:
    with board.locked():
        state = ProjectState.from_events(board.read(), project=config.name)
        ready = state.ready(wip=config.wip)
        if not ready:
            return None
        task = ready[0]
        board._append_locked(
            "task.claimed",
            _actor(agent),
            _attrs(
                config.name,
                task.id,
                {
                    "agent.name": agent,
                    "lease.until": time.time_ns() + lease_seconds * 1_000_000_000,
                    "task.sha": task.sha,
                    "spec.sha": task.spec_sha,
                    "vcs.base": task.base or config.base,
                    "vcs.branch": task.branch or f"task/{task.id}-{task.sha}",
                    "risk": task.risk,
                    "paths.allowed": task.allowed_paths,
                },
            ),
            f"claim {task.id}",
        )
        return task


def heartbeat(board: Board, config: Config, task_id: str, agent: str, lease_seconds: int = LEASE_SECONDS) -> dict:
    return board.append(
        "task.heartbeat",
        _actor(agent),
        _attrs(
            config.name,
            task_id,
            {"agent.name": agent, "lease.until": time.time_ns() + lease_seconds * 1_000_000_000},
        ),
        f"heartbeat {task_id}",
    )


def block(board: Board, config: Config, task_id: str, agent: str, question: str) -> dict:
    if not question.strip():
        raise BoardError("--question is required")
    return board.append(
        "task.blocked",
        _actor(agent),
        _attrs(config.name, task_id, {"agent.name": agent, "question": question}),
        f"block {task_id}",
    )


def worker_done(board: Board, config: Config, task_id: str, agent: str) -> dict:
    """Explicit completion signal; idle is not proof."""
    return board.append(
        "worker.done",
        _actor(agent),
        _attrs(config.name, task_id, {"agent.name": agent}),
        f"worker done {task_id}",
    )


def answer(board: Board, config: Config, task_id: str, by: str, text: str) -> dict:
    if by not in {"human", "lead", "judge"}:
        raise BoardError("answer is human-only, lead-only or judge-only: pass --by human|lead|judge")
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    if by in {"lead", "judge"} and task.risk == "high":
        raise BoardError("high-risk answer is human-only")
    actor = _actor("human", "human") if by == "human" else _actor(by, "agent")
    return board.append(
        "task.answered",
        actor,
        _attrs(config.name, task_id, {"answer": text, "answered.by": by}),
        f"answer {task_id}",
    )


def done(
    board: Board,
    config: Config,
    task_id: str,
    agent: str,
    *,
    commit: str = "",
    no_commit: bool = False,
    evidence: str,
) -> dict:
    if not evidence.strip():
        raise BoardError("--evidence is required")
    if not commit and not no_commit:
        raise BoardError("pass --commit <sha> or --no-commit with evidence")
    if commit:
        passed = any(
            event.get("action") == "gate.passed"
            and str((event.get("attributes") or {}).get("task.id", "")) == task_id
            and str((event.get("attributes") or {}).get("vcs.commit", "")) == commit
            for event in board.read()
        )
        if not passed:
            raise BoardError("board done with a commit requires gate.passed for that commit")
    return board.append(
        "task.done",
        _actor(agent),
        _attrs(config.name, task_id, {"agent.name": agent, "vcs.commit": commit, "evidence": evidence}),
        f"done {task_id}",
    )


def fail(board: Board, config: Config, task_id: str, agent: str, reason: str) -> dict:
    return board.append(
        "task.failed",
        _actor(agent),
        _attrs(config.name, task_id, {"agent.name": agent, "evidence": reason}),
        f"fail {task_id}",
    )


def note(board: Board, config: Config, task_id: str, agent: str, text: str) -> dict:
    return board.append(
        "task.note",
        _actor(agent),
        _attrs(config.name, task_id, {"agent.name": agent}),
        text,
    )


def pr(board: Board, config: Config, task_id: str, agent: str, url: str) -> dict:
    return board.append(
        "task.pr",
        _actor(agent),
        _attrs(config.name, task_id, {"pr.url": url}),
        f"pr {task_id}",
    )


def ask(board: Board, config: Config, sender: str, to: str, text: str, hop: int) -> dict:
    if hop > 5:
        raise BoardError("hop limit is 5")
    return board.append(
        "message.sent",
        _actor(sender),
        {"project.name": config.name, "message.from": sender, "message.to": to, "message.hop": hop},
        text,
    )


def list_tasks(state: ProjectState, status: str | None = None) -> list[Task]:
    tasks = state.all()
    if status:
        tasks = [t for t in tasks if t.status == status]
    return tasks


def status(state: ProjectState) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for task in state.tasks.values():
        counts[task.status] = counts.get(task.status, 0) + 1
    return {
        "project": state.project,
        "paused": state.paused,
        "events": len(state.events),
        "tasks": len(state.tasks),
        "status": counts,
        "active": [t.id for t in state.current()],
        "blocked": [t.id for t in state.blocked()],
    }


def mark_paused(board: Board, config: Config, paused: bool, by: str) -> dict:
    action = "factory.paused" if paused else "factory.resumed"
    return board.append(action, _actor(by), {"project.name": config.name}, action)


def render_views(board: Board, config: Config) -> None:
    render(board.views_dir, ProjectState.from_events(board.read(), project=config.name))
