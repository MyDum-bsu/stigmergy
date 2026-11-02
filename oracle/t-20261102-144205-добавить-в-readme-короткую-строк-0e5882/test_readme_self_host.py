"""Oracle: README states that stigmergy is developed through self-host in space stigmergy."""

from __future__ import annotations

import re
from pathlib import Path

REQUIRED_HEADINGS = (
    "# stigmergy",
    "## Документы",
    "## P0: идея → принятая задача",
    "## Состояние (2026-11-02)",
    "## Быстрый старт",
)
SECTION_BOUNDARY = "## документы"
MAX_LINE = 120


def _readme() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "README.md"
        if candidate.is_file() and (parent / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("README.md next to pyproject.toml not found above this test")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", " ").lower()).strip()


def test_readme_declares_self_host() -> None:
    text = _readme().read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"README lost section {heading!r}"

    normalized = _normalize(text)
    assert "stigmergy разрабатывается через self-host" in normalized, (
        "README does not say stigmergy is developed through self-host"
    )
    assert "space stigmergy" in normalized, "README does not name the space stigmergy"
    assert normalized.index("self-host") < normalized.index(SECTION_BOUNDARY), (
        "the self-host sentence must sit in the intro, before the '## Документы' section"
    )

    host_lines = [line for line in text.splitlines() if "self-host" in line.lower()]
    assert host_lines, "no README line mentions self-host"
    assert all(len(line) <= MAX_LINE for line in host_lines), "the self-host line must stay short"
