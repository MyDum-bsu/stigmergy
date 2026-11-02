"""Taste judge: search the owner's recorded decisions with citations.

The judge does not invent. It returns the closest verbatim decisions with
source/date; the lead answers from them, and "new" still goes to the human.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.spec import SpecError, parse_frontmatter, split_frontmatter


def decision_roots(config: Config) -> list[Path]:
    roots = [config.root / "decisions"]
    integration = config.root / ".factory" / "integration" / "decisions"
    if integration != roots[0]:
        roots.append(integration)
    return roots


def parse_decision(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    front, body = split_frontmatter(raw)
    meta = parse_frontmatter(front)
    question = str(meta.get("question") or "").strip()
    decision = str(meta.get("decision") or "").strip()
    if not question or not decision:
        raise SpecError(f"{path}: question and decision are required")
    return {
        "id": str(meta.get("id") or path.stem),
        "date": str(meta.get("date") or ""),
        "scope": str(meta.get("scope") or "project"),
        "question": question,
        "decision": decision,
        "quote": str(meta.get("quote") or "").strip(),
        "source": str(meta.get("source") or path.name),
        "path": str(path),
        "body": body.strip(),
    }


def decisions(config: Config) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in decision_roots(config):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            if path.resolve() in seen:
                continue
            seen.add(str(path.resolve()))
            try:
                out.append(parse_decision(path))
            except (OSError, SpecError):
                continue
    return out




def add(
    config: Config,
    question: str,
    decision: str,
    *,
    quote: str = "",
    source: str = "",
    date: str | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    """Record a human decision in the base the judge reads."""
    question = question.strip()
    decision = decision.strip()
    if not question or not decision:
        raise ValueError("question and decision are required")
    root = config.integration_root / "decisions"
    if not config.integration_root.exists():
        root = config.root / "decisions"
    root.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", question.lower(), flags=re.IGNORECASE).strip("-")
    path = root / f"dec-{time.strftime('%Y%m%d-%H%M%S')}-{slug[:32] or 'decision'}.md"
    path.write_text(
        "---\n"
        f"id: {path.stem}\n"
        f"date: {date or time.strftime('%Y-%m-%d')}\n"
        f"scope: {scope}\n"
        f"question: {question}\n"
        f"decision: {decision}\n"
        f"quote: {quote}\n"
        f"source: {source or path.name}\n"
        "---\n",
        encoding="utf-8",
    )
    return parse_decision(path)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-яё0-9]{3,}", text.lower())
        if token not in {"что", "как", "для", "или", "это", "все", "the", "and"}
    }


def search(config: Config, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q = _tokens(query)
    if not q:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in decisions(config):
        text = " ".join(
            [item["question"], item["decision"], item["quote"], item["body"]]
        )
        tokens = _tokens(text)
        overlap = len(q & tokens)
        if not overlap:
            continue
        score = overlap / max(1, len(q))
        if item["quote"]:
            score += 0.15
        if item["date"]:
            score += 0.05
        scored.append((round(score, 3), item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["date"]), reverse=True)
    return [
        {"score": score, **item}
        for score, item in scored[: max(1, limit)]
    ]


def answer_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "В базе решений ответа нет — адресуй вопрос человеку."
    lines = []
    for item in items:
        cite = item["quote"] or item["decision"]
        lines.append(
            f"- {item['decision']} — «{cite}» ({item['source']}, {item['date'] or 'дата не указана'})"
        )
    return "\n".join(lines)
