from __future__ import annotations

from pathlib import Path

from conftest import git, write

from stigmergy import bootstrap
from stigmergy.config import Config


def test_bootstrap_initializes_project_without_manual_commands(tmp_path: Path) -> None:
    root = tmp_path / "newproj"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "x@example.com")
    git(root, "config", "user.name", "X")
    write(root / "README.md", "# new\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "init")
    data = bootstrap.run(root, name="newproj", space="newproj", register=False, open_lead=False)
    assert data["ok"] and data["base"] == "dev"
    assert (root / ".agent").is_dir() and (root / "specs").is_dir()
    assert git(root, "show-ref", "--verify", "refs/heads/dev").returncode == 0
    config = Config.load(root)
    assert config.space == "newproj"
    assert config.section("factory")["auto_approve"] is True
    assert ".agent/" in (root / ".gitignore").read_text()
