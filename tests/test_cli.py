from __future__ import annotations

import json
from pathlib import Path

from stigmergy.cli import main


def test_cli_init_add_list_validate(repo: Path, capsys) -> None:
    assert main(["init", "--path", str(repo)]) == 0
    assert main(["--board", str(repo), "board", "add", "T1", "--spec", "specs/T1.md", "--json"]) == 0
    capsys.readouterr()
    assert main(["--board", str(repo), "board", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["id"] == "T1"
    assert main(["--board", str(repo), "spec", "validate", "specs/T1.md", "--base", "dev"]) == 0
    assert main(["--board", str(repo), "status"]) == 0
    assert main(["migrate", "--check", str(repo)]) == 0


def test_cli_unknown_command_is_an_error(repo: Path, capsys) -> None:
    assert main(["init", "--path", str(repo)]) == 0
    assert main(["--board", str(repo), "board", "show", "missing"]) == 1
    assert "unknown task" in capsys.readouterr().err
