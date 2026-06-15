#!/usr/bin/env python3
"""Final JSON release-gate probe for the supported Chainless V1 entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
from sqlalchemy import delete, func, or_, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from app.api.deps import _async_session_factory
from app.config import settings
from app.models.llm_provider import LLMProvider
from app.models.tenant import Tenant
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.artifact import Artifact
from app.models.tool_confirmation import ToolConfirmation


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    server_version = "ChainlessSpecMock/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or "0")
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.calls.append({"path": self.path, "body": body})  # type: ignore[attr-defined]
        if self.path.endswith("/embeddings"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [{"object": "embedding", "index": 0, "embedding": [0.0] * 1536}],
                    "model": body.get("model") or "embedding-3",
                },
            )
            return
        if self.path.endswith("/chat/completions"):
            self._stream_chat(body)
            return
        self._json(404, {"error": "not found"})

    def _stream_chat(self, body: dict) -> None:
        messages = [message for message in body.get("messages", []) if isinstance(message, dict)]
        if messages and messages[-1].get("role") == "tool":
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            base = {
                "id": "chatcmpl-w11-spec-complete",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model") or "w11-spec-mock",
            }
            self._write_text(base, "w11-tool-result-ack")
            return
        prompt = " ".join(
            str(message.get("content") or "")
            for message in messages
        ).lower()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        base = {
            "id": "chatcmpl-w11-spec-complete",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": body.get("model") or "w11-spec-mock",
        }
        if "shell_exec" in prompt or "date" in prompt:
            self._write_tool(base, "call_w11_shell", "shell_exec", {"command": "date"})
            return
        if "fibonacci" in prompt or "55" in prompt:
            script = (
                "def fibonacci(n):\n"
                "    a, b = 0, 1\n"
                "    for _ in range(n):\n"
                "        a, b = b, a + b\n"
                "    print(a)\n"
                "fibonacci(10)\n"
            )
            self._write_tool(base, "call_w11_fib", "code_as_action", {"script": script})
            return
        self._write_text(base, "w11-spec-text-ok")

    def _write_frame(self, payload: dict) -> None:
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))

    def _write_text(self, base: dict, content: str) -> None:
        self._write_frame({**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]})
        self._write_frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")

    def _write_tool(self, base: dict, call_id: str, name: str, args: dict) -> None:
        self._write_frame(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": name, "arguments": ""},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        )
        self._write_frame(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(args)}}]},
                        "finish_reason": None,
                    }
                ],
            }
        )
        self._write_frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
        self.wfile.write(b"data: [DONE]\n\n")


class MockOpenAIServer:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        self.httpd.calls = []  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "MockOpenAIServer":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    @property
    def chat_calls(self) -> int:
        return sum(1 for call in self.httpd.calls if call["path"].endswith("/chat/completions"))  # type: ignore[attr-defined]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_page(body: dict, label: str) -> None:
    required = {"items", "total", "limit", "offset", "next"}
    if not required.issubset(body) or not isinstance(body.get("items"), list):
        raise AssertionError(f"{label} is not paginated: {body}")


def _assert_error(body: dict, code: str, label: str) -> None:
    error = body.get("error")
    if not isinstance(error, dict) or error.get("code") != code or "message" not in error or "detail" not in error:
        raise AssertionError(f"{label} did not return {code} envelope: {body}")


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        name = ""
        payload: dict = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        if name:
            events.append((name, payload))
    return events


async def _delete_tenant(tenant_name: str) -> None:
    async with _async_session_factory() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.name == tenant_name))).scalar_one_or_none()
        if tenant is not None:
            await db.execute(delete(Tenant).where(Tenant.id == tenant.id))
            await db.commit()


async def _restore_provider(default_tenant_id: str, original_default_name: str | None, probe_name: str) -> None:
    async with _async_session_factory() as db:
        if original_default_name:
            provider = (
                await db.execute(
                    select(LLMProvider).where(
                        LLMProvider.tenant_id == uuid.UUID(default_tenant_id),
                        LLMProvider.name == original_default_name,
                    )
                )
            ).scalar_one_or_none()
            if provider is not None:
                provider.is_default = True
        probe = (
            await db.execute(
                select(LLMProvider).where(
                    LLMProvider.tenant_id == uuid.UUID(default_tenant_id),
                    LLMProvider.name == probe_name,
                )
            )
        ).scalar_one_or_none()
        if probe is not None:
            await db.delete(probe)
        await db.commit()


async def _default_tenant_and_provider() -> tuple[str, str | None]:
    async with _async_session_factory() as db:
        tenant = (await db.execute(select(Tenant).where(Tenant.name == "default"))).scalar_one()
        provider_name = (
            await db.execute(
                select(LLMProvider.name)
                .where(LLMProvider.tenant_id == tenant.id, LLMProvider.is_default.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        return str(tenant.id), provider_name


async def _ensure_no_probe_residue(prefix: str) -> dict[str, int]:
    async with _async_session_factory() as db:
        tenants = int((await db.execute(select(func.count()).select_from(Tenant).where(Tenant.name.like(f"{prefix}%")))).scalar() or 0)
        users = int((await db.execute(select(func.count()).select_from(User).where(User.username.like(f"{prefix}%")))).scalar() or 0)
        providers = int((await db.execute(select(func.count()).select_from(LLMProvider).where(LLMProvider.name.like(f"{prefix}%")))).scalar() or 0)
        conversations = int((await db.execute(select(func.count()).select_from(Conversation).where(Conversation.title.like(f"{prefix}%")))).scalar() or 0)
        messages = int((await db.execute(select(func.count()).select_from(Message).where(Message.content.like(f"%{prefix}%")))).scalar() or 0)
        artifacts = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Artifact)
                    .where(
                        or_(
                            Artifact.run_id.like(f"%{prefix}%"),
                            Artifact.tool_call_id.like(f"%{prefix}%"),
                            Artifact.workspace_path.like(f"%{prefix}%"),
                            Artifact.content_path.like(f"%{prefix}%"),
                            Artifact.diff_path.like(f"%{prefix}%"),
                            Artifact.meta_data.contains({"probe_prefix": prefix}),
                        )
                    )
                )
            ).scalar()
            or 0
        )
    return {
        "tenants": tenants,
        "users": users,
        "providers": providers,
        "conversations": conversations,
        "messages": messages,
        "artifacts": artifacts,
    }


async def _denied_confirmation_recorded(conv_id: str, tool_call_id: str) -> bool:
    async with _async_session_factory() as db:
        confirmation = (
            await db.execute(
                select(ToolConfirmation).where(
                    ToolConfirmation.conversation_id == uuid.UUID(conv_id),
                    ToolConfirmation.tool_call_id == tool_call_id,
                )
            )
        ).scalar_one_or_none()
        denial_message = (
            await db.execute(
                select(Message.content).where(
                    Message.conversation_id == uuid.UUID(conv_id),
                    Message.content.like("%User denied destructive tool%"),
                )
            )
        ).scalar_one_or_none()
    return bool(confirmation and confirmation.status == "denied" and denial_message)


async def probe(base_url: str) -> dict[str, Any]:
    prefix = f"w11-spec-{uuid.uuid4().hex[:10]}"
    probe_provider = f"{prefix}-provider"
    member_tenant = f"{prefix}-member"
    member_user = f"{prefix}-user"
    steps: list[dict[str, Any]] = []
    cleanup: list[dict[str, Any]] = []
    default_tenant_id = ""
    original_provider: str | None = None

    async with httpx.AsyncClient(base_url=base_url, timeout=90.0) as client:
        try:
            health = await client.get("/api/v1/health")
            health.raise_for_status()
            steps.append({"name": "public-health", "ok": health.json().get("status") == "ok"})

            no_auth = await client.get("/api/v1/system/health")
            _assert_error(no_auth.json(), "AUTH_EXPIRED", "no-auth detailed health")
            steps.append({"name": "no-auth-health-envelope", "ok": no_auth.status_code == 401})

            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_name": "default",
                    "username": "admin",
                    "password": settings.bootstrap_admin_password,
                },
            )
            login.raise_for_status()
            token = login.json()["access_token"]
            refresh = await client.post("/api/v1/auth/refresh", headers=_auth(token))
            refresh.raise_for_status()
            token = refresh.json()["access_token"]
            me = await client.get("/api/v1/auth/me", headers=_auth(token))
            me.raise_for_status()
            steps.append({"name": "auth-login-refresh-me", "ok": me.json().get("role") == "admin"})

            member = await client.post(
                "/api/v1/auth/register",
                json={"tenant_name": member_tenant, "username": member_user, "password": "member-secret-123"},
            )
            member.raise_for_status()
            member_health = await client.get("/api/v1/system/health", headers=_auth(member.json()["access_token"]))
            _assert_error(member_health.json(), "FORBIDDEN", "member detailed health")
            steps.append({"name": "member-admin-boundary", "ok": member_health.status_code == 403})

            admin_health = await client.get("/api/v1/system/health", headers=_auth(token))
            admin_metrics = await client.get("/api/v1/system/metrics", headers=_auth(token))
            admin_health.raise_for_status()
            admin_metrics.raise_for_status()
            metric_text = admin_metrics.text
            required_metrics = [
                "chainless_db_up",
                "chainless_redis_up",
                "chainless_worker_up",
                "chainless_sandbox_up",
                "chainless_rate_limit_per_minute",
            ]
            steps.append({
                "name": "admin-health-metrics",
                "ok": all(metric in metric_text for metric in required_metrics),
            })

            for label, path in [
                ("conversations", "/api/v1/conversations/?limit=2&offset=0"),
                ("memories", "/api/v1/memories/?limit=2&offset=0"),
                ("tools", "/api/v1/tools/?limit=2&offset=0"),
                ("channels", "/api/v1/channels?limit=2&offset=0"),
                ("proactive", "/api/v1/proactive-tasks?limit=2&offset=0"),
                ("proactive-runs", "/api/v1/proactive-tasks/runs?limit=2&offset=0"),
                ("agents", "/api/v1/agents/?limit=2&offset=0"),
                ("providers", "/api/v1/llm-providers/?limit=2&offset=0"),
                ("skills", "/api/v1/skills/?limit=2&offset=0"),
                ("audit", "/api/v1/audit/?limit=2&offset=0"),
            ]:
                response = await client.get(path, headers=_auth(token))
                response.raise_for_status()
                _assert_page(response.json(), label)
            steps.append({"name": "pagination-route-families", "ok": True})

            missing = await client.get(
                "/api/v1/conversations/00000000-0000-0000-0000-000000000000",
                headers=_auth(token),
            )
            _assert_error(missing.json(), "CONVERSATION_NOT_FOUND", "missing conversation")
            steps.append({"name": "not-found-envelope", "ok": missing.status_code == 404})

            default_tenant_id, original_provider = await _default_tenant_and_provider()
            with MockOpenAIServer() as mock:
                provider = await client.post(
                    "/api/v1/llm-providers/",
                    headers=_auth(token),
                    json={
                        "name": probe_provider,
                        "api_base": mock.base_url,
                        "api_key": f"sk-{prefix}",
                        "model": "w11-spec-mock",
                        "embedding_model": "embedding-3",
                        "is_default": True,
                    },
                )
                provider.raise_for_status()
                await client.post(f"/api/v1/llm-providers/{probe_provider}/default", headers=_auth(token))

                conversation = await client.post(
                    "/api/v1/conversations/",
                    headers=_auth(token),
                    json={"title": f"{prefix} text"},
                )
                conversation.raise_for_status()
                conv_id = conversation.json()["id"]
                artifacts = await client.get(
                    f"/api/v1/artifacts/?conversation_id={conv_id}&limit=2&offset=0",
                    headers=_auth(token),
                )
                artifacts.raise_for_status()
                _assert_page(artifacts.json(), "artifacts")
                steps.append({"name": "conversation-scoped-artifacts-page", "ok": True})

                text_chat = await client.post(
                    f"/api/v1/conversations/{conv_id}/chat",
                    headers=_auth(token),
                    json={"content": "say a short W11 text response"},
                )
                text_chat.raise_for_status()
                text_events = _parse_sse(text_chat.text)
                text_names = [name for name, _ in text_events]
                steps.append({
                    "name": "sse-text-done-contract",
                    "ok": "text" in text_names and "done" in text_names,
                    "events": text_names,
                })
                await client.delete(f"/api/v1/conversations/{conv_id}?purge=true", headers=_auth(token))

                fib_conv = await client.post(
                    "/api/v1/conversations/",
                    headers=_auth(token),
                    json={"title": f"{prefix} fib"},
                )
                fib_conv.raise_for_status()
                fib_id = fib_conv.json()["id"]
                fib_chat = await client.post(
                    f"/api/v1/conversations/{fib_id}/chat",
                    headers=_auth(token),
                    json={"content": "Use code_as_action to print fibonacci 55."},
                )
                fib_chat.raise_for_status()
                fib_events = _parse_sse(fib_chat.text)
                fib_names = [name for name, _ in fib_events]
                fib_text = "\n".join(json.dumps(data, ensure_ascii=False) for _, data in fib_events)
                steps.append({
                    "name": "sse-code-as-action-fibonacci",
                    "ok": "sandbox_output" in fib_names and "55" in fib_text,
                    "events": fib_names,
                })
                await client.delete(f"/api/v1/conversations/{fib_id}?purge=true", headers=_auth(token))

                confirm_conv = await client.post(
                    "/api/v1/conversations/",
                    headers=_auth(token),
                    json={"title": f"{prefix} confirm"},
                )
                confirm_conv.raise_for_status()
                confirm_id = confirm_conv.json()["id"]
                confirm_chat = await client.post(
                    f"/api/v1/conversations/{confirm_id}/chat",
                    headers=_auth(token),
                    json={"content": "Use shell_exec to run date."},
                )
                confirm_chat.raise_for_status()
                confirm_events = _parse_sse(confirm_chat.text)
                required = next((data for name, data in confirm_events if name == "confirmation_required"), None)
                if not required:
                    raise AssertionError(f"confirmation_required missing: {confirm_events}")
                deny = await client.post(
                    f"/api/v1/conversations/{confirm_id}/confirm",
                    headers=_auth(token),
                    json={
                        "decision": "deny",
                        "tool_call_id": required["tool_call_id"],
                        "tool_name": required["tool_name"],
                        "args": required["args"],
                    },
                )
                deny.raise_for_status()
                deny_events = _parse_sse(deny.text)
                denied_recorded = await _denied_confirmation_recorded(confirm_id, required["tool_call_id"])
                steps.append({
                    "name": "destructive-confirmation-deny",
                    "ok": denied_recorded and any(name == "done" for name, _ in deny_events),
                })
                await client.delete(f"/api/v1/conversations/{confirm_id}?purge=true", headers=_auth(token))

                steps.append({"name": "mock-provider-chat-calls", "ok": mock.chat_calls >= 3, "chat_calls": mock.chat_calls})

            audit = await client.get("/api/v1/audit/?limit=50", headers=_auth(token))
            audit.raise_for_status()
            audit_text = json.dumps(audit.json(), ensure_ascii=False)
            steps.append({
                "name": "audit-secret-redaction",
                "ok": f"sk-{prefix}" not in audit_text and settings.bootstrap_admin_password not in audit_text,
            })
        finally:
            if default_tenant_id:
                await _restore_provider(default_tenant_id, original_provider, probe_provider)
                cleanup.append({"name": "provider-restore-delete", "ok": True})
            await _delete_tenant(member_tenant)
            cleanup.append({"name": "member-tenant-delete", "ok": True})

    residue = await _ensure_no_probe_residue(prefix)
    cleanup.append({"name": "probe-residue", "ok": all(value == 0 for value in residue.values()), "residue": residue})
    ok = all(step.get("ok") for step in steps) and all(item.get("ok") for item in cleanup)
    return {"ok": ok, "base_url": base_url, "steps": steps, "cleanup": cleanup}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://chainless-nginx")
    args = parser.parse_args()
    result = asyncio.run(probe(args.base_url.rstrip("/")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
