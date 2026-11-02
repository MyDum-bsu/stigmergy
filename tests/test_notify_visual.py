from __future__ import annotations

from pathlib import Path

from stigmergy import notify, visual
from stigmergy.config import Config


def test_notify_dry_run_never_needs_token(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["notify"] = {"telegram_chat_id": "123", "webhook_url": "https://example.invalid/hook"}
    data = notify.send(config, "gate failed")
    assert data["ok"] and data["dry_run"] and data["sent"] == 0
    assert {item["kind"] for item in data["results"]} == {"telegram", "webhook"}
    assert all(item.get("dry_run") for item in data["results"])


def test_notify_real_send_without_token_fails_safely(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["notify"] = {"telegram_chat_id": "123", "telegram_token_env": "STG_MISSING_TOKEN"}
    data = notify.send(config, "gate failed", send_now=True)
    assert not data["ok"] and data["sent"] == 0
    assert data["results"][0]["detail"] == "token missing"


def test_visual_dry_run_and_command(repo: Path) -> None:
    config = Config.load(repo)
    assert not visual.check(config, "http://127.0.0.1:3000")["ok"]
    config.raw["visual"] = {
        "command": "python3 -c 'import os; assert os.environ[\"STG_VISUAL_TARGET\"] == \"http://x\"'"
    }
    dry = visual.check(config, "http://x")
    assert dry["ok"] and dry["dry_run"]
    run = visual.check(config, "http://x", run_now=True)
    assert run["ok"], run
    assert (config.artifacts_root / "visual" / "latest").is_dir()
