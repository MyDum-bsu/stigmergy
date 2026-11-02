from __future__ import annotations

from pathlib import Path

from stigmergy import judge
from stigmergy.config import Config


def _decision(root: Path, name: str, question: str, decision: str, quote: str = "") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        "---\n"
        f"id: {Path(name).stem}\n"
        "date: 2026-11-02\n"
        "scope: project\n"
        f"question: {question}\n"
        f"decision: {decision}\n"
        f"quote: {quote}\n"
        "source: decisions/example.md\n"
        "---\n",
        encoding="utf-8",
    )


def test_search_returns_citation_and_date(repo: Path) -> None:
    config = Config.load(repo)
    _decision(
        repo / "decisions",
        "dec-001.md",
        "Куда деплоить?",
        "Только через поезд в прод",
        "не выкатываем без гейта",
    )
    items = judge.search(config, "куда деплоить")
    assert items
    assert items[0]["decision"] == "Только через поезд в прод"
    assert items[0]["source"] == "decisions/example.md"
    assert items[0]["date"] == "2026-11-02"
    assert "Только через поезд" in judge.answer_text(items)


def test_no_match_is_explicit(repo: Path) -> None:
    config = Config.load(repo)
    assert judge.search(config, "совершенно другой вопрос") == []
    assert "нет" in judge.answer_text([])


def test_add_decision_roundtrip(repo: Path) -> None:
    config = Config.load(repo)
    item = judge.add(
        config,
        "Можно ли пушить в main?",
        "Только человек, фабрика не пишет main",
        quote="main не пишется фабрикой",
        source="AGENTS.md",
        date="2026-11-02",
    )
    assert Path(item["path"]).exists()
    found = judge.search(config, "пушить main")
    assert found and found[0]["decision"] == "Только человек, фабрика не пишет main"
