from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import dash
from stigmergy.config import Config
from stigmergy.log import Board


def test_project_snapshot(repo: Path) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    data = dash.project_snapshot(repo)
    assert data["name"] == "fixture"
    assert data["counts"].get("queued") == 1
    assert len(data["tasks"]) == 1


def test_http_state(repo: Path, tmp_path: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    registry = tmp_path / "projects.toml"
    registry.write_text(
        f'[[project]]\nname = "fixture"\nroot = "{repo}"\nboard = ".agent"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("STIGMERGY_REGISTRY", str(registry))
    server = dash.serve_in_thread(0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        assert data["projects"][0]["name"] == "fixture"
        assert data["projects"][0]["tasks"][0]["id"] == "T1"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            assert response.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()
