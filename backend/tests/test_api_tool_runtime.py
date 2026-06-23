"""Generic API tool runtime policy and execution tests."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from app.core.agent import engine as agent_engine
from app.core.tools.api_runtime import (
    APIRuntimeHTTPResponse,
    APIToolConfirmationRequired,
    DefaultHTTPTransport,
    APIToolRuntimeClient,
    APIToolRuntimeError,
    APIToolRuntimePolicy,
)


@dataclass
class _QueuedResponse:
    status_code: int = 200
    headers: dict[str, str] | None = None
    content: bytes = b'{"ok": true}'
    connected_ips: tuple[str, ...] | None = ("93.184.216.34",)
    redirect_url: str | None = None
    error: Exception | None = None


class _FakeTransport:
    def __init__(self, responses: list[_QueuedResponse] | None = None) -> None:
        self.responses = responses or [_QueuedResponse()]
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
        timeout_s: int,
        approved_resolved_ips: tuple[str, ...] | list[str],
        max_response_bytes: int,
        normalized_host: str,
        normalized_url: str,
    ) -> APIRuntimeHTTPResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "content": content,
                "timeout_s": timeout_s,
                "approved_resolved_ips": tuple(approved_resolved_ips),
                "max_response_bytes": max_response_bytes,
                "normalized_host": normalized_host,
                "normalized_url": normalized_url,
            }
        )
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if response.error is not None:
            raise response.error
        return APIRuntimeHTTPResponse(
            status_code=response.status_code,
            headers=response.headers or {"content-type": "application/json"},
            content=response.content,
            connected_ips=response.connected_ips,
            redirect_url=response.redirect_url,
        )


class _RotatingResolver:
    def __init__(self, answers: list[list[str]]) -> None:
        self.answers = answers
        self.calls = 0

    def __call__(self, host: str) -> list[str]:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


def _policy(**overrides: Any) -> APIToolRuntimePolicy:
    base = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "activation_target_id": uuid.uuid4(),
        "name": "weather_lookup",
        "canonical_tool_name": "api__weather_lookup",
        "base_url": "https://api.example.com",
        "method": "GET",
        "path_template": "/v1/weather/{city}",
        "headers_schema": {},
        "auth_scheme": "none",
        "credential_ref": None,
        "credential_generation": None,
        "input_schema": {
            "type": "object",
            "required": ["city"],
            "properties": {"city": {"type": "string"}},
        },
        "output_schema": {"type": "object"},
        "allowed_hosts": ["api.example.com"],
        "deny_private_networks": True,
        "redirect_policy": {"follow": False},
        "allowed_content_types": ["application/json"],
        "max_request_bytes": 512,
        "max_response_bytes": 1024,
        "idempotency_policy": {"idempotent": True},
        "response_redaction_policy": {"json_fields": ["token", "secret"]},
        "rate_limit": {"max_requests": 10, "per_seconds": 60},
        "timeout_s": 2,
        "retry_policy": {"max_retries": 0, "retry_statuses": [500, 502, 503, 504]},
        "error_contract": {"format": "normalized"},
        "risk_level": "safe",
    }
    base.update(overrides)
    return APIToolRuntimePolicy(**base)


@pytest.mark.asyncio
async def test_api_tool_requires_allowed_host() -> None:
    client = APIToolRuntimeClient(
        _policy(allowed_hosts=["other.example.com"]),
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "HOST_NOT_ALLOWLISTED"


@pytest.mark.asyncio
async def test_api_tool_rejects_private_network() -> None:
    client = APIToolRuntimeClient(
        _policy(),
        transport=_FakeTransport(),
        resolver=lambda host: ["10.0.0.5"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "PRIVATE_NETWORK_DENIED"


@pytest.mark.asyncio
async def test_api_tool_rejects_dns_rebinding() -> None:
    resolver = _RotatingResolver([["93.184.216.34"]])
    client = APIToolRuntimeClient(
        _policy(),
        transport=_FakeTransport([_QueuedResponse(connected_ips=("203.0.113.77",))]),
        resolver=resolver,
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "DNS_REBINDING_DENIED"
    assert resolver.calls == 1


@pytest.mark.asyncio
async def test_api_tool_fails_closed_without_connected_ip_evidence() -> None:
    client = APIToolRuntimeClient(
        _policy(),
        transport=_FakeTransport([_QueuedResponse(connected_ips=None)]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "DNS_RESOLUTION_REQUIRED"


@pytest.mark.asyncio
async def test_default_http_transport_connects_to_approved_ip_and_returns_peer_evidence() -> None:
    observed: dict[str, Any] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.readuntil(b"\r\n\r\n")
        observed["request"] = data.decode("iso-8859-1")
        body = b'{"ok": true}'
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = APIToolRuntimeClient(
        _policy(
            base_url=f"http://api.example.com:{port}",
            allowed_hosts=[f"api.example.com:{port}"],
            deny_private_networks=False,
        ),
        resolver=lambda host: ["127.0.0.1"],
    )

    try:
        result = await client.execute({"city": "Paris"})
    finally:
        server.close()
        await server.wait_closed()

    assert result["ok"] is True
    assert result["body"] == {"ok": True}
    assert "Host: api.example.com" in observed["request"]


@pytest.mark.asyncio
async def test_default_http_transport_enforces_total_timeout_for_slow_response() -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{")
        await writer.drain()
        await asyncio.sleep(1.5)
        writer.write(b"}")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = APIToolRuntimeClient(
        _policy(
            base_url=f"http://api.example.com:{port}",
            allowed_hosts=[f"api.example.com:{port}"],
            deny_private_networks=False,
            timeout_s=1,
        ),
        transport=DefaultHTTPTransport(),
        resolver=lambda host: ["127.0.0.1"],
    )

    try:
        with pytest.raises(APIToolRuntimeError) as exc:
            await client.execute({"city": "Paris"})
    finally:
        server.close()
        await server.wait_closed()

    assert exc.value.code == "UPSTREAM_TIMEOUT"


@pytest.mark.asyncio
async def test_api_tool_rejects_unsafe_redirect() -> None:
    client = APIToolRuntimeClient(
        _policy(),
        transport=_FakeTransport(
            [
                _QueuedResponse(
                    status_code=302,
                    headers={"location": "https://evil.example.net/hop"},
                    content=b"",
                    connected_ips=("93.184.216.34",),
                    redirect_url="https://evil.example.net/hop",
                )
            ]
        ),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "REDIRECT_DENIED"


@pytest.mark.asyncio
async def test_api_tool_rejects_disallowed_content_type() -> None:
    client = APIToolRuntimeClient(
        _policy(),
        transport=_FakeTransport(
            [_QueuedResponse(headers={"content-type": "text/html"}, content=b"<html></html>")]
        ),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "CONTENT_TYPE_DENIED"


@pytest.mark.asyncio
async def test_api_tool_enforces_rate_limit_timeout_retry_and_error_contract() -> None:
    transport = _FakeTransport(
        [
            _QueuedResponse(status_code=503, content=b'{"error": "temporary"}'),
            _QueuedResponse(status_code=200, content=b'{"ok": true}'),
        ]
    )
    client = APIToolRuntimeClient(
        _policy(
            rate_limit={"max_requests": 1, "per_seconds": 60},
            retry_policy={"max_retries": 1, "retry_statuses": [503]},
            timeout_s=7,
        ),
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    result = await client.execute({"city": "Paris"}, context={"confirmation_context": {"confirmed": True}})

    assert result["ok"] is True
    assert len(transport.calls) == 2
    assert transport.calls[0]["timeout_s"] == 7

    with pytest.raises(APIToolRuntimeError) as rate_limited:
        await client.execute({"city": "Berlin"})
    assert rate_limited.value.code == "RATE_LIMITED"
    assert rate_limited.value.to_contract()["ok"] is False
    assert "Berlin" not in json.dumps(rate_limited.value.to_contract())


@pytest.mark.asyncio
async def test_api_tool_supports_configured_write_methods() -> None:
    transport = _FakeTransport()
    client = APIToolRuntimeClient(
        _policy(
            method="PATCH",
            path_template="/v1/weather",
            idempotency_policy={"idempotent": True},
        ),
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    result = await client.execute({"city": "Paris"}, context={"confirmation_context": {"confirmed": True}})

    assert result["ok"] is True
    assert transport.calls[0]["method"] == "PATCH"


@pytest.mark.asyncio
async def test_api_tool_does_not_retry_confirmed_non_idempotent_external_write() -> None:
    transport = _FakeTransport(
        [
            _QueuedResponse(status_code=503, content=b'{"error": "temporary"}'),
            _QueuedResponse(status_code=200, content=b'{"ok": true}'),
        ]
    )
    client = APIToolRuntimeClient(
        _policy(
            method="POST",
            path_template="/v1/messages",
            idempotency_policy={"idempotent": False, "action_category": "external_write"},
            retry_policy={"max_retries": 3, "retry_statuses": [503]},
        ),
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"}, context={"confirmation_context": {"confirmed": True}})

    assert exc.value.code == "UPSTREAM_HTTP_ERROR"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_api_tool_retries_write_only_with_backend_idempotency_key_strategy() -> None:
    transport = _FakeTransport(
        [
            _QueuedResponse(status_code=503, content=b'{"error": "temporary"}'),
            _QueuedResponse(status_code=200, content=b'{"ok": true}'),
        ]
    )
    client = APIToolRuntimeClient(
        _policy(
            method="POST",
            path_template="/v1/messages",
            idempotency_policy={"strategy": "idempotency_key", "action_category": "external_write"},
            retry_policy={"max_retries": 1, "retry_statuses": [503]},
        ),
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )

    result = await client.execute({"city": "Paris"}, context={"confirmation_context": {"confirmed": True}})

    assert result["ok"] is True
    assert len(transport.calls) == 2
    assert transport.calls[0]["headers"]["idempotency-key"]
    assert transport.calls[0]["headers"]["idempotency-key"] == transport.calls[1]["headers"]["idempotency-key"]


@pytest.mark.asyncio
async def test_api_tool_rate_limit_is_shared_across_client_instances() -> None:
    policy = _policy(rate_limit={"max_requests": 1, "per_seconds": 60})
    first = APIToolRuntimeClient(
        policy,
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
        clock=lambda: 100.0,
    )
    second = APIToolRuntimeClient(
        policy,
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
        clock=lambda: 101.0,
    )

    assert (await first.execute({"city": "Paris"}))["ok"] is True
    with pytest.raises(APIToolRuntimeError) as exc:
        await second.execute({"city": "Berlin"})

    assert exc.value.code == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_api_tool_injects_credential_by_reference_only() -> None:
    credential_id = uuid.uuid4()
    transport = _FakeTransport()

    async def credential_resolver(ref: uuid.UUID) -> str:
        assert ref == credential_id
        return "raw-secret-token"

    client = APIToolRuntimeClient(
        _policy(auth_scheme="bearer", credential_ref=credential_id),
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
        credential_resolver=credential_resolver,
    )

    result = await client.execute({"city": "Paris"})

    assert transport.calls[0]["headers"]["authorization"] == "Bearer raw-secret-token"
    assert str(credential_id) not in json.dumps(result)
    assert "raw-secret-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_api_tool_respects_request_and_response_byte_caps() -> None:
    request_client = APIToolRuntimeClient(
        _policy(
            method="POST",
            path_template="/v1/weather",
            max_request_bytes=10,
            idempotency_policy={"idempotent": True},
        ),
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as request_exc:
        await request_client.execute({"city": "x" * 100}, context={"confirmation_context": {"confirmed": True}})
    assert request_exc.value.code == "REQUEST_TOO_LARGE"

    response_client = APIToolRuntimeClient(
        _policy(max_response_bytes=5),
        transport=_FakeTransport(
            [_QueuedResponse(headers={"content-type": "application/json", "content-length": "6"}, content=b"123456")]
        ),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as response_exc:
        await response_client.execute({"city": "Paris"})
    assert response_exc.value.code == "RESPONSE_TOO_LARGE"

    chunk_response_client = APIToolRuntimeClient(
        _policy(max_response_bytes=5),
        transport=_FakeTransport(
            [_QueuedResponse(headers={"content-type": "application/json"}, content=b"not-json-too-long")]
        ),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as chunk_response_exc:
        await chunk_response_client.execute({"city": "Paris"})
    assert chunk_response_exc.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_api_tool_validates_output_schema_before_returning_body() -> None:
    client = APIToolRuntimeClient(
        _policy(
            output_schema={
                "type": "object",
                "required": ["temperature"],
                "properties": {"temperature": {"type": "number"}},
                "additionalProperties": False,
            },
        ),
        transport=_FakeTransport([_QueuedResponse(content=b'{"ok": true, "token": "raw-secret"}')]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    contract = exc.value.to_contract(
        {"code_field": "errorCode", "message_field": "errorMessage", "status_field": "httpStatus"}
    )
    assert exc.value.code == "OUTPUT_VALIDATION_FAILED"
    assert contract["error"]["errorCode"] == "OUTPUT_VALIDATION_FAILED"
    assert "raw-secret" not in json.dumps(contract)


@pytest.mark.asyncio
async def test_api_tool_uses_full_json_schema_validation() -> None:
    input_client = APIToolRuntimeClient(
        _policy(
            input_schema={
                "type": "object",
                "required": ["city"],
                "properties": {"city": {"type": "string", "maxLength": 3}},
                "additionalProperties": False,
            },
        ),
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as input_exc:
        await input_client.execute({"city": "Paris", "__confirmed": True})
    assert input_exc.value.code == "INPUT_VALIDATION_FAILED"

    output_client = APIToolRuntimeClient(
        _policy(
            output_schema={
                "type": "object",
                "required": ["temperature"],
                "properties": {"temperature": {"type": "number", "minimum": -90, "maximum": 60}},
            },
        ),
        transport=_FakeTransport([_QueuedResponse(content=b'{"temperature": 99}')]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as output_exc:
        await output_client.execute({"city": "Bei"})
    assert output_exc.value.code == "OUTPUT_VALIDATION_FAILED"


def test_api_tool_definition_rejects_invalid_json_schema_before_exposure() -> None:
    from app.core.tools.api_runtime import APIToolPolicyError, api_tool_definition

    with pytest.raises(APIToolPolicyError):
        api_tool_definition(_policy(input_schema={"type": "not-a-json-type"}))


def test_api_tool_definition_rejects_unsupported_auth_scheme_before_exposure() -> None:
    from app.core.tools.api_runtime import APIToolPolicyError, api_tool_definition

    with pytest.raises(APIToolPolicyError):
        api_tool_definition(_policy(auth_scheme="basic", credential_ref=uuid.uuid4()))


@pytest.mark.asyncio
async def test_api_tool_error_contract_uses_configured_fields() -> None:
    policy = _policy(
        error_contract={
            "code_field": "errorCode",
            "message_field": "errorMessage",
            "status_field": "httpStatus",
        }
    )
    client = APIToolRuntimeClient(
        policy,
        transport=_FakeTransport([_QueuedResponse(status_code=500, content=b'{"secret": "do-not-leak"}')]),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris", "api_key": "input-secret"})

    contract = exc.value.to_contract(policy.error_contract)
    assert contract["error"]["errorCode"] == "UPSTREAM_HTTP_ERROR"
    assert contract["error"]["errorMessage"] == "API tool upstream returned an error"
    assert contract["error"]["httpStatus"] == 500
    assert "input-secret" not in json.dumps(contract)
    assert "do-not-leak" not in json.dumps(contract)


@pytest.mark.asyncio
async def test_api_tool_requires_confirmation_for_non_idempotent_or_external_write() -> None:
    client = APIToolRuntimeClient(
        _policy(
            method="POST",
            path_template="/v1/messages",
            idempotency_policy={"idempotent": False, "action_category": "external_write"},
        ),
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})
    assert exc.value.code == "CONFIRMATION_REQUIRED"

    with pytest.raises(APIToolRuntimeError) as model_confirmed:
        await client.execute({"city": "Paris", "__confirmed": True})
    assert model_confirmed.value.code == "CONFIRMATION_REQUIRED"

    result = await client.execute({"city": "Paris"}, context={"confirmation_context": {"confirmed": True}})
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_api_tool_write_method_requires_confirmation_even_when_retry_safe() -> None:
    client = APIToolRuntimeClient(
        _policy(
            method="POST",
            path_template="/v1/messages",
            idempotency_policy={"idempotent": True},
        ),
        transport=_FakeTransport(),
        resolver=lambda host: ["93.184.216.34"],
    )

    with pytest.raises(APIToolRuntimeError) as exc:
        await client.execute({"city": "Paris"})

    assert exc.value.code == "CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_api_tool_confirmation_exception_emits_confirmation_required_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confirmation_context = {
        "proposal_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "target_type": "api_tool",
        "approved_snapshot_hash": "approved",
        "current_snapshot_hash": "approved",
        "permission_scope_hash": "{}",
        "risk_level": "risky",
        "tool_context_hash": "{}",
        "action_category": "external_write",
    }

    class FakeGateway:
        async def chat_stream(self, provider, messages, tools, tenant_id=None):
            yield {
                "type": "tool_call",
                "index": 0,
                "id": "api-call-1",
                "name": "api__write_weather",
                "arguments": json.dumps(
                    {"city": "Paris", "__confirmed": True, "api_key": "model-secret"}
                ),
            }

    async def fake_execute_tool(tool_name: str, args: dict, context: dict | None = None):
        raise APIToolConfirmationRequired(
            tool_name=tool_name,
            args={"city": args["city"], "api_key": "[REDACTED]"},
            risk="risky",
            confirmation_context=confirmation_context,
            code="RUNTIME_CONFIRMATION_REQUIRED",
            message="Runtime confirmation required",
        )

    monkeypatch.setattr(agent_engine, "execute_tool", fake_execute_tool)
    events = [
        event
        async for event in agent_engine.run_agent(
            FakeGateway(),
            sandbox_manager=object(),
            provider="test",
            messages=[{"role": "user", "content": "send weather"}],
            tools=[
                {
                    "type": "function",
                    "risk": "risky",
                    "function": {
                        "name": "api__write_weather",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
    ]

    confirmation = next(event for event in events if event["type"] == "confirmation_required")
    assert confirmation["tool_call_id"] == "api-call-1"
    assert confirmation["tool_name"] == "api__write_weather"
    assert confirmation["risk"] == "risky"
    assert confirmation["args"]["city"] == "Paris"
    assert confirmation["args"]["api_key"] == "[REDACTED]"
    assert "__confirmed" not in confirmation["args"]
    assert confirmation["args"]["__acquisition_confirmation_context"] == confirmation_context
    assert events[-1]["type"] == "done"
