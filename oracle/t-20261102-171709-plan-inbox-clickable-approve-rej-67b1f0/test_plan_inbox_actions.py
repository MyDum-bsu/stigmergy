"""Oracle for t-20261102-171709-plan-inbox-clickable-approve-rej-67b1f0.

Criterion: the plan inbox exposes one-shot human approve/reject actions for
normal and high lane pending plans, refuses forged tokens before it inspects
state, and applies a decision at most once.
"""

import pytest

from stigmergy.planinbox import PLAN_ACTIONS, action_token, actions_html, handle_action

SECRET = "oracle-secret"
SHA = "abc123def456"


def _call(**overrides):
    applied = []
    kwargs = {
        "plan_id": "p1",
        "action": "approve",
        "token": action_token("p1", SHA, SECRET),
        "spec_sha": SHA,
        "secret": SECRET,
        "state": "pending",
        "apply": applied.append,
    }
    kwargs.update(overrides)
    return handle_action(**kwargs), applied


def test_plan_actions_are_exactly_approve_and_reject():
    assert PLAN_ACTIONS == ("approve", "reject")


def test_action_token_is_deterministic_and_bound():
    token = action_token("p1", SHA, SECRET)
    assert token and isinstance(token, str)
    assert token == action_token("p1", SHA, SECRET)
    assert token != action_token("p2", SHA, SECRET)
    assert token != action_token("p1", "other-sha", SECRET)
    assert token != action_token("p1", SHA, "other-secret")


@pytest.mark.parametrize("lane", ["normal", "high"])
def test_pending_plan_exposes_both_actions(lane):
    html = actions_html("p1", spec_sha=SHA, secret=SECRET, lane=lane, state="pending")
    token = action_token("p1", SHA, SECRET)
    assert html
    assert 'method="post"' in html
    assert "/plan/p1/action/approve" in html
    assert "/plan/p1/action/reject" in html
    assert html.count(token) == 2


@pytest.mark.parametrize(
    ("lane", "state"),
    [
        ("fast", "pending"),
        ("normal", "approved"),
        ("normal", "rejected"),
        ("high", "approved"),
        ("high", "rejected"),
    ],
)
def test_decided_or_auto_approved_plan_has_no_actions(lane, state):
    assert actions_html("p1", spec_sha=SHA, secret=SECRET, lane=lane, state=state) == ""


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_valid_token_applies_the_decision_once(action):
    (status, body), applied = _call(action=action)
    assert status == 200
    assert applied == [action]
    assert action in body


def test_forged_token_is_forbidden_and_changes_nothing():
    (status, _body), applied = _call(token="deadbeef")
    assert status == 403
    assert applied == []


@pytest.mark.parametrize(
    "token",
    [
        action_token("p2", SHA, SECRET),
        action_token("p1", "old-sha", SECRET),
        action_token("p1", SHA, "other-secret"),
    ],
)
def test_token_bound_to_other_plan_or_spec_is_forbidden(token):
    (status, _body), applied = _call(token=token)
    assert status == 403
    assert applied == []


def test_forged_token_on_decided_plan_is_forbidden_not_conflict():
    (status, _body), applied = _call(token="deadbeef", state="approved")
    assert status == 403
    assert applied == []


@pytest.mark.parametrize("state", ["approved", "rejected"])
def test_replay_after_decision_is_conflict(state):
    (status, _body), applied = _call(state=state)
    assert status == 409
    assert applied == []


@pytest.mark.parametrize("action", ["delete", "", "APPROVE"])
def test_unknown_action_is_bad_request(action):
    (status, _body), applied = _call(action=action)
    assert status == 400
    assert applied == []
