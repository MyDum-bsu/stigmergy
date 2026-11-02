"""Proactive inbox: external signals as JSONL, each source-id is idempotent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stigmergy import intake
from stigmergy.config import Config
from stigmergy.log import Board


def ingest(
    config: Config,
    board: Board,
    path: Path,
    *,
    app: str = "herdr-app",
    start_planner: bool = True,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return [{"error": f"feed not found: {path}"}]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        idea = str(item.get("idea") or "").strip()
        if not idea:
            out.append({"error": "missing idea", "item": item})
            continue
        try:
            result = intake.create_task(
                config,
                board,
                idea,
                title=item.get("title"),
                source=str(item.get("source") or "feed"),
                source_id=str(item.get("id") or ""),
                app=app,
                start_planner=start_planner,
            )
            out.append(result)
        except Exception as exc:
            out.append({"error": str(exc)[:500], "item": item})
    return out
