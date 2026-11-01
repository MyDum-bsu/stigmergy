from __future__ import annotations

import pytest

from stigmergy.runner import herdr


def test_unit_text_is_a_service_with_a_session() -> None:
    text = herdr.unit_text("factory")
    assert "--session factory" in text
    assert "script -qec" in text
    assert "Restart=on-failure" in text


def test_guard_rejects_foreign_workspaces(monkeypatch) -> None:
    monkeypatch.setattr(herdr, "workspaces", lambda session: [{"label": "stg-T1"}])
    ok, detail = herdr.guard()
    assert ok, detail
    monkeypatch.setattr(herdr, "workspaces", lambda session: [{"label": "lab"}])
    ok, detail = herdr.guard()
    assert not ok
    assert "foreign" in detail


def test_guard_allows_the_empty_home_workspace(monkeypatch) -> None:
    monkeypatch.setattr(herdr, "workspaces", lambda session: [{"label": "~", "number": 1}])
    ok, detail = herdr.guard()
    assert ok, detail


def test_detect_provider_error() -> None:
    assert herdr.detect_error("Error: 429: GoUsageLimitError") == "GoUsageLimitError"
    assert herdr.detect_error("Reply exactly: herdr-ok") == ""


def test_reset_requires_yes() -> None:
    with pytest.raises(herdr.HerdrError):
        herdr.reset_session("factory", yes=False)
