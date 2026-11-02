from __future__ import annotations

from pathlib import Path

from stigmergy import sandbox


def test_worker_argv_masks_secrets_and_binds_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    root = tmp_path / "repo"
    worktree.mkdir()
    (root / ".agent").mkdir(parents=True)
    argv = sandbox.worker_argv(worktree, root, "pi", ["--exclude-tools", "AskUserQuestion"])
    assert argv[0] == "bwrap"
    assert "--ro-bind" in argv
    assert str(worktree) in argv
    assert str(root / ".agent") in argv
    assert "pi" in argv and argv[-1] == "AskUserQuestion"


def test_worker_argv_aa_profile(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    root = tmp_path / "repo"
    worktree.mkdir()
    (root / ".agent").mkdir(parents=True)
    argv = sandbox.worker_argv(worktree, root, "pi", [], aa_profile="zcode")
    assert argv[:4] == ["aa-exec", "-p", "zcode", "--"]
    assert argv[4] == "bwrap"


def test_gate_argv_can_use_aa_prefix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox, "_aa_profile", lambda: "zcode")
    argv = sandbox.gate_argv(tmp_path, [], "true", {}, tmp_path)
    assert argv[:4] == ["aa-exec", "-p", "zcode", "--"]
    assert argv[4] == "bwrap"
