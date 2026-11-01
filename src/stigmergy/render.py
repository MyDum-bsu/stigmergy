"""Human-readable projections: Current / Backlog / Worklog."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from stigmergy.model import DONE, FAILED, REJECTED, ProjectState, Task


def _ts(ns: int) -> str:
    if not ns:
        return "-"
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _line(task: Task) -> str:
    return f"- **{task.id}** [{task.status}] {task.title}"


def _generated(state: ProjectState) -> str:
    stamp = _ts(state.events[-1]["timeUnixNano"]) if state.events else "-"
    return f"_Generated from `.agent/events.jsonl` at {stamp}. Do not edit by hand._"


def render_current(state: ProjectState) -> str:
    lines = [
        "# Current",
        "",
        _generated(state),
        "",
    ]
    active = state.current()
    blocked = state.blocked()
    if not active and not blocked:
        lines.append("No active work.")
    for task in active:
        lines.append(_line(task))
        lines.append(f"  - agent: {task.agent or '-'}; lease: {_ts(task.lease_until)}")
        if task.branch:
            lines.append(f"  - branch: `{task.branch}`")
    if blocked:
        lines.append("")
        lines.append("## Blocked")
        for task in blocked:
            lines.append(_line(task))
            lines.append(f"  - question: {task.question or '-'}")
    return "\n".join(lines).rstrip() + "\n"


def render_backlog(state: ProjectState) -> str:
    lines = [
        "# Backlog",
        "",
        _generated(state),
        "",
    ]
    queued = [t for t in state.all() if t.status in {"queued", "proposed"}]
    if not queued:
        lines.append("Empty.")
    for task in queued:
        deps = ", ".join(task.deps) if task.deps else "none"
        lines.append(f"- `{task.id}` P{task.priority} [{task.status}] {task.title}")
        lines.append(f"  - deps: {deps}; risk: {task.risk}; spec: {task.spec or '-'}")
        if task.allowed_paths:
            lines.append(f"  - paths: {', '.join(task.allowed_paths)}")
    return "\n".join(lines).rstrip() + "\n"


def render_worklog(state: ProjectState) -> str:
    lines = [
        "# Worklog",
        "",
        _generated(state),
        "",
    ]
    done = [t for t in state.all() if t.status in {DONE, FAILED, REJECTED}]
    if not done:
        lines.append("Empty.")
    for task in done:
        lines.append(f"- `{task.id}` [{task.status}] {task.title}")
        if task.commit:
            lines.append(f"  - commit: `{task.commit}`")
        if task.evidence:
            lines.append(f"  - evidence: {task.evidence}")
    return "\n".join(lines).rstrip() + "\n"


def render(board_views_dir: Path, state: ProjectState) -> None:
    board_views_dir.mkdir(parents=True, exist_ok=True)
    (board_views_dir / "Current.md").write_text(render_current(state), encoding="utf-8")
    (board_views_dir / "Backlog.md").write_text(render_backlog(state), encoding="utf-8")
    (board_views_dir / "Worklog.md").write_text(render_worklog(state), encoding="utf-8")
