"""Deterministic fast-lane policy.

A human enables the lane once in ``.agent.toml`` ([factory].auto_approve).
The policy then checks a planner-authored spec; it never trusts the planner's
prose. Fast lane is intentionally narrow: one file, low risk, one command,
an oracle, no external/destructive operations and no protected data.
"""

from __future__ import annotations

import re
from typing import Any

from stigmergy.config import Config
from stigmergy.spec import Spec

POLICY = "fast-low-v1"
FORBIDDEN_PATHS = (
    r"(^|/)data(/|$)",
    r"(^|/)tracker/data(/|$)",
    r"(^|/)\.git(/|$)",
    r"(^|/)\.env",
    r"(^|/)secrets?",
)
FORBIDDEN_COMMANDS = (
    r"\brm\s+-rf\b",
    r"\bgit\s+push\b",
    r"\bsudo\b",
    r"\b(curl|wget|ssh|scp|rsync)\b",
    r"\b(mkfs|dd|chmod|chown)\b",
    r"\bsystemctl\b",
    r"\bgh\s+",
)


def _count(paths: list[str]) -> int:
    return len([path for path in paths if path.strip()])


def evaluate(config: Config, spec: Spec) -> dict[str, Any]:
    settings = config.section("factory")
    reasons: list[str] = []
    if not bool(settings.get("auto_approve")):
        reasons.append("fast lane disabled: [factory].auto_approve=false")
    if spec.risk != "low":
        reasons.append(f"risk is {spec.risk}, fast lane is low only")
    if not spec.auto_approve:
        reasons.append("spec does not declare auto_approve: true")
    max_paths = int(settings.get("fast_max_paths", 1) or 1)
    max_oracle = int(settings.get("fast_max_oracle", 2) or 2)
    if _count(spec.allowed_paths) != max_paths:
        reasons.append(f"allowed_paths must be exactly {max_paths}")
    if _count(spec.oracle_paths) < 1 or _count(spec.oracle_paths) > max_oracle:
        reasons.append(f"oracle_paths must be 1..{max_oracle}")
    if len(spec.dod) > int(settings.get("fast_max_dod_chars", 1200) or 1200):
        reasons.append("dod is too long for fast lane")
    for path in spec.allowed_paths:
        if path in {"*", "**", "/**"} or "**" in path:
            reasons.append(f"broad path is not fast-lane safe: {path}")
        for pattern in FORBIDDEN_PATHS:
            if re.search(pattern, path, re.IGNORECASE):
                reasons.append(f"protected path: {path}")
    for pattern in FORBIDDEN_COMMANDS:
        if re.search(pattern, spec.dod, re.IGNORECASE):
            reasons.append(f"dod contains forbidden operation: {pattern}")
    if spec.invariants and spec.risk != "high":
        reasons.append("invariants are for high-risk formal tasks")
    return {
        "ok": not reasons,
        "policy": POLICY,
        "reasons": reasons,
        "spec_sha": spec.sha,
        "risk": spec.risk,
        "allowed_paths": spec.allowed_paths,
        "oracle_paths": spec.oracle_paths,
    }


def text(data: dict[str, Any]) -> str:
    if data["ok"]:
        return f"fast-lane: PASS policy={data['policy']}"
    return f"fast-lane: NO policy={data['policy']} " + "; ".join(data["reasons"])
