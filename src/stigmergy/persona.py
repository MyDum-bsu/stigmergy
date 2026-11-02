"""Nightly persona ingest: raw decision rows become cited judge decisions."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from stigmergy import judge
from stigmergy.config import Config


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        " ".join(str(row.get("question") or "").split()),
        " ".join(str(row.get("decision") or "").split()),
        str(row.get("source") or ""),
    )


def _clean(row: dict[str, Any]) -> dict[str, str]:
    out = {}
    for key in ("question", "decision", "quote", "source", "date", "scope"):
        value = " ".join(str(row.get(key) or "").split())
        if "\n" in value:
            raise ValueError(f"{key} must be a single line")
        out[key] = value
    return out


def ingest(config: Config, path: Path, *, source: str = "nightly") -> dict[str, Any]:
    """Idempotently import JSONL decisions and write a daily digest."""
    if not path.exists():
        return {
            "ok": False,
            "imported": 0,
            "skipped": 0,
            "errors": 0,
            "detail": f"inbox not found: {path}",
            "digest": "",
        }
    existing = {_key(item) for item in judge.decisions(config)}
    imported: list[dict[str, str]] = []
    skipped = 0
    errors = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            row = _clean(raw)
            if not row["question"] or not row["decision"]:
                raise ValueError("question and decision are required")
            if not row["source"]:
                row["source"] = f"persona:{source}"
            key = _key(row)
            if key in existing:
                skipped += 1
                continue
            item = judge.add(
                config,
                row["question"],
                row["decision"],
                quote=row["quote"],
                source=row["source"],
                date=row["date"] or time.strftime("%Y-%m-%d"),
                scope=row["scope"] or "project",
            )
            imported.append({"id": item["id"], "question": row["question"], "decision": row["decision"]})
            existing.add(key)
        except (ValueError, KeyError, OSError, json.JSONDecodeError):
            errors += 1
    root = config.integration_root if config.integration_root.exists() else config.root
    digest = root / "persona" / f"{time.strftime('%Y-%m-%d')}.md"
    digest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Persona ingest · {time.strftime('%Y-%m-%d')}",
        "",
        f"Источник: `{path}`",
        f"Импортировано: {len(imported)}; пропущено: {skipped}; ошибок: {errors}.",
        "",
        "## Новые решения",
    ]
    if imported:
        for item in imported:
            lines.append(f"- `{item['id']}`: {item['question']} → {item['decision']}")
    else:
        lines.append("- нет")
    digest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": errors == 0,
        "imported": len(imported),
        "skipped": skipped,
        "errors": errors,
        "detail": "",
        "digest": str(digest),
        "path": str(path),
    }


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9а-яё]+", "-", text.lower(), flags=re.IGNORECASE).strip("-")[:48]
