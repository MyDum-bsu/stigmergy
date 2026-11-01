from __future__ import annotations

from pathlib import Path

from stigmergy.log import Board


def test_monotonic_seq_and_trace(tmp_path: Path) -> None:
    board = Board(tmp_path)
    first = board.append(
        "task.created",
        {"kind": "agent", "name": "a"},
        {"project.name": "p", "task.id": "T1"},
        "one",
    )
    second = board.append(
        "task.claimed",
        {"kind": "agent", "name": "a"},
        {"project.name": "p", "task.id": "T1"},
        "two",
    )
    assert second["seq"] == first["seq"] + 1
    assert second["timeUnixNano"] > first["timeUnixNano"]
    assert second["eventId"] != first["eventId"]
    assert second["traceId"] == first["traceId"]
    assert len(board.read()) == 2


def test_read_rejects_bad_json(tmp_path: Path) -> None:
    board = Board(tmp_path)
    board.ensure()
    board.events_path.write_text("{not json}\n", encoding="utf-8")
    try:
        board.read()
    except Exception as exc:  # BoardError
        assert "bad event" in str(exc)
    else:
        raise AssertionError("expected BoardError")
