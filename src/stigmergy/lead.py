"""Lead architect: one persistent Herdr tab for the human, workers as tabs."""

from __future__ import annotations

from stigmergy import board as board_mod
from stigmergy.config import Config
from stigmergy.log import Board, BoardError
from stigmergy.model import ProjectState
from stigmergy.runner import herdr_app

LEAD_TAB = "Lead"
LEAD_AGENT_ARGS = ["--exclude-tools", "edit,write"]


def lead_prompt(config: Config, space: str) -> str:
    return f"""You are the lead architect of the stigmergy factory for project {config.name}.

The human talks only to you. You do not write code, do not edit files in the
repo, and do not merge: the contour commits, gates and merges. Your tools are
the shell (stg, hc) and reads.

Startup rule: do nothing until the human writes a task or you receive a
blocked-worker notice. Do not scan the board, old tasks, worktrees or git
history on startup. Reply once with "Lead ready; жду задачу" and wait.

Board root: {config.root}
Project space: {space}

Always prefix stg commands with `--board {config.root}`. Do not rely on the
current directory, especially after `cd`: a worktree has no board of its own.

Human task intake (the human does not create branches or specs):
  stg task "<raw idea>"
For a tiny, reversible, one-file change use:
  stg task --quick "<raw idea>"
--quick writes a compact fast-lane spec; the dispatcher may policy-approve it
without the human. Otherwise the normal plan needs one human approve:
  stg plan show <ID>
  stg plan approve <ID>
Never run `plan approve` yourself: it is human-only and will fail without the
token. If a fast-lane task is not auto-approved, report why briefly; do not
retry the human command.
The dispatcher starts approved tasks; a worker opens as a tab in this space
and owns its worktree. Never edit its worktree and never run the same task twice.

Scope: only this project root. If the request points outside the repository,
say so in one line and do not inspect/change the other repository.

Workers are forbidden to ask the human. When a worker is blocked it writes
task.blocked and stops. Inspect the lead inbox:
  stg lead inbox
Before answering, search the decisions with citations:
  stg judge search "<question>"
Use only a decision with quote/source/date. If nothing matches, say
"в базе решений нет" and escalate to the human. Answer one blocked worker:
  stg lead answer <ID> --text "<decision>"
That records the answer on the board and sends it to the worker terminal.

Escalate to the human only for: a criterion/spec change, a high-risk merge,
or an irreversible action. Everything else decide yourself and report briefly.
The gate is the verdict, not you. Do not call `stg board done` yourself.

When the human asks for status, answer with: active tasks, blocked questions,
last gate result, and what you need from them. Keep it short. Do not run a
status investigation unless asked.
"""


def _space_id(space: dict) -> str:
    return str(space.get("space") or space.get("id") or "")


def _find_tab(space: dict, name: str) -> dict | None:
    for tab in space.get("tabs") or []:
        if str(tab.get("name", "")) == name:
            return tab
    return None


def _tab_terminal(tab: dict | None) -> str:
    if not tab:
        return ""
    for terminal in tab.get("terminals") or []:
        if isinstance(terminal, dict):
            return str(terminal.get("terminal", ""))
        return str(terminal)
    return str(tab.get("terminal", ""))


def _tab_id(tab: dict) -> str:
    return str(tab.get("tab") or tab.get("id") or "")


def start_lead(
    config: Config,
    board: Board,
    *,
    app: str = "herdr-app",
    space: str | None = None,
    tab_name: str = LEAD_TAB,
    force: bool = False,
) -> dict:
    """Create (or return) the persistent lead tab in the project space."""
    space_name = space or config.space
    project_space = herdr_app.ensure_space(app, space_name, config.root)
    space_id = _space_id(project_space)
    if not space_id:
        raise BoardError(f"space {space_name!r} not found/created")
    if not force and tab_name != LEAD_TAB:
        tab = _find_tab(project_space, tab_name)
        if tab is not None:
            return {
                "space": space_id,
                "tab": _tab_id(tab),
                "terminal": _tab_terminal(tab),
                "created": False,
            }
    argv = None
    from stigmergy import routing, sandbox

    lead_args = routing.args(config, "lead", LEAD_AGENT_ARGS)
    if config.runner.get("sandbox", True) and sandbox.bwrap_available():
        argv = sandbox.lead_argv(
            config.root,
            str(config.runner.get("agent", "pi")),
            lead_args,
        )
    prompt = lead_prompt(config, space_name)
    if not force and tab_name == LEAD_TAB:
        outcome = herdr_app.ensure_lead_tab(
            app=app,
            space=space_name,
            folder=config.root,
            agent=str(config.runner.get("agent", "pi")),
            task=prompt,
            agent_args=lead_args,
            argv=argv,
        )
        if not outcome["created"]:
            found = outcome["tab"]
            return {
                "space": space_id,
                "tab": _tab_id(found),
                "terminal": _tab_terminal(found),
                "created": False,
            }
        created = outcome["tab"]
    else:
        created = herdr_app.create_tab(
            app,
            space_id,
            tab_name,
            config.root,
            "pi",
            prompt,
            agent_args=lead_args,
            argv=argv,
        )
    terminal = str(created.get("terminal", ""))
    board.append(
        "lead.started",
        {"kind": "agent", "name": "lead"},
        {
            "project.name": config.name,
            "lead.space": space_id,
            "lead.tab": _tab_id(created),
            "lead.handle": terminal,
        },
        "lead started",
    )
    return {
        "space": space_id,
        "tab": _tab_id(created),
        "terminal": terminal,
        "created": True,
    }


def runner_handle(board: Board, task_id: str) -> str:
    """Latest worker terminal for a task from episode events."""
    for event in reversed(board.read()):
        attrs = event.get("attributes") or {}
        if attrs.get("task.id") != task_id:
            continue
        if event.get("action") not in {"episode.started", "episode.finished"}:
            continue
        handle = str(attrs.get("runner.handle", "") or "")
        if handle:
            return handle
    return ""


def inbox(board: Board, config: Config) -> list[dict]:
    state = ProjectState.from_events(board.read(), project=config.name)
    items: list[dict] = []
    for task in state.all():
        if task.status != "blocked":
            continue
        items.append(
            {
                "id": task.id,
                "title": task.title,
                "risk": task.risk,
                "question": task.question,
                "terminal": runner_handle(board, task.id),
            }
        )
    return items


def answer(
    config: Config,
    board: Board,
    task_id: str,
    text: str,
    *,
    app: str = "herdr-app",
) -> dict:
    """Lead answer: record it, then resume the worker's terminal."""
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    if task.status != "blocked":
        raise BoardError(f"task {task_id} is {task.status}, not blocked")
    event = board_mod.answer(board, config, task_id, "lead", text)
    terminal = runner_handle(board, task_id)
    sent = False
    detail = ""
    if terminal:
        sent, detail = herdr_app.send_paused(
            terminal,
            f"Лид: {text}\n\nПродолжай работу по спеке.",
        )
    return {
        "task": task_id,
        "answer": text,
        "terminal": terminal,
        "sent": sent,
        "detail": detail,
        "event": event,
    }
