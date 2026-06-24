"""Client owner for isolated browser automation runtime sessions."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.observability import increment_acquisition_metric

from .policy import (
    BrowserAutomationPolicyError,
    BrowserAutomationRuntimePolicy,
    build_profile_scope,
    validate_browser_actions,
    validate_browser_runtime_policy,
)
from .traces import BrowserAutomationTraceRecorder, redact_trace_value


class BrowserAutomationRuntimeError(RuntimeError):
    """Normalized runtime error that never includes raw browser payload values."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_contract(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
        }


@dataclass(frozen=True)
class BrowserAutomationLease:
    """Held concurrency slot for a browser automation run."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    run_id: str


@dataclass
class BrowserAutomationConcurrencyEvidence:
    """In-memory resource accounting evidence retained for tests and audit."""

    active_system: int = 0
    active_by_user: dict[tuple[uuid.UUID, uuid.UUID], int] = field(default_factory=lambda: defaultdict(int))
    cleanup_events: list[dict[str, Any]] = field(default_factory=list)


class BrowserAutomationConcurrencyLimiter:
    """Per-user and system-wide runtime concurrency guard."""

    def __init__(self, *, system_limit: int) -> None:
        if system_limit < 1:
            raise ValueError("system_limit must be positive")
        self.system_limit = system_limit
        self._lock = asyncio.Lock()
        self.evidence = BrowserAutomationConcurrencyEvidence()

    async def acquire(self, policy: BrowserAutomationRuntimePolicy, *, run_id: str) -> BrowserAutomationLease:
        async with self._lock:
            key = (policy.tenant_id, policy.user_id)
            system_limit = min(self.system_limit, policy.system_concurrency_limit)
            if self.evidence.active_system >= system_limit:
                self._record_cleanup(run_id, policy, "system_concurrency_denied")
                raise BrowserAutomationRuntimeError(
                    "SYSTEM_CONCURRENCY_LIMIT",
                    "browser automation system concurrency limit exceeded",
                    retryable=True,
                )
            if self.evidence.active_by_user[key] >= policy.concurrency_limit:
                self._record_cleanup(run_id, policy, "user_concurrency_denied")
                raise BrowserAutomationRuntimeError(
                    "USER_CONCURRENCY_LIMIT",
                    "browser automation per-user concurrency limit exceeded",
                    retryable=True,
                )
            self.evidence.active_system += 1
            self.evidence.active_by_user[key] += 1
            return BrowserAutomationLease(tenant_id=policy.tenant_id, user_id=policy.user_id, run_id=run_id)

    async def release(self, lease: BrowserAutomationLease, policy: BrowserAutomationRuntimePolicy, *, reason: str) -> None:
        async with self._lock:
            key = (lease.tenant_id, lease.user_id)
            self.evidence.active_system = max(0, self.evidence.active_system - 1)
            self.evidence.active_by_user[key] = max(0, self.evidence.active_by_user[key] - 1)
            if self.evidence.active_by_user[key] == 0:
                self.evidence.active_by_user.pop(key, None)
            self._record_cleanup(lease.run_id, policy, reason)

    def _record_cleanup(self, run_id: str, policy: BrowserAutomationRuntimePolicy, reason: str) -> None:
        self.evidence.cleanup_events.append(
            {
                "run_id": run_id,
                "tenant_id": str(policy.tenant_id),
                "user_id": str(policy.user_id),
                "reason": reason,
                "active_system": self.evidence.active_system,
            }
        )


class DefaultBrowserRuntimeTransport:
    """HTTP transport to the compose-managed browser-runtime service."""

    async def run(self, payload: Mapping[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
        timeout = max(float(policy.max_session_seconds) + 2.0, 5.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(f"{policy.runtime_url}/run", json=dict(payload))
            response.raise_for_status()
            content = response.content
            if len(content) > policy.max_trace_bytes:
                raise BrowserAutomationRuntimeError("TRACE_TOO_LARGE", "browser runtime response exceeds trace byte cap")
            data = response.json()
        if not isinstance(data, dict):
            raise BrowserAutomationRuntimeError("INVALID_RUNTIME_RESPONSE", "browser runtime response must be an object")
        return data


_DEFAULT_LIMITER = BrowserAutomationConcurrencyLimiter(system_limit=8)


class BrowserAutomationRuntimeClient:
    """Executes approved browser automation runs in the isolated runtime service."""

    def __init__(
        self,
        policy: BrowserAutomationRuntimePolicy,
        *,
        transport: Any | None = None,
        limiter: BrowserAutomationConcurrencyLimiter | None = None,
        clock: Any | None = None,
    ) -> None:
        validate_browser_runtime_policy(policy)
        self.policy = policy
        self.transport = transport or DefaultBrowserRuntimeTransport()
        self.limiter = limiter or _DEFAULT_LIMITER
        self.clock = clock or time.monotonic
        self.last_trace_artifact: dict[str, Any] | None = None

    def build_runtime_payload(
        self,
        actions: Sequence[Mapping[str, Any]],
        *,
        context: Mapping[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_actions = validate_browser_actions(self.policy, actions, context=context)
        run_id = run_id or uuid.uuid4().hex
        profile = build_profile_scope(self.policy, run_id=run_id)
        return {
            "run_id": run_id,
            "runtime_kind": "isolated_browser",
            "allowed_hosts": self.policy.allowed_hosts,
            "deny_private_networks": True,
            "max_session_seconds": self.policy.max_session_seconds,
            "deadline_epoch_ms": int((time.time() + float(self.policy.max_session_seconds)) * 1000),
            "max_actions_per_run": self.policy.max_actions_per_run,
            "max_trace_bytes": self.policy.max_trace_bytes,
            "trace_retention_days": self.policy.trace_retention_days,
            "profile": profile,
            "cookie_scope": dict(self.policy.cookie_scope),
            "write_confirmation_policy": dict(self.policy.write_confirmation_policy),
            "confirmation": _confirmation_payload(context),
            "actions": normalized_actions,
        }

    async def run(
        self,
        actions: Sequence[Mapping[str, Any]],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        payload = self.build_runtime_payload(actions, context=context, run_id=run_id)
        recorder = BrowserAutomationTraceRecorder(
            max_trace_bytes=self.policy.max_trace_bytes,
            redaction_policy=self.policy.action_redaction_policy,
            trace_retention_days=self.policy.trace_retention_days,
        )
        recorder.record_event(
            "session_start",
            {
                "runtime_service_name": self.policy.runtime_service_name,
                "runtime_image_ref": self.policy.runtime_image_ref,
                "allowed_hosts": self.policy.allowed_hosts,
                "profile": payload["profile"],
            },
        )
        for action in payload["actions"]:
            recorder.record_event("action_requested", action)

        lease: BrowserAutomationLease | None = None
        cleanup_reason = "failure"
        try:
            lease = await self.limiter.acquire(self.policy, run_id=run_id)
            result = await asyncio.wait_for(
                self.transport.run(payload, policy=self.policy),
                timeout=float(self.policy.max_session_seconds),
            )
            recorder.record_event("runtime_response", result)
            safe_result = _sanitize_runtime_result(result, policy=self.policy)
            cleanup_reason = "success"
            artifact = recorder.artifact(run_id=run_id)
            self.last_trace_artifact = artifact
            return {
                "ok": True,
                "run_id": run_id,
                "profile": payload["profile"],
                "result": safe_result,
                "trace_artifact": artifact,
            }
        except asyncio.TimeoutError as exc:
            cleanup_reason = "timeout"
            recorder.record_event("session_timeout", {"max_session_seconds": self.policy.max_session_seconds})
            self.last_trace_artifact = recorder.artifact(run_id=run_id)
            raise BrowserAutomationRuntimeError("SESSION_TIMEOUT", "browser automation session timed out", retryable=True) from exc
        except BrowserAutomationPolicyError:
            cleanup_reason = "policy_denied"
            self.last_trace_artifact = recorder.artifact(run_id=run_id)
            raise
        except BrowserAutomationRuntimeError:
            self.last_trace_artifact = recorder.artifact(run_id=run_id)
            raise
        except httpx.TimeoutException as exc:
            cleanup_reason = "timeout"
            recorder.record_event("session_timeout", {"max_session_seconds": self.policy.max_session_seconds})
            self.last_trace_artifact = recorder.artifact(run_id=run_id)
            raise BrowserAutomationRuntimeError("SESSION_TIMEOUT", "browser automation session timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            recorder.record_event("runtime_error", {"error_type": exc.__class__.__name__})
            self.last_trace_artifact = recorder.artifact(run_id=run_id)
            raise BrowserAutomationRuntimeError("RUNTIME_HTTP_ERROR", "browser runtime request failed", retryable=True) from exc
        finally:
            if lease is not None:
                await self.limiter.release(lease, self.policy, reason=cleanup_reason)
                increment_acquisition_metric("acquisition_session_cleanups")


def _confirmation_payload(context: Mapping[str, Any] | None) -> dict[str, Any]:
    confirmation = (context or {}).get("confirmation_context")
    if not isinstance(confirmation, Mapping):
        return {"confirmed": False}
    return {
        "confirmed": confirmation.get("confirmed") is True,
        "confirmation_id": str(confirmation.get("confirmation_id") or ""),
        "approved_action_ids": [
            str(action_id)
            for action_id in confirmation.get("approved_action_ids", [])
            if str(action_id).strip()
        ]
        if isinstance(confirmation.get("approved_action_ids"), Sequence)
        and not isinstance(confirmation.get("approved_action_ids"), (str, bytes))
        else [],
    }


def _sanitize_runtime_result(result: Mapping[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
    safe_result, _ = redact_trace_value(result, policy=policy.action_redaction_policy)
    if not isinstance(safe_result, dict):
        return {"ok": False, "redacted": True}
    return safe_result
