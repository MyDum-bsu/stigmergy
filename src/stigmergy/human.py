"""Human authorization for the two non-delegable actions.

The human token lives outside the worker sandbox (``~/.config`` is masked).
It does not authenticate a person cryptographically; it separates the human
terminal from an agent tab, which is the threat we actually have.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from stigmergy.log import BoardError

TOKEN_PATH = Path.home() / ".config" / "stigmergy" / "human.token"


def init(force: bool = False) -> Path:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists() and not force:
        return TOKEN_PATH
    TOKEN_PATH.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    TOKEN_PATH.chmod(0o600)
    return TOKEN_PATH


def available() -> bool:
    return TOKEN_PATH.is_file() and bool(TOKEN_PATH.read_text(encoding="utf-8").strip())


def require() -> None:
    if not available():
        raise BoardError(
            f"human action requires a token: run `stg human init` ({TOKEN_PATH})"
        )
    provided = os.environ.get("STG_HUMAN_TOKEN", "").strip()
    if provided:
        expected = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not secrets.compare_digest(provided, expected):
            raise BoardError("human token does not match")


def status() -> dict:
    return {"path": str(TOKEN_PATH), "available": available()}
