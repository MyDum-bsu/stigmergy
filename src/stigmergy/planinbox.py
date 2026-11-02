"""Plan inbox: a human approves or rejects a plan with one click.

A plan page served by ``stg plan serve`` carries one POST form per action. The
form token is an HMAC over the plan id and the spec digest, keyed with a secret
that exists only in the serving process: an agent tab cannot mint one, and a
page rendered before a spec edit stops working.

``handle_action`` is pure: it picks the status code and calls ``apply`` at most
once. The caller owns the effect, so the HTTP layer and the CLI share one
application path (``apply_decision``) and differ only in audit attributes.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import secrets
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from stigmergy import critic, intake, policy
from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState
from stigmergy.spec import Spec, SpecError

PLAN_ACTIONS: tuple[str, str] = ("approve", "reject")
LANES: tuple[str, ...] = ("normal", "high", "fast")
STATES: tuple[str, ...] = ("pending", "approved", "rejected")

REJECT_REASON = "rejected from the plan inbox"

#: Board actions that decide a plan; the last one for a task wins.
DECISIONS = {"plan.approved": "approved", "task.rejected": "rejected"}
#: The state each action records.
APPLIED = {"approve": "approved", "reject": "rejected"}
#: A plan whose task already moved past approval is decided, not pending.
ADVANCED = {
    "task.claimed",
    "workspace.created",
    "episode.started",
    "gate.passed",
    "integration.passed",
    "merge.done",
    "task.done",
}
#: A re-proposed task starts a fresh plan and needs a fresh decision.
REOPENED = {"task.created", "task.proposed"}

PLAN_ID = re.compile(r"^[^\W_][\w.-]{0,199}$")
FORMAL_FILES = ("model", "config", "mutant_model", "mutant_cfg")


class Blocked(RuntimeError):
    """The inbox refuses to apply the action: a precondition is not green."""


# ── token ──────────────────────────────────────────────────────────────────
def _require(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"planinbox: {name} is required")
    return value


def new_secret() -> str:
    """A per-server HMAC key; it never reaches the page or the log."""
    return secrets.token_urlsafe(32)


def action_token(plan_id: str, spec_sha: str, secret: str) -> str:
    _require("plan_id", plan_id)
    _require("spec_sha", spec_sha)
    _require("secret", secret)
    message = f"{plan_id}\n{spec_sha}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def token_matches(plan_id: str, spec_sha: str, secret: str, token: str) -> bool:
    """Constant-time token check; an absent or unparsable token is never valid."""
    if not isinstance(token, str) or not token:
        return False
    try:
        expected = action_token(plan_id, spec_sha, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, token)


# ── rendering ──────────────────────────────────────────────────────────────
def message(title: str, plan_id: str, detail: str = "", notes: Iterable[str] = ()) -> str:
    """A short answer page: the state, the task, the reason. No JS, no redirect."""
    items = "".join(f"<li>{html.escape(str(note))}</li>" for note in notes)
    listing = f"<ul>{items}</ul>" if items else ""
    reason = f"<p>{html.escape(detail)}</p>" if detail else ""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>"
        "body{margin:0 auto;max-width:640px;padding:24px;background:#101012;"
        "color:#ece9e4;font:15px/1.5 system-ui,sans-serif}"
        "h1{font-size:22px;margin:0 0 6px}code{color:#f4d345}a{color:#f4d345}"
        "</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>plan <code>{html.escape(plan_id)}</code></p>"
        f"{reason}{listing}"
        "<p><a href=\"/\">back to the plan</a></p>"
        "</body></html>"
    )


def actions_html(
    plan_id: str, *, spec_sha: str, secret: str, lane: str, state: str
) -> str:
    """Both action forms for a pending human decision; ``""`` when there is none."""
    if lane not in LANES:
        raise ValueError(f"planinbox: lane must be one of {LANES}, got {lane!r}")
    if state not in STATES:
        raise ValueError(f"planinbox: state must be one of {STATES}, got {state!r}")
    if lane == "fast" or state != "pending":
        return ""
    token = action_token(plan_id, spec_sha, secret)
    slug = quote(plan_id, safe="")
    forms = "".join(
        f'<form method="post" action="/plan/{slug}/action/{action}">'
        f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
        f'<input type="hidden" name="spec_sha" value="{html.escape(spec_sha, quote=True)}">'
        f'<button type="submit" class="{action}">{label}</button></form>'
        for action, label in (("approve", "Approve"), ("reject", "Reject"))
    )
    return f'<div class="actions">{forms}</div>'


# ── pure handler ───────────────────────────────────────────────────────────
def handle_action(
    plan_id: str,
    action: str,
    *,
    token: str,
    spec_sha: str,
    secret: str,
    state: str,
    apply: Callable[[str], None],
) -> tuple[int, str]:
    """Decide the status for one click; call ``apply`` at most once.

    The token is checked before the state so a forged click on a decided plan
    cannot tell a decided plan from a pending one. Failures of ``apply`` are not
    swallowed: the caller maps them to a 5xx.
    """
    if not token_matches(plan_id, spec_sha, secret, token):
        return 403, message("forbidden", plan_id, "bad or expired token")
    if action not in PLAN_ACTIONS:
        return 400, message("bad request", plan_id, f"unknown action: {action}")
    if state not in STATES:
        raise ValueError(f"planinbox: state must be one of {STATES}, got {state!r}")
    if state != "pending":
        return 409, message("conflict", plan_id, f"plan already decided: {state}")
    apply(action)
    return 200, message(APPLIED[action], plan_id, "decision recorded")


# ── projection over the board ──────────────────────────────────────────────
def plan_id_ok(plan_id: str) -> bool:
    """A plan id is a path segment, never a traversal."""
    return bool(PLAN_ID.fullmatch(plan_id or "")) and ".." not in (plan_id or "")


def plan_exists(config: Config, board: Board, plan_id: str) -> bool:
    if not plan_id_ok(plan_id):
        return False
    paths = intake.paths_for(config, plan_id)
    if any(paths[key].is_file() for key in ("request", "prd", "spec")):
        return True
    state = ProjectState.from_events(board.read(), project=config.name)
    return plan_id in state.tasks


def plan_state(config: Config, board: Board, plan_id: str) -> str:
    """``pending`` until a decision event, ``approved`` once the task moved on."""
    decision = ""
    advanced = False
    for event in board.read():
        attributes = event.get("attributes") or {}
        if attributes.get("task.id") != plan_id:
            continue
        name = str(event.get("action", ""))
        if name in DECISIONS:
            decision = DECISIONS[name]
        elif name in ADVANCED:
            advanced = True
        elif name in REOPENED:
            decision, advanced = "", False
    if decision:
        return decision
    return "approved" if advanced else "pending"


def draft_spec(config: Config, plan_id: str) -> Spec | None:
    """The planner draft, or ``None`` while the planner has not written one."""
    path = intake.paths_for(config, plan_id)["spec"]
    if not path.is_file():
        return None
    return Spec.from_text(path.read_text(encoding="utf-8"), path)


def spec_sha(config: Config, plan_id: str) -> str:
    spec = draft_spec(config, plan_id)
    return spec.sha if spec is not None else ""


def plan_lane(config: Config, plan_id: str) -> str:
    """``high`` by risk, ``fast`` when policy would auto-approve, else ``normal``."""
    spec = draft_spec(config, plan_id)
    if spec is None:
        return "normal"
    if spec.risk == "high":
        return "high"
    return "fast" if policy.evaluate(config, spec)["ok"] else "normal"


# ── high-risk preconditions ────────────────────────────────────────────────
def _resolve(config: Config, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else config.root / path


def high_risk_gaps(config: Config, plan_id: str) -> list[str]:
    """What a high-risk approve is still missing; empty when it may proceed."""
    try:
        gaps = list(intake.preflight_draft(config, plan_id)["errors"])
        spec = draft_spec(config, plan_id)
    except SpecError as exc:
        return [f"draft spec is not readable: {exc}"]
    if spec is None:
        return list(dict.fromkeys(gaps)) or [f"no draft spec: {plan_id}"]
    formal = spec.formal
    if not formal:
        gaps.append("formal: spec has no formal block (model/config/mutant_model/mutant_cfg)")
    else:
        for key in FORMAL_FILES:
            if key == "mutant_cfg":
                value = str(formal.get("mutant_cfg") or formal.get("mutant_config") or "").strip()
            else:
                value = str(formal.get(key) or "").strip()
            if not value:
                gaps.append(f"formal: {key} is missing")
            elif not _resolve(config, value).is_file():
                gaps.append(f"formal: {key} not found: {value}")
    if not (spec.meta.get("mutations") or []):
        gaps.append("mutant: spec.mutations has no command")
    verdict = critic.evaluate(config, plan_id)
    if not verdict["ok"]:
        gaps.append(f"critic: {verdict['detail']}")
    if not spec.negative_corpus:
        gaps.append("negative control: negative_control.corpus is missing")
    return list(dict.fromkeys(gaps))


def precondition_gaps(config: Config, plan_id: str, action: str) -> list[str]:
    """Gaps that must stop ``action`` before anything is written to the board."""
    if action != "approve" or plan_lane(config, plan_id) != "high":
        return []
    return high_risk_gaps(config, plan_id)


# ── application ────────────────────────────────────────────────────────────
class _AuthoredBoard:
    """Board proxy: every event of one human action is marked with ``via``.

    The inbox action is human presence, so a decision written through it claims
    the human actor even though ``intake`` labels the CLI approver an agent.
    """

    def __init__(self, board: Board, via: str, actor: str = "human"):
        self._board = board
        self._via = via
        self._actor = actor

    def append(
        self,
        action: str,
        actor: dict[str, str],
        attributes: dict[str, Any] | None = None,
        body: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        attributes = dict(attributes or {})
        attributes["via"] = self._via
        if self._via == "inbox" and actor.get("name") == self._actor:
            actor = {"kind": "human", "name": self._actor}
        return self._board.append(action, actor, attributes, body, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._board, name)


def apply_decision(
    config: Config,
    board: Board,
    plan_id: str,
    action: str,
    *,
    actor: str = "human",
    via: str = "inbox",
) -> dict[str, Any]:
    """The one application path: the same code the CLI approve/reject runs."""
    target = _AuthoredBoard(board, via, actor) if via else board
    if action == "approve":
        return intake.approve_plan(config, target, plan_id, agent=actor)
    if action == "reject":
        return intake.reject_plan(config, target, plan_id, REJECT_REASON)
    raise ValueError(f"planinbox: unknown action {action!r}")
