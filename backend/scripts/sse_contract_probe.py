#!/usr/bin/env python3
"""Probe a running backend for canonical SSE event names and JSON shapes."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def request(base_url: str, method: str, path: str, body: dict | None = None, token: str = ""):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            text = response.read().decode("utf-8")
            return response.status, text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        return exc.code, text


def json_request(base_url: str, method: str, path: str, body: dict | None = None, token: str = ""):
    status, text = request(base_url, method, path, body, token)
    return status, json.loads(text) if text else {}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        event_name = ""
        data = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_name:
            events.append((event_name, data))
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    suffix = str(int(time.time() * 1000))

    status, body = json_request(
        args.base_url,
        "POST",
        "/api/v1/auth/register",
        {
            "tenant_name": f"sse-probe-{suffix}",
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert status == 200, body
    token = body["access_token"]

    status, body = json_request(
        args.base_url,
        "POST",
        "/api/v1/conversations/",
        {"title": "sse-probe"},
        token,
    )
    assert status == 200, body
    conv_id = body["id"]

    status, text = request(
        args.base_url,
        "POST",
        f"/api/v1/conversations/{conv_id}/chat",
        {"content": "Please answer with exactly: pong"},
        token,
    )
    assert status == 200, text[:500]
    events = parse_sse(text)
    event_names = [name for name, _ in events]
    assert "text" in event_names or "error" in event_names, event_names
    assert "done" in event_names, event_names
    assert "tool_call_start" not in event_names, event_names
    assert "tool_error" not in event_names, event_names
    for name, data in events:
        assert isinstance(data, dict), (name, data)
        if name == "error":
            assert set(["code", "message", "detail"]).issubset(data["error"]), data

    print(json.dumps({"ok": True, "events": event_names}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise
