"""Install the recurring factory jobs as user systemd units.

The timer is deliberately outside the model loop: weekly learning and nightly
persona ingest are deterministic jobs with logs on the event board, not an
agent that decides when to improve itself.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from stigmergy.config import Config

LEARN_SERVICE = "stigmergy-learn.service"
LEARN_TIMER = "stigmergy-learn.timer"
PERSONA_SERVICE = "stigmergy-persona.service"
PERSONA_TIMER = "stigmergy-persona.timer"


def unit_dir() -> Path:
    override = Path.home() / ".config" / "systemd" / "user"
    return override


def _stg() -> str:
    found = shutil.which("stg")
    if found:
        return shlex.quote(found)
    return shlex.quote(sys.executable) + " -m stigmergy"


def units(config: Config, *, learn_calendar: str = "Mon 09:00", persona_calendar: str = "03:30") -> dict[str, str]:
    root = shlex.quote(str(config.root))
    stg = _stg()
    inbox = config.root / ".factory" / "persona" / "inbox.jsonl"
    learn_service = f"""\
[Unit]
Description=Stigmergy weekly learning report
After=network.target

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={stg} --board {root} learn --days 7
Nice=10
TimeoutStartSec=600
"""
    learn_timer = f"""\
[Unit]
Description=Run Stigmergy learning weekly

[Timer]
OnCalendar={learn_calendar}
Persistent=true
Unit={LEARN_SERVICE}

[Install]
WantedBy=timers.target
"""
    persona_service = f"""\
[Unit]
Description=Stigmergy nightly persona ingest
After=network.target
ConditionPathExists={shlex.quote(str(inbox))}

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={stg} --board {root} persona ingest --file {shlex.quote(str(inbox))}
Nice=10
TimeoutStartSec=600
"""
    persona_timer = f"""\
[Unit]
Description=Run Stigmergy persona ingest nightly

[Timer]
OnCalendar=*-*-* {persona_calendar}:00
Persistent=true
Unit={PERSONA_SERVICE}

[Install]
WantedBy=timers.target
"""
    return {
        LEARN_SERVICE: learn_service,
        LEARN_TIMER: learn_timer,
        PERSONA_SERVICE: persona_service,
        PERSONA_TIMER: persona_timer,
    }


def install(
    config: Config,
    *,
    enable: bool = False,
    directory: Path | None = None,
    learn_calendar: str = "Mon 09:00",
    persona_calendar: str = "03:30",
) -> dict[str, Any]:
    target = directory or unit_dir()
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, text in units(
        config,
        learn_calendar=learn_calendar,
        persona_calendar=persona_calendar,
    ).items():
        path = target / name
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    enabled = False
    detail = ""
    if enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        proc = subprocess.run(
            ["systemctl", "--user", "enable", "--now", LEARN_TIMER, PERSONA_TIMER],
            text=True,
            capture_output=True,
            check=False,
        )
        enabled = proc.returncode == 0
        detail = (proc.stdout or proc.stderr).strip()[:1000]
    return {
        "ok": True,
        "directory": str(target),
        "written": written,
        "enabled": enabled,
        "detail": detail,
        "timers": [LEARN_TIMER, PERSONA_TIMER],
    }


def status(directory: Path | None = None) -> dict[str, Any]:
    target = directory or unit_dir()
    paths = {name: target / name for name in (LEARN_SERVICE, LEARN_TIMER, PERSONA_SERVICE, PERSONA_TIMER)}
    proc = subprocess.run(
        ["systemctl", "--user", "list-timers", "--no-pager", "--all"],
        text=True,
        capture_output=True,
        check=False,
    )
    text = proc.stdout or proc.stderr or ""
    return {
        "ok": all(path.exists() for path in paths.values()),
        "directory": str(target),
        "installed": {name: path.exists() for name, path in paths.items()},
        "timers": text[-3000:],
    }
