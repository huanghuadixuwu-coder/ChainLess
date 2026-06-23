"""Generic API tool runtime client."""

from __future__ import annotations

import asyncio
import http.client
import json
import socket
import ssl
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit

import httpx
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for

from app.core.security.egress_policy import (
    EgressDecision,
    prepare_egress_runtime_guard,
    validate_egress_request,
    validate_egress_response_chunk,
    validate_runtime_egress,
)

from .policy import APIToolRuntimePolicy, SAFE_METHODS, WRITE_METHODS, validate_api_runtime_policy


Resolver = Callable[[str], Sequence[str]]
CredentialResolver = Callable[[uuid.UUID], Awaitable[str]]


class APIToolRuntimeError(RuntimeError):
    """Normalized runtime error that never includes raw request/secret values."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.detail = dict(detail or {})

    def to_contract(self, error_contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
        fields = _error_contract_fields(error_contract or {})
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                fields["code"]: self.code,
                fields["message"]: self.message,
                "retryable": self.retryable,
            },
        }
        if self.status_code is not None:
            payload["error"][fields["status"]] = self.status_code
        if self.detail:
            payload["error"]["detail"] = _redact_value(self.detail)
        return payload


@dataclass(frozen=True)
class APIRuntimeHTTPResponse:
    """Transport response with explicit post-connect IP evidence."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes
    connected_ips: Sequence[str] | None = None
    redirect_url: str | None = None


class DefaultHTTPTransport:
    """Pinned-peer HTTP transport for approved API-tool egress."""

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
        timeout_s: int,
        approved_resolved_ips: Sequence[str],
        max_response_bytes: int,
        normalized_host: str,
        normalized_url: str,
    ) -> APIRuntimeHTTPResponse:
        return await asyncio.to_thread(
            self._request_sync,
            method=method,
            url=normalized_url or url,
            headers=headers,
            content=content,
            timeout_s=timeout_s,
            approved_resolved_ips=tuple(approved_resolved_ips),
            max_response_bytes=max_response_bytes,
            normalized_host=normalized_host,
        )

    def _request_sync(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
        timeout_s: int,
        approved_resolved_ips: Sequence[str],
        max_response_bytes: int,
        normalized_host: str,
    ) -> APIRuntimeHTTPResponse:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise APIToolRuntimeError("INVALID_EGRESS_URL", "API tool URL must be absolute HTTP(S)")
        if method.upper() not in SAFE_METHODS | WRITE_METHODS:
            raise APIToolRuntimeError("UNSUPPORTED_HTTP_METHOD", "API tool HTTP method is unsupported")
        if not approved_resolved_ips:
            raise APIToolRuntimeError("DNS_RESOLUTION_REQUIRED", "Approved DNS evidence is required")

        deadline = time.monotonic() + max(float(timeout_s), 0.001)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"

        last_error: Exception | None = None
        for approved_ip in approved_resolved_ips:
            conn: http.client.HTTPConnection | None = None
            try:
                conn = _pinned_connection(
                    scheme=parsed.scheme,
                    host=parsed.hostname,
                    port=port,
                    connect_ip=approved_ip,
                    timeout_s=_remaining_timeout(deadline),
                )
                conn.putrequest(method.upper(), target, skip_host=True, skip_accept_encoding=True)
                conn.putheader("Host", normalized_host)
                conn.putheader("Accept-Encoding", "identity")
                for key, value in headers.items():
                    if key.lower() in {"host", "content-length", "accept-encoding"}:
                        continue
                    conn.putheader(key, value)
                if content is not None:
                    conn.putheader("Content-Length", str(len(content)))
                conn.endheaders(content)
                _set_socket_deadline(conn, deadline)

                response = conn.getresponse()
                _set_socket_deadline(conn, deadline)
                peer_ip = str(conn.sock.getpeername()[0]) if conn.sock is not None else approved_ip
                response_headers = {key.lower(): value for key, value in response.getheaders()}
                content_length = response_headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > max_response_bytes:
                            raise APIToolRuntimeError(
                                "RESPONSE_TOO_LARGE",
                                "API tool response exceeds configured byte cap",
                            )
                    except ValueError:
                        pass

                chunks: list[bytes] = []
                received = 0
                while True:
                    _set_socket_deadline(conn, deadline)
                    chunk = response.read(min(65536, max_response_bytes + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_response_bytes:
                        raise APIToolRuntimeError(
                            "RESPONSE_TOO_LARGE",
                            "API tool response exceeds configured byte cap",
                        )
                    chunks.append(chunk)

                return APIRuntimeHTTPResponse(
                    status_code=response.status,
                    headers=response_headers,
                    content=b"".join(chunks),
                    connected_ips=(peer_ip,),
                    redirect_url=response_headers.get("location"),
                )
            except APIToolRuntimeError:
                raise
            except (socket.timeout, TimeoutError):
                raise
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
                continue
            finally:
                if conn is not None:
                    conn.close()

        raise APIToolRuntimeError(
            "UPSTREAM_HTTP_ERROR",
            "API tool request failed",
            retryable=True,
            detail={"transport_error": last_error.__class__.__name__ if last_error else "connection_failed"},
        )


_SHARED_RATE_WINDOWS: dict[tuple[str, str, str, int, int], deque[float]] = {}


class APIToolRuntimeClient:
    """Executes one approved API tool under its policy constraints."""

    def __init__(
        self,
        policy: APIToolRuntimePolicy,
        *,
        transport: Any | None = None,
        resolver: Resolver | None = None,
        credential_resolver: CredentialResolver | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        validate_api_runtime_policy(policy)
        self.policy = policy
        self.transport = transport or DefaultHTTPTransport()
        self.resolver = resolver or _socket_resolver
        self.credential_resolver = credential_resolver
        self.clock = clock or time.monotonic

    async def execute(self, args: dict[str, Any], *, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        arguments = dict(args or {})
        self._validate_input(arguments)
        self._enforce_confirmation(arguments, context=context)
        self._enforce_rate_limit()

        url, path_keys = self._render_url(arguments)
        headers = await self._render_headers()
        self._inject_idempotency_headers(headers)
        content = self._render_body(arguments, path_keys)
        self._enforce_request_cap(url=url, headers=headers, content=content)

        attempts = self._attempt_count()
        retry_statuses = {int(value) for value in self.policy.retry_policy.get("retry_statuses", [])}
        last_error: APIToolRuntimeError | None = None
        current_url = url

        for attempt in range(attempts):
            guard = prepare_egress_runtime_guard(
                self.policy.egress_policy,
                current_url,
                network_scope="configured_api_base",
                target_type="api_tool",
                activated_target=True,
                resolver=self.resolver,
            )
            _raise_if_denied(guard)
            try:
                response = await self.transport.request(
                    method=self.policy.method.upper(),
                    url=current_url,
                    headers=headers,
                    content=content,
                    timeout_s=self.policy.timeout_s,
                    approved_resolved_ips=guard.approved_resolved_ips,
                    max_response_bytes=guard.max_response_bytes,
                    normalized_host=guard.normalized_host,
                    normalized_url=guard.normalized_url,
                )
            except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
                last_error = APIToolRuntimeError("UPSTREAM_TIMEOUT", "API tool request timed out", retryable=True)
                if attempt + 1 < attempts:
                    continue
                raise last_error
            except httpx.HTTPError:
                last_error = APIToolRuntimeError("UPSTREAM_HTTP_ERROR", "API tool request failed", retryable=True)
                if attempt + 1 < attempts:
                    continue
                raise last_error

            runtime_decision = validate_runtime_egress(guard, connected_ips=response.connected_ips)
            _raise_if_denied(runtime_decision)

            redirect_url = _absolute_redirect_url(current_url, response)
            if redirect_url and 300 <= response.status_code < 400:
                redirect_decision = validate_egress_request(
                    self.policy.egress_policy,
                    current_url,
                    network_scope="configured_api_base",
                    target_type="api_tool",
                    activated_target=True,
                    resolved_ips=guard.approved_resolved_ips,
                    redirect_url=redirect_url,
                    resolver=self.resolver,
                )
                _raise_if_denied(redirect_decision)
                current_url = redirect_url
                continue

            if response.status_code in retry_statuses and attempt + 1 < attempts:
                continue
            if response.status_code >= 400:
                raise APIToolRuntimeError(
                    "UPSTREAM_HTTP_ERROR",
                    "API tool upstream returned an error",
                    status_code=response.status_code,
                    retryable=response.status_code in retry_statuses,
                )

            self._enforce_response_cap(response, runtime_decision=runtime_decision)
            self._enforce_content_type(response)
            body = self._decode_body(response)
            self._validate_output(body)
            return {
                "ok": True,
                "status_code": response.status_code,
                "content_type": _header(response.headers, "content-type"),
                "body": self._redact_response(body),
            }

        if last_error is not None:
            raise last_error
        raise APIToolRuntimeError("UPSTREAM_HTTP_ERROR", "API tool request failed")

    def _validate_input(self, args: dict[str, Any]) -> None:
        _validate_json_schema(
            _strip_internal_keys(args),
            self.policy.input_schema or {"type": "object"},
            code="INPUT_VALIDATION_FAILED",
            label="input",
        )

    def _validate_output(self, body: Any) -> None:
        if not self.policy.output_schema:
            return
        _validate_json_schema(
            body,
            self.policy.output_schema,
            code="OUTPUT_VALIDATION_FAILED",
            label="output",
        )

    def _enforce_confirmation(self, args: dict[str, Any], *, context: Mapping[str, Any] | None) -> None:
        confirmation_context = (context or {}).get("confirmation_context")
        confirmed = bool(isinstance(confirmation_context, Mapping) and confirmation_context.get("confirmed") is True)
        if self.policy.requires_confirmation and not confirmed:
            raise APIToolRuntimeError(
                "CONFIRMATION_REQUIRED",
                "API tool write requires runtime confirmation or an idempotency strategy",
            )

    def _enforce_rate_limit(self) -> None:
        max_requests = _int_policy(self.policy.rate_limit, "max_requests", 0)
        per_seconds = _int_policy(self.policy.rate_limit, "per_seconds", 0)
        if max_requests <= 0 or per_seconds <= 0:
            return
        now = self.clock()
        key = (
            str(self.policy.tenant_id),
            str(self.policy.user_id),
            str(self.policy.id),
            max_requests,
            per_seconds,
        )
        window = _SHARED_RATE_WINDOWS.setdefault(key, deque())
        while window and now - window[0] >= per_seconds:
            window.popleft()
        if len(window) >= max_requests:
            raise APIToolRuntimeError("RATE_LIMITED", "API tool rate limit exceeded", retryable=True)
        window.append(now)

    def _render_url(self, args: dict[str, Any]) -> tuple[str, set[str]]:
        path_keys: set[str] = set()

        def replace(match) -> str:
            key = match.group(1)
            path_keys.add(key)
            if key not in args:
                raise APIToolRuntimeError("INPUT_VALIDATION_FAILED", "API tool path parameter is missing")
            return quote(str(args[key]), safe="")

        import re

        path = re.sub(r"{([A-Za-z_][A-Za-z0-9_]*)}", replace, self.policy.path_template)
        url = urljoin(self.policy.base_url.rstrip("/") + "/", path.lstrip("/"))
        if self.policy.method.upper() in SAFE_METHODS:
            query = {
                key: value
                for key, value in args.items()
                if key not in path_keys and not key.startswith("__") and value is not None
            }
            if query:
                separator = "&" if urlsplit(url).query else "?"
                url = f"{url}{separator}{urlencode(query, doseq=True)}"
        return url, path_keys

    async def _render_headers(self) -> dict[str, str]:
        headers = {str(k).lower(): str(v) for k, v in (self.policy.headers_schema.get("static") or {}).items()}
        headers.setdefault("accept", ", ".join(self.policy.allowed_content_types))
        if self.policy.method.upper() not in SAFE_METHODS:
            headers.setdefault("content-type", "application/json")
        if self.policy.credential_ref is not None:
            if self.credential_resolver is None:
                raise APIToolRuntimeError("CREDENTIAL_RESOLUTION_REQUIRED", "API tool credential resolver is required")
            secret = await self.credential_resolver(self.policy.credential_ref)
            self._inject_credential(headers, secret)
        return headers

    def _attempt_count(self) -> int:
        if self.policy.write_like and not self._retry_safe_for_write():
            return 1
        return max(0, _int_policy(self.policy.retry_policy, "max_retries", 0)) + 1

    def _retry_safe_for_write(self) -> bool:
        if self.policy.idempotency_policy.get("idempotent") is True:
            return True
        strategy = self.policy.idempotency_policy.get("strategy")
        return strategy in {"idempotency_key", "safe_retry"}

    def _inject_idempotency_headers(self, headers: dict[str, str]) -> None:
        if not self.policy.write_like:
            return
        if self.policy.idempotency_policy.get("strategy") != "idempotency_key":
            return
        header_name = str(self.policy.idempotency_policy.get("header_name") or "Idempotency-Key").lower()
        headers.setdefault(header_name, str(uuid.uuid4()))

    def _inject_credential(self, headers: dict[str, str], secret: str) -> None:
        scheme = self.policy.auth_scheme.lower()
        if scheme == "bearer":
            headers["authorization"] = f"Bearer {secret}"
            return
        if scheme in {"api_key_header", "header"}:
            header_name = str(self.policy.headers_schema.get("auth_header", "x-api-key")).lower()
            headers[header_name] = secret
            return
        raise APIToolRuntimeError("UNSUPPORTED_AUTH_SCHEME", "API tool auth_scheme is unsupported")

    def _render_body(self, args: dict[str, Any], path_keys: set[str]) -> bytes | None:
        if self.policy.method.upper() in SAFE_METHODS:
            return None
        payload = {
            key: value
            for key, value in args.items()
            if key not in path_keys and not key.startswith("__")
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def _enforce_request_cap(self, *, url: str, headers: dict[str, str], content: bytes | None) -> None:
        header_bytes = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in headers.items())
        total = len(url.encode("utf-8")) + header_bytes + len(content or b"")
        if total > self.policy.max_request_bytes:
            raise APIToolRuntimeError("REQUEST_TOO_LARGE", "API tool request exceeds configured byte cap")

    def _enforce_response_cap(self, response: APIRuntimeHTTPResponse, *, runtime_decision: EgressDecision) -> None:
        content_length = _header(response.headers, "content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.policy.max_response_bytes:
                    raise APIToolRuntimeError("RESPONSE_TOO_LARGE", "API tool response exceeds configured byte cap")
            except ValueError:
                pass
        chunk_decision = validate_egress_response_chunk(
            self.policy.egress_policy,
            bytes_received=0,
            chunk_size=len(response.content),
            normalized_host=runtime_decision.normalized_host,
            normalized_url=runtime_decision.normalized_url,
            resolved_ips=runtime_decision.resolved_ips,
        )
        _raise_if_denied(chunk_decision)

    def _enforce_content_type(self, response: APIRuntimeHTTPResponse) -> None:
        content_type = (_header(response.headers, "content-type") or "").split(";", 1)[0].strip().lower()
        allowed = [value.lower() for value in self.policy.allowed_content_types]
        if content_type not in allowed:
            raise APIToolRuntimeError("CONTENT_TYPE_DENIED", "API tool response content type is not allowed")

    def _decode_body(self, response: APIRuntimeHTTPResponse) -> Any:
        content_type = (_header(response.headers, "content-type") or "").lower()
        if "json" in content_type:
            try:
                return json.loads(response.content.decode("utf-8") or "null")
            except json.JSONDecodeError:
                raise APIToolRuntimeError("INVALID_RESPONSE_BODY", "API tool response was not valid JSON")
        return response.content.decode("utf-8", errors="replace")

    def _redact_response(self, value: Any) -> Any:
        fields = {str(field).lower() for field in self.policy.response_redaction_policy.get("json_fields", [])}
        return _redact_value(value, redacted_keys=fields)


def _raise_if_denied(decision: Any) -> None:
    if isinstance(decision, EgressDecision) and not decision.allowed:
        raise APIToolRuntimeError(decision.code, decision.message)
    if getattr(decision, "allowed", True) is False:
        raise APIToolRuntimeError(getattr(decision, "code", "EGRESS_DENIED"), getattr(decision, "message", "Egress denied"))


def _socket_resolver(host: str) -> Sequence[str]:
    return sorted({item[4][0] for item in socket.getaddrinfo(host, None)})


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, connect_ip: str, timeout_s: float) -> None:
        super().__init__(host, port=port, timeout=timeout_s)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._connect_ip, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    default_port = 443

    def __init__(self, host: str, port: int, *, connect_ip: str, timeout_s: float) -> None:
        super().__init__(host, port=port, connect_ip=connect_ip, timeout_s=timeout_s)
        self._ssl_context = ssl.create_default_context()

    def connect(self) -> None:
        raw_sock = socket.create_connection((self._connect_ip, self.port), self.timeout, self.source_address)
        self.sock = self._ssl_context.wrap_socket(raw_sock, server_hostname=self.host)


def _pinned_connection(
    *,
    scheme: str,
    host: str,
    port: int,
    connect_ip: str,
    timeout_s: float,
) -> http.client.HTTPConnection:
    if scheme == "https":
        return _PinnedHTTPSConnection(host, port, connect_ip=connect_ip, timeout_s=timeout_s)
    return _PinnedHTTPConnection(host, port, connect_ip=connect_ip, timeout_s=timeout_s)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return max(0.001, remaining)


def _set_socket_deadline(conn: http.client.HTTPConnection, deadline: float) -> None:
    if conn.sock is not None:
        conn.sock.settimeout(_remaining_timeout(deadline))


def _absolute_redirect_url(url: str, response: APIRuntimeHTTPResponse) -> str | None:
    location = response.redirect_url or _header(response.headers, "location")
    if not location:
        return None
    return urljoin(url, location)


def _header(headers: Mapping[str, str], key: str) -> str | None:
    for header, value in headers.items():
        if header.lower() == key.lower():
            return value
    return None


def _int_policy(policy: Mapping[str, Any], key: str, default: int) -> int:
    value = policy.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_json_schema(value: Any, schema: Mapping[str, Any], *, code: str, label: str) -> None:
    if not isinstance(schema, Mapping) or not schema:
        return
    schema_dict = dict(schema)
    try:
        validator_cls = validator_for(schema_dict)
        validator_cls.check_schema(schema_dict)
        errors = sorted(validator_cls(schema_dict).iter_errors(value), key=lambda error: list(error.absolute_path))
    except SchemaError:
        raise APIToolRuntimeError(code, f"API tool {label} schema is invalid")
    if errors:
        raise APIToolRuntimeError(code, f"API tool {label} does not match schema")


def _strip_internal_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_internal_keys(item) for key, item in value.items() if not str(key).startswith("__")}
    if isinstance(value, list):
        return [_strip_internal_keys(item) for item in value]
    return value


def _error_contract_fields(error_contract: Mapping[str, Any]) -> dict[str, str]:
    fields = error_contract.get("fields") if isinstance(error_contract.get("fields"), Mapping) else {}
    return {
        "code": str(error_contract.get("code_field") or fields.get("code") or "code"),
        "message": str(error_contract.get("message_field") or fields.get("message") or "message"),
        "status": str(error_contract.get("status_field") or fields.get("status") or "status_code"),
    }


def _redact_value(value: Any, *, redacted_keys: set[str] | None = None) -> Any:
    keys = redacted_keys or {"authorization", "api_key", "password", "secret", "token"}
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in keys else _redact_value(item, redacted_keys=keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, redacted_keys=keys) for item in value]
    return value
