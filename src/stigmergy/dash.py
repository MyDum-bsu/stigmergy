"""Minimal stdlib dashboard: projections from events, nothing else."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from stigmergy.config import Config
from stigmergy.log import Board
from stigmergy.model import ProjectState


def project_snapshot(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    board = Board(root)
    config = Config.load(root)
    state = ProjectState.from_events(board.read(), project=config.name)
    tasks = [t.as_dict() for t in state.all()]
    events = board.read()[-80:]
    return {
        "name": config.name,
        "root": str(root),
        "paused": state.paused,
        "counts": _counts(tasks),
        "tasks": tasks,
        "events": events,
    }


def _counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status", "?"))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def snapshot(projects: list[dict[str, str]] | None = None) -> dict[str, Any]:
    from stigmergy.registry import load

    projects = projects or load()
    return {"projects": [project_snapshot(item["root"]) for item in projects]}


HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stigmergy · factory</title>
<style>
:root{--bg:#100e0b;--panel:#16130f;--line:#29231a;--fg:#e9e1d2;--mut:#9a8f7c;--acc:#f2b544;--red:#e2644a;--grn:#8fb36a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
header{display:flex;gap:12px;align-items:baseline;padding:18px 22px;border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0;letter-spacing:.08em;text-transform:uppercase}h1 span{color:var(--acc)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px;padding:16px 22px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
h2{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin:0 0 8px}
table{width:100%;border-collapse:collapse}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left;font-size:12px}
th{color:var(--mut);font-weight:400}.q{color:var(--mut)}.done{color:var(--grn)}.blocked{color:var(--red)}.running{color:var(--acc)}
ul{list-style:none;margin:0;padding:0;max-height:300px;overflow:auto}li{padding:3px 0;border-bottom:1px solid var(--line);font-size:12px}
code{color:var(--acc)}
</style></head><body>
<header><h1>stigmergy <span>·</span> factory</h1><span class="q" id="stamp"></span></header>
<main id="root"></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function render(s){
  document.getElementById('stamp').textContent = new Date().toISOString();
  document.getElementById('root').innerHTML = s.projects.map(p=>`
    <section><h2>${esc(p.name)} ${p.paused?'· PAUSED':''}</h2>
      <div class="q">${esc(p.root)}</div>
      <div>${Object.entries(p.counts).map(([k,v])=>`<span class="${k==='blocked'?'blocked':k==='done'?'done':k==='episode'?'running':'q'}">${esc(k)} ${v}</span>`).join(' · ')}</div>
      <table><tr><th>id</th><th>status</th><th>risk</th><th>title</th></tr>
      ${p.tasks.slice(-40).reverse().map(t=>`<tr><td><code>${esc(t.id)}</code></td><td class="${t.status==='blocked'?'blocked':t.status==='done'?'done':t.status==='episode'?'running':''}">${esc(t.status)}</td><td>${esc(t.risk)}</td><td>${esc(t.title)}</td></tr>`).join('')}
      </table>
      <h2 style="margin-top:12px">events</h2><ul>${p.events.slice(-30).reverse().map(e=>`<li><code>${esc(e.action)}</code> <span class="q">${esc(e.body)}</span></li>`).join('')}</ul>
    </section>`).join('');
}
async function tick(){try{const r=await fetch('/api/state');render(await r.json())}catch(e){}}
tick();setInterval(tick,2000);
</script></body></html>
"""


def make_handler(projects_provider):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # silence
            return

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/state":
                payload = snapshot(projects_provider())
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
                return
            if self.path == "/health":
                self._send(200, b"ok", "text/plain")
                return
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(port: int = 8787, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    from stigmergy.registry import load

    server = ThreadingHTTPServer((host, port), make_handler(load))
    return server


def serve_forever(port: int = 8787, host: str = "127.0.0.1") -> None:
    server = serve(port, host)
    print(f"stg dash: http://{host}:{port}")
    server.serve_forever()


def serve_in_thread(port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    server = serve(port, host)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
