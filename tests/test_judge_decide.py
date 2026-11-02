from __future__ import annotations

import json
from pathlib import Path

from stigmergy import judge
from stigmergy.config import Config


def _decision(root: Path, question: str, decision: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dec.md").write_text(
        "---\n"
        "id: dec\n"
        "date: 2026-11-02\n"
        "scope: project\n"
        f"question: {question}\n"
        f"decision: {decision}\n"
        "quote: цитата\n"
        "source: AGENTS.md\n"
        "---\n",
        encoding="utf-8",
    )


def test_decide_three_outcomes(repo: Path) -> None:
    config = Config.load(repo)
    _decision(repo / "decisions", "Куда деплоить сервис?", "Только через поезд в прод")
    assert judge.decide(config, "Куда деплоить сервис?")["outcome"] == "resolved"
    assert judge.decide(config, "сделай красиво")["outcome"] == "wrong"
    assert judge.decide(config, "Можно оплатить сервис?")["outcome"] == "human"
    assert judge.decide(config, "Какой цвет у неба?")["outcome"] == "new"


def test_eval_threshold(repo: Path) -> None:
    config = Config.load(repo)
    _decision(repo / "decisions", "Куда деплоить сервис?", "Только через поезд в прод")
    cases = repo / "decisions" / "eval.jsonl"
    cases.write_text(
        json.dumps({"question": "Куда деплоить сервис?", "expected": "resolved"}) + "\n"
        + json.dumps({"question": "Можно оплатить сервис?", "expected": "human"}) + "\n",
        encoding="utf-8",
    )
    data = judge.evaluate(config, cases)
    assert data["ok"] and data["accuracy"] >= 0.9 and data["always_human_accuracy"] == 1.0
