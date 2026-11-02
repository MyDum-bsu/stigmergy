from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import dispatcher
from stigmergy.config import Config
from stigmergy.log import Board


def test_auto_judge_answers_and_resumes(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.started",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "runner.handle": "t1"},
    )
    board_mod.block(board, config, "T1", "pi", "Куда деплоить сервис?")
    decisions = repo / "decisions"
    decisions.mkdir()
    (decisions / "dec.md").write_text(
        "---\nid: dec\ndate: 2026-11-02\nscope: project\n"
        "question: Куда деплоить сервис?\ndecision: Только через поезд в прод\n"
        "quote: цитата\nsource: AGENTS.md\n---\n",
        encoding="utf-8",
    )
    config.raw["dispatcher"] = {"auto_judge": True}
    monkeypatch.setattr(dispatcher.herdr_app, "status", lambda app: {"ok": True})
    sent = []
    monkeypatch.setattr(
        dispatcher.herdr_app,
        "send_paused",
        lambda handle, text: (sent.append((handle, text)) or (True, "")),
    )
    result = dispatcher.tick(config, board, auto_finish=False, state={})
    assert result["actions"][0]["action"] == "judge_answer"
    assert sent and sent[0][0] == "t1"
    assert dispatcher.state_of(board, "fixture").task("T1").answer_by == "judge"
