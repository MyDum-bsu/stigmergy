from __future__ import annotations

import http.client
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import pytest

from stigmergy import human, intake, planinbox, planui
from stigmergy.cli import main
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState

SECRET = "unit-secret"
SHA = "0123456789abcdef"
KEY = "page-key"


def _spec(task_id: str, *, risk: str = "medium", extra: str = "") -> str:
    return f"""---
id: {task_id}
title: plan inbox fixture
risk: {risk}
{extra}allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
dod: python3 test_gate.py
negative_control:
  corpus: oracle/negative/T1/
---
Fixture body.
"""


def _plan(
    repo: Path, *, risk: str = "medium", extra: str = "", idea: str = "plan inbox"
) -> tuple[Config, Board, str]:
    config = Config.load(repo)
    board = Board(repo)
    task_id = intake.create_task(config, board, f"{idea} {risk} {extra}", start_planner=False)["task"]
    intake.paths_for(config, task_id)["spec"].write_text(_spec(task_id, risk=risk, extra=extra), encoding="utf-8")
    return config, board, task_id


def _events(board: Board) -> list[dict]:
    return board.read()


def _decisions(board: Board, task_id: str, action: str) -> list[dict]:
    return [
        event
        for event in board.read()
        if event["action"] == action and (event.get("attributes") or {}).get("task.id") == task_id
    ]


def _token_of(page: str) -> str:
    match = re.search(r'name="token" value="([0-9a-f]{64})"', page)
    assert match, page[:500]
    return match.group(1)


def _sha_of(page: str) -> str:
    match = re.search(r'name="spec_sha" value="([0-9a-f]{64})"', page)
    assert match, page[:500]
    return match.group(1)


@contextmanager
def _serving(config: Config, board: Board, task_id: str, *, secret: str = SECRET):
    server = planui.make_server(config, board, task_id, port=0, secret=secret, key=KEY)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _call(server, method: str, path: str, body: dict | None = None, host: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    headers = {}
    payload = None
    if body is not None:
        payload = urlencode(body)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if host:
        headers["Host"] = host
    try:
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        conn.close()


# ── module contract beyond the oracle ─────────────────────────────────────
def test_actions_html_needs_a_secret_and_known_lane_and_state():
    with pytest.raises(ValueError):
        planinbox.actions_html("p1", spec_sha=SHA, secret="", lane="normal", state="pending")
    with pytest.raises(ValueError):
        planinbox.actions_html("p1", spec_sha=SHA, secret=SECRET, lane="turbo", state="pending")
    with pytest.raises(ValueError):
        planinbox.actions_html("p1", spec_sha=SHA, secret=SECRET, lane="normal", state="maybe")


def test_pending_forms_carry_the_spec_digest_but_not_the_secret():
    html = planinbox.actions_html("p1", spec_sha=SHA, secret=SECRET, lane="high", state="pending")
    assert html.count(f'name="spec_sha" value="{SHA}"') == 2
    assert SECRET not in html
    assert html.count("/plan/p1/action/") == 2


def test_plan_id_is_never_a_path():
    assert planinbox.plan_id_ok("t-20261102-171709-plan-inbox-67b1f0")
    assert not planinbox.plan_id_ok("../etc/passwd")
    assert not planinbox.plan_id_ok("a/b")
    assert not planinbox.plan_id_ok("")


# ── projection and application ────────────────────────────────────────────
def test_plan_state_follows_the_board(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    assert planinbox.plan_state(config, board, task_id) == "pending"
    assert planinbox.plan_lane(config, task_id) == "normal"
    planinbox.apply_decision(config, board, task_id, "approve")
    assert planinbox.plan_state(config, board, task_id) == "approved"
    approved = _decisions(board, task_id, "plan.approved")
    assert len(approved) == 1
    assert approved[0]["attributes"]["via"] == "inbox"
    assert ProjectState.from_events(board.read()).task(task_id).status == "queued"


def test_reject_marks_the_task_and_the_event(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    planinbox.apply_decision(config, board, task_id, "reject")
    assert planinbox.plan_state(config, board, task_id) == "rejected"
    rejected = _decisions(board, task_id, "task.rejected")
    assert len(rejected) == 1
    assert rejected[0]["attributes"]["via"] == "inbox"
    assert ProjectState.from_events(board.read()).task(task_id).status == "rejected"


def test_apply_decision_refuses_unknown_actions(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with pytest.raises(ValueError):
        planinbox.apply_decision(config, board, task_id, "delete")
    assert not _decisions(board, task_id, "plan.approved")


def test_cli_approve_and_reject_use_the_same_path(repo: Path, monkeypatch, tmp_path, capsys) -> None:
    config, board, rejected_id = _plan(repo, idea="cli reject")
    _, _, approved_id = _plan(repo, idea="cli approve")
    token = tmp_path / "human.token"
    token.write_text("0" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr(human, "TOKEN_PATH", token)
    assert main(["--board", str(repo), "plan", "reject", rejected_id, "--json"]) == 0
    assert main(["--board", str(repo), "plan", "approve", approved_id, "--json"]) == 0
    capsys.readouterr()
    rejected = _decisions(board, rejected_id, "task.rejected")
    approved = _decisions(board, approved_id, "plan.approved")
    assert len(rejected) == 1 and rejected[0]["attributes"]["via"] == "cli"
    assert len(approved) == 1 and approved[0]["attributes"]["via"] == "cli"
    assert planinbox.plan_state(config, board, rejected_id) == "rejected"
    assert planinbox.plan_state(config, board, approved_id) == "approved"


# ── HTTP wrapper ──────────────────────────────────────────────────────────
def test_page_requires_the_key_and_a_local_host(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        assert _call(server, "GET", f"/?key={KEY}")[0] == 200
        assert _call(server, "GET", "/")[0] == 403
        assert _call(server, "GET", "/?key=nope")[0] == 403
        status, body = _call(server, "GET", f"/?key={KEY}", host="evil.example")
        assert status == 403 and "unexpected host" in body


def test_page_shows_both_actions_for_a_pending_normal_plan(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        status, page = _call(server, "GET", f"/?key={KEY}")
        assert status == 200
        assert f"/plan/{task_id}/action/approve" in page
        assert f"/plan/{task_id}/action/reject" in page
        assert page.count(_token_of(page)) == 2


def test_click_approve_writes_exactly_one_inbox_event(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    before = len(_events(board))
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 200
        assert "approved" in answer
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 409
    approved = _decisions(board, task_id, "plan.approved")
    assert len(approved) == 1
    assert approved[0]["attributes"]["via"] == "inbox"
    assert approved[0]["actor"] == {"kind": "human", "name": "human"}
    assert len(_events(board)) > before


def test_click_reject_marks_the_plan_rejected(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/reject?key={KEY}", body)
        assert status == 200 and "rejected" in answer
    rejected = _decisions(board, task_id, "task.rejected")
    assert len(rejected) == 1
    assert rejected[0]["attributes"]["via"] == "inbox"
    assert planinbox.plan_state(config, board, task_id) == "rejected"


def test_forged_token_and_unknown_plan_change_nothing(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": "deadbeef", "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 403
        assert "pending" not in answer and "approved" not in answer
        status, _ = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", {})
        assert status == 403
        status, _ = _call(server, "POST", f"/plan/t-missing/action/approve?key={KEY}", body)
        assert status == 404
        status, _ = _call(server, "POST", f"/plan/{task_id}/action/approve", body)
        assert status == 403
        status, _ = _call(server, "POST", f"/plan/{task_id}/nope?key={KEY}", body)
        assert status == 404
    assert not _decisions(board, task_id, "plan.approved")


def test_get_on_the_action_path_never_decides(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        status, answer = _call(server, "GET", f"/plan/{task_id}/action/approve?key={KEY}")
        assert status == 405 and "POST-only" in answer
    assert not _decisions(board, task_id, "plan.approved")


def test_spec_edited_after_render_is_a_conflict(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        spec = intake.paths_for(config, task_id)["spec"]
        spec.write_text(spec.read_text(encoding="utf-8") + "\nedited after render\n", encoding="utf-8")
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 409 and "spec changed since render" in answer
    assert not _decisions(board, task_id, "plan.approved")


def test_high_risk_approve_requires_a_green_preflight(repo: Path) -> None:
    extra = "invariants:\n  - one event per action\nproperties:\n  command: python3 test_gate.py\n"
    config, board, task_id = _plan(repo, risk="high", extra=extra)
    assert planinbox.plan_lane(config, task_id) == "high"
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 409
        assert "preflight" in answer and "formal" in answer
    assert not _decisions(board, task_id, "plan.approved")
    assert planinbox.plan_state(config, board, task_id) == "pending"


def test_high_risk_approve_passes_with_green_artifacts(repo: Path) -> None:
    extra = "invariants:\n  - one event per action\nproperties:\n  command: python3 test_gate.py\n"
    config, board, task_id = _plan(repo, risk="high", extra=extra)
    spec = intake.paths_for(config, task_id)["spec"]
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "---\nFixture body.",
            "formal:\n"
            "  model: formal/model.tla\n"
            "  config: formal/model.cfg\n"
            "  mutant_model: formal/mutant.tla\n"
            "  mutant_cfg: formal/mutant.cfg\n"
            "mutations:\n"
            "  - python3 test_gate.py\n"
            "---\nFixture body.",
        ),
        encoding="utf-8",
    )
    for name in ("model.tla", "model.cfg", "mutant.tla", "mutant.cfg"):
        (repo / "formal" / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / "formal" / name).write_text("---- MODULE fixture ----\n", encoding="utf-8")
    report = repo / ".factory" / "critic" / f"{task_id}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"findings": []}), encoding="utf-8")
    assert planinbox.high_risk_gaps(config, task_id) == []
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 200, answer
    assert len(_decisions(board, task_id, "plan.approved")) == 1


def test_apply_failure_is_a_500_with_the_cause(repo: Path, monkeypatch) -> None:
    config, board, task_id = _plan(repo)

    def boom(*_args, **_kwargs):
        raise RuntimeError("git commit failed: index.lock")

    monkeypatch.setattr(planinbox, "apply_decision", boom)
    with _serving(config, board, task_id) as server:
        _, page = _call(server, "GET", f"/?key={KEY}")
        body = {"token": _token_of(page), "spec_sha": _sha_of(page)}
        status, answer = _call(server, "POST", f"/plan/{task_id}/action/approve?key={KEY}", body)
        assert status == 500
        assert "git commit failed" in answer
        assert "approved" not in answer
    assert not _decisions(board, task_id, "plan.approved")


def test_decided_plan_page_has_no_forms(repo: Path) -> None:
    config, board, task_id = _plan(repo)
    planinbox.apply_decision(config, board, task_id, "approve")
    with _serving(config, board, task_id) as server:
        status, page = _call(server, "GET", f"/?key={KEY}")
        assert status == 200
        assert f"/plan/{task_id}/action/approve" not in page
        assert "approved" in page


def test_fast_lane_page_has_no_forms(repo: Path) -> None:
    config = Config.load(repo)
    config.raw["factory"] = {"auto_approve": True}
    board = Board(repo)
    task_id = intake.create_task(config, board, "fast lane page", start_planner=False)["task"]
    spec = intake.paths_for(config, task_id)["spec"]
    spec.write_text(
        f"""---
id: {task_id}
title: fast lane fixture
risk: low
auto_approve: true
allowed_paths:
  - src.txt
oracle_paths:
  - test_gate.py
dod: python3 test_gate.py
---
Fast lane body.
""",
        encoding="utf-8",
    )
    assert planinbox.plan_lane(config, task_id) == "fast"
    with _serving(config, board, task_id) as server:
        status, page = _call(server, "GET", f"/?key={KEY}")
        assert status == 200
        assert "/action/approve" not in page
        assert "Fast lane" in page
