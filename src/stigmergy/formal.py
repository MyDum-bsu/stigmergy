"""TLA+ verification of the factory lifecycle and live board invariants.

The model is deliberately small: claim → start → block/answer → workerdone →
gate → merge, with WIP and gate/control invariants. A broken mutant must be
rejected by TLC; the live board must satisfy the same invariants.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState

MODELS = Path(__file__).parent / "formal"


def jar_path(config: Config | None = None) -> Path | None:
    candidates = []
    env = os.environ.get("TLA2TOOLS_JAR")
    if env:
        candidates.append(Path(env))
    candidates.append(Path.home() / ".local" / "share" / "tlaplus" / "tla2tools.jar")
    if config is not None:
        candidates.append(config.root / ".tools" / "tla2tools.jar")
    for path in candidates:
        if path.is_file():
            return path
    return None


def run_tlc(model: Path, config: Path, *, timeout: int = 120) -> dict[str, Any]:
    jar = jar_path()
    java = shutil.which("java")
    if not jar or not java:
        return {"ok": False, "detail": "java/tla2tools.jar not found", "output": ""}
    if not model.is_file() or not config.is_file():
        return {"ok": False, "detail": f"missing model/config: {model}, {config}", "output": ""}
    with tempfile.TemporaryDirectory(prefix="stg-tla-") as temp:
        work = Path(temp)
        shutil.copy2(model, work / model.name)
        shutil.copy2(config, work / config.name)
        proc = subprocess.run(
            [
                java,
                "-cp",
                str(jar),
                "tlc2.TLC",
                "-config",
                config.name,
                "-workers",
                "1",
                "-deadlock",
                model.name,
            ],
            cwd=temp,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and "No error has been found" in output
        return {
            "ok": ok,
            "exit_code": proc.returncode,
            "model": str(model),
            "output": output[-4000:],
        }


def live_violations(config: Config, board: Board) -> list[str]:
    events = board.read()
    state = ProjectState.from_events(events, project=config.name)
    gated = {
        str((event.get("attributes") or {}).get("task.id"))
        for event in events
        if event.get("action") == "gate.passed"
    }
    merged = {
        str((event.get("attributes") or {}).get("task.id"))
        for event in events
        if event.get("action") == "merge.done"
    }
    migrated = max(
        (
            int(event.get("seq", 0))
            for event in events
            if event.get("action") == "board.migrated"
        ),
        default=0,
    )
    out: list[str] = []
    for task in state.all():
        if task.created_seq <= migrated:
            continue  # legacy board: no gate.passed event existed then
        if task.status == "done" and task.id not in gated:
            out.append(f"done without gate.passed: {task.id}")
        if task.id in merged and task.id not in gated:
            out.append(f"merged without gate.passed: {task.id}")
    active = len(state.current())
    if active > config.wip:
        out.append(f"WIP violation: active={active} > wip={config.wip}")
    return out


def verify_core(config: Config, board: Board | None = None) -> dict[str, Any]:
    good = run_tlc(MODELS / "TaskLifecycle.tla", MODELS / "TaskLifecycle.cfg")
    broken = run_tlc(
        MODELS / "TaskLifecycleBroken.tla",
        MODELS / "TaskLifecycleBroken.cfg",
    )
    mutant_text = broken.get("output", "").lower()
    control = not broken["ok"] and ("violat" in mutant_text or "error" in mutant_text)
    live = live_violations(config, board) if board is not None else []
    passed = bool(good["ok"] and control and not live)
    return {
        "passed": passed,
        "model": good,
        "mutant": broken,
        "mutant_rejected": control,
        "live": live,
        "jar": str(jar_path(config) or ""),
    }


def text(data: dict[str, Any]) -> str:
    return (
        f"formal: {'PASS' if data['passed'] else 'FAIL'} "
        f"model={'ok' if data['model']['ok'] else 'fail'} "
        f"mutant_rejected={data['mutant_rejected']} "
        f"live_violations={len(data['live'])}"
    )
