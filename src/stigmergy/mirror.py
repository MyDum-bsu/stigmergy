"""GitHub mirror: issues are a view, the event board remains the truth."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def payloads(config: Config, board: Board) -> list[dict[str, Any]]:
    state = ProjectState.from_events(board.read(), project=config.name)
    out = []
    for task in state.all():
        if task.status in {"done", "rejected"}:
            continue
        out.append(
            {
                "task": task.id,
                "title": f"[stg] {task.id}: {task.title}",
                "body": (
                    f"Project: {config.name}\n"
                    f"Status: {task.status}\n"
                    f"Spec: {task.spec or '-'}\n"
                    f"Question: {task.question or '-'}\n\n"
                    "Mirror only; the stigmergy board is the source of truth."
                ),
                "labels": ["stigmergy", f"stg:{task.id}"],
            }
        )
    return out


def apply(config: Config, board: Board) -> dict[str, Any]:
    """Create missing issues via gh. Requires explicit --apply from a human."""
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "detail": "gh not installed"}
    created = []
    for payload in payloads(config, board):
        search = subprocess.run(
            [gh, "issue", "list", "--search", f"stg:{payload['task']} in:body", "--json", "number"],
            text=True,
            capture_output=True,
            check=False,
        )
        if search.returncode != 0:
            return {"ok": False, "detail": search.stderr.strip()[:500], "created": created}
        try:
            existing = json.loads(search.stdout or "[]")
        except ValueError:
            existing = []
        if existing:
            continue
        proc = subprocess.run(
            [
                gh,
                "issue",
                "create",
                "--title",
                payload["title"],
                "--body",
                payload["body"],
                *sum((["--label", label] for label in payload["labels"]), []),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return {"ok": False, "detail": proc.stderr.strip()[:500], "created": created}
        created.append({"task": payload["task"], "url": proc.stdout.strip()})
    return {"ok": True, "created": created, "count": len(created)}
