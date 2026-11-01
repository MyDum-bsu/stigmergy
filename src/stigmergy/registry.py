"""Global registry of stigmergy projects (read-only except add/remove)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def registry_path() -> Path:
    env = os.environ.get("STIGMERGY_REGISTRY")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "stigmergy" / "projects.toml"


def load() -> list[dict[str, str]]:
    path = registry_path()
    if not path.exists():
        return []
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    projects = data.get("project", [])
    if isinstance(projects, dict):
        projects = [projects]
    out = []
    for item in projects:
        if isinstance(item, dict) and item.get("root"):
            out.append(
                {
                    "name": str(item.get("name") or Path(item["root"]).name),
                    "root": str(Path(item["root"]).expanduser()),
                    "board": str(item.get("board", ".agent")),
                }
            )
    return out


def _write(projects: list[dict[str, str]]) -> Path:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# stigmergy projects"]
    for item in projects:
        lines.extend(
            [
                "",
                "[[project]]",
                f'name = "{item["name"]}"',
                f'root = "{item["root"]}"',
                f'board = "{item.get("board", ".agent")}"',
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def add(name: str, root: str) -> Path:
    projects = [p for p in load() if p["name"] != name]
    projects.append({"name": name, "root": str(Path(root).expanduser().resolve()), "board": ".agent"})
    return _write(projects)


def remove(name: str) -> Path:
    projects = [p for p in load() if p["name"] != name]
    return _write(projects)
