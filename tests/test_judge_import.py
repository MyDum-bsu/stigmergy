from __future__ import annotations

import json
from pathlib import Path

from stigmergy import judge
from stigmergy.config import Config


def test_import_decisions(repo: Path) -> None:
    path = repo / "import.jsonl"
    path.write_text(
        json.dumps(
            {
                "question": "Куда деплоить?",
                "decision": "Через поезд",
                "quote": "цитата",
                "source": "x",
                "date": "2026-11-02",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data = judge.import_file(Config.load(repo), path)
    assert data["imported"] == 1
    assert judge.decisions(Config.load(repo))
