"""Stage-based model routing.

The route is data in ``.agent.toml``; the factory never guesses a model from a
prompt. ``worker``/``planner``/``critic``/``lead`` are resolved at tab creation
time, so swapping a model does not change the event schema or the gate.
"""

from __future__ import annotations

from typing import Any

from stigmergy.config import Config

STAGES = ("worker", "planner", "critic", "lead", "judge")


def configured(config: Config) -> dict[str, str]:
    section = config.section("models")
    return {stage: str(section.get(stage) or "").strip() for stage in ("default", *STAGES)}


def choose(config: Config, stage: str) -> str:
    """Return the route for ``stage``; fall back to the runner's old keys."""
    if stage not in STAGES:
        raise ValueError(f"unknown model stage: {stage}")
    routes = configured(config)
    if routes.get(stage):
        return routes[stage]
    if routes.get("default"):
        return routes["default"]
    runner = config.runner
    if stage == "critic" and str(runner.get("critic_model") or "").strip():
        return str(runner["critic_model"]).strip()
    if stage in {"worker", "planner", "lead"} and str(runner.get("model") or "").strip():
        return str(runner["model"]).strip()
    return ""


def args(config: Config, stage: str, base: list[str] | None = None) -> list[str]:
    """Agent argv with ``--model`` inserted once, unless the caller set one."""
    argv = list(base or [])
    if any(item == "--model" or item.startswith("--model=") for item in argv):
        return argv
    model = choose(config, stage)
    if model:
        argv.extend(["--model", model])
    return argv


def table(config: Config) -> dict[str, Any]:
    return {
        "routes": configured(config),
        "resolved": {stage: choose(config, stage) for stage in STAGES},
    }
