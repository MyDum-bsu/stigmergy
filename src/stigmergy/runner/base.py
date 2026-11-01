"""Runner interface: the contour never imports a specific product."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RunnerHandle:
    kind: str
    session: str = ""
    handle: str = ""
    pane: str = ""
    workspace: str = ""
    meta: dict = field(default_factory=dict)


class Runner(Protocol):
    kind: str

    def start(self, task_id: str, prompt: str, workspace: Path) -> RunnerHandle: ...

    def status(self, handle: RunnerHandle) -> str: ...

    def read(self, handle: RunnerHandle, lines: int = 120) -> str: ...

    def stop(self, handle: RunnerHandle) -> None: ...
