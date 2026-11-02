from __future__ import annotations

import re
from pathlib import Path


def _agents() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "AGENTS.md"
        if candidate.is_file() and (parent / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("AGENTS.md next to pyproject.toml not found")


AGENTS = _agents()

REQUIRED_TOKENS = ("gh issue", "gh pr", "stg board", "MyDum-bsu/stigmergy")
REQUIRED_HEADINGS = ("# Stigmergy", "## Работа", "## Приёмка", "## Ветки")
REQUIRED_ROOTS = ("зеркал", "доск")
STUB_MARKERS = ("TBD", "TODO")
MIN_BULLETS = 4


def github_section(text: str) -> str:
    """Body of the single `## GitHub` section, up to the next level 1-2 heading."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^##\s+GitHub\b", line)]
    if not starts:
        raise AssertionError("в AGENTS.md нет раздела `## GitHub`")
    if len(starts) > 1:
        raise AssertionError("раздел `## GitHub` объявлен больше одного раза")
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if re.match(r"^#{1,2}\s", line):
            break
        body.append(line)
    return "\n".join(body)


def problems(text: str) -> list[str]:
    findings: list[str] = []
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            findings.append(f"пропал существующий раздел {heading!r}")
    try:
        body = github_section(text)
    except AssertionError as exc:
        findings.append(str(exc))
        return findings
    for token in REQUIRED_TOKENS:
        if token not in body:
            findings.append(f"в разделе `## GitHub` нет {token!r}")
    bullets = [line for line in body.splitlines() if line.startswith("- ")]
    if len(bullets) < MIN_BULLETS:
        findings.append(f"в разделе `## GitHub` {len(bullets)} пунктов списка, нужно >= {MIN_BULLETS}")
    lowered = body.lower()
    for root in REQUIRED_ROOTS:
        if root not in lowered:
            findings.append(f"в разделе `## GitHub` нет корня {root!r}")
    for marker in STUB_MARKERS:
        if marker in body:
            findings.append(f"в разделе `## GitHub` осталась заглушка {marker!r}")
    return findings


def test_agents_md_has_github_section() -> None:
    assert AGENTS.is_file(), f"{AGENTS} отсутствует"
    findings = problems(AGENTS.read_text(encoding="utf-8"))
    assert not findings, "AGENTS.md: " + "; ".join(findings)
