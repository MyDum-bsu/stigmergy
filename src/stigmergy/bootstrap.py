"""One-command onboarding: git repo -> initialized Stigmergy project + Lead tab."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from stigmergy import registry
from stigmergy.config import Config


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_dev(root: Path, base: str) -> str:
    proc = _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{base}")
    if proc.returncode == 0:
        return base
    proc = _git(root, "branch", base, "HEAD")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:500])
    return base


def _patch_config(root: Path, name: str, space: str) -> None:
    path = root / ".agent.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        path.write_text(
            f"""[project]
name = "{name}"
base = "dev"
protected = ["main"]
wip = 1

[runner]
kind = "herdr-app"
app = "herdr-app"
agent = "pi"
space = "{space}"

[factory]
auto_approve = true

[risk]
low = "auto"
medium = "auto"
high = "human"
""",
            encoding="utf-8",
        )
        return
    if "[runner]" in text and "space =" not in text.split("[runner]", 1)[1].split("[", 1)[0]:
        text = text.replace("[runner]\n", f'[runner]\nspace = "{space}"\n', 1)
    if "[factory]" not in text:
        text = text.rstrip() + "\n\n[factory]\nauto_approve = true\n"
    path.write_text(text, encoding="utf-8")


def run(
    root: str | Path,
    *,
    name: str = "",
    space: str = "",
    register: bool = True,
    open_lead: bool = True,
    app: str = "herdr-app",
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not (root / ".git").exists():
        raise RuntimeError(f"{root} is not a git repository")
    project = name.strip() or root.name
    project_space = space.strip() or project
    base = _ensure_dev(root, "dev")
    (root / ".agent" / "views").mkdir(parents=True, exist_ok=True)
    (root / ".factory").mkdir(exist_ok=True)
    (root / "specs").mkdir(exist_ok=True)
    gi = root / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for entry in (".agent/", ".factory/"):
        if entry not in lines:
            lines.append(entry)
    gi.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    _patch_config(root, project, project_space)
    config = Config.load(root)
    if register and project not in {item["name"] for item in registry.load()}:
        registry.add(project, root)
    lead: dict[str, Any] = {"started": False}
    if open_lead:
        from stigmergy import lead as lead_mod

        lead = {"started": True, **lead_mod.start_lead(config, config_board(root), app=app, space=project_space)}
    return {
        "ok": True,
        "root": str(root),
        "project": project,
        "space": project_space,
        "base": base,
        "config": str(root / ".agent.toml"),
        "lead": lead,
    }


def config_board(root: Path):
    from stigmergy.log import Board

    return Board(root)
