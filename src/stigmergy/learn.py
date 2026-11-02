"""Weekly learning proposals: never self-modify skills without a human PR."""

from __future__ import annotations

import time
from pathlib import Path

from stigmergy import retro
from stigmergy.config import Config
from stigmergy.log import Board


def propose(config: Config, board: Board, *, days: int = 7) -> Path:
    data = retro.collect(config, board, days=days)
    body = retro.render(data)
    body += "\n## Guardrail proposals\n\n"
    for item in data["suggestions"]:
        body += f"- [ ] {item}\n"
    body += (
        "\nПриоритет: архитектура → линтер/тип → тест/хук → слово в skill/AGENTS. "
        "Ни одно правило не вступает в силу без PR и человеческого approve.\n"
    )
    root = config.integration_root if config.integration_root.exists() else config.root
    out = root / "lessons" / f"{time.strftime('%Y-%m-%d')}-proposals.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out
