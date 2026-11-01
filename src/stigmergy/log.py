"""Append-only event log.

One writer is enforced with ``flock`` on ``.agent/lock``.  Events are JSONL with
OpenTelemetry-shaped field names and a per-host monotonic ``seq``/``timeUnixNano``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = "stigmergy/v1"


class BoardError(RuntimeError):
    """Raised when the board cannot honour a request."""


def now_ns() -> int:
    return time.time_ns()


def new_id() -> str:
    return str(uuid.uuid4())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def trace_for(project: str, task_id: str) -> str:
    return hashlib.sha256(f"{project}:{task_id}".encode()).hexdigest()[:16]


class Board:
    """A project board rooted at ``<root>/.agent``."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.agent_dir = self.root / ".agent"
        self.events_path = self.agent_dir / "events.jsonl"
        self.lock_path = self.agent_dir / "lock"
        self.views_dir = self.agent_dir / "views"

    # ── lifecycle ──────────────────────────────────────────────────────────
    def ensure(self) -> None:
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            self.events_path.touch()
        if not self.lock_path.exists():
            self.lock_path.touch()

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.ensure()
        with self.lock_path.open("a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    # ── read ───────────────────────────────────────────────────────────────
    def read(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.events_path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BoardError(f"bad event at {self.events_path}:{lineno}: {exc}") from exc
                events.append(event)
        return events

    def last(self) -> dict[str, Any] | None:
        events = self.read()
        return events[-1] if events else None

    # ── append ─────────────────────────────────────────────────────────────
    def append(
        self,
        action: str,
        actor: dict[str, str],
        attributes: dict[str, Any] | None = None,
        body: str = "",
        *,
        trace_id: str | None = None,
        parent_span_id: str = "",
        severity: str = "INFO",
    ) -> dict[str, Any]:
        with self.locked():
            return self._append_locked(
                action,
                actor,
                attributes or {},
                body,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                severity=severity,
            )

    def _append_locked(
        self,
        action: str,
        actor: dict[str, str],
        attributes: dict[str, Any],
        body: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str = "",
        severity: str = "INFO",
    ) -> dict[str, Any]:
        events = self.read()
        last = events[-1] if events else None
        seq = int(last["seq"]) + 1 if last else 1
        last_ns = int(last["timeUnixNano"]) if last else 0
        observed = now_ns()
        timestamp = max(observed, last_ns + 1)
        attributes = dict(attributes)
        task_id = attributes.get("task.id")
        if trace_id is None and task_id:
            project = attributes.get("project.name", self.root.name)
            trace_id = trace_for(str(project), str(task_id))
        event = {
            "schema": SCHEMA,
            "seq": seq,
            "eventId": new_id(),
            "timeUnixNano": timestamp,
            "observedTimeUnixNano": observed,
            "traceId": trace_id or new_id().replace("-", "")[:16],
            "spanId": new_id().replace("-", "")[:16],
            "parentSpanId": parent_span_id,
            "severityText": severity,
            "action": action,
            "actor": actor,
            "attributes": attributes,
            "body": body,
        }
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return event

    # ── helpers ────────────────────────────────────────────────────────────
    def append_many(self, events: list[dict[str, Any]]) -> None:
        with self.locked():
            for event in events:
                self._append_locked(
                    event["action"],
                    event["actor"],
                    event.get("attributes", {}),
                    event.get("body", ""),
                    trace_id=event.get("traceId"),
                    parent_span_id=event.get("parentSpanId", ""),
                    severity=event.get("severityText", "INFO"),
                )


def read_events(path: str | Path) -> list[dict[str, Any]]:
    board = Board(Path(path).parent.parent if Path(path).name == "events.jsonl" else path)
    return board.read()
