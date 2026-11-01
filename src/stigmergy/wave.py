"""A wave: one Herdr space with a lead architect and one tab per task."""

from __future__ import annotations

import re
import time

from stigmergy.config import Config
from stigmergy.episode import start_episode, state_of
from stigmergy.log import Board
from stigmergy.runner.herdr_app import DEFAULT_APP, create_space, ensure_app


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:32] or "goal"


def lead_prompt(config: Config, wave: str, goal: str, tasks: list[str]) -> str:
    return f"""You are the lead architect of stigmergy wave {wave}.

Goal: {goal}
Tasks: {", ".join(tasks)}
Board: {config.root}

The workers are tabs in this space; each has its own git worktree and spec.
Do not write code. Read the board with:
  stg --board {config.root} board status
  stg --board {config.root} board list
  stg --board {config.root} board log --limit 40
Watch a worker with `hc read <terminal>`; answer decisions only through
`stg board answer --by human` (you are not the human), and report to the person
in this tab. The factory runs the gate and the merge; do not self-certify and
do not merge.
"""


def create_wave(
    config: Config,
    board: Board,
    goal: str,
    tasks: list[str],
    *,
    agent: str = "stg",
    runner: str = "herdr-app",
    app: str = DEFAULT_APP,
) -> dict:
    if not tasks:
        raise ValueError("wave needs at least one task")
    state = state_of(board, config.name)
    for task_id in tasks:
        task = state.task(task_id)
        if task.status != "queued":
            raise RuntimeError(f"task {task_id} is {task.status}, not queued")
        if not task.spec:
            raise RuntimeError(f"task {task_id} has no spec; write specs/{task_id}.md first")
    ensure_app(app)
    wave = f"w{time.strftime('%Y%m%d%H%M%S')}"
    name = f"stg-wave-{wave}"
    created = create_space(
        app,
        name,
        config.root,
        str(config.runner.get("agent", "pi")),
        lead_prompt(config, wave, goal, tasks),
    )
    space = str(created.get("space", ""))
    lead_terminal = str(created.get("terminal", ""))
    if not space:
        raise RuntimeError("space.new returned no space")
    board.append(
        "wave.created",
        {"kind": "agent", "name": agent},
        {
            "project.name": config.name,
            "wave.id": wave,
            "wave.goal": goal,
            "wave.space": space,
            "wave.tasks": tasks,
        },
        f"wave {wave}: {goal}",
    )
    workers = []
    for task_id in tasks:
        result, _prompt = start_episode(
            config,
            board,
            task_id,
            agent,
            runner,
            wait_runner=False,
            space=space,
            tab_name=f"stg-{task_id}",
        )
        workers.append(
            {
                "task": task_id,
                "space": space,
                "terminal": result.runner_handle,
                "episode": result.episode,
            }
        )
    return {
        "wave": wave,
        "goal": goal,
        "space": space,
        "lead": lead_terminal,
        "tasks": tasks,
        "workers": workers,
    }
