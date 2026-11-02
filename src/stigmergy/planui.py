"""Local review page for a plan: approve or reject without hand-writing CLI."""

from __future__ import annotations

import html
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from stigmergy import human, intake
from stigmergy.config import Config
from stigmergy.log import Board


def review_html(config: Config, task_id: str, key: str) -> str:
    data = intake.plan_show(config, task_id)
    title = html.escape(task_id)
    body = "\n".join(
        f"<section><h2>{label}</h2><pre>{html.escape(data.get(key, '') or '(empty)')}</pre></section>"
        for key, label in (("prd", "PRD"), ("spec", "SPEC"), ("request", "RAW REQUEST"))
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plan · {title}</title><style>
body{{margin:0 auto;max-width:920px;padding:24px;background:#101012;color:#ece9e4;
font:15px/1.5 system-ui,sans-serif}}h1{{font-size:24px;margin:0 0 8px}}
h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#f4d345;margin:26px 0 8px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#19191c;border:1px solid #333337;
border-radius:10px;padding:14px}}form{{display:inline-flex;gap:8px;align-items:center;margin:8px 8px 8px 0}}
button{{background:#f4d345;color:#101012;border:0;border-radius:8px;padding:9px 14px;font-weight:600}}
button.reject{{background:#3a1d1d;color:#ffb3ab}}input{{background:#19191c;color:#ece9e4;
border:1px solid #444;border-radius:8px;padding:8px}}code{{color:#f4d345}}
</style></head><body>
<h1>Plan · {title}</h1>
<p>Approve is the only human step. Reject sends it back to the planner.</p>
<form method="post" action="/approve"><input type="hidden" name="key" value="{html.escape(key)}">
<button type="submit">Approve</button></form>
<form method="post" action="/reject"><input type="hidden" name="key" value="{html.escape(key)}">
<input name="reason" placeholder="Почему отклонить" required><button class="reject" type="submit">Reject</button></form>
{body}</body></html>"""


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
    url = f"http://127.0.0.1:{port}/?key={key}"
    if open_browser:
        webbrowser.open(url)
    print(url, flush=True)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            if query.get("key", [""])[0] != key:
                self._send(403, "forbidden")
                return
            self._send(200, review_html(config, task_id, key))

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            if form.get("key", [""])[0] != key:
                self._send(403, "forbidden")
                return
            if urlparse(self.path).path == "/approve":
                intake.approve_plan(config, board, task_id)
                self._send(200, "<p>Approved. The dispatcher will start the task.</p>")
            elif urlparse(self.path).path == "/reject":
                intake.reject_plan(config, board, task_id, form.get("reason", [""])[0])
                self._send(200, "<p>Rejected.</p>")
            else:
                self._send(404, "not found")

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
