from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.runner.base import RunnerHandle
from stigmergy.wave import create_wave


def test_wave_starts_lead_and_workers(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board_mod.add_task(board, config, "T2", "", spec_path="specs/T1.md")
    calls = {"workers": []}

    def fake_space(app, name, folder, agent, task):
        return {"space": "sp-wave", "terminal": "t-lead"}

    monkeypatch.setattr("stigmergy.wave.create_space", fake_space)
    monkeypatch.setattr("stigmergy.wave.ensure_app", lambda app: {"ok": True})

    class FakeRunner:
        kind = "herdr-app"

        def __init__(self, *args, **kwargs):
            self.space = kwargs.get("space")
            self.tab_name = kwargs.get("tab_name")

        def start(self, task_id, prompt, workspace, wait=True):
            calls["workers"].append((task_id, self.space, self.tab_name))
            return RunnerHandle(
                kind="herdr-app",
                handle=f"t-{task_id}",
                workspace=str(workspace),
                meta={"space": self.space or ""},
            )

    monkeypatch.setattr("stigmergy.runner.herdr_app.HerdrAppRunner", FakeRunner)
    data = create_wave(config, board, "goal", ["T1", "T2"])
    assert data["space"] == "sp-wave"
    assert data["lead"] == "t-lead"
    assert [worker["terminal"] for worker in data["workers"]] == ["t-T1", "t-T2"]
    assert calls["workers"] == [
        ("T1", "sp-wave", "stg-T1"),
        ("T2", "sp-wave", "stg-T2"),
    ]
    assert "wave.created" in [event["action"] for event in board.read()]
