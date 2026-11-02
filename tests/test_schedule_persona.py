from __future__ import annotations

import json
from pathlib import Path

from stigmergy import judge, persona, schedule
from stigmergy.config import Config


def test_persona_ingest_is_idempotent(repo: Path, tmp_path: Path) -> None:
    inbox = tmp_path / "inbox.jsonl"
    rows = [
        {
            "question": "Куда деплоить?",
            "decision": "только через поезд",
            "quote": "не выкатываем без гейта",
            "source": "runbook",
            "date": "2026-11-01",
        },
        {
            "question": "Кто approves high risk?",
            "decision": "человек",
            "source": "decision",
            "date": "2026-11-01",
        },
    ]
    inbox.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    config = Config.load(repo)
    first = persona.ingest(config, inbox)
    assert first["ok"] and first["imported"] == 2 and first["errors"] == 0
    assert Path(first["digest"]).exists()
    assert len(judge.decisions(config)) == 2
    second = persona.ingest(config, inbox)
    assert second["ok"] and second["imported"] == 0 and second["skipped"] == 2
    assert len(judge.decisions(config)) == 2


def test_persona_bad_row_is_counted(repo: Path, tmp_path: Path) -> None:
    inbox = tmp_path / "bad.jsonl"
    inbox.write_text('{"question": "missing decision"}\n', encoding="utf-8")
    data = persona.ingest(Config.load(repo), inbox)
    assert not data["ok"] and data["errors"] == 1


def test_schedule_units_and_install(repo: Path, tmp_path: Path) -> None:
    config = Config.load(repo)
    units = schedule.units(config, learn_calendar="Mon 09:00", persona_calendar="03:30")
    assert "learn --days 7" in units[schedule.LEARN_SERVICE]
    assert "OnCalendar=Mon 09:00" in units[schedule.LEARN_TIMER]
    assert "persona ingest" in units[schedule.PERSONA_SERVICE]
    assert "OnCalendar=*-*-* 03:30:00" in units[schedule.PERSONA_TIMER]
    target = tmp_path / "units"
    data = schedule.install(config, directory=target)
    assert data["ok"] and len(data["written"]) == 4
    assert all((target / name).exists() for name in units)
    assert schedule.status(target)["installed"][schedule.LEARN_TIMER]
