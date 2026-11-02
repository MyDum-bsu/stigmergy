"""Local plan page: read the plan, then approve or reject it with one click."""

from __future__ import annotations

import html
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from stigmergy import human, intake, planinbox
from stigmergy.config import Config
from stigmergy.log import Board

ACTION_PATH = re.compile(r"^/plan/(?P<plan>[^/]+)/action/(?P<action>[^/]+)$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 64 * 1024


def _host_name(raw: str) -> str:
    """``Host`` without the port, IPv6 literal included."""
    value = raw.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def _with_key(markup: str, key: str) -> str:
    """Carry the page key through a round trip: submit URLs and the back link."""
    suffix = quote(key, safe="")
    markup = re.sub(
        r'action="([^"?]+)"', lambda m: f'action="{m.group(1)}?key={suffix}"', markup
    )
    return markup.replace('href="/"', f'href="/?key={suffix}"')


def review_html(
    config: Config, board: Board, task_id: str, page_key: str, *, secret: str = ""
) -> str:
    data = intake.plan_show(config, task_id)
    title = html.escape(task_id)
    state = planinbox.plan_state(config, board, task_id)
    lane = planinbox.plan_lane(config, task_id)
    sha = planinbox.spec_sha(config, task_id)
    actions = ""
    if sha and secret:
        actions = planinbox.actions_html(
            task_id, spec_sha=sha, secret=secret, lane=lane, state=state
        )
        actions = _with_key(actions, page_key)
    if actions:
        hint = ""
    elif not sha:
        hint = '<div class="bar">The planner has not written a draft spec yet.</div>'
    elif lane == "fast":
        hint = '<div class="bar">Fast lane: policy approves this plan, there is nothing to click.</div>'
    else:
        hint = f'<div class="bar">Decision already recorded: <code>{html.escape(state)}</code></div>'
    body = "\n".join(
        f"<section><h2>{label}</h2><pre>{html.escape(data.get(field, '') or '(empty)')}</pre></section>"
        for field, label in (("prd", "PRD"), ("spec", "SPEC"), ("request", "RAW REQUEST"))
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Plan · {title}</title><style>
body{{margin:0 auto;max-width:920px;padding:24px;background:#101012;color:#ece9e4;
font:15px/1.5 system-ui,sans-serif}}h1{{font-size:24px;margin:0 0 8px}}
h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#f4d345;margin:26px 0 8px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#19191c;border:1px solid #333337;
border-radius:10px;padding:14px}}form{{display:inline-flex;gap:8px;align-items:center;margin:8px 8px 8px 0}}
button{{background:#f4d345;color:#101012;border:0;border-radius:8px;padding:9px 14px;font-weight:600}}
button.reject{{background:#3a1d1d;color:#ffb3ab}}.bar{{border-left:3px solid #f4d345;padding:10px 12px;
background:#19191c;border-radius:8px;margin:12px 0}}.actions{{margin-top:26px;padding-top:14px;
border-top:1px solid #333337}}code{{color:#f4d345}}
</style></head><body>
<h1>Plan · {title}</h1>
<p>Approve is the only human step; reject sends the plan back to the planner.</p>
{hint}
<div class="bar">state: <code>{html.escape(state)}</code> · lane: <code>{html.escape(lane)}</code></div>
{body}
{actions}</body></html>"""


def _read_form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    raw = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(raw)
    except ValueError:
        return {}
    if length <= 0:
        return {}
    return parse_qs(handler.rfile.read(min(length, MAX_BODY)).decode("utf-8", "replace"))


def make_server(
    config: Config,
    board: Board,
    task_id: str,
    *,
    port: int = 8788,
    secret: str | None = None,
    key: str | None = None,
) -> ThreadingHTTPServer:
    """A loopback-only plan page; the token secret lives in this closure."""
    page_key = key or secrets.token_urlsafe(18)
    signing = secret or planinbox.new_secret()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "stg-plan/1"

        def log_message(self, *_args: Any) -> None:
            # The request line can carry a token: the plan inbox logs nothing.
            return

        def _send(self, code: int, body: str) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def _host_ok(self) -> bool:
            return _host_name(self.headers.get("Host") or "") in LOCAL_HOSTS

        def _key_ok(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return secrets.compare_digest(query.get("key", [""])[0], page_key)

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                self._send(403, planinbox.message("forbidden", task_id, "unexpected host"))
                return
            if ACTION_PATH.match(urlparse(self.path).path):
                self._send(
                    405,
                    _with_key(
                        planinbox.message("method not allowed", task_id, "actions are POST-only"),
                        page_key,
                    ),
                )
                return
            if not self._key_ok():
                self._send(403, planinbox.message("forbidden", task_id, "bad or expired page key"))
                return
            try:
                page = review_html(config, board, task_id, page_key, secret=signing)
            except Exception as exc:  # boundary: the page says why it cannot render
                self._send(500, planinbox.message("plan not readable", task_id, str(exc)))
                return
            self._send(200, page)

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                self._send(403, planinbox.message("forbidden", task_id, "unexpected host"))
                return
            match = ACTION_PATH.match(urlparse(self.path).path)
            if not match:
                self._send(
                    404,
                    planinbox.message(
                        "not found",
                        task_id,
                        "POST is accepted on /plan/<id>/action/<approve|reject> only",
                    ),
                )
                return
            if not self._key_ok():
                self._send(403, planinbox.message("forbidden", task_id, "bad or expired page key"))
                return
            plan_id = unquote(match.group("plan"))
            action = unquote(match.group("action"))
            if plan_id != task_id:
                self._send(404, planinbox.message("not found", plan_id, "no such plan"))
                return
            try:
                status, body = self._decide(plan_id, action, _read_form(self))
            except Exception as exc:  # boundary: a board fault is a 5xx, not a dropped request
                status, body = 500, planinbox.message("apply failed", plan_id, str(exc))
            self._send(status, _with_key(body, page_key))

        def _decide(self, plan_id: str, action: str, form: dict[str, list[str]]) -> tuple[int, str]:
            token = form.get("token", [""])[0]
            rendered_sha = form.get("spec_sha", [""])[0]
            if not planinbox.plan_exists(config, board, plan_id):
                return 404, planinbox.message("not found", plan_id, "no such plan")
            if not planinbox.token_matches(plan_id, rendered_sha, signing, token):
                return 403, planinbox.message("forbidden", plan_id, "bad or expired token")
            current_sha = planinbox.spec_sha(config, plan_id)
            if rendered_sha != current_sha:
                return 409, planinbox.message("conflict", plan_id, "spec changed since render")

            def apply(decision: str) -> None:
                gaps = planinbox.precondition_gaps(config, plan_id, decision)
                if gaps:
                    raise planinbox.Blocked(
                        "high risk preflight is not green: " + "; ".join(gaps)
                    )
                planinbox.apply_decision(config, board, plan_id, decision, via="inbox")

            with lock:
                state = planinbox.plan_state(config, board, plan_id)
                try:
                    return planinbox.handle_action(
                        plan_id,
                        action,
                        token=token,
                        spec_sha=current_sha,
                        secret=signing,
                        state=state,
                        apply=apply,
                    )
                except planinbox.Blocked as exc:
                    return 409, planinbox.message("conflict", plan_id, str(exc))
                except Exception as exc:  # boundary: 5xx plus the cause, never a success page
                    return 500, planinbox.message("apply failed", plan_id, str(exc))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(
    config: Config,
    board: Board,
    task_id: str,
    *,
    port: int = 8788,
    open_browser: bool = False,
) -> None:
    human.require()
    key = secrets.token_urlsafe(18)
    server = make_server(config, board, task_id, port=port, key=key)
    url = f"http://127.0.0.1:{server.server_address[1]}/?key={key}"
    if open_browser:
        webbrowser.open(url)
    print(url, flush=True)
    server.serve_forever()
