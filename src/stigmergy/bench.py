"""Model benchmark harness: run a command per case, compare expected output.

No provider is hard-coded. A benchmark command is configured once (for example
a small CLI that talks to the provider) and receives:

  STG_MODEL, STG_CASE, STG_PROMPT_FILE, STG_EXPECTED

It exits zero and prints the answer; the harness checks ``expected`` as a
substring. This keeps benchmarking deterministic and auditable.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from stigmergy.config import Config


def _safe(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", text).strip("-")[:80] or "model"


def evaluate(
    config: Config,
    cases_path: Path,
    model: str,
    *,
    command: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    template = (command or str(config.section("models").get("bench_command") or "")).strip()
    if not template:
        return {
            "ok": False,
            "detail": "no bench command: pass --command or [models].bench_command",
            "model": model,
            "score": 0.0,
            "total": 0,
        }
    if not cases_path.exists():
        return {"ok": False, "detail": f"cases not found: {cases_path}", "model": model, "score": 0.0, "total": 0}
    rows = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"prompt": line, "expected": ""})
    results: list[dict[str, Any]] = []
    passed = 0
    with tempfile.TemporaryDirectory(prefix="stg-bench-") as temp:
        root = Path(temp)
        for index, row in enumerate(rows):
            prompt = str(row.get("prompt") or "")
            expected = str(row.get("expected") or row.get("expect") or "")
            case_command = str(row.get("command") or template)
            prompt_file = root / f"case-{index}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            case_command = (
                case_command.replace("{model}", shlex.quote(model))
                .replace("{prompt_file}", shlex.quote(str(prompt_file)))
                .replace("{expected}", shlex.quote(expected))
                .replace("{case}", str(index))
            )
            env = {
                "PATH": str(Path.home() / ".local" / "bin") + ":/usr/local/bin:/usr/bin:/bin",
                "STG_MODEL": model,
                "STG_CASE": str(index),
                "STG_PROMPT_FILE": str(prompt_file),
                "STG_EXPECTED": expected,
            }
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    case_command,
                    shell=True,
                    cwd=str(config.root),
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                code = proc.returncode
                output = (proc.stdout or "") + (proc.stderr or "")
            except subprocess.TimeoutExpired:
                code, output = 124, "benchmark timeout"
            good = code == 0 and (not expected or expected in output)
            passed += int(good)
            results.append(
                {
                    "case": index,
                    "ok": good,
                    "exit_code": code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "output_tail": output[-500:],
                }
            )
    total = len(rows)
    score = passed / total if total else 0.0
    report = {
        "ok": total > 0 and passed == total,
        "model": model,
        "command": template,
        "cases": str(cases_path),
        "total": total,
        "passed": passed,
        "score": round(score, 3),
        "results": results,
    }
    out_dir = config.root / ".factory" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{_safe(model)}.json"
    report["artifact"] = str(out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def text(data: dict[str, Any]) -> str:
    return (
        f"bench {data.get('model', '')}: {'PASS' if data.get('ok') else 'FAIL'} "
        f"{data.get('passed', 0)}/{data.get('total', 0)} score={data.get('score', 0)}"
    )
