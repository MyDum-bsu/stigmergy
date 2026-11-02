"""Project configuration: ``.agent.toml`` plus global registry helpers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    "project": {"name": "", "base": "dev", "protected": ["main"], "wip": 1},
    "workspace": {"provider": "git", "root": ".factory/worktrees"},
    "gate": {"default_dod": "", "timeout_seconds": 1800, "network": False, "env": {}},
    "sandbox": {
        "engine": "bwrap",
        "episode_network": "proxy",
        "gate_network": "none",
        "mask": ["$HOME", "data", "tracker/data", ".ssh"],
    },
    "runner": {
        "kind": "manual",
        "session": "factory",
        "agent": "pi",
        "sandbox": True,
        "keep_workspace": True,
        "model": "",
        "critic_model": "",
        "space": "",
    },
    "risk": {"low": "auto", "medium": "auto", "high": "human"},
    "dispatcher": {"auto_finish": True, "interval_seconds": 5, "max_retries": 1, "auto_judge": True},
    "factory": {
        "auto_approve": False,
        "fast_max_paths": 1,
        "fast_max_oracle": 2,
        "fast_max_dod_chars": 1200,
    },
    "models": {
        "default": "",
        "worker": "",
        "planner": "",
        "critic": "",
        "lead": "",
        "judge": "",
        "bench_command": "",
    },
    "notify": {
        "telegram_token_env": "STG_TELEGRAM_TOKEN",
        "telegram_chat_id": "",
        "webhook_url": "",
    },
    "visual": {"command": "", "timeout_seconds": 120},
    "github": {"repo": "", "label": "stigmergy", "close_on_done": False},
}


@dataclass
class Config:
    root: Path
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: str | Path) -> Config:
        path = Path(root) / ".agent.toml"
        if path.exists():
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        else:
            raw = {}
        return cls(root=Path(root), raw=raw)

    def section(self, name: str) -> dict[str, Any]:
        merged = dict(DEFAULTS.get(name, {}))
        merged.update(self.raw.get(name, {}) or {})
        return merged

    @property
    def name(self) -> str:
        return str(self.section("project").get("name") or self.root.name)

    @property
    def base(self) -> str:
        return str(self.section("project").get("base", "dev"))

    @property
    def protected(self) -> list[str]:
        return [str(x) for x in (self.section("project").get("protected") or [])]

    @property
    def wip(self) -> int:
        return int(self.section("project").get("wip", 1))

    @property
    def runner(self) -> dict[str, Any]:
        return self.section("runner")

    @property
    def space(self) -> str:
        """Herdr project space: explicit runner.space, else the project name."""
        return str(self.runner.get("space") or "") or self.name

    @property
    def gate(self) -> dict[str, Any]:
        return self.section("gate")

    @property
    def sandbox(self) -> dict[str, Any]:
        return self.section("sandbox")

    @property
    def workspace_root(self) -> Path:
        return self.root / str(self.section("workspace").get("root", ".factory/worktrees"))

    @property
    def artifacts_root(self) -> Path:
        return self.root / ".factory" / "artifacts"

    @property
    def gate_root(self) -> Path:
        return self.root / ".factory" / "gate"

    @property
    def integration_root(self) -> Path:
        return self.root / ".factory" / "integration"

    def write_default(self) -> Path:
        path = self.root / ".agent.toml"
        if path.exists():
            return path
        name = self.root.name
        path.write_text(
            f"""# stigmergy project config
[project]
name = "{name}"
base = "dev"
protected = ["main"]
wip = 1

[workspace]
provider = "git"
root = ".factory/worktrees"

[gate]
timeout_seconds = 1800
network = false

[sandbox]
engine = "bwrap"
episode_network = "proxy"
gate_network = "none"

[runner]
kind = "manual"
agent = "pi"
space = "{name}"

[factory]
auto_approve = false
fast_max_paths = 1
fast_max_oracle = 2
fast_max_dod_chars = 1200

[models]
default = ""
worker = ""
planner = ""
critic = ""
lead = ""
bench_command = ""

[notify]
telegram_token_env = "STG_TELEGRAM_TOKEN"
telegram_chat_id = ""
webhook_url = ""

[visual]
command = ""

[github]
repo = ""
label = "stigmergy"

[risk]
low = "auto"
medium = "auto"
high = "human"
""",
            encoding="utf-8",
        )
        return path
