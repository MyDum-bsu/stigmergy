from __future__ import annotations

from pathlib import Path

import pytest

from stigmergy import human
from stigmergy.log import BoardError


def test_token_roundtrip(tmp_path: Path, monkeypatch) -> None:
    token = tmp_path / "human.token"
    monkeypatch.setattr(human, "TOKEN_PATH", token)
    monkeypatch.delenv("STG_HUMAN_TOKEN", raising=False)
    path = human.init()
    assert path == token and token.exists()
    assert oct(token.stat().st_mode & 0o777) == "0o600"
    human.require()
    expected = token.read_text(encoding="utf-8").strip()
    monkeypatch.setenv("STG_HUMAN_TOKEN", expected)
    human.require()


def test_bad_and_missing_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(human, "TOKEN_PATH", tmp_path / "missing")
    monkeypatch.delenv("STG_HUMAN_TOKEN", raising=False)
    with pytest.raises(BoardError, match="human init"):
        human.require()
    human.init()
    monkeypatch.setenv("STG_HUMAN_TOKEN", "wrong")
    with pytest.raises(BoardError, match="does not match"):
        human.require()
