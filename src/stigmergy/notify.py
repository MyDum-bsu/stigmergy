"""Outbound notification adapters: Telegram or a generic webhook.

Dry-run is the default. Real sends require an explicit ``--send`` from the
human CLI; the token is read from the environment named in config, never from
the repository.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from stigmergy.config import Config


def _telegram_url(token: str) -> str:
    return f"https://api.telegram.org/bot{token}/sendMessage"


def channels(config: Config) -> list[dict[str, str]]:
    section = config.section("notify")
    out: list[dict[str, str]] = []
    chat_id = str(section.get("telegram_chat_id") or "").strip()
    token_env = str(section.get("telegram_token_env") or "STG_TELEGRAM_TOKEN").strip()
    if chat_id:
        out.append(
            {
                "kind": "telegram",
                "chat_id": chat_id,
                "token_env": token_env,
                "token": os.environ.get(token_env, ""),
            }
        )
    webhook = str(section.get("webhook_url") or "").strip()
    if webhook:
        out.append({"kind": "webhook", "url": webhook})
    return out


def send(config: Config, text: str, *, send_now: bool = False, timeout: int = 15) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {"ok": False, "detail": "empty notification", "sent": 0, "results": []}
    items = channels(config)
    if not items:
        return {"ok": False, "detail": "no notify channels configured", "sent": 0, "results": []}
    results: list[dict[str, Any]] = []
    sent = 0
    for item in items:
        if item["kind"] == "telegram":
            token = item.get("token", "")
            payload = {"chat_id": item["chat_id"], "text": text[:4000]}
            if not send_now:
                results.append(
                    {
                        "kind": "telegram",
                        "dry_run": True,
                        "url": "https://api.telegram.org/bot<token>/sendMessage",
                        "token": "set" if token else "missing",
                        "payload": payload,
                    }
                )
                continue
            if not token:
                results.append({"kind": "telegram", "ok": False, "detail": "token missing"})
                continue
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                _telegram_url(token),
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read(5000)
                ok = 200 <= response.status < 300
                results.append({"kind": "telegram", "ok": ok, "response": data.decode("utf-8", "replace")[:500]})
                sent += int(ok)
            except Exception as exc:  # network/provider failure is a result
                results.append({"kind": "telegram", "ok": False, "detail": str(exc)[:500]})
        else:
            payload = {"text": text[:4000], "source": "stigmergy"}
            if not send_now:
                results.append({"kind": "webhook", "dry_run": True, "url": item["url"], "payload": payload})
                continue
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                item["url"],
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read(5000)
                ok = 200 <= response.status < 300
                results.append({"kind": "webhook", "ok": ok, "response": data.decode("utf-8", "replace")[:500]})
                sent += int(ok)
            except Exception as exc:
                results.append({"kind": "webhook", "ok": False, "detail": str(exc)[:500]})
    return {
        "ok": all(item.get("dry_run") or item.get("ok") for item in results),
        "sent": sent,
        "dry_run": not send_now,
        "results": results,
        "endpoint": urllib.parse.urlparse(items[0].get("url", "")).hostname or items[0]["kind"],
    }
