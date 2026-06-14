#!/usr/bin/env python3
"""Probe a running backend for canonical V1 API contract shapes."""

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
        with urllib.request.urlopen(req, timeout=20) as response:
            text = response.read().decode("utf-8")
            return response.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        return exc.code, json.loads(text) if text else {}


def assert_error(body: dict, code: str) -> None:
    error = body.get("error")
    assert isinstance(error, dict), body
    assert error.get("code") == code, body
    assert "message" in error, body
    assert "detail" in error, body


def assert_page(body: dict) -> None:
    assert set(["items", "total", "limit", "offset", "next"]).issubset(body), body
    assert isinstance(body["items"], list), body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    suffix = str(int(time.time() * 1000))

    status_code, body = request(args.base_url, "GET", "/api/v1/conversations/")
    assert status_code == 401, body
    assert_error(body, "AUTH_EXPIRED")

    status_code, body = request(
        args.base_url,
        "POST",
        "/api/v1/auth/register",
        {
            "tenant_name": f"probe-{suffix}",
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert status_code == 200, body
    token = body["access_token"]

    status_code, body = request(args.base_url, "GET", "/api/v1/conversations/?limit=1&offset=0", token=token)
    assert status_code == 200, body
    assert_page(body)

    status_code, body = request(args.base_url, "POST", "/api/v1/auth/refresh", token=token)
    assert status_code == 200, body
    refreshed_token = body["access_token"]

    status_code, body = request(args.base_url, "GET", "/api/v1/auth/me", token=refreshed_token)
    assert status_code == 200, body
    assert {"tenant_id", "user_id", "username", "role"}.issubset(body), body

    status_code, body = request(args.base_url, "GET", "/api/v1/channels?limit=1&offset=0", token=token)
    assert status_code == 200, body
    assert_page(body)

    status_code, body = request(args.base_url, "GET", "/api/v1/tools/?limit=2&offset=0", token=token)
    assert status_code == 200, body
    assert_page(body)

    status_code, body = request(
        args.base_url,
        "POST",
        "/api/v1/proactive-tasks",
        {
            "type": "cron",
            "cron_expr": "0 9 * * *",
            "agent_id": "default",
            "prompt": "contract probe cleanup",
            "channel_type": "feishu",
        },
        token=token,
    )
    assert status_code == 201, body
    task_id = body["task_id"]

    status_code, body = request(args.base_url, "GET", "/api/v1/proactive-tasks?limit=20&offset=0", token=token)
    assert status_code == 200, body
    assert_page(body)
    assert any(item["task_id"] == task_id for item in body["items"]), body

    status_code, body = request(args.base_url, "GET", "/api/v1/proactive-tasks/runs?limit=1&offset=0", token=token)
    assert status_code == 200, body
    assert_page(body)

    status_code, body = request(args.base_url, "DELETE", f"/api/v1/proactive-tasks/{task_id}", token=token)
    assert status_code == 200, body

    status_code, body = request(args.base_url, "GET", "/api/v1/conversations/00000000-0000-0000-0000-000000000000", token=token)
    assert status_code == 404, body
    assert_error(body, "CONVERSATION_NOT_FOUND")

    print(json.dumps({"ok": True, "base_url": args.base_url}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise
