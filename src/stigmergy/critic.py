"""Independent critic: a separate tab, different model, fresh context.

This is not a gate: it is an explicit review role the lead can open after a
worker finished. The gate remains the verdict; the critic adds blast-radius,
property, and money/data checks with frequency × harm.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState
from stigmergy.runner import herdr_app
from stigmergy.spec import load_for
from stigmergy.workspace import rev_parse

CRITIC_TAB = "Critic · "
DEFAULT_CRITIC_ARGS = ["--exclude-tools", "edit,write,AskUserQuestion"]


def _git(path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(path), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return (proc.stdout or proc.stderr).strip()


def critic_prompt(
    config: Config,
    task_id: str,
    *,
    base: str,
    commit: str,
    diff_stat: str,
    prd: str,
) -> str:
    return f"""You are the independent critic for task {task_id}.

You did not write this code and you are not told what the author intended.
Read the diff, tests, PRD and spec. Try to break it:
- blast radius: what else can this change;
- missing edge cases and property-based tests;
- mutation: would a deliberately broken version be caught;
- money, data, external-system duplication: harm = 10;
- mismatch with the PRD/spec, not just with the tests.

Base: {base}
Commit: {commit}
Diff stat:
{diff_stat}

PRD:
{prd or "(no PRD)"}

Output only findings as:
  finding | frequency 1..10 | harm 1..10 | evidence (file:line or command)
If frequency × harm < 5, put it in the catalog and do not block. Do not edit
files, do not run the gate, do not merge. The gate is the verdict.
"""


def _prd(config: Config, task_id: str) -> str:
    path = config.integration_root / "prd" / f"{task_id}.md"
    if not path.exists():
        path = config.root / "prd" / f"{task_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def start_critic(
    config: Config,
    board: Board,
    task_id: str,
    *,
    app: str = "herdr-app",
) -> dict:
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    base = task.base or config.base
    commit = task.commit
    if not commit:
        workspace = config.workspace_root / f"{task.id}-{task.sha}"
        commit = rev_parse(workspace, "HEAD")
    diff_stat = _git(config.root, "diff", "--stat", f"{base}..{commit}")
    spec = load_for(config.root, base, task.spec)
    prompt = critic_prompt(
        config,
        task_id,
        base=base,
        commit=commit,
        diff_stat=diff_stat,
        prd=_prd(config, task_id),
    )
    space_name = str(config.runner.get("space", "") or "") or "optimization"
    space = herdr_app.ensure_space(app, space_name, config.root)
    space_id = str(space.get("space") or space.get("id") or "")
    args = list(DEFAULT_CRITIC_ARGS)
    model = str(config.runner.get("critic_model", "") or "")
    if model:
        args += ["--model", model]
    created = herdr_app.create_tab(
        app,
        space_id,
        f"{CRITIC_TAB}{task_id}",
        config.root,
        str(config.runner.get("agent", "pi")),
        prompt,
        agent_args=args,
    )
    return {
        "task": task_id,
        "space": space_id,
        "terminal": str(created.get("terminal", "")),
        "commit": commit,
        "model": model or "default",
        "spec": spec.id,
    }
