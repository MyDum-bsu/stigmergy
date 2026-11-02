"""Episodes: start, finish, gate, integrate, merge.

The contour owns the commit and the tree.  The runner is only a way to produce
changes; the verdict comes from the gate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from stigmergy.config import Config
from stigmergy.gate import GateResult, run_gate
from stigmergy.integrate import IntegrationResult, ff_base, integrate
from stigmergy.log import Board, sha256_text
from stigmergy.model import ProjectState, Task
from stigmergy.render import render
from stigmergy.spec import Spec, load_for
from stigmergy.workspace import (
    commit_all,
    create_task_worktree,
    remove_worktree,
    rev_parse,
    tree_of,
)


@dataclass
class EpisodeResult:
    task_id: str
    episode: str
    commit: str
    tree: str
    gate: GateResult | None = None
    integration: IntegrationResult | None = None
    merged: bool = False
    blocked: bool = False
    detail: str = ""
    runner_handle: str = ""
    runner_workspace: str = ""
    runner_space: str = ""

    def as_dict(self) -> dict:
        return {
            "task": self.task_id,
            "episode": self.episode,
            "commit": self.commit,
            "tree": self.tree,
            "merged": self.merged,
            "blocked": self.blocked,
            "detail": self.detail,
            "gate": self.gate.as_dict() if self.gate else None,
            "integration": self.integration.as_dict() if self.integration else None,
            "runner_handle": self.runner_handle,
            "runner_workspace": self.runner_workspace,
            "runner_space": self.runner_space,
        }


def state_of(board: Board, project: str) -> ProjectState:
    return ProjectState.from_events(board.read(), project=project)


def new_episode_id() -> str:
    return f"ep_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


def build_prompt(
    task: Task,
    spec: Spec,
    workspace: Path,
    agent: str = "stg",
    board_root: Path | None = None,
) -> str:
    board = str(board_root or workspace)

    oracle = ", ".join(spec.oracle_paths) if spec.oracle_paths else "none"
    allowed = ", ".join(task.allowed_paths or spec.allowed_paths) or "see spec"
    return f"""You are the implementer for stigmergy task {task.id}.

Workspace: {workspace}
Allowed paths: {allowed}
Oracle paths (do not edit): {oracle}
Gate command (the contour runs it; you may run it to check): {spec.dod}

Spec:
{spec.body.strip()}

Rules:
- Work only inside the workspace. Do not touch oracle paths.
- Do not merge or move branches. The contour commits the tree and runs the gate.
- If you are blocked on a decision, run exactly:
  `stg --board {board} board block {task.id} --agent {agent} --question "<one question>"`
  and stop. Do not use AskUserQuestion and do not ask the human: the lead
  answers through `stg lead answer` and resumes you.
- When the work is done, run exactly:
  `stg --board {board} worker done {task.id} --agent {agent}`
  then stop. Idle is not proof; the dispatcher waits for this marker. The
  gate decides whether it is done.
"""


def _append(
    board: Board,
    action: str,
    project: str,
    task_id: str,
    agent: str,
    attributes: dict | None = None,
    body: str = "",
) -> dict:
    attrs = {"project.name": project, "task.id": task_id, "agent.name": agent}
    attrs.update(attributes or {})
    return board.append(action, {"kind": "agent", "name": agent}, attrs, body)


def start_episode(
    config: Config,
    board: Board,
    task_id: str,
    agent: str = "stg",
    runner: str = "manual",
    *,
    wait_runner: bool = True,
    space: str | None = None,
    tab_name: str | None = None,
) -> tuple[EpisodeResult, str]:
    state = state_of(board, config.name)
    task = state.task(task_id)
    if task.status == "queued":
        from stigmergy.board import claim

        claim(board, config, task_id, agent)
        state = state_of(board, config.name)
        task = state.task(task_id)
    if task.status not in {"claimed", "workspace"}:
        raise RuntimeError(f"task {task_id} is {task.status}; claim it first")
    wt = create_task_worktree(config, task)
    if task.status != "workspace":
        _append(
            board,
            "workspace.created",
            config.name,
            task.id,
            agent,
            {"workspace.path": str(wt.path), "vcs.branch": wt.branch, "vcs.base": wt.base},
        )
    episode = new_episode_id()
    spec = load_for(config.root, wt.base, task.spec)
    prompt = build_prompt(task, spec, wt.path, agent=agent, board_root=config.root)
    handle = None
    if runner == "herdr-app":
        from stigmergy import routing
        from stigmergy.runner.herdr_app import HerdrAppRunner

        space = space or str(config.runner.get("space", "") or "") or None
        tab_name = tab_name or (f"{task.id} · {task.title}".strip(" ·") if task.title else task.id)
        agent_args = routing.args(config, "worker", ["--exclude-tools", "AskUserQuestion"])
        for skill in spec.skills:
            agent_args.extend(["--skill", skill])
        worker_argv = None
        if config.runner.get("sandbox", True):
            from stigmergy import sandbox

            if config.sandbox.get("engine") == "bwrap" and sandbox.bwrap_available():
                worker_argv = sandbox.worker_argv(
                    wt.path,
                    config.root,
                    str(config.runner.get("agent", "pi")),
                    agent_args,
                )
        app_runner = HerdrAppRunner(
            app=str(config.runner.get("app", "herdr-app")),
            agent=str(config.runner.get("agent", "pi")),
            timeout_s=int(config.runner.get("prompt_timeout_s", 1800)),
            space=space,
            tab_name=tab_name,
            space_folder=config.root,
            agent_args=agent_args,
            argv=worker_argv,
        )
        try:
            handle = app_runner.start(task.id, prompt, wt.path, wait=wait_runner)
        except Exception as exc:
            _append(
                board,
                "episode.failed",
                config.name,
                task.id,
                agent,
                {"evidence": f"runner failed: {exc}", "episode.id": episode},
                "runner failed",
            )
            raise
    elif runner == "herdr":
        from stigmergy.runner.herdr import HerdrRunner

        herdr_runner = HerdrRunner(
            session=str(config.runner.get("session", "factory")),
            agent=str(config.runner.get("agent", "pi")),
        )
        try:
            handle = herdr_runner.start(task.id, prompt, wt.path, wait=wait_runner)
        except Exception as exc:
            _append(
                board,
                "episode.failed",
                config.name,
                task.id,
                agent,
                {"evidence": f"runner failed: {exc}", "episode.id": episode},
                "runner failed",
            )
            raise
    attributes = {
        "episode.id": episode,
        "runner.kind": runner,
        "prompt.sha": sha256_text(prompt),
        "sandbox.profile": "episode" if config.runner.get("sandbox", True) else "none",
    }
    if handle is not None:
        attributes.update(
            {
                "runner.handle": handle.handle,
                "runner.pane": handle.pane,
                "runner.workspace": handle.workspace,
            }
        )
        if handle.meta.get("space"):
            attributes["runner.space"] = handle.meta["space"]
    _append(board, "episode.started", config.name, task.id, agent, attributes)
    result = EpisodeResult(
        task_id=task.id,
        episode=episode,
        commit="",
        tree="",
        runner_handle=handle.handle if handle else "",
        runner_workspace=handle.workspace if handle else "",
        runner_space=str(handle.meta.get("space", "")) if handle else "",
    )
    return result, prompt


def _gate_events(
    config: Config,
    board: Board,
    task: Task,
    episode: str,
    gate: GateResult,
    agent: str,
) -> None:
    attrs = {
        "episode.id": episode,
        "gate.command": gate.command,
        "gate.exit_code": gate.exit_code,
        "gate.duration_ms": gate.duration_ms,
        "gate.artifact": str(gate.artifact_dir / "gate.json"),
        "oracle.sha": gate.oracle_sha,
        "control.result": gate.control.get("result"),
        "vcs.commit": gate.commit,
        "vcs.tree": gate.tree,
    }
    if gate.passed:
        _append(board, "gate.passed", config.name, task.id, agent, attrs, "gate passed")
        if gate.control.get("result") == "proven":
            _append(
                board,
                "control.passed",
                config.name,
                task.id,
                agent,
                {"control.cases": gate.control.get("cases", 0)},
                "negative control proven",
            )
        return
    _append(
        board,
        "gate.failed",
        config.name,
        task.id,
        agent,
        attrs,
        f"gate failed: exit={gate.exit_code} control={gate.control.get('result')}",
    )
    if gate.control.get("result") == "dead":
        _append(
            board,
            "control.failed",
            config.name,
            task.id,
            agent,
            {"control.cases": gate.control.get("cases", 0)},
            "negative control passed — the gate is dead",
        )
    elif gate.control.get("result") == "absent" and task.risk in {"medium", "high"}:
        _append(
            board,
            "task.blocked",
            config.name,
            task.id,
            agent,
            {"question": "Нет негативного контроля для medium/high — критерий не доказан"},
            "blocked: control absent",
        )


def finish_episode(
    config: Config,
    board: Board,
    task_id: str,
    agent: str = "stg",
    *,
    noop: bool = False,
    auto: bool = False,
    use_sandbox: bool | None = None,
) -> EpisodeResult:
    try:
        return _finish_episode(
            config,
            board,
            task_id,
            agent,
            noop=noop,
            auto=auto,
            use_sandbox=use_sandbox,
        )
    finally:
        if not bool(config.runner.get("keep_workspace", True)):
            _close_runner_workspace(config, board, task_id)


def _close_runner_workspace(config: Config, board: Board, task_id: str) -> None:
    events = [
        event
        for event in board.read()
        if event.get("action") == "episode.started"
        and (event.get("attributes") or {}).get("task.id") == task_id
        and (event.get("attributes") or {}).get("runner.workspace")
    ]
    if not events:
        return
    attributes = events[-1]["attributes"]
    if attributes.get("runner.space"):
        try:
            from stigmergy.runner.herdr_app import close_space

            close_space(str(attributes["runner.space"]))
        except Exception:
            return
        return
    workspace = str(attributes["runner.workspace"])
    try:
        from stigmergy.runner.herdr import close_workspace

        close_workspace(str(config.runner.get("session", "factory")), workspace)
    except Exception:
        return


def _finish_episode(
    config: Config,
    board: Board,
    task_id: str,
    agent: str = "stg",
    *,
    noop: bool = False,
    auto: bool = False,
    use_sandbox: bool | None = None,
) -> EpisodeResult:
    state = state_of(board, config.name)
    task = state.task(task_id)
    episode = new_episode_id()
    wt_path = config.workspace_root / f"{task.id}-{task.sha}"
    if not wt_path.exists():
        raise RuntimeError(f"workspace not found: {wt_path}")
    if noop:
        commit = rev_parse(wt_path, "HEAD")
        tree = tree_of(wt_path, "HEAD")
    else:
        commit, _ = commit_all(wt_path, f"{task.id}: episode {episode}")
        tree = tree_of(wt_path, "HEAD")
    _append(
        board,
        "episode.finished",
        config.name,
        task.id,
        agent,
        {"episode.id": episode, "vcs.commit": commit, "vcs.tree": tree},
        "episode finished",
    )
    spec = load_for(config.root, task.base or config.base, task.spec)
    if task.spec_sha and spec.sha != task.spec_sha:
        raise RuntimeError("spec changed after claim; open a new task")
    _append(
        board,
        "gate.started",
        config.name,
        task.id,
        agent,
        {"episode.id": episode, "gate.command": spec.dod, "vcs.commit": commit},
    )
    result = EpisodeResult(
        task_id=task.id, episode=episode, commit=commit, tree=tree, detail="gated"
    )
    base = task.base or config.base
    gate = run_gate(config, spec, commit, base, episode, use_sandbox=use_sandbox)
    result.gate = gate
    _gate_events(config, board, task, episode, gate, agent)
    if not gate.passed:
        result.detail = f"gate failed: exit={gate.exit_code} control={gate.control.get('result')}"
        return result
    if not auto:
        result.detail = "gate passed; run stg integrate"
        return result
    _append(
        board,
        "integration.started",
        config.name,
        task.id,
        agent,
        {"episode.id": episode, "vcs.base": base},
    )
    do_merge = task.risk != "high"
    integration = integrate(
        config,
        spec,
        wt_path,
        base,
        episode,
        use_sandbox=use_sandbox,
        do_merge=do_merge,
    )
    result.integration = integration
    artifact = str(integration.artifact)
    if not integration.ok:
        _append(
            board,
            "integration.failed",
            config.name,
            task.id,
            agent,
            {"episode.id": episode, "integration.artifact": artifact},
            integration.detail,
        )
        result.detail = integration.detail
        return result
    _append(
        board,
        "integration.passed",
        config.name,
        task.id,
        agent,
        {
            "episode.id": episode,
            "vcs.commit": integration.commit,
            "vcs.tree": integration.tree,
            "integration.artifact": artifact,
        },
        "integration passed",
    )
    if task.risk == "high":
        _append(
            board,
            "task.blocked",
            config.name,
            task.id,
            agent,
            {"question": f"High-risk merge {task.id}: мержить в {config.base}?"},
            "blocked: high-risk merge",
        )
        result.blocked = True
        result.detail = "integration passed; high-risk merge awaits human"
        return result
    _append(
        board,
        "merge.done",
        config.name,
        task.id,
        agent,
        {"vcs.commit": integration.commit, "vcs.tree": integration.tree},
        f"merged into {config.base}",
    )
    _append(
        board,
        "task.done",
        config.name,
        task.id,
        agent,
        {
            "vcs.commit": integration.commit,
            "evidence": f"gate={artifact} oracle={gate.oracle_sha} control={gate.control.get('result')}",
        },
        "done",
    )
    remove_worktree(config.root, wt_path)
    _append(
        board,
        "workspace.removed",
        config.name,
        task.id,
        agent,
        {"workspace.path": str(wt_path)},
        "workspace removed",
    )
    result.merged = True
    result.detail = f"merged into {config.base}"
    render(board.views_dir, state_of(board, config.name))
    if str(config.runner.get("kind", "")) == "herdr-app":
        try:
            from stigmergy.runner import herdr_app

            herdr_app.close_task_tabs(
                str(config.runner.get("app", "herdr-app")), task.id
            )
        except Exception:
            pass
    return result


def merge_task(config: Config, board: Board, task_id: str, agent: str = "stg") -> EpisodeResult:
    state = state_of(board, config.name)
    task = state.task(task_id)
    if not task.commit or not task.tree:
        raise RuntimeError("no integrated commit for task")
    if task.risk == "high" and task.answer_by != "human":
        raise RuntimeError("high-risk merge requires a human answer (answered.by=human)")
    ok, detail = ff_base(config, task.commit)
    result = EpisodeResult(
        task_id=task.id,
        episode="",
        commit=task.commit,
        tree=task.tree,
        merged=ok,
        detail=detail or "fast-forward",
    )
    if not ok:
        _append(
            board,
            "integration.failed",
            config.name,
            task.id,
            agent,
            {"detail": detail},
            "ff merge failed",
        )
        return result
    _append(
        board,
        "merge.done",
        config.name,
        task.id,
        agent,
        {"vcs.commit": task.commit, "vcs.tree": task.tree},
        f"merged into {config.base}",
    )
    _append(
        board,
        "task.done",
        config.name,
        task.id,
        agent,
        {"vcs.commit": task.commit, "evidence": task.evidence or "merged"},
        "done",
    )
    wt_path = config.workspace_root / f"{task.id}-{task.sha}"
    if wt_path.exists():
        remove_worktree(config.root, wt_path)
        _append(
            board,
            "workspace.removed",
            config.name,
            task.id,
            agent,
            {"workspace.path": str(wt_path)},
            "workspace removed",
        )
    render(board.views_dir, state_of(board, config.name))
    return result
