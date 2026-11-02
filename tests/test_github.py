from __future__ import annotations

import json
from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import github
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def _fake_gh(monkeypatch, *, comments=None, issue_comments=None, pr_url="https://github.com/acme/repo/pull/3"):
    issue_comments = issue_comments if issue_comments is not None else []
    calls: list[tuple[str, ...]] = []

    def fake(config, *args, input_text=None):
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return 0, json.dumps(
                [
                    {
                        "number": 7,
                        "title": "Fix YAML",
                        "url": "https://github.com/acme/repo/issues/7",
                        "state": "OPEN",
                        "labels": [{"name": "stigmergy"}],
                    }
                ]
            ), ""
        if args[:2] == ("issue", "view"):
            return 0, json.dumps(
                {
                    "number": 7,
                    "title": "Fix YAML",
                    "body": "one line",
                    "url": "https://github.com/acme/repo/issues/7",
                    "state": "OPEN",
                    "labels": [{"name": "stigmergy"}],
                    "comments": issue_comments,
                }
            ), ""
        if args[:2] == ("issue", "comment"):
            return 0, "https://github.com/acme/repo/issues/7#issuecomment-1\n", ""
        if args[:2] == ("pr", "create"):
            return 0, pr_url + "\n", ""
        if args[:2] == ("pr", "checks"):
            return 0, json.dumps([{"name": "ci", "state": "SUCCESS", "conclusion": "SUCCESS"}]), ""
        return 1, "", "unexpected gh call"

    monkeypatch.setattr(github, "_gh", fake)
    return calls


def test_sync_imports_issue_and_links_task(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    config.raw["github"] = {"repo": "acme/repo"}
    _fake_gh(monkeypatch)
    data = github.sync(config, board, apply=True, include_push=False, start_planner=False)
    assert data["ok"] and data["imported"] == 1
    links = github.links(board)
    assert 7 in links
    task_id = links[7]["task"]
    assert ProjectState.from_events(board.read(), project=config.name).task(task_id).title == "Fix YAML"
    assert Path(repo / ".factory" / "integration" / "requests" / f"{task_id}.md").exists()


def test_comment_in_dedupes_and_comment_out_is_idempotent(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    config.raw["github"] = {"repo": "acme/repo"}
    _fake_gh(
        monkeypatch,
        issue_comments=[
            {
                "id": "c1",
                "author": {"login": "alice"},
                "body": "please use quotes",
                "url": "https://github.com/acme/repo/issues/7#issuecomment-1",
            }
        ],
    )
    first = github.sync(config, board, apply=True, include_push=False, start_planner=False)
    assert first["ok"] and first["imported"] == 1
    second = github.sync(config, board, apply=True, include_push=False, start_planner=False)
    assert second["comments_in"] == 1
    assert len([e for e in board.read() if e["action"] == "github.comment.in"]) == 1
    third = github.sync(config, board, apply=True, include_push=False, start_planner=False)
    assert third["comments_in"] == 0

    task_id = github.links(board)[7]["task"]
    board_mod.note(board, config, task_id, "lead", "fixed in dev")
    fourth = github.sync(config, board, apply=True, include_import=False, include_push=True, start_planner=False)
    assert fourth["comments_out"] == 1
    fifth = github.sync(config, board, apply=True, include_import=False, include_push=True, start_planner=False)
    assert fifth["comments_out"] == 0


def test_pr_create_and_checks(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    config.raw["github"] = {"repo": "acme/repo"}
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    _fake_gh(monkeypatch)
    data = github.open_pr(config, board, "T1")
    assert data["url"].endswith("/pull/3")
    checks = github.checks(config, board, "T1")
    assert checks["pr"] == 3 and checks["checks"][0]["conclusion"] == "SUCCESS"
