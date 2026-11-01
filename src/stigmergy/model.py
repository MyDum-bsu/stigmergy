"""Domain model projected from the append-only event log."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

QUEUED = "queued"
PROPOSED = "proposed"
CLAIMED = "claimed"
WORKSPACE = "workspace"
EPISODE = "episode"
GATED = "gated"
INTEGRATED = "integrated"
DONE = "done"
BLOCKED = "blocked"
FAILED = "failed"
REJECTED = "rejected"

ACTIVE_STATIONS = {CLAIMED, WORKSPACE, EPISODE, GATED, INTEGRATED}
READY_STATIONS = {QUEUED}


def task_sha(task_id: str, title: str, deps: Iterable[str], dod: str) -> str:
    payload = "\n".join([task_id, title, ",".join(sorted(deps)), dod])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Task:
    id: str
    title: str = ""
    status: str = QUEUED
    priority: int = 2
    deps: list[str] = field(default_factory=list)
    risk: str = "low"
    spec: str = ""
    spec_sha: str = ""
    allowed_paths: list[str] = field(default_factory=list)
    branch: str = ""
    base: str = ""
    agent: str = ""
    lease_until: int = 0
    evidence: str = ""
    commit: str = ""
    tree: str = ""
    retries: int = 0
    created_seq: int = 0
    last_seq: int = 0
    sha: str = ""
    question: str = ""
    answer: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "deps": list(self.deps),
            "risk": self.risk,
            "spec": self.spec,
            "spec_sha": self.spec_sha,
            "allowed_paths": list(self.allowed_paths),
            "branch": self.branch,
            "base": self.base,
            "agent": self.agent,
            "lease_until": self.lease_until,
            "evidence": self.evidence,
            "commit": self.commit,
            "tree": self.tree,
            "retries": self.retries,
            "sha": self.sha,
            "question": self.question,
            "answer": self.answer,
        }


@dataclass
class ProjectState:
    project: str
    tasks: dict[str, Task] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    paused: bool = False
    migrated: bool = False

    # ── projection ─────────────────────────────────────────────────────────
    @classmethod
    def from_events(cls, events: Iterable[dict[str, Any]], project: str = "") -> ProjectState:
        state = cls(project=project)
        for event in events:
            state.apply(event)
        return state

    def _task(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            task = Task(id=task_id, created_seq=self._next_seq)
            self.tasks[task_id] = task
        return task

    @property
    def _next_seq(self) -> int:
        return int(self.events[-1]["seq"]) + 1 if self.events else 1

    def apply(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        action = event.get("action", "")
        attrs = event.get("attributes") or {}
        task_id = attrs.get("task.id")
        seq = int(event.get("seq", 0))

        if action == "board.migrated":
            self.migrated = True
            return
        if action == "factory.paused":
            self.paused = True
            return
        if action == "factory.resumed":
            self.paused = False
            return
        if not task_id:
            return

        task = self._task(str(task_id))
        task.last_seq = seq

        if action in {"task.created", "task.proposed"}:
            task.title = attrs.get("task.title", task.title)
            task.priority = int(attrs.get("task.priority", task.priority))
            task.deps = list(attrs.get("task.deps") or [])
            task.sha = attrs.get("task.sha", task.sha)
            task.status = PROPOSED if action == "task.proposed" else QUEUED
            task.created_seq = seq
            task.branch = attrs.get("vcs.branch", task.branch)
            task.base = attrs.get("vcs.base", task.base)
            task.spec = attrs.get("spec.path", task.spec)
            task.spec_sha = attrs.get("spec.sha", task.spec_sha)
            task.risk = attrs.get("risk", task.risk)
            task.allowed_paths = list(attrs.get("paths.allowed") or [])
            task.labels = dict(attrs.get("task.labels") or {})
        elif action == "task.approved":
            task.status = QUEUED
            task.spec_sha = attrs.get("spec.sha", task.spec_sha)
        elif action == "task.rejected":
            task.status = REJECTED
            task.answer = attrs.get("answer", "")
        elif action == "task.claimed":
            task.status = CLAIMED
            task.agent = attrs.get("agent.name", task.agent)
            task.lease_until = int(attrs.get("lease.until", task.lease_until))
            task.branch = attrs.get("vcs.branch", task.branch)
            task.base = attrs.get("vcs.base", task.base)
            task.sha = attrs.get("task.sha", task.sha)
            task.spec_sha = attrs.get("spec.sha", task.spec_sha)
            if attrs.get("paths.allowed"):
                task.allowed_paths = list(attrs["paths.allowed"])
            if attrs.get("risk"):
                task.risk = attrs["risk"]
        elif action == "task.heartbeat":
            task.lease_until = int(attrs.get("lease.until", task.lease_until))
        elif action == "workspace.created":
            task.status = WORKSPACE
            task.branch = attrs.get("vcs.branch", task.branch)
            task.base = attrs.get("vcs.base", task.base)
        elif action == "episode.started":
            task.status = EPISODE
            task.agent = attrs.get("agent.name", task.agent)
        elif action == "episode.finished":
            task.status = EPISODE
            task.commit = attrs.get("vcs.commit", task.commit)
            task.tree = attrs.get("vcs.tree", task.tree)
        elif action == "episode.failed":
            task.status = FAILED
            task.evidence = attrs.get("evidence", task.evidence)
        elif action == "gate.passed":
            task.status = GATED
            task.commit = attrs.get("vcs.commit", task.commit)
            task.tree = attrs.get("vcs.tree", task.tree)
            task.evidence = attrs.get("gate.artifact", task.evidence)
        elif action == "gate.failed":
            task.status = QUEUED
            task.retries += 1
            task.evidence = attrs.get("gate.artifact", task.evidence)
        elif action == "control.failed":
            task.status = BLOCKED
            task.question = "Гейт мёртв: негативный контроль не падает"
        elif action == "integration.started":
            task.status = GATED
        elif action == "integration.passed":
            task.status = INTEGRATED
            task.commit = attrs.get("vcs.commit", task.commit)
            task.tree = attrs.get("vcs.tree", task.tree)
            task.evidence = attrs.get("integration.artifact", task.evidence)
        elif action == "integration.failed":
            task.status = QUEUED
            task.retries += 1
            task.evidence = attrs.get("integration.artifact", task.evidence)
        elif action == "merge.done":
            task.status = DONE
            task.commit = attrs.get("vcs.commit", task.commit)
            task.tree = attrs.get("vcs.tree", task.tree)
        elif action == "task.done":
            task.status = DONE
            task.commit = attrs.get("vcs.commit", task.commit)
            task.evidence = attrs.get("evidence", task.evidence)
        elif action == "task.failed":
            task.status = FAILED
            task.evidence = attrs.get("evidence", task.evidence)
        elif action == "task.blocked":
            task.status = BLOCKED
            task.question = attrs.get("question", task.question)
        elif action == "task.answered":
            task.answer = attrs.get("answer", task.answer)
            if task.commit and task.tree:
                task.status = INTEGRATED
            else:
                task.status = QUEUED
        elif action == "task.requeued":
            task.status = QUEUED
            task.retries += 1
            task.evidence = attrs.get("evidence", task.evidence)
        elif action == "task.note":
            pass

    # ── queries ────────────────────────────────────────────────────────────
    def task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise KeyError(f"unknown task: {task_id}")
        return self.tasks[task_id]

    def all(self) -> list[Task]:
        return sorted(self.tasks.values(), key=lambda t: (t.created_seq, t.id))

    def ready(self, wip: int = 1, active_paths: list[str] | None = None) -> list[Task]:
        if self.paused:
            return []
        now = time.time_ns()
        active = [
            t
            for t in self.all()
            if t.active and (not t.lease_until or t.lease_until > now)
        ]
        if len(active) >= wip:
            return []
        busy_paths = list(active_paths or [])
        for task in active:
            busy_paths.extend(task.allowed_paths)
        ready = []
        for task in self.all():
            if task.status != QUEUED:
                expired_claim = (
                    task.status == CLAIMED and task.lease_until and task.lease_until <= now
                )
                if not expired_claim:
                    continue
            if any(self.tasks.get(dep) is None or self.tasks[dep].status != DONE for dep in task.deps):
                continue
            if _overlaps_any(task.allowed_paths, busy_paths):
                continue
            ready.append(task)
        return sorted(ready, key=lambda t: (t.priority, t.created_seq, t.id))

    def current(self) -> list[Task]:
        return [t for t in self.all() if t.active]

    def blocked(self) -> list[Task]:
        return [t for t in self.all() if t.status == BLOCKED]


def _literal_prefix(pattern: str) -> str:
    out = []
    for ch in pattern:
        if ch in "*?[":
            break
        out.append(ch)
    return "".join(out)


def paths_overlap(a: str, b: str) -> bool:
    """Conservative check: two glob patterns may touch the same path."""
    if not a or not b:
        return True
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    if not pa or not pb:
        return True
    return pa.startswith(pb) or pb.startswith(pa)


def _overlaps_any(paths: list[str], others: list[str]) -> bool:
    return any(paths_overlap(p, q) for p in paths for q in others)
