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




def import_file(config: Config, path: Path) -> dict[str, Any]:
    """Import decisions from JSONL; used by the nightly persona ingest."""
    import json

    count = 0
    errors = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            add(
                config,
                str(row["question"]),
                str(row["decision"]),
                quote=str(row.get("quote") or ""),
                source=str(row.get("source") or ""),
                date=str(row.get("date") or ""),
                scope=str(row.get("scope") or "project"),
            )
            count += 1
        except (KeyError, ValueError, OSError):
            errors += 1
    return {"imported": count, "errors": errors, "path": str(path)}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-яё0-9]{3,}", text.lower())
        if token
        not in {
            "что", "как", "для", "или", "это", "все", "the", "and",
            "какой", "какие", "какая", "какое", "кто", "где", "когда",
            "зачем", "почему", "можно", "нужно", "делать", "сделать",
            "этот", "эта", "эти", "если", "чем", "чего", "такой",
            "такая", "такие",
        }
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



ALWAYS_HUMAN = re.compile(
    r"деньг|оплат|платеж|платёж|доступ|парол|секрет|удал|уничтож|"
    r"необратим|люд|сообщ|публик|рассылк|инвойс|касс",
    re.IGNORECASE,
)


def decide(config: Config, question: str, *, threshold: float = 0.45) -> dict[str, Any]:
    """Three outcomes: resolved with citations, wrong question, or new/human."""
    question = question.strip()
    if ALWAYS_HUMAN.search(question):
        return {
            "outcome": "human",
            "decision": "",
            "citations": [],
            "score": 0.0,
            "reason": "always-human category",
        }
    if not ("?" in question or " или " in question or " либо " in question or re.search(r"\d", question)):
        return {
            "outcome": "wrong",
            "decision": "",
            "citations": [],
            "score": 0.0,
            "reason": "question has no options, price or concrete choice",
        }
    items = search(config, question, limit=3)
    if not items:
        return {"outcome": "new", "decision": "", "citations": [], "score": 0.0, "reason": "not in decisions"}
    top = items[0]
    if top["score"] >= threshold and top.get("quote") and top.get("source") and top.get("date"):
        return {
            "outcome": "resolved",
            "decision": top["decision"],
            "citations": [top],
            "score": top["score"],
            "reason": "decision found with citation",
        }
    return {
        "outcome": "new",
        "decision": "",
        "citations": items[:3],
        "score": top["score"],
        "reason": "match below threshold or missing citation/date",
    }


def evaluate(config: Config, cases_path: Path | None = None) -> dict[str, Any]:
    import json

    path = cases_path or (config.integration_root / "decisions" / "eval.jsonl")
    if not path.exists():
        path = config.root / "decisions" / "eval.jsonl"
    if not path.exists():
        return {"ok": False, "detail": f"eval cases missing: {path}", "total": 0}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    correct = 0
    always_total = always_correct = 0
    details = []
    for row in rows:
        got = decide(config, str(row.get("question", "")))
        expected = str(row.get("expected", ""))
        good = got["outcome"] == expected
        correct += int(good)
        if expected == "human":
            always_total += 1
            always_correct += int(good)
        details.append({"question": row.get("question"), "expected": expected, "got": got["outcome"], "ok": good})
    total = len(rows)
    accuracy = correct / total if total else 0.0
    always = always_correct / always_total if always_total else 1.0
    return {
        "ok": total > 0 and accuracy >= 0.9 and always >= 1.0,
        "total": total,
        "correct": correct,
        "accuracy": round(accuracy, 3),
        "always_human_accuracy": round(always, 3),
        "path": str(path),
        "details": details,
    }

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
