from __future__ import annotations

from pathlib import Path

from stigmergy import board as board_mod
from stigmergy import critic
from stigmergy.config import Config
from stigmergy.log import Board


def test_critic_prompt_has_frequency_and_harm() -> None:
    text = critic.critic_prompt(Config.load(Path(".")), "T1", base="dev", commit="abc", diff_stat="1 file", prd="goal")
    assert "frequency 1..10" in text
    assert "harm 1..10" in text
    assert "money, data" in text


def test_start_critic_opens_separate_tab(repo: Path, monkeypatch) -> None:
    board = Board(repo)
    config = Config.load(repo)
    board_mod.add_task(board, config, "T1", "", spec_path="specs/T1.md")
    board.append(
        "episode.finished",
        {"kind": "agent", "name": "pi"},
        {"project.name": "fixture", "task.id": "T1", "vcs.commit": "ce653a9", "vcs.tree": "tree"},
    )
    monkeypatch.setattr(
        critic.herdr_app, "ensure_space", lambda app, name, folder: {"space": "sp0", "tabs": []}
    )
    seen = {}

    def fake_tab(app, space, name, folder, agent, task, agent_args=None):
        seen.update(name=name, agent_args=agent_args)
        return {"space": space, "terminal": "t-critic"}

    monkeypatch.setattr(critic.herdr_app, "create_tab", fake_tab)
    data = critic.start_critic(config, board, "T1")
    assert data["terminal"] == "t-critic"
    assert seen["name"] == "Critic · T1"
    assert "edit,write,AskUserQuestion" in seen["agent_args"]
