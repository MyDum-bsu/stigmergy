"""GitHub communication adapter.

The board remains the source of truth. GitHub issues and pull requests are a
communication surface:

* an issue labelled for stigmergy becomes an intake request;
* issue comments are recorded as ``github.comment.in`` events;
* board notes/answers are pushed as issue comments by ``sync --apply``;
* PRs are opened from task branches and their checks are read back.

Every write is behind ``sync --apply`` / ``comment`` / ``pr`` and the CLI asks
for the human token. Tests replace ``_gh`` and never touch the network.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board, BoardError
from stigmergy.model import ProjectState


def _section(config: Config) -> dict[str, Any]:
    return config.section("github")


def _gh(config: Config, *args: str, input_text: str | None = None) -> tuple[int, str, str]:
    gh = shutil.which("gh")
    if not gh:
        return 127, "", "gh not installed"
    proc = subprocess.run(
        [gh, *args],
        cwd=str(config.root),
        text=True,
        capture_output=True,
        input=input_text,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _json(config: Config, *args: str) -> tuple[Any, str]:
    code, out, err = _gh(config, *args)
    if code != 0:
        return None, (err or out).strip()[:1000]
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return None, f"non-JSON gh output: {out[:500]}"


def repo(config: Config) -> str:
    explicit = str(_section(config).get("repo") or "").strip()
    if explicit:
        return explicit
    data, err = _json(config, "repo", "view", "--json", "nameWithOwner")
    if not data:
        raise BoardError(f"cannot resolve GitHub repo: {err}")
    return str(data["nameWithOwner"])


def _labels(issue: dict[str, Any]) -> set[str]:
    out = set()
    for label in issue.get("labels") or []:
        if isinstance(label, dict):
            out.add(str(label.get("name", "")))
        else:
            out.add(str(label))
    return out


def _task_from_labels(issue: dict[str, Any]) -> str:
    for label in _labels(issue):
        if label.startswith("stg:"):
            return label[4:]
    return ""


def _issue_number(issue: dict[str, Any]) -> int:
    return int(issue.get("number") or 0)


def links(board: Board) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for event in board.read():
        if event.get("action") != "github.issue.linked":
            continue
        attrs = event.get("attributes") or {}
        number = int(attrs.get("github.issue.number") or 0)
        if not number:
            continue
        out[number] = {
            "number": number,
            "task": str(attrs.get("task.id") or ""),
            "url": str(attrs.get("github.issue.url") or ""),
            "repo": str(attrs.get("github.repo") or ""),
            "seq": int(event.get("seq") or 0),
        }
    return out


def link(
    config: Config,
    board: Board,
    task_id: str,
    number: int,
    url: str,
    *,
    repo_name: str = "",
) -> dict[str, Any]:
    return board.append(
        "github.issue.linked",
        {"kind": "agent", "name": "github"},
        {
            "project.name": config.name,
            "task.id": task_id,
            "github.issue.number": number,
            "github.issue.url": url,
            "github.repo": repo_name or "",
        },
        f"link {task_id} ↔ #{number}",
    )


def task_for_issue(board: Board, number: int) -> str:
    return str(links(board).get(number, {}).get("task", ""))


def issue_for_task(board: Board, task_id: str) -> dict[str, Any] | None:
    for item in links(board).values():
        if item["task"] == task_id:
            return item
    return None


def fetch_issues(config: Config, *, state: str = "open") -> list[dict[str, Any]]:
    label = str(_section(config).get("label") or "stigmergy")
    data, err = _json(
        config,
        "issue",
        "list",
        "--label",
        label,
        "--state",
        state,
        "--limit",
        "100",
        "--json",
        "number,title,url,state,labels,author",
    )
    if data is None:
        raise BoardError(f"gh issue list failed: {err}")
    issues: list[dict[str, Any]] = []
    for item in data:
        number = int(item.get("number") or 0)
        if not number:
            continue
        detail, detail_err = _json(
            config,
            "issue",
            "view",
            str(number),
            "--json",
            "number,title,body,url,state,labels,comments,author",
        )
        if detail is None:
            raise BoardError(f"gh issue view #{number} failed: {detail_err}")
        issues.append(detail)
    return issues


def _seen_comments(board: Board, issue: int) -> set[str]:
    seen = set()
    for event in board.read():
        if event.get("action") not in {"github.comment.in", "github.comment.out"}:
            continue
        attrs = event.get("attributes") or {}
        if int(attrs.get("github.issue.number") or 0) != issue:
            continue
        cid = attrs.get("github.comment.id")
        if cid:
            seen.add(str(cid))
    return seen


def _outbound_candidates(config: Config, board: Board) -> list[dict[str, Any]]:
    links_by_task = {item["task"]: item for item in links(board).values()}
    posted = set()
    for event in board.read():
        if event.get("action") == "github.comment.out":
            attrs = event.get("attributes") or {}
            if attrs.get("source.seq"):
                posted.add(str(attrs["source.seq"]))
    out: list[dict[str, Any]] = []
    for event in board.read():
        action = event.get("action")
        if action not in {"task.note", "task.answered"}:
            continue
        attrs = event.get("attributes") or {}
        task_id = str(attrs.get("task.id") or "")
        link_item = links_by_task.get(task_id)
        if not link_item or str(event.get("seq")) in posted:
            continue
        if int(event.get("seq") or 0) <= int(link_item.get("seq") or 0):
            continue
        body = str(event.get("body") or attrs.get("answer") or "").strip()
        if not body:
            continue
        out.append(
            {
                "task": task_id,
                "number": link_item["number"],
                "body": body[:4000],
                "source_seq": str(event.get("seq")),
                "kind": action,
            }
        )
    return out


def _plan_sync(
    config: Config,
    board: Board,
    *,
    include_import: bool,
    include_push: bool,
    repo_name: str,
) -> dict[str, Any]:
    state = ProjectState.from_events(board.read(), project=config.name)
    linked = links(board)
    actions: list[dict[str, Any]] = []
    for issue in fetch_issues(config):
        number = _issue_number(issue)
        task_id = str(linked.get(number, {}).get("task") or _task_from_labels(issue))
        known = bool(task_id and task_id in state.tasks)
        if not known:
            actions.append(
                {
                    "action": "import" if include_import else "skip",
                    "issue": number,
                    "title": issue.get("title", ""),
                    "body": issue.get("body", ""),
                    "url": issue.get("url", ""),
                    "author": str((issue.get("author") or {}).get("login") or ""),
                }
            )
            continue
        if number not in linked:
            actions.append(
                {
                    "action": "link",
                    "issue": number,
                    "task": task_id,
                    "url": issue.get("url", ""),
                }
            )
        seen = _seen_comments(board, number)
        for comment in issue.get("comments") or []:
            cid = str(comment.get("id") or comment.get("databaseId") or "")
            if not cid or cid in seen:
                continue
            actions.append(
                {
                    "action": "comment-in",
                    "issue": number,
                    "task": task_id,
                    "comment": cid,
                    "author": str((comment.get("author") or {}).get("login") or ""),
                    "body": str(comment.get("body") or "")[:4000],
                }
            )
    if include_push:
        for item in _outbound_candidates(config, board):
            actions.append({"action": "comment-out", **item})
    return {"actions": actions, "repo": repo_name}


def sync(
    config: Config,
    board: Board,
    *,
    apply: bool = False,
    include_import: bool = True,
    include_push: bool = True,
    start_planner: bool = True,
) -> dict[str, Any]:
    repo_name = repo(config)
    plan = _plan_sync(
        config,
        board,
        include_import=include_import,
        include_push=include_push,
        repo_name=repo_name,
    )
    actions = plan["actions"]
    if not apply:
        return {
            "ok": True,
            "dry_run": True,
            "repo": repo_name,
            "actions": actions,
            "imported": 0,
            "comments_in": 0,
            "comments_out": 0,
        }
    imported = comments_in = comments_out = 0
    errors: list[str] = []
    for action in actions:
        kind = action["action"]
        if kind == "import":
            from stigmergy import source

            number = int(action["issue"])
            trigger = source.Trigger(
                source="github",
                trigger_id=f"{repo_name}#{number}",
                thread=f"github:{repo_name}#{number}",
                actor=str(action.get("author") or "github"),
                title=str(action["title"]),
                text=(
                    f"GitHub issue #{number}: {action['title']}\n\n"
                    f"{action.get('body') or ''}\n\n"
                    f"{action['url']}\n\n"
                    "This request came from GitHub; the issue is a mirror, the board is the source of truth."
                ),
                kind="issue",
                url=str(action["url"]),
            )
            github_cfg = config.section("github")
            result = source.ingest(
                config,
                board,
                trigger,
                accept_mode=str(github_cfg.get("accept_mode") or "auto"),
                allowed_actors=tuple(str(x) for x in (github_cfg.get("allowed_users") or [])),
                start_planner=start_planner,
            )
            task_id = str(result.get("task") or "")
            if task_id:
                link(config, board, task_id, number, str(action["url"]), repo_name=repo_name)
                imported += 1
        elif kind == "link":
            link(
                config,
                board,
                str(action["task"]),
                int(action["issue"]),
                str(action["url"]),
                repo_name=repo_name,
            )
        elif kind == "comment-in":
            board.append(
                "github.comment.in",
                {"kind": "agent", "name": f"github:{action.get('author') or 'unknown'}"},
                {
                    "project.name": config.name,
                    "task.id": action["task"],
                    "github.issue.number": int(action["issue"]),
                    "github.comment.id": str(action["comment"]),
                    "github.author": str(action.get("author") or ""),
                },
                str(action.get("body") or ""),
            )
            comments_in += 1
        elif kind == "comment-out":
            number = int(action["number"])
            code, out, err = _gh(
                config,
                "issue",
                "comment",
                str(number),
                "--body",
                str(action["body"]),
            )
            if code != 0:
                errors.append(f"#{number}: {(err or out).strip()[:300]}")
                continue
            board.append(
                "github.comment.out",
                {"kind": "agent", "name": "github"},
                {
                    "project.name": config.name,
                    "task.id": action["task"],
                    "github.issue.number": number,
                    "github.comment.url": out.strip().splitlines()[-1] if out.strip() else "",
                    "source.seq": str(action["source_seq"]),
                },
                str(action["body"]),
            )
            comments_out += 1
    return {
        "ok": not errors,
        "dry_run": False,
        "repo": repo_name,
        "imported": imported,
        "comments_in": comments_in,
        "comments_out": comments_out,
        "errors": errors,
        "actions": actions,
    }


def comment(config: Config, board: Board, task_id: str, text: str) -> dict[str, Any]:
    link_item = issue_for_task(board, task_id)
    if not link_item:
        raise BoardError(f"task {task_id} has no linked GitHub issue")
    number = int(link_item["number"])
    code, out, err = _gh(config, "issue", "comment", str(number), "--body", text)
    if code != 0:
        raise BoardError(f"gh issue comment failed: {(err or out).strip()[:500]}")
    event = board.append(
        "github.comment.out",
        {"kind": "human", "name": "human"},
        {
            "project.name": config.name,
            "task.id": task_id,
            "github.issue.number": number,
            "github.comment.url": out.strip().splitlines()[-1] if out.strip() else "",
        },
        text,
    )
    return {"task": task_id, "issue": number, "url": out.strip(), "event": event}


def _pr_number(board: Board, task_id: str) -> int:
    for event in reversed(board.read()):
        attrs = event.get("attributes") or {}
        if event.get("action") != "task.pr" or attrs.get("task.id") != task_id:
            continue
        url = str(attrs.get("pr.url") or "")
        match = re.search(r"/pull/(\d+)", url)
        if match:
            return int(match.group(1))
    return 0


def open_pr(
    config: Config,
    board: Board,
    task_id: str,
    *,
    push: bool = False,
    draft: bool = False,
) -> dict[str, Any]:
    state = ProjectState.from_events(board.read(), project=config.name)
    task = state.task(task_id)
    if not task.branch:
        raise BoardError(f"task {task_id} has no branch")
    if push:
        proc = subprocess.run(
            ["git", "-C", str(config.root), "push", "-u", "origin", task.branch],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise BoardError(f"git push failed: {(proc.stderr or proc.stdout).strip()[:500]}")
    body = (
        f"Stigmergy task: `{task.id}`\n\n"
        f"Spec: `{task.spec or '-'}`\n"
        f"Risk: `{task.risk}`\n"
        f"Gate: `{task.evidence or 'pending'}`\n\n"
        "The stigmergy gate is the verdict; GitHub checks are communication."
    )
    args = [
        "pr",
        "create",
        "--base",
        config.base,
        "--head",
        task.branch,
        "--title",
        f"[stg] {task.id}: {task.title}",
        "--body",
        body,
    ]
    if draft:
        args.append("--draft")
    code, out, err = _gh(config, *args)
    if code != 0:
        raise BoardError(f"gh pr create failed: {(err or out).strip()[:1000]}")
    url = out.strip().splitlines()[-1]
    from stigmergy import board as board_mod

    event = board_mod.pr(board, config, task_id, "github", url)
    return {"task": task_id, "url": url, "branch": task.branch, "event": event}


def checks(config: Config, board: Board, task_id: str) -> dict[str, Any]:
    number = _pr_number(board, task_id)
    if not number:
        raise BoardError(f"task {task_id} has no linked PR")
    data, err = _json(config, "pr", "checks", str(number), "--json", "name,state,conclusion,detailsUrl")
    if data is None:
        raise BoardError(f"gh pr checks failed: {err}")
    return {"task": task_id, "pr": number, "checks": data}


def status(config: Config, board: Board) -> dict[str, Any]:
    repo_name = repo(config)
    linked = links(board)
    return {
        "repo": repo_name,
        "linked": list(linked.values()),
        "open_issues": len(fetch_issues(config)),
    }
