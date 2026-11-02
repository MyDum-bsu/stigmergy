"""``stg`` command line."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from stigmergy import __version__, dash, registry, sandbox
from stigmergy import board as board_mod
from stigmergy import doctor as doctor_mod
from stigmergy import migrate as migrate_mod
from stigmergy.config import Config
from stigmergy.episode import finish_episode, merge_task, start_episode
from stigmergy.gate import gate_artifact, run_gate
from stigmergy.log import Board, BoardError
from stigmergy.model import ProjectState
from stigmergy.render import render
from stigmergy.spec import Spec, SpecError, load_for


def find_root(start: str | Path) -> Path:
    path = Path(start).expanduser().resolve()
    for cur in [path, *path.parents]:
        if (cur / ".agent").exists():
            return cur
    for cur in [path, *path.parents]:
        if (cur / ".git").exists():
            return cur
    return path


def _ctx(args: argparse.Namespace) -> tuple[Path, Config, Board]:
    root = find_root(args.board or Path.cwd())
    return root, Config.load(root), Board(root)


def _state(board: Board, config: Config) -> ProjectState:
    return ProjectState.from_events(board.read(), project=config.name)


def _emit(args: argparse.Namespace, data: dict | list, text: str | None = None) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _task_text(task) -> str:
    lines = [f"{task.id} [{task.status}] P{task.priority} {task.title}"]
    if task.agent:
        lines.append(f"  agent: {task.agent} lease: {task.lease_until}")
    if task.branch:
        lines.append(f"  branch: {task.branch}")
    if task.spec:
        lines.append(f"  spec: {task.spec} sha: {task.spec_sha}")
    if task.commit:
        lines.append(f"  commit: {task.commit}")
    if task.evidence:
        lines.append(f"  evidence: {task.evidence}")
    return "\n".join(lines)


# ── init ───────────────────────────────────────────────────────────────────
def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".agent" / "views").mkdir(parents=True, exist_ok=True)
    (root / "specs").mkdir(exist_ok=True)
    (root / ".factory").mkdir(exist_ok=True)
    config = Config.load(root)
    config.write_default()
    gi = root / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for entry in (".agent/", ".factory/"):
        if entry not in lines:
            lines.append(entry)
    gi.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"initialised {root}")
    return 0


# ── board ──────────────────────────────────────────────────────────────────
def cmd_board(args: argparse.Namespace) -> int:
    root, config, board = _ctx(args)
    state = _state(board, config)
    cmd = args.board_cmd
    if cmd == "add":
        task = board_mod.add_task(
            board,
            config,
            args.id,
            args.title or "",
            priority=args.priority,
            deps=args.deps or [],
            spec_path=args.spec or "",
            risk=args.risk,
            branch=args.branch or "",
            sha=args.sha or "",
            agent=args.agent,
        )
        _emit(args, task.as_dict(), _task_text(task))
        return 0
    if cmd == "propose":
        event = board_mod.propose_task(
            board, config, args.id, args.title or "", priority=args.priority, spec_path=args.spec or ""
        )
        _emit(args, event)
        return 0
    if cmd == "approve":
        _emit(args, board_mod.approve(board, config, args.id, args.by))
        return 0
    if cmd == "spec":
        _emit(args, board_mod.attach_spec(board, config, args.id, args.spec, args.agent))
        return 0
    if cmd == "reject":
        _emit(args, board_mod.reject(board, config, args.id, args.by, args.reason or ""))
        return 0
    if cmd == "claim":
        _emit(args, board_mod.claim(board, config, args.id, args.agent, lease_seconds=args.lease))
        return 0
    if cmd == "next":
        task = board_mod.next_task(board, config, args.agent, lease_seconds=args.lease)
        if task is None:
            print("NO_TASK")
            return 0
        _emit(args, task.as_dict(), _task_text(task))
        return 0
    if cmd == "heartbeat":
        _emit(args, board_mod.heartbeat(board, config, args.id, args.agent, args.lease))
        return 0
    if cmd == "block":
        _emit(args, board_mod.block(board, config, args.id, args.agent, args.question))
        return 0
    if cmd == "answer":
        if args.by == "human":
            from stigmergy import human

            human.require()
        _emit(args, board_mod.answer(board, config, args.id, args.by, args.text))
        return 0
    if cmd == "done":
        _emit(
            args,
            board_mod.done(
                board,
                config,
                args.id,
                args.agent,
                commit=args.commit or "",
                no_commit=args.no_commit,
                evidence=args.evidence,
            ),
        )
        return 0
    if cmd == "fail":
        _emit(args, board_mod.fail(board, config, args.id, args.agent, args.reason))
        return 0
    if cmd == "note":
        _emit(args, board_mod.note(board, config, args.id, args.agent, args.text))
        return 0
    if cmd == "pr":
        _emit(args, board_mod.pr(board, config, args.id, args.agent, args.url))
        return 0
    if cmd == "ask":
        _emit(args, board_mod.ask(board, config, args.sender, args.to, args.text, args.hop))
        return 0
    if cmd == "list":
        tasks = board_mod.list_tasks(state, args.status)
        data = [t.as_dict() for t in tasks]
        text = "\n".join(f"{t.id}\t{t.priority}\t{t.status}\t{t.title}" for t in tasks)
        _emit(args, data, text or "NO_TASK")
        return 0
    if cmd == "show":
        task = state.task(args.id)
        recent = [e for e in state.events if (e.get("attributes") or {}).get("task.id") == args.id][-10:]
        _emit(args, {"task": task.as_dict(), "events": recent}, _task_text(task))
        return 0
    if cmd == "log":
        events = state.events[-args.limit :]
        text = "\n".join(
            f"{e['seq']:>4} {e.get('action',''):<20} {e.get('body','')}" for e in events
        )
        _emit(args, events, text)
        return 0
    if cmd == "audit":
        from stigmergy import metrics

        data = metrics.anonymous(board.read())
        _emit(args, data, "\n".join(f"{e['seq']}\t{e['action']}" for e in data) or "no anonymous events")
        return 0
    if cmd == "status":
        data = board_mod.status(state)
        counts = ", ".join(f"{k}={v}" for k, v in data["status"].items())
        text = (
            f"{data['project']}: {data['tasks']} tasks, {data['events']} events, "
            f"paused={data['paused']}\n{counts}"
        )
        _emit(args, data, text)
        return 0
    if cmd == "render":
        render(board.views_dir, state)
        print(f"rendered {board.views_dir}")
        return 0
    raise BoardError(f"unknown board command: {cmd}")


# ── spec ───────────────────────────────────────────────────────────────────
def cmd_spec(args: argparse.Namespace) -> int:
    root, config, _board = _ctx(args)
    if args.spec_cmd == "new":
        path = root / "specs" / f"{args.id}.md"
        if path.exists():
            raise SpecError(f"spec exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"""---
id: {args.id}
title: {args.title or args.id}
risk: low
deps: []
allowed_paths:
  - src/**
oracle_paths:
  - tests/**
gate_inputs:
  - Makefile
  - pyproject.toml
dod: make test
negative_control:
  corpus: oracle/negative/{args.id}/
---

## Intent

## Given

## When

## Then
""",
            encoding="utf-8",
        )
        print(path)
        return 0
    spec_path = root / args.path
    spec = Spec.load(spec_path) if spec_path.exists() else load_for(root, config.base, args.path)
    if args.spec_cmd == "validate":
        errors = (
            spec.validate_against_repo(root, args.base)
            if args.base
            else spec.validate()
        )
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"ok {spec.id} sha={spec.sha}")
        return 0
    if args.spec_cmd == "hash":
        print(spec.sha)
        return 0
    if args.spec_cmd == "show":
        print(json.dumps({"id": spec.id, "sha": spec.sha, "meta": spec.meta}, ensure_ascii=False, indent=2))
        return 0
    raise SpecError(f"unknown spec command: {args.spec_cmd}")


# ── episodes ───────────────────────────────────────────────────────────────
def _ensure_claimed(board: Board, config: Config, task_id: str, agent: str) -> None:
    state = _state(board, config)
    task = state.task(task_id)
    if task.status == "queued":
        board_mod.claim(board, config, task_id, agent)


def cmd_episode(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    if args.episode_cmd == "start":
        _ensure_claimed(board, config, args.id, args.agent)
        result, prompt_text = start_episode(config, board, args.id, args.agent, args.runner)
        if args.json:
            _emit(args, {"episode": result.as_dict(), "prompt": prompt_text})
        else:
            print(prompt_text)
        return 0
    if args.episode_cmd == "finish":
        use_sandbox = False if args.no_sandbox else None
        result = finish_episode(
            config,
            board,
            args.id,
            args.agent,
            noop=args.noop,
            auto=args.auto,
            use_sandbox=use_sandbox,
        )
        _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.gate and result.gate.passed else 1
    if args.episode_cmd == "stop":
        event = board.append(
            "episode.stopped",
            {"kind": "agent", "name": args.agent},
            {"project.name": config.name, "task.id": args.id, "agent.name": args.agent},
            "episode stopped",
        )
        _emit(args, event)
        return 0
    if args.episode_cmd == "status":
        state = _state(board, config)
        task = state.task(args.id)
        _emit(args, task.as_dict(), _task_text(task))
        return 0
    raise RuntimeError(f"unknown episode command: {args.episode_cmd}")


def cmd_run(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    if args.detach and args.auto:
        raise BoardError("--detach and --auto are mutually exclusive; finish later with stg episode finish")
    _ensure_claimed(board, config, args.id, args.agent)
    result, prompt_text = start_episode(
        config,
        board,
        args.id,
        args.agent,
        args.runner,
        wait_runner=not args.detach,
    )
    if args.detach:
        _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        print(
            f"detached: space={result.runner_space or '-'} handle={result.runner_handle or '-'}\n"
            f"finish: stg episode finish {args.id} --auto"
        )
        return 0
    if args.runner == "noop":
        result = finish_episode(
            config,
            board,
            args.id,
            args.agent,
            noop=True,
            auto=args.auto,
            use_sandbox=False if args.no_sandbox else None,
        )
        _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.merged or (result.gate and result.gate.passed) else 1
    if args.runner in {"herdr", "herdr-app"} and args.auto:
        result = finish_episode(
            config,
            board,
            args.id,
            args.agent,
            noop=False,
            auto=True,
            use_sandbox=False if args.no_sandbox else None,
        )
        _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.merged or (result.gate and result.gate.passed) else 1
    print(prompt_text)
    print("\nWhen the work is done, run: stg episode finish", args.id, "--auto")
    return 0


# ── gate / integrate / merge ───────────────────────────────────────────────
def cmd_gate(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    state = _state(board, config)
    task = state.task(args.id)
    if args.gate_cmd == "show":
        data = gate_artifact(config, args.id, args.episode)
        _emit(args, data)
        return 0
    if not task.spec:
        raise BoardError(f"task {args.id} has no spec")
    spec = load_for(config.root, task.base or config.base, task.spec)
    commit = task.commit
    if not commit:
        from stigmergy.workspace import rev_parse

        commit = rev_parse(config.workspace_root / f"{task.id}-{task.sha}", "HEAD")
    base = task.base or config.base
    result = run_gate(
        config,
        spec,
        commit,
        base,
        args.episode or "manual",
        use_sandbox=False if args.no_sandbox else None,
    )
    _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


def cmd_integrate(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    state = _state(board, config)
    task = state.task(args.id)
    if not task.commit:
        raise BoardError("task has no commit; run stg episode finish first")
    spec = load_for(config.root, task.base or config.base, task.spec)
    from stigmergy.integrate import integrate

    wt = config.workspace_root / f"{task.id}-{task.sha}"
    result = integrate(
        config,
        spec,
        wt,
        task.base or config.base,
        f"{args.id}-manual",
        use_sandbox=False if args.no_sandbox else None,
        do_merge=not args.no_merge,
    )
    _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def cmd_merge(args: argparse.Namespace) -> int:
    _root, _config, board = _ctx(args)
    config = Config.load(board.root)
    result = merge_task(config, board, args.id, args.agent)
    _emit(args, result.as_dict(), json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.merged else 1


# ── dash / status / doctor ─────────────────────────────────────────────────
def cmd_critique(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import critic

    data = critic.start_critic(config, board, args.id, app=args.app)
    _emit(args, data, f"critic {data['task']} terminal={data['terminal']} model={data['model']}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import formal

    if args.id:
        from stigmergy.spec import load_for

        state = _state(board, config)
        task = state.task(args.id)
        spec = load_for(config.root, task.base or config.base, task.spec)
        core = formal.verify_core(config, board)
        task_formal = formal.verify_task(config, spec, task.base or config.base)
        data = {"core": core, "task": task_formal, "passed": bool(core["passed"] and task_formal["ok"])}
        _emit(args, data, f"formal task={args.id} core={core['passed']} task_model={task_formal['ok']}")
        return 0 if data["passed"] else 1
    data = formal.verify_core(config, board)
    _emit(args, data, formal.text(data))
    return 0 if data["passed"] else 1


def cmd_retro(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import retro

    data = retro.collect(config, board, days=args.days)
    if args.write:
        path = retro.write(config, board, days=args.days)
        _emit(args, {"path": str(path), **data}, f"{path}\n\n{retro.render(data)}")
    else:
        _emit(args, data, retro.render(data))
    return 0


def cmd_mutation(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import mutation
    from stigmergy.spec import load_for

    state = _state(board, config)
    task = state.task(args.id)
    commit = task.commit
    if not commit:
        from stigmergy.workspace import rev_parse

        commit = rev_parse(config.workspace_root / f"{task.id}-{task.sha}", "HEAD")
    spec = load_for(config.root, task.base or config.base, task.spec)
    commands = [str(item) for item in (spec.meta.get("mutations") or [])]
    data = mutation.run(config, commit, commands)
    _emit(args, data, f"mutation: {'PASS' if data['ok'] else 'FAIL'} survivors={len(data['survivors'])}")
    return 0 if data["ok"] else 1


def cmd_mirror(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import human, mirror

    if args.apply:
        human.require()
        data = mirror.apply(config, board)
    else:
        items = mirror.payloads(config, board)
        data = {"ok": True, "dry_run": True, "items": items}
    _emit(args, data, json.dumps(data, ensure_ascii=False))
    return 0 if data.get("ok") else 1


def cmd_usage(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import usage

    data = usage.record(
        config,
        board,
        task_id=args.task,
        stage=args.stage,
        model=args.model,
        prompt_tokens=args.prompt_tokens,
        completion_tokens=args.completion_tokens,
        duration_ms=args.duration_ms,
        cost_usd=args.cost_usd,
    )
    _emit(args, data, f"usage {args.task} {args.stage}")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import learn

    path = learn.propose(config, board, days=args.days)
    _emit(args, {"path": str(path)}, str(path))
    return 0


def cmd_persona(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import persona

    data = persona.ingest(config, Path(args.file))
    _emit(
        args,
        data,
        f"persona: imported={data['imported']} skipped={data['skipped']} errors={data['errors']}\n"
        f"{data.get('digest', '')}",
    )
    return 0 if data["ok"] else 1


def cmd_schedule(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import schedule

    if args.schedule_cmd == "status":
        data = schedule.status()
    else:
        data = schedule.install(
            config,
            enable=args.enable,
            learn_calendar=args.learn_calendar,
            persona_calendar=args.persona_calendar,
        )
    _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 1


def cmd_model(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import bench, routing

    if args.model_cmd == "route":
        model = routing.choose(config, args.stage)
        _emit(args, {"stage": args.stage, "model": model}, model or "default")
        return 0
    if args.model_cmd == "list":
        data = routing.table(config)
        _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    data = bench.evaluate(
        config,
        Path(args.cases),
        args.model,
        command=args.command,
        timeout=args.timeout,
    )
    _emit(args, data, bench.text(data))
    return 0 if data["ok"] else 1


def cmd_pbt(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import properties
    from stigmergy.spec import load_for
    from stigmergy.workspace import rev_parse

    state = _state(board, config)
    task = state.task(args.id)
    spec = load_for(config.root, task.base or config.base, task.spec)
    commit = task.commit
    if not commit:
        commit = rev_parse(config.workspace_root / f"{task.id}-{task.sha}", "HEAD")
    data = properties.run(
        config,
        spec,
        commit,
        use_sandbox=not args.no_sandbox,
    )
    _emit(args, data, properties.text(data))
    return 0 if data["ok"] and not data.get("skipped") else 1


def cmd_promote(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import human, promote

    if args.apply:
        human.require()
        data = promote.apply(config)
    else:
        data = promote.status(config)
    _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") and (data.get("applied", True)) else 1


def cmd_notify(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import human, notify

    if args.send:
        human.require()
    data = notify.send(config, args.text, send_now=args.send)
    _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data["ok"] else 1


def cmd_visual(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import human, visual

    if args.run:
        human.require()
    data = visual.check(config, args.target, run_now=args.run, timeout=args.timeout)
    _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data["ok"] else 1


def cmd_feed(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from pathlib import Path

    from stigmergy import feed

    data = feed.ingest(
        config,
        board,
        Path(args.file),
        start_planner=not args.no_planner,
    )
    _emit(args, data, f"feed: {len(data)} item(s)")
    return 0 if not any(item.get("error") for item in data) else 1


def cmd_human(args: argparse.Namespace) -> int:
    from stigmergy import human

    if args.human_cmd == "init":
        path = human.init(force=args.force)
        _emit(args, {"path": str(path)}, f"human token: {path}")
        return 0
    data = human.status()
    _emit(args, data, f"human token: {data['path']} available={data['available']}")
    return 0 if data["available"] else 1


def cmd_metrics(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import metrics

    data = metrics.snapshot(config, board)
    _emit(args, data, metrics.text(data))
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import board as board_mod

    data = board_mod.worker_done(board, config, args.id, args.agent)
    _emit(args, data, f"worker.done {args.id} agent={args.agent}")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import intake

    data = intake.create_task(
        config,
        board,
        " ".join(args.idea),
        title=args.title,
        priority=args.priority,
        app=args.app,
        start_planner=not args.no_planner,
        source=args.source,
        source_id=args.source_id or "",
    )
    planner = data.get("planner") or {}
    text = (
        f"task {data['task']}\n"
        f"request {data['request']}\n"
        f"planner {planner.get('terminal') or 'not started'} {planner.get('error') or ''}\n"
        f"next: stg plan show {data['task']} && stg plan approve {data['task']}"
    )
    _emit(args, data, text)
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import intake

    if args.plan_cmd == "list":
        rows = intake.plan_list(config, board)
        lines = []
        for row in rows:
            flags = (
                f"request={int(row['request'])} "
                f"prd={int(row['prd'])} spec={int(row['spec_file'])}"
            )
            lines.append(f"{row['id']}\t{row['status']}\t{flags}\t{row['title']}")
        _emit(args, rows, "\n".join(lines) or "no plans")
        return 0
    if args.plan_cmd == "show":
        data = intake.plan_show(config, args.id)
        text = []
        for key, title in (("request", "REQUEST"), ("prd", "PRD"), ("spec", "SPEC")):
            text.append(f"===== {title} =====")
            text.append(data.get(key) or "(empty)")
        _emit(args, data, "\n".join(text))
        return 0
    if args.plan_cmd == "render":
        path = intake.render_plan(config, args.id)
        _emit(args, {"path": str(path)}, str(path))
        return 0
    if args.plan_cmd == "serve":
        from stigmergy import planui

        planui.serve(
            config,
            board,
            args.id,
            port=args.port,
            open_browser=args.open,
        )
        return 0
    if args.plan_cmd == "approve":
        from stigmergy import human

        human.require()
        data = intake.approve_plan(config, board, args.id, agent=args.agent)
        _emit(args, data, f"approved {data['task']} spec={data['spec_sha']}")
        return 0
    raise RuntimeError(f"unknown plan command: {args.plan_cmd}")


def cmd_dispatcher(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import dispatcher

    if args.all:
        from stigmergy.config import Config
        from stigmergy.log import Board
        from stigmergy.registry import load as registry_load

        projects = [
            (Config.load(Path(item["root"])), Board(Path(item["root"])))
            for item in registry_load()
        ]
        if args.watch:
            def show_global(result: dict) -> None:
                print(json.dumps(result, ensure_ascii=False), flush=True)

            dispatcher.watch_all(
                projects,
                app=args.app,
                interval=args.interval,
                on_tick=show_global,
            )
            return 0
        results = []
        for item in registry_load():
            root = Path(item["root"])
            project_config = Config.load(root)
            project_board = Board(root)
            results.append(
                {
                    "project": project_config.name,
                    **dispatcher.tick(
                        project_config,
                        project_board,
                        app=args.app,
                        auto_finish=not args.no_auto_finish,
                    ),
                }
            )
        _emit(args, results, json.dumps(results, ensure_ascii=False))
        return 0
    if args.watch:
        def show(result: dict) -> None:
            print(json.dumps(result, ensure_ascii=False), flush=True)

        dispatcher.watch(
            config,
            board,
            app=args.app,
            interval=args.interval,
            auto_finish=not args.no_auto_finish,
            on_tick=show,
        )
        return 0
    result = dispatcher.tick(
        config,
        board,
        app=args.app,
        auto_finish=not args.no_auto_finish,
    )
    _emit(args, result, json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_judge(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    from stigmergy import judge

    if args.judge_cmd == "list":
        items = judge.decisions(config)
        lines = [f"{item['id']}\t{item['date']}\t{item['question']}" for item in items]
        _emit(args, items, "\n".join(lines) or "no decisions")
        return 0
    if args.judge_cmd == "decide":
        data = judge.decide(config, " ".join(args.query))
        _emit(args, data, f"{data['outcome']}: {data['decision'] or data['reason']}")
        return 0
    if args.judge_cmd == "eval":
        data = judge.evaluate(config, Path(args.cases) if args.cases else None)
        verdict = "PASS" if data["ok"] else "FAIL"
        _emit(args, data, f"judge eval: {verdict} {data.get('correct', 0)}/{data.get('total', 0)}")
        return 0 if data["ok"] else 1
    if args.judge_cmd == "import":
        data = judge.import_file(config, Path(args.file))
        _emit(args, data, f"judge import: {data['imported']} imported, {data['errors']} errors")
        return 0 if data["errors"] == 0 else 1
    if args.judge_cmd == "add":
        item = judge.add(
            config,
            args.question,
            args.decision,
            quote=args.quote or "",
            source=args.source or "",
            date=args.date,
            scope=args.scope,
        )
        _emit(args, item, f"decision {item['id']} -> {item['path']}")
        return 0
    items = judge.search(config, " ".join(args.query), limit=args.limit)
    _emit(args, items, judge.answer_text(items))
    return 0


def cmd_lead(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy import lead

    if args.lead_cmd == "inbox":
        items = lead.inbox(board, config)
        lines = [
            f"{item['id']}\t{item['terminal'] or '-'}\t{item['question']}"
            for item in items
        ]
        _emit(args, items, "\n".join(lines) or "no blocked tasks")
        return 0
    if args.lead_cmd == "answer":
        if not args.id or not args.text:
            raise SystemExit("lead answer needs ID and --text")
        data = lead.answer(config, board, args.id, args.text, app=args.app)
        _emit(args, data, f"answered {args.id}; sent={data['sent']} terminal={data['terminal'] or '-'}")
        return 0
    data = lead.start_lead(
        config,
        board,
        app=args.app,
        space=args.space,
        force=args.force,
    )
    _emit(args, data, f"lead space={data['space']} terminal={data['terminal']} created={data['created']}")
    return 0


def cmd_wave(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    from stigmergy.wave import create_wave

    data = create_wave(
        config,
        board,
        args.goal,
        args.tasks,
        agent=args.agent,
        runner=args.runner,
        app=args.app,
    )
    text = (
        f"wave {data['wave']} space {data['space']} lead {data['lead']}\n"
        + "\n".join(
            f"worker {worker['task']} terminal {worker['terminal']}" for worker in data["workers"]
        )
    )
    _emit(args, data, text)
    return 0


def cmd_dash(args: argparse.Namespace) -> int:
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    dash.serve_forever(args.port, args.host)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if not args.all:
        _root, config, board = _ctx(args)
        data = board_mod.status(_state(board, config))
        _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    projects = registry.load()
    data = []
    for item in projects:
        root = Path(item["root"])
        board = Board(root)
        config = Config.load(root)
        data.append(board_mod.status(_state(board, config)))
    _emit(args, data, "\n".join(f"{d['project']}: {d['tasks']} tasks, {d['events']} events" for d in data))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    items = doctor_mod.checks(config, board)
    data = doctor_mod.summary(items)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for item in items:
            mark = "ok" if item["ok"] else ("FAIL" if item["required"] else "warn")
            print(f"{mark:4} {item['name']:<16} {item['detail']}")
    return 0 if data["ok"] else 1


def cmd_migrate(args: argparse.Namespace) -> int:
    if args.check:
        report = migrate_mod.check(args.check)
        _emit(args, report, json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if not args.from_path or not args.to:
        raise BoardError("pass --check PATH or --from SRC --to DST")
    report = migrate_mod.run(args.from_path, args.to, args.project or "", force=args.force)
    _emit(args, report, json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    _root, config, board = _ctx(args)
    _emit(args, board_mod.mark_paused(board, config, args.pause_cmd == "pause", args.by))
    return 0


def cmd_sandbox(args: argparse.Namespace) -> int:
    _root, config, _board = _ctx(args)
    canary = config.root / ".factory" / "sandbox-canary"
    canary.mkdir(parents=True, exist_ok=True)
    forbidden = [Path.home() / ".ssh", config.root / "data", config.root / "tracker" / "data"]
    ok, detail = sandbox.run_canary(canary, forbidden, Path.home(), sandbox.default_env())
    _emit(args, {"ok": ok, "detail": detail}, detail)
    return 0 if ok else 1


def cmd_project(args: argparse.Namespace) -> int:
    if args.project_cmd == "add":
        path = registry.add(args.name, args.root)
        print(path)
        return 0
    if args.project_cmd == "remove":
        print(registry.remove(args.name))
        return 0
    if args.project_cmd == "list":
        items = registry.load()
        _emit(args, items, "\n".join(f"{p['name']}\t{p['root']}" for p in items) or "empty")
        return 0
    raise RuntimeError(f"unknown project command: {args.project_cmd}")


def cmd_app(args: argparse.Namespace) -> int:
    from stigmergy.runner import herdr_app

    if args.app_cmd == "doctor":
        data = herdr_app.status(args.app)
        _emit(args, data, json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data["ok"] else 1
    if args.app_cmd == "list":
        items = herdr_app.spaces(args.app)
        lines = []
        for space in items:
            terminals = [
                terminal.get("terminal", "")
                for tab in space.get("tabs", [])
                for terminal in tab.get("terminals", [])
            ]
            lines.append(
                f"{space.get('name','')}\t{space.get('folder','')}\t{','.join(terminals)}"
            )
        _emit(args, items, "\n".join(lines) or "no spaces")
        return 0
    if args.app_cmd == "cleanup":
        closed = herdr_app.cleanup(args.app, args.task)
        _emit(args, {"closed": closed}, "\n".join(closed) or "nothing to close")
        return 0
    raise RuntimeError(f"unknown app command: {args.app_cmd}")


def cmd_herdr(args: argparse.Namespace) -> int:
    from stigmergy.runner import herdr

    if args.herdr_cmd == "doctor":
        data = herdr.status(args.session)
        _emit(args, data, data["text"])
        return 0 if data["ok"] else 1
    if args.herdr_cmd == "guard":
        ok, detail = herdr.guard(args.session)
        _emit(args, {"ok": ok, "detail": detail}, detail)
        return 0 if ok else 1
    if args.herdr_cmd == "list":
        items = herdr.own_workspaces(args.session)
        text = "\n".join(
            f"{item.get('label')}\t{item.get('workspace_id')}\t{item.get('agent_status')}"
            for item in items
        )
        _emit(args, items, text or "no factory workspaces")
        return 0
    if args.herdr_cmd == "cleanup":
        closed = herdr.cleanup(args.session, args.task)
        _emit(args, {"closed": closed}, "\n".join(closed) or "nothing to close")
        return 0
    if args.herdr_cmd == "install-service":
        path = herdr.install_service(args.session)
        print(path)
        if args.enable:
            import subprocess

            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            subprocess.run(["systemctl", "--user", "enable", "--now", path.name], check=False)
        return 0
    if args.herdr_cmd == "reset-session":
        moved = herdr.reset_session(args.session, yes=args.yes)
        _emit(args, {"moved": moved}, "\n".join(moved) or "nothing to do")
        return 0
    raise RuntimeError(f"unknown herdr command: {args.herdr_cmd}")


# ── parser ─────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stg", description="stigmergy dark-factory contour")
    parser.add_argument("--board", "-b", default=None, help="project root (default: walk up from cwd)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--version", action="version", version=f"stg {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .agent, .agent.toml, specs/")
    p.add_argument("--path", default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("board", help="coordination board")
    b = p.add_subparsers(dest="board_cmd", required=True)
    q = b.add_parser("add")
    q.add_argument("id")
    q.add_argument("--title")
    q.add_argument("--priority", type=int, default=2)
    q.add_argument("--deps", nargs="*")
    q.add_argument("--spec")
    q.add_argument("--risk", default="low")
    q.add_argument("--branch")
    q.add_argument("--sha")
    q.add_argument("--agent", default="stg")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("propose")
    q.add_argument("id")
    q.add_argument("--title")
    q.add_argument("--priority", type=int, default=2)
    q.add_argument("--spec")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("approve")
    q.add_argument("id")
    q.add_argument("--by", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("spec")
    q.add_argument("id")
    q.add_argument("--spec", required=True)
    q.add_argument("--agent", default="architect")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("reject")
    q.add_argument("id")
    q.add_argument("--by", required=True)
    q.add_argument("--reason", default="")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("claim")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--lease", type=int, default=1800)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("next")
    q.add_argument("--agent", default="stg")
    q.add_argument("--lease", type=int, default=1800)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("heartbeat")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--lease", type=int, default=1800)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("block")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--question", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("answer")
    q.add_argument("id")
    q.add_argument("--by", required=True)
    q.add_argument("--text", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("done")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--commit", default="")
    q.add_argument("--no-commit", action="store_true")
    q.add_argument("--evidence", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("fail")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--reason", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("note")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--text", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("pr")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--url", required=True)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("ask")
    q.add_argument("--from", dest="sender", required=True)
    q.add_argument("--to", required=True)
    q.add_argument("--text", required=True)
    q.add_argument("--hop", type=int, default=1)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("list")
    q.add_argument("--status")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("show")
    q.add_argument("id")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("log")
    q.add_argument("--limit", type=int, default=30)
    q.set_defaults(func=cmd_board)
    q = b.add_parser("status")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("audit")
    q.set_defaults(func=cmd_board)
    q = b.add_parser("render")
    q.set_defaults(func=cmd_board)

    p = sub.add_parser("spec", help="task specifications")
    s = p.add_subparsers(dest="spec_cmd", required=True)
    q = s.add_parser("new")
    q.add_argument("id")
    q.add_argument("--title")
    q.set_defaults(func=cmd_spec)
    for name in ("validate", "hash", "show"):
        q = s.add_parser(name)
        q.add_argument("path")
        q.add_argument("--base")
        q.set_defaults(func=cmd_spec)

    p = sub.add_parser("app", help="Herdr desktop app")
    ap = p.add_subparsers(dest="app_cmd", required=True)
    q = ap.add_parser("doctor")
    q.add_argument("--app", default="herdr-app")
    q.set_defaults(func=cmd_app)
    q = ap.add_parser("list")
    q.add_argument("--app", default="herdr-app")
    q.set_defaults(func=cmd_app)
    q = ap.add_parser("cleanup")
    q.add_argument("--app", default="herdr-app")
    q.add_argument("--task", default=None)
    q.set_defaults(func=cmd_app)

    p = sub.add_parser("episode", help="episode lifecycle")
    e = p.add_subparsers(dest="episode_cmd", required=True)
    q = e.add_parser("start")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--runner", default="manual", choices=["manual", "herdr", "herdr-app", "noop"])
    q.set_defaults(func=cmd_episode)
    q = e.add_parser("finish")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.add_argument("--noop", action="store_true")
    q.add_argument("--auto", action="store_true")
    q.add_argument("--no-sandbox", action="store_true")
    q.set_defaults(func=cmd_episode)
    q = e.add_parser("stop")
    q.add_argument("id")
    q.add_argument("--agent", default="stg")
    q.set_defaults(func=cmd_episode)
    q = e.add_parser("status")
    q.add_argument("id")
    q.set_defaults(func=cmd_episode)

    p = sub.add_parser("run", help="claim, workspace, episode")
    p.add_argument("id")
    p.add_argument("--agent", default="stg")
    p.add_argument("--runner", default="manual", choices=["manual", "herdr", "herdr-app", "noop"])
    p.add_argument("--auto", action="store_true")
    p.add_argument("--detach", action="store_true")
    p.add_argument("--no-sandbox", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("gate", help="run/show the gate")
    g = p.add_subparsers(dest="gate_cmd", required=True)
    q = g.add_parser("run")
    q.add_argument("id")
    q.add_argument("--episode")
    q.add_argument("--no-sandbox", action="store_true")
    q.set_defaults(func=cmd_gate)
    q = g.add_parser("show")
    q.add_argument("id")
    q.add_argument("--episode", required=True)
    q.set_defaults(func=cmd_gate)

    p = sub.add_parser("integrate", help="rebase + full gate + merge")
    p.add_argument("id")
    p.add_argument("--no-sandbox", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.set_defaults(func=cmd_integrate)

    p = sub.add_parser("merge", help="fast-forward the base branch")
    p.add_argument("id")
    p.add_argument("--agent", default="stg")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("worker", help="worker completion signal")
    w = p.add_subparsers(dest="worker_cmd", required=True)
    q = w.add_parser("done")
    q.add_argument("id")
    q.add_argument("--agent", default="pi")
    q.set_defaults(func=cmd_worker)

    p = sub.add_parser("task", help="intake: raw idea -> planner")
    p.add_argument("idea", nargs="+")
    p.add_argument("--title")
    p.add_argument("--priority", type=int, default=2)
    p.add_argument("--app", default="herdr-app")
    p.add_argument("--no-planner", action="store_true")
    p.add_argument("--source", default="human")
    p.add_argument("--source-id", default="")
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("plan", help="planner drafts and approval")
    pl = p.add_subparsers(dest="plan_cmd", required=True)
    q = pl.add_parser("list")
    q.set_defaults(func=cmd_plan)
    q = pl.add_parser("show")
    q.add_argument("id")
    q.set_defaults(func=cmd_plan)
    q = pl.add_parser("serve")
    q.add_argument("id")
    q.add_argument("--port", type=int, default=8788)
    q.add_argument("--open", action="store_true")
    q.set_defaults(func=cmd_plan)
    q = pl.add_parser("render")
    q.add_argument("id")
    q.set_defaults(func=cmd_plan)
    q = pl.add_parser("approve")
    q.add_argument("id")
    q.add_argument("--agent", default="human")
    q.set_defaults(func=cmd_plan)

    p = sub.add_parser("dispatcher", help="event-driven factory loop")
    p.add_argument("--once", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--interval", type=int)
    p.add_argument("--app", default="herdr-app")
    p.add_argument("--no-auto-finish", action="store_true")
    p.set_defaults(func=cmd_dispatcher)

    p = sub.add_parser("judge", help="decision base with citations")
    j = p.add_subparsers(dest="judge_cmd", required=True)
    q = j.add_parser("list")
    q.set_defaults(func=cmd_judge)
    q = j.add_parser("decide")
    q.add_argument("query", nargs="+")
    q.set_defaults(func=cmd_judge)
    q = j.add_parser("eval")
    q.add_argument("--cases")
    q.set_defaults(func=cmd_judge)
    q = j.add_parser("import")
    q.add_argument("--file", required=True)
    q.set_defaults(func=cmd_judge)
    q = j.add_parser("add")
    q.add_argument("question")
    q.add_argument("--decision", required=True)
    q.add_argument("--quote", default="")
    q.add_argument("--source", default="")
    q.add_argument("--date")
    q.add_argument("--scope", default="project")
    q.set_defaults(func=cmd_judge)
    q = j.add_parser("search")
    q.add_argument("query", nargs="+")
    q.add_argument("--limit", type=int, default=5)
    q.set_defaults(func=cmd_judge)

    p = sub.add_parser("lead", help="lead architect tab")
    p.add_argument("lead_cmd", nargs="?", choices=["start", "inbox", "answer"], default="start")
    p.add_argument("id", nargs="?")
    p.add_argument("--text")
    p.add_argument("--space")
    p.add_argument("--app", default="herdr-app")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_lead)

    p = sub.add_parser("wave", help="one Herdr space: lead + worker tabs")
    p.add_argument("--goal", required=True)
    p.add_argument("--tasks", nargs="+", required=True)
    p.add_argument("--agent", default="stg")
    p.add_argument("--runner", default="herdr-app", choices=["herdr-app", "herdr", "manual", "noop"])
    p.add_argument("--app", default="herdr-app")
    p.set_defaults(func=cmd_wave)

    p = sub.add_parser("dash", help="local dashboard")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_dash)

    p = sub.add_parser("critique", help="open an independent critic tab")
    p.add_argument("id")
    p.add_argument("--app", default="herdr-app")
    p.set_defaults(func=cmd_critique)

    p = sub.add_parser("verify", help="TLA+ lifecycle model + live invariants")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("retro", help="weekly learning report")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_retro)

    p = sub.add_parser("mutation", help="run mutation commands on a throwaway worktree")
    p.add_argument("id")
    p.set_defaults(func=cmd_mutation)

    p = sub.add_parser("mirror", help="mirror tasks to GitHub issues")
    mi = p.add_subparsers(dest="mirror_cmd", required=True)
    q = mi.add_parser("github")
    q.add_argument("--apply", action="store_true")
    q.set_defaults(func=cmd_mirror)

    p = sub.add_parser("usage", help="token/duration/cost usage")
    u = p.add_subparsers(dest="usage_cmd", required=True)
    q = u.add_parser("add")
    q.add_argument("--task", required=True)
    q.add_argument("--stage", required=True)
    q.add_argument("--model", default="")
    q.add_argument("--prompt-tokens", type=int, default=0)
    q.add_argument("--completion-tokens", type=int, default=0)
    q.add_argument("--duration-ms", type=int, default=0)
    q.add_argument("--cost-usd", default="0")
    q.set_defaults(func=cmd_usage)

    p = sub.add_parser("learn", help="weekly learning proposals")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("persona", help="nightly cited-decision ingest")
    pe = p.add_subparsers(dest="persona_cmd", required=True)
    q = pe.add_parser("ingest")
    q.add_argument("--file", required=True)
    q.set_defaults(func=cmd_persona)

    p = sub.add_parser("schedule", help="weekly/nightly systemd timers")
    sc = p.add_subparsers(dest="schedule_cmd", required=True)
    q = sc.add_parser("install")
    q.add_argument("--enable", action="store_true")
    q.add_argument("--learn-calendar", default="Mon 09:00")
    q.add_argument("--persona-calendar", default="03:30")
    q.set_defaults(func=cmd_schedule)
    q = sc.add_parser("status")
    q.set_defaults(func=cmd_schedule)

    p = sub.add_parser("model", help="stage routing and model benchmarks")
    mo = p.add_subparsers(dest="model_cmd", required=True)
    q = mo.add_parser("route")
    q.add_argument("--stage", required=True, choices=["worker", "planner", "critic", "lead", "judge"])
    q.set_defaults(func=cmd_model)
    q = mo.add_parser("list")
    q.set_defaults(func=cmd_model)
    q = mo.add_parser("bench")
    q.add_argument("--cases", required=True)
    q.add_argument("--model", required=True)
    q.add_argument("--command")
    q.add_argument("--timeout", type=int, default=120)
    q.set_defaults(func=cmd_model)

    p = sub.add_parser("pbt", help="property seeds + live-model check")
    p.add_argument("id")
    p.add_argument("--no-sandbox", action="store_true")
    p.set_defaults(func=cmd_pbt)

    p = sub.add_parser("promote", help="dry-run/apply dev → protected main")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("notify", help="Telegram/webhook notification")
    p.add_argument("--text", required=True)
    p.add_argument("--send", action="store_true")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("visual", help="visual/computer acceptance adapter")
    v = p.add_subparsers(dest="visual_cmd", required=True)
    q = v.add_parser("check")
    q.add_argument("--target", required=True)
    q.add_argument("--run", action="store_true")
    q.add_argument("--timeout", type=int, default=None)
    q.set_defaults(func=cmd_visual)

    p = sub.add_parser("feed", help="proactive JSONL inbox")
    p.add_argument("--file", required=True)
    p.add_argument("--no-planner", action="store_true")
    p.set_defaults(func=cmd_feed)

    p = sub.add_parser("human", help="human authorization token")
    h = p.add_subparsers(dest="human_cmd", required=True)
    q = h.add_parser("init")
    q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_human)
    q = h.add_parser("status")
    q.set_defaults(func=cmd_human)

    p = sub.add_parser("metrics", help="factory metrics and actor audit")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("status", help="project status")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="environment readiness")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("migrate", help="validate/copy a legacy board")
    p.add_argument("--check", nargs="?", const="", default=None)
    p.add_argument("--from", dest="from_path", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--project", default="")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("pause", help="pause the factory")
    p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_pause, pause_cmd="pause")
    p = sub.add_parser("resume", help="resume the factory")
    p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_pause, pause_cmd="resume")

    p = sub.add_parser("sandbox", help="sandbox checks")
    sb = p.add_subparsers(dest="sandbox_cmd", required=True)
    q = sb.add_parser("check")
    q.set_defaults(func=cmd_sandbox)

    p = sub.add_parser("project", help="global project registry")
    pr = p.add_subparsers(dest="project_cmd", required=True)
    q = pr.add_parser("add")
    q.add_argument("name")
    q.add_argument("--root", default=".")
    q.set_defaults(func=cmd_project)
    q = pr.add_parser("remove")
    q.add_argument("name")
    q.set_defaults(func=cmd_project)
    q = pr.add_parser("list")
    q.set_defaults(func=cmd_project)

    p = sub.add_parser("herdr", help="Herdr adapter")
    h = p.add_subparsers(dest="herdr_cmd", required=True)
    q = h.add_parser("doctor")
    q.add_argument("--session", default="factory")
    q.set_defaults(func=cmd_herdr)
    q = h.add_parser("guard")
    q.add_argument("--session", default="factory")
    q.set_defaults(func=cmd_herdr)
    q = h.add_parser("install-service")
    q.add_argument("--session", default="factory")
    q.add_argument("--enable", action="store_true")
    q.set_defaults(func=cmd_herdr)
    q = h.add_parser("list")
    q.add_argument("--session", default="factory")
    q.set_defaults(func=cmd_herdr)
    q = h.add_parser("cleanup")
    q.add_argument("--session", default="factory")
    q.add_argument("--task", default=None)
    q.set_defaults(func=cmd_herdr)
    q = h.add_parser("reset-session")
    q.add_argument("--session", default="factory")
    q.add_argument("--yes", action="store_true")
    q.set_defaults(func=cmd_herdr)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_flag = "--json" in raw
    raw = [item for item in raw if item != "--json"]
    board_val: str | None = None
    cleaned: list[str] = []
    i = 0
    while i < len(raw):
        item = raw[i]
        if item in ("--board", "-b") and i + 1 < len(raw):
            board_val = raw[i + 1]
            i += 2
            continue
        if item.startswith("--board="):
            board_val = item.split("=", 1)[1]
            i += 1
            continue
        cleaned.append(item)
        i += 1
    parser = build_parser()
    args = parser.parse_args(cleaned)
    if json_flag:
        args.json = True
    if board_val:
        args.board = board_val
    if getattr(args, "check", None) == "":
        args.check = str(Path.cwd())
    try:
        return int(args.func(args))
    except (BoardError, SpecError, RuntimeError, KeyError, OSError) as exc:
        print(f"stg: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
