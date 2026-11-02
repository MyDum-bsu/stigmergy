from __future__ import annotations

import json
from pathlib import Path

from stigmergy import feed
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def test_feed_is_idempotent(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    path = repo / "inbox.jsonl"
    path.write_text(
        json.dumps({"source": "chat", "id": "m1", "idea": "Добавить виджет", "title": "Виджет"}) + "\n"
        + json.dumps({"source": "chat", "id": "m1", "idea": "Добавить виджет", "title": "Виджет"}) + "\n",
        encoding="utf-8",
    )
    data = feed.ingest(config, board, path, start_planner=False)
    assert len(data) == 2 and data[0].get("duplicate") is not True
    assert data[1].get("duplicate") is True
    assert len(ProjectState.from_events(board.read()).all()) == 1
