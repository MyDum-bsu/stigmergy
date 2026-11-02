"""Token/time/cost usage recorded on the board (one event per call)."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board


def record(
    config: Config,
    board: Board,
    *,
    task_id: str,
    stage: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    cost_usd: str = "0",
) -> dict[str, Any]:
    return board.append(
        "usage.recorded",
        {"kind": "agent", "name": "usage"},
        {
            "project.name": config.name,
            "task.id": task_id,
            "stage": stage,
            "model": model,
            "prompt.tokens": max(0, int(prompt_tokens)),
            "completion.tokens": max(0, int(completion_tokens)),
            "duration.ms": max(0, int(duration_ms)),
            "cost.usd": str(Fraction(cost_usd)),
        },
        f"usage {stage} {task_id}",
    )


def totals(board: Board) -> dict[str, Any]:
    prompt = completion = duration = 0
    cost = Fraction(0)
    calls = 0
    for event in board.read():
        if event.get("action") != "usage.recorded":
            continue
        attrs = event.get("attributes") or {}
        calls += 1
        prompt += int(attrs.get("prompt.tokens") or 0)
        completion += int(attrs.get("completion.tokens") or 0)
        duration += int(attrs.get("duration.ms") or 0)
        try:
            cost += Fraction(str(attrs.get("cost.usd") or "0"))
        except (ValueError, ZeroDivisionError):
            pass
    return {
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "duration_ms": duration,
        "cost_usd": str(cost),
    }
