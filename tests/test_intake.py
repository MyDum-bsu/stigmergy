from __future__ import annotations

from pathlib import Path

import pytest

from stigmergy import intake
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState
from stigmergy.spec import SpecError


def _spec(task_id: str) -> str:
    return f"""---
id: {task_id}
title: Intake fixture
risk: low
deps: []
allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
gate_inputs: []
dod: python3 test_gate.py
---

## Intent
Fixture.
"""


def test_create_task_writes_request_and_planner(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    calls = {}

    monkeypatch.setattr(
        intake.herdr_app,
        "ensure_space",
        lambda app, name, folder: {"space": "sp0", "tabs": []},
    )

    def fake_tab(app, space, name, folder, agent, task, agent_args=None, argv=None):
        calls.update(space=space, name=name, folder=str(folder), agent_args=agent_args)
        return {"space": space, "terminal": "t-plan"}

    monkeypatch.setattr(intake.herdr_app, "create_tab", fake_tab)
    data = intake.create_task(config, board, "Добавить виджет в трекер")
    task = ProjectState.from_events(board.read()).task(data["task"])
    assert task.status == "queued"
    assert intake.paths_for(config, data["task"])["request"].exists()
    assert not intake.paths_for(config, data["task"])["spec"].exists()
    assert calls["name"] == f"Plan · {data['task']}"
    assert calls["agent_args"] == intake.PLANNER_TOOLS
    assert data["planner"]["terminal"] == "t-plan"


def test_approve_plan_commits_and_attaches(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app,
        "ensure_space",
        lambda app, name, folder: {"space": "sp0", "tabs": []},
    )
    monkeypatch.setattr(
        intake.herdr_app,
        "create_tab",
        lambda *args, **kwargs: {"space": "sp0", "terminal": "t-plan"},
    )
    data = intake.create_task(config, board, "Добавить виджет")
    task_id = data["task"]
    paths = intake.paths_for(config, task_id)
    paths["spec"].write_text(_spec(task_id), encoding="utf-8")
    result = intake.approve_plan(config, board, task_id)
    assert result["spec"] == f"specs/{task_id}.md"
    task = ProjectState.from_events(board.read()).task(task_id)
    assert task.spec == f"specs/{task_id}.md"
    assert task.spec_sha
    log = intake._git(config.integration_root, "log", "-1", "--pretty=%s").stdout
    assert f"plan({task_id})" in log


def test_approve_rejects_invalid_draft(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app,
        "ensure_space",
        lambda app, name, folder: {"space": "sp0", "tabs": []},
    )
    monkeypatch.setattr(
        intake.herdr_app,
        "create_tab",
        lambda *args, **kwargs: {"space": "sp0", "terminal": "t-plan"},
    )
    task_id = intake.create_task(config, board, "Добавить виджет")["task"]
    paths = intake.paths_for(config, task_id)
    paths["spec"].write_text("---\nid: bad\n---\n", encoding="utf-8")
    with pytest.raises(SpecError):
        intake.approve_plan(config, board, task_id)


def test_plan_show_and_list(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app,
        "ensure_space",
        lambda app, name, folder: {"space": "sp0", "tabs": []},
    )
    monkeypatch.setattr(
        intake.herdr_app,
        "create_tab",
        lambda *args, **kwargs: {"space": "sp0", "terminal": "t-plan"},
    )
    task_id = intake.create_task(config, board, "Добавить виджет")["task"]
    shown = intake.plan_show(config, task_id)
    assert "Добавить виджет" in shown["request"]
    rows = intake.plan_list(config, board)
    assert any(row["id"] == task_id and row["request"] for row in rows)


def test_source_id_is_idempotent(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app, "ensure_space", lambda app, name, folder: {"space": "sp0", "tabs": []}
    )
    monkeypatch.setattr(
        intake.herdr_app, "create_tab", lambda *args, **kwargs: {"space": "sp0", "terminal": "t"}
    )
    first = intake.create_task(
        config, board, "Инцидент из чата", source="telegram", source_id="msg-1"
    )
    second = intake.create_task(
        config, board, "Инцидент из чата", source="telegram", source_id="msg-1"
    )
    assert second.get("duplicate") is True
    assert second["task"] == first["task"]


def test_render_plan_writes_html(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    monkeypatch.setattr(
        intake.herdr_app, "ensure_space", lambda app, name, folder: {"space": "sp0", "tabs": []}
    )
    monkeypatch.setattr(
        intake.herdr_app, "create_tab", lambda *args, **kwargs: {"space": "sp0", "terminal": "t"}
    )
    task_id = intake.create_task(config, board, "План")["task"]
    path = intake.render_plan(config, task_id)
    assert path.exists()
    assert "stg plan approve" in path.read_text(encoding="utf-8")
