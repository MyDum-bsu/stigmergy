"""Weekly learning: turn reactions, gate failures and questions into lessons.

This is deliberately a report, not a self-modifying skill. The rule from the
frontier: architecture/linter/test/hook first, skill/AGENTS last.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def _since_ns(days: int) -> int:
    return int((time.time() - max(0, days) * 86400) * 1_000_000_000)


def collect(config: Config, board: Board, *, days: int = 7) -> dict[str, Any]:
    cutoff = _since_ns(days)
    events = [
        event
        for event in board.read()
        if int(event.get("timeUnixNano") or 0) >= cutoff
    ]
    state = ProjectState.from_events(board.read(), project=config.name)
    gate_failures = [
        event
        for event in events
        if event.get("action") in {"gate.failed", "control.failed", "integration.failed"}
    ]
    blocked = [
        event
        for event in events
        if event.get("action") == "task.blocked"
    ]
    answers = [
        event
        for event in events
        if event.get("action") == "task.answered"
    ]
    retries = [task for task in state.all() if task.retries]
    decisions_dir = config.integration_root / "decisions"
    if not decisions_dir.exists():
        decisions_dir = config.root / "decisions"
    decisions = len(list(decisions_dir.glob("*.md"))) if decisions_dir.is_dir() else 0
    suggestions = [
        "Повторяющийся gate.failed → добавить тест/oracle/negative; сначала структура, не слово.",
        "Повторяющийся вопрос worker'а → записать решение в decisions/ с цитатой и датой.",
        "retries > 0 → уточнить allowed_paths/oracle/DoD, а не просить агента стараться.",
        "Правки после гейта → добавить хук/линтер/тест, только потом правило в skill.",
    ]
    return {
        "project": config.name,
        "days": days,
        "events": len(events),
        "tasks": len(state.all()),
        "gate_failures": gate_failures[-20:],
        "blocked_questions": blocked[-20:],
        "answers": answers[-20:],
        "retries": [{"id": task.id, "retries": task.retries, "status": task.status} for task in retries],
        "decisions": decisions,
        "suggestions": suggestions,
    }


def render(data: dict[str, Any]) -> str:
    lines = [
        f"# Retro · {data['project']} · {time.strftime('%Y-%m-%d')}",
        "",
        f"Окно: {data['days']} дней; событий: {data['events']}; задач: {data['tasks']}.",
        "",
        "## Падения гейта",
    ]
    if data["gate_failures"]:
        for event in data["gate_failures"]:
            attrs = event.get("attributes") or {}
            lines.append(f"- #{event.get('seq')} {event.get('action')} · {attrs.get('task.id', '')}")
    else:
        lines.append("- нет")
    lines += ["", "## Вопросы worker'ов"]
    if data["blocked_questions"]:
        for event in data["blocked_questions"]:
            attrs = event.get("attributes") or {}
            lines.append(f"- {attrs.get('task.id', '')}: {attrs.get('question', '')}")
    else:
        lines.append("- нет")
    lines += ["", "## Ответы"]
    human = sum(
        1 for event in data["answers"]
        if (event.get("attributes") or {}).get("answered.by") == "human"
    )
    lead = sum(
        1 for event in data["answers"]
        if (event.get("attributes") or {}).get("answered.by") == "lead"
    )
    lines.append(f"- человек: {human}")
    lines.append(f"- лид: {lead}")
    lines += ["", "## Переделки"]
    if data["retries"]:
        for row in data["retries"]:
            lines.append(f"- {row['id']}: retries={row['retries']} status={row['status']}")
    else:
        lines.append("- нет")
    lines += ["", "## Решения"]
    lines.append(f"- файлов в decisions/: {data['decisions']}")
    lines += ["", "## Предложения (guardrail раньше слова)"]
    lines += [f"- {item}" for item in data["suggestions"]]
    return "\n".join(lines) + "\n"


def write(config: Config, board: Board, *, days: int = 7) -> Path:
    data = collect(config, board, days=days)
    root = config.integration_root if config.integration_root.exists() else config.root
    out = root / "lessons" / f"{time.strftime('%Y-%m-%d')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    return out
