"""Task specifications: a decision procedure with an executable gate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RISKS = {"low", "medium", "high"}
ABSOLUTE_OR_ESCAPE = re.compile(r"(^/)|(^\.\./)|(/\.\./)|(^~)")


class SpecError(ValueError):
    """Invalid or unusable specification."""


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SpecError("spec must start with '---' frontmatter")
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[1:idx]), "\n".join(lines[idx + 1 :])
    raise SpecError("unterminated frontmatter")


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n")
        return inner
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(part) for part in value[1:-1].split(",") if part.strip()]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_frontmatter(raw: str) -> dict[str, Any]:
    lines = raw.splitlines()
    data: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if len(line) - len(line.lstrip()) != 0:
            raise SpecError(f"unexpected indentation: {line!r}")
        key, sep, value = line.partition(":")
        if not sep:
            raise SpecError(f"not a mapping line: {line!r}")
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = _parse_scalar(value)
            i += 1
            continue
        block: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                j += 1
                continue
            if len(nxt) - len(nxt.lstrip()) == 0:
                break
            block.append(nxt)
            j += 1
        data[key] = _parse_block(block)
        i = j
    return data


def _parse_block(lines: list[str]) -> Any:
    items = [line for line in lines if line.strip()]
    if not items:
        return None
    if items[0].lstrip().startswith("-"):
        out = []
        for line in items:
            stripped = line.lstrip()
            if not stripped.startswith("-"):
                raise SpecError(f"mixed list block: {line!r}")
            out.append(_parse_scalar(stripped[1:].strip()))
        return out
    out: dict[str, Any] = {}
    for line in items:
        key, sep, value = line.strip().partition(":")
        if not sep:
            raise SpecError(f"not a mapping line in block: {line!r}")
        out[key.strip()] = _parse_scalar(value.strip())
    return out


def _canonical(meta: dict[str, Any], body: str) -> str:
    return json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" + body


@dataclass
class Spec:
    path: Path
    meta: dict[str, Any]
    body: str
    sha: str = field(default="")

    @classmethod
    def load(cls, path: str | Path) -> Spec:
        p = Path(path)
        return cls.from_text(p.read_text(encoding="utf-8"), p)

    @classmethod
    def from_text(cls, raw: str, path: str | Path) -> Spec:
        fm, body = split_frontmatter(raw)
        meta = parse_frontmatter(fm)
        sha = hashlib.sha256(_canonical(meta, body).encode("utf-8")).hexdigest()
        return cls(path=Path(path), meta=meta, body=body, sha=sha)

    @classmethod
    def from_git(cls, repo: str | Path, rev: str, path: str | Path) -> Spec:
        proc = _git(Path(repo), "show", f"{rev}:{path}")
        if proc.returncode != 0:
            raise SpecError(f"spec not in {rev}: {path}")
        return cls.from_text(proc.stdout, path)

    # ── fields ─────────────────────────────────────────────────────────────
    @property
    def id(self) -> str:
        return str(self.meta.get("id", "")).strip()

    @property
    def title(self) -> str:
        return str(self.meta.get("title", "")).strip()

    @property
    def risk(self) -> str:
        return str(self.meta.get("risk", "low")).strip()

    @property
    def deps(self) -> list[str]:
        return [str(x) for x in (self.meta.get("deps") or [])]

    @property
    def allowed_paths(self) -> list[str]:
        return [str(x) for x in (self.meta.get("allowed_paths") or [])]

    @property
    def oracle_paths(self) -> list[str]:
        return [str(x) for x in (self.meta.get("oracle_paths") or [])]

    @property
    def gate_inputs(self) -> list[str]:
        return [str(x) for x in (self.meta.get("gate_inputs") or [])]

    @property
    def dod(self) -> str:
        return str(self.meta.get("dod") or "").strip()

    @property
    def negative_corpus(self) -> str:
        nc = self.meta.get("negative_control") or {}
        if isinstance(nc, dict):
            return str(nc.get("corpus", "")).strip()
        return ""

    @property
    def budget(self) -> dict[str, Any]:
        budget = self.meta.get("budget") or {}
        return budget if isinstance(budget, dict) else {}

    # ── validation ─────────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("id is required")
        elif self.path.stem != self.id:
            errors.append(f"id {self.id!r} does not match filename {self.path.stem!r}")
        if self.risk not in RISKS:
            errors.append(f"risk must be one of {sorted(RISKS)}")
        if not self.allowed_paths:
            errors.append("allowed_paths is required")
        for label, paths in (
            ("allowed_paths", self.allowed_paths),
            ("oracle_paths", self.oracle_paths),
            ("gate_inputs", self.gate_inputs),
        ):
            for path in paths:
                if not path or ABSOLUTE_OR_ESCAPE.search(path):
                    errors.append(f"{label}: unsafe path {path!r}")
        if not self.dod:
            errors.append("dod is required")
        if "\n" in self.dod:
            errors.append("dod must be a single line")
        if self.risk in {"medium", "high"} and not self.negative_corpus:
            errors.append("negative_control.corpus is required for medium/high risk")
        return errors

    def validate_against_repo(self, repo: str | Path, base: str) -> list[str]:
        errors = self.validate()
        root = Path(repo)
        if not (root / ".git").exists():
            errors.append(f"{root} is not a git repository")
            return errors
        for path in self.oracle_paths:
            if not _path_in_git(root, base, path):
                errors.append(f"oracle path not in {base}: {path}")
        if self.negative_corpus and not _path_in_git(root, base, self.negative_corpus):
            errors.append(f"negative corpus not in {base}: {self.negative_corpus}")
        return errors


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _path_in_git(repo: Path, rev: str, path: str) -> bool:
    proc = _git(repo, "ls-tree", "-r", "--name-only", rev, "--", path)
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def load_spec_for_task(repo: str | Path, spec_path: str) -> Spec:
    root = Path(repo)
    path = root / spec_path
    if not path.exists():
        raise SpecError(f"spec not found: {path}")
    spec = Spec.load(path)
    errors = spec.validate()
    if errors:
        raise SpecError("; ".join(errors))
    return spec


def load_for(repo: str | Path, base: str, spec_path: str) -> Spec:
    """Load the spec at ``base`` first; fall back to the working tree."""
    try:
        return Spec.from_git(repo, base, spec_path)
    except (SpecError, OSError):
        path = Path(repo) / spec_path
        if not path.exists():
            raise SpecError(f"spec not found: {spec_path} (base {base})") from None
        return Spec.load(path)
