"""Browser automation runtime owner, policy, trace, and compose evidence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
import json
import threading
import time
import types
import urllib.request
from pathlib import Path
from typing import Any
import uuid

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.acquisition import lifecycle
from app.core.acquisition.activation import approve_activation, run_activation_saga
from app.core.acquisition.rollback import rollback_activation
from app.core.acquisition.verification import verify_proposal
from app.core.browser_automation import (
    BrowserAutomationConfirmationRequired,
    BrowserAutomationConcurrencyLimiter,
    BrowserAutomationPolicyError,
    BrowserAutomationRuntimeClient,
    BrowserAutomationRuntimeError,
    BrowserAutomationRuntimePolicy,
    BrowserAutomationTraceRecorder,
    browser_tool_name,
    execute_browser_tool,
    get_browser_tool_definitions,
    redact_trace_value,
    validate_browser_runtime_policy,
)
from app.core.browser_automation.client import DefaultBrowserRuntimeTransport
from app.models.acquisition import (
    AcquisitionProposal,
    ActivationTarget,
    BrowserAutomationConfiguration,
    CapabilityGap,
    CapabilityRecommendation,
    StandingPermission,
)
from app.models.conversation import Conversation
from app.services.auth_service import decode_token
from app.services.conversation_stream_service import (
    build_confirmation_message,
    claim_confirmation,
    execute_confirmed_tool,
    get_agent_tools,
    persist_confirmation_required,
    public_agent_event,
)


ROOT = Path("/repo")
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parents[2]


def _compose_services() -> tuple[dict[str, Any], dict[str, Any]]:
    production = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    test = yaml.safe_load((ROOT / "docker-compose.test.yml").read_text(encoding="utf-8"))
    return production["services"], test["services"]


def _runtime_service_module() -> types.ModuleType:
    module_path = ROOT / "browser-runtime" / "runtime_service.py"
    spec = importlib.util.spec_from_file_location("browser_runtime_service_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def approved_browser_policy(**overrides: Any) -> BrowserAutomationRuntimePolicy:
    data = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "activation_target_id": uuid.uuid4(),
        "name": "public browser probe",
        "allowlisted_domains": ["example.com", "*.example.org"],
        "credential_ref": None,
        "credential_generation": None,
        "runtime_service_name": "browser-runtime",
        "runtime_url": "http://browser-runtime:9222",
        "runtime_image_ref": "chainless-browser-runtime:w6-1",
        "runtime_health_check": {"path": "/health", "interval_seconds": 10},
        "network_policy": {
            "mode": "allowlist",
            "allowed_hosts": ["example.com", "*.example.org"],
            "deny_private_networks": True,
            "allow_docker_socket": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        "cookie_scope": {"mode": "runtime_only", "persist_cookies": False},
        "profile_policy": {"isolation": "per_run", "allow_host_fs": False},
        "profile_storage_ref": None,
        "profile_retention_policy": {"mode": "discard_after_run"},
        "max_session_seconds": 10,
        "max_actions_per_run": 5,
        "concurrency_limit": 1,
        "system_concurrency_limit": 2,
        "cpu_limit": "1.0",
        "memory_limit_mb": 512,
        "max_trace_bytes": 65536,
        "trace_retention_days": 7,
        "action_redaction_policy": {"sensitive_keys": ["email", "phone"]},
        "write_confirmation_policy": {"mode": "before_each_external_write"},
        "enabled": True,
    }
    data.update(overrides)
    return BrowserAutomationRuntimePolicy(**data)


class EchoBrowserTransport:
    async def run(self, payload: dict[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
        return {
            "ok": True,
            "seen_profile": payload["profile"],
            "cookies": [{"name": "session", "value": "secret-cookie"}],
            "secret": "raw-runtime-secret",
            "body": "Authorization: Bearer raw-runtime-token",
            "screenshot": "data:image/png;base64,raw-secret-screenshot",
        }


class EchoActionsBrowserTransport:
    async def run(self, payload: dict[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
        return {
            "ok": True,
            "actions": payload["actions"],
        }


class SlowBrowserTransport:
    async def run(self, payload: dict[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {"ok": True}


class BlockingBrowserTransport:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, payload: dict[str, Any], *, policy: BrowserAutomationRuntimePolicy) -> dict[str, Any]:
        self.started.set()
        await self.release.wait()
        return {"ok": True}


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def _browser_gap(tenant_id: uuid.UUID, user_id: uuid.UUID) -> CapabilityGap:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=f"browser-run-{uuid.uuid4().hex}",
            dedupe_key=f"browser-gap-{uuid.uuid4().hex}",
            title="Missing browser automation",
            description="The task needs a reusable isolated browser automation capability.",
            gap_type="missing_browser_automation",
            severity="medium",
            evidence={"host": "example.com"},
            source_evidence=[{"kind": "tool_gap", "message": "Browser automation target required"}],
            idempotency_key=f"browser-gap-{uuid.uuid4().hex}",
        )
        await db.commit()
        return gap


async def _browser_recommendation(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
) -> CapabilityRecommendation:
    async with _async_session_factory() as db:
        recommendation = await lifecycle.create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap_id,
            recommendation_type="browser_automation_recommendation",
            title="Configure public browser probe",
            summary="Use an isolated browser runtime for example.com.",
            reason="Public data requires DOM inspection and bounded browser automation.",
            evidence={"source": "browser-runtime-test"},
            risk_level="risky",
            expected_value={"reusable": True},
            required_permissions={"network": "public_web", "browser": "isolated"},
            candidate_targets=[{"target_type": "browser_automation", "name": "public browser probe"}],
            idempotency_key=f"browser-rec-{uuid.uuid4().hex}",
        )
        await db.commit()
        return recommendation


def _browser_permission_bundle(*, duration: str = "until_revoked") -> dict[str, Any]:
    return {
        "target_type": "browser_automation",
        "permission_scope": {
            "hosts": ["example.com"],
            "actions": ["navigate", "dom_snapshot", "submit"],
        },
        "risk_level": "risky",
        "confirmation_policy": "confirm_external_write",
        "credential_scope": "none",
        "credential_connection_refs": [],
        "data_scope": "public_web",
        "network_scope": "public_web",
        "egress_policy": {
            "allow_hosts": ["example.com"],
            "deny_private_networks": True,
            "max_response_bytes": 65536,
        },
        "write_scope": "external_write_requires_confirmation",
        "execution_scope": "browser_automation",
        "duration": duration,
        "revocation_plan": {"disable": True, "hide_manifest_refs": True},
        "audit_events": [],
    }


def _browser_primary_target(*, name: str = "public browser probe") -> dict[str, Any]:
    return {
        "target_type": "browser_automation",
        "target_name": name,
        "target_owner": "core/browser_automation",
        "target_payload": {
            "name": name,
            "allowlisted_domains": ["example.com"],
            "network_policy": {
                "mode": "allowlist",
                "allowed_hosts": ["example.com"],
                "deny_private_networks": True,
                "allow_docker_socket": False,
                "allow_host_fs": False,
                "mounts": [],
            },
            "max_session_seconds": 10,
            "max_actions_per_run": 5,
            "concurrency_limit": 1,
            "max_trace_bytes": 65536,
        },
        "permission_bundle": _browser_permission_bundle(),
        "verification_plan": {"kind": "browser_contract"},
        "rollback_plan": {"disable": True, "hide_manifest_refs": True},
        "activation_status": "draft",
        "activation_result": {},
    }


async def _browser_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    target: dict[str, Any] | None = None,
) -> AcquisitionProposal:
    gap = await _browser_gap(tenant_id, user_id)
    recommendation = await _browser_recommendation(tenant_id, user_id, gap.id)
    async with _async_session_factory() as db:
        proposal = await lifecycle.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind="runtime_activation",
            gap_id=gap.id,
            recommendation_id=recommendation.id,
            title="Activate public browser probe",
            reason="DOM inspection for public data should be reusable.",
            evidence={"source": "browser-runtime-test"},
            risk_level="risky",
            permission_bundle=_browser_permission_bundle(),
            primary_target=target or _browser_primary_target(),
            secondary_targets=[],
            verification_plan={"kind": "browser_contract"},
            rollback_plan={"disable": True, "hide_manifest_refs": True},
            user_visible_effect="A browser automation tool can inspect example.com in isolation.",
            idempotency_key=f"browser-proposal-{uuid.uuid4().hex}",
        )
        await db.commit()
        return proposal


async def _approved_browser_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    target: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, str]:
    proposal = await _browser_proposal(tenant_id, user_id, target=target)
    async with _async_session_factory() as db:
        verification = await verify_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            verification_kind="browser_contract",
            input_fixture={"url": "https://example.com"},
            expected_result={"ok": True},
            actual_result={"ok": True},
            artifact_refs=[{"artifact_id": f"browser-verify-{proposal.id}", "digest": "sha256:evidence"}],
            idempotency_key=f"browser-verify-{proposal.id}",
        )
        await approve_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            approved_hash=verification.verified_snapshot_hash,
            idempotency_key=f"browser-approve-{proposal.id}",
        )
        await db.commit()
        return proposal.id, verification.verified_snapshot_hash


async def _activate_browser_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    target: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, str]:
    proposal_id, approved_hash = await _approved_browser_proposal(tenant_id, user_id, target=target)
    async with _async_session_factory() as db:
        await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key=f"browser-activate-{proposal_id}",
        )
        await db.commit()
    return proposal_id, approved_hash


async def _activated_browser_rows(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> tuple[ActivationTarget, BrowserAutomationConfiguration]:
    async with _async_session_factory() as db:
        target = (
            await db.execute(
                select(ActivationTarget).where(
                    ActivationTarget.tenant_id == tenant_id,
                    ActivationTarget.user_id == user_id,
                    ActivationTarget.proposal_id == proposal_id,
                    ActivationTarget.target_type == "browser_automation",
                )
            )
        ).scalar_one()
        config = (
            await db.execute(
                select(BrowserAutomationConfiguration).where(
                    BrowserAutomationConfiguration.tenant_id == tenant_id,
                    BrowserAutomationConfiguration.user_id == user_id,
                    BrowserAutomationConfiguration.activation_target_id == target.id,
                )
            )
        ).scalar_one()
        return target, config


def test_browser_runtime_requires_allowed_hosts() -> None:
    with pytest.raises(BrowserAutomationPolicyError, match="allowlisted_domains"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                allowlisted_domains=[],
                network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": [],
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                },
            )
        )

    with pytest.raises(BrowserAutomationPolicyError) as missing_hosts:
        validate_browser_runtime_policy(
            approved_browser_policy(
                network_policy={
                    "mode": "allowlist",
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                },
            )
        )
    assert missing_hosts.value.code == "ALLOWED_HOSTS_REQUIRED"

    with pytest.raises(BrowserAutomationPolicyError) as non_list_hosts:
        validate_browser_runtime_policy(
            approved_browser_policy(
                network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": "example.com",
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                },
            )
        )
    assert non_list_hosts.value.code == "ALLOWED_HOSTS_REQUIRED"

    validate_browser_runtime_policy(
        approved_browser_policy(
            network_policy={
                "mode": "allowlist",
                "allow_hosts": ["example.com"],
                "deny_private_networks": True,
                "allow_docker_socket": False,
                "allow_host_fs": False,
                "mounts": [],
            },
        )
    )

    client = BrowserAutomationRuntimeClient(approved_browser_policy())
    with pytest.raises(BrowserAutomationPolicyError, match="HOST_NOT_ALLOWLISTED"):
        client.build_runtime_payload([{"type": "navigate", "url": "https://evil.example.net"}])


def test_browser_runtime_rejects_disabled_policy_and_non_internal_runtime_url() -> None:
    with pytest.raises(BrowserAutomationPolicyError) as disabled:
        validate_browser_runtime_policy(approved_browser_policy(enabled=False))
    assert disabled.value.code == "BROWSER_AUTOMATION_DISABLED"

    for runtime_url in (
        "https://browser-runtime:9222",
        "http://localhost:9222",
        "http://browser-runtime:9222/run",
        "http://browser-runtime:9222?proxy=http://evil.example.net",
        "http://browser-runtime:9230",
    ):
        with pytest.raises(BrowserAutomationPolicyError) as invalid_url:
            validate_browser_runtime_policy(approved_browser_policy(runtime_url=runtime_url))
        assert invalid_url.value.code == "BROWSER_AUTOMATION_RUNTIME_URL_INVALID"

    config = types.SimpleNamespace(**approved_browser_policy().__dict__)
    policy = BrowserAutomationRuntimePolicy.from_model(config, runtime_url="http://127.0.0.1:9222")
    with pytest.raises(BrowserAutomationPolicyError) as override_url:
        validate_browser_runtime_policy(policy)
    assert override_url.value.code == "BROWSER_AUTOMATION_RUNTIME_URL_INVALID"


@pytest.mark.asyncio
async def test_browser_runtime_transport_disables_env_proxy_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        content = b'{"ok":true}'

        def raise_for_status(self) -> None:
            return

        def json(self) -> dict[str, Any]:
            return {"ok": True}

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.core.browser_automation.client.httpx.AsyncClient", FakeAsyncClient)

    result = await DefaultBrowserRuntimeTransport().run({"run_id": "proxy-check"}, policy=approved_browser_policy())

    assert result == {"ok": True}
    assert captured["kwargs"]["trust_env"] is False
    assert captured["url"] == "http://browser-runtime:9222/run"
    assert captured["payload"] == {"run_id": "proxy-check"}


def test_browser_runtime_network_allowed_hosts_must_be_allowlist_subset() -> None:
    validate_browser_runtime_policy(
        approved_browser_policy(
            allowlisted_domains=["*.example.org"],
            network_policy={
                "mode": "allowlist",
                "allowed_hosts": ["specific.example.org", "*.safe.example.org"],
                "deny_private_networks": True,
                "allow_docker_socket": False,
                "allow_host_fs": False,
                "mounts": [],
            },
        )
    )

    with pytest.raises(BrowserAutomationPolicyError, match="ALLOWED_HOSTS_SCOPE_INVALID"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                allowlisted_domains=["example.com"],
                network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": ["example.com", "evil.example.net"],
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                },
            )
        )

    with pytest.raises(BrowserAutomationPolicyError, match="PRIVATE_NETWORKS_DENIED"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                allowlisted_domains=["127.0.0.1"],
                network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": ["127.0.0.1"],
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                },
            )
        )


def test_browser_runtime_uses_dedicated_image_with_healthcheck() -> None:
    services, test_services = _compose_services()
    service = services["browser-runtime"]
    backend = services["backend"]

    assert service["build"]["context"] == "./browser-runtime"
    assert service["image"] == "chainless-browser-runtime:w6-1"
    assert service["container_name"] == "chainless-browser-runtime"
    assert service["environment"]["BROWSER_RUNTIME_KIND"] == "isolated_browser"
    assert service["environment"]["BROWSER_RUNTIME_APPROVED_IMAGE"] == "chainless-browser-runtime:w6-1"
    assert service["environment"]["BROWSER_RUNTIME_NETWORK_ENFORCEMENT"] == "playwright_request_interception_fail_closed"
    assert "healthcheck" in service
    assert "browser_runtime" in service["networks"]
    assert backend["environment"]["BROWSER_AUTOMATION_RUNTIME_URL"] == "http://browser-runtime:9222"
    assert "browser_runtime" in backend["networks"]
    assert backend["depends_on"]["browser-runtime"]["condition"] == "service_healthy"
    assert test_services["browser-runtime"]["container_name"] == "chainless-browser-runtime-test"
    assert (
        test_services["browser-runtime"]["environment"]["BROWSER_RUNTIME_NETWORK_ENFORCEMENT"]
        == "playwright_request_interception_fail_closed"
    )
    assert test_services["backend-test"]["environment"]["BROWSER_AUTOMATION_RUNTIME_URL"] == "http://browser-runtime:9222"
    assert test_services["backend-test"]["depends_on"]["browser-runtime"]["condition"] == "service_healthy"

    dockerfile = (ROOT / "browser-runtime" / "Dockerfile").read_text(encoding="utf-8")
    runtime_source = (ROOT / "browser-runtime" / "runtime_service.py").read_text(encoding="utf-8")
    assert "mcr.microsoft.com/playwright/python" in dockerfile
    assert "COPY runtime_service.py /browser-runtime/runtime_service.py" in dockerfile
    assert "RUN cat > /browser-runtime/runtime_service.py" not in dockerfile
    assert "context.route(\"**/*\", guard.route)" in runtime_source
    assert 'service_workers="block"' in runtime_source
    assert "_install_websocket_guard(context, guard)" in runtime_source
    assert "route_web_socket" in runtime_source
    assert "RuntimeNetworkGuard" in runtime_source
    assert "HEALTHCHECK" in dockerfile
    assert "USER runtime" in dockerfile


def test_browser_runtime_uses_isolated_profile() -> None:
    client = BrowserAutomationRuntimeClient(approved_browser_policy())
    first = client.build_runtime_payload([{"type": "navigate", "url": "https://example.com"}], run_id="run-a")
    second = client.build_runtime_payload([{"type": "navigate", "url": "https://example.com"}], run_id="run-b")

    assert first["profile"]["profile_id"] != second["profile"]["profile_id"]
    assert first["profile"]["isolation"] == "per_run"
    assert first["profile"]["ephemeral"] is True
    assert first["profile"]["storage_ref"] is None
    assert "/workspace" not in json.dumps(first["profile"])
    assert "/var/run/docker.sock" not in json.dumps(first["profile"])


@pytest.mark.asyncio
async def test_browser_runtime_records_redacted_trace_artifact() -> None:
    client = BrowserAutomationRuntimeClient(
        approved_browser_policy(max_trace_bytes=65536),
        transport=EchoBrowserTransport(),
        limiter=BrowserAutomationConcurrencyLimiter(system_limit=2),
    )

    result = await client.run(
        [
            {
                "type": "navigate",
                "url": "https://example.com/path?token=raw-url-token",
                "cookies": [{"name": "session", "value": "raw-cookie"}],
                "screenshot": "raw-action-screenshot",
            }
        ]
    )

    artifact = result["trace_artifact"]
    encoded = json.dumps(artifact, sort_keys=True)
    full_encoded = json.dumps(result, sort_keys=True)
    assert artifact["artifact_type"] == "browser_automation_trace"
    assert artifact["schema_version"] == "browser_automation_trace.v1"
    assert artifact["redaction"]["cookies"] >= 1
    assert artifact["redaction"]["screenshots"] >= 1
    assert "raw-cookie" not in encoded
    assert "raw-url-token" not in encoded
    assert "raw-secret-screenshot" not in encoded
    assert "secret-cookie" not in full_encoded
    assert "raw-runtime-secret" not in full_encoded
    assert "raw-runtime-token" not in full_encoded
    assert "raw-secret-screenshot" not in full_encoded
    assert result["profile"]["ephemeral"] is True


@pytest.mark.asyncio
async def test_browser_runtime_redacts_fill_and_type_action_values_from_trace_and_result() -> None:
    client = BrowserAutomationRuntimeClient(
        approved_browser_policy(max_trace_bytes=65536),
        transport=EchoActionsBrowserTransport(),
        limiter=BrowserAutomationConcurrencyLimiter(system_limit=2),
    )
    actions = [
        {
            "type": "fill",
            "selector": "#password",
            "value": "raw-fill-password-with-token",
            "action_id": "fill-password",
        },
        {
            "type": "type",
            "selector": "#token",
            "text": "raw-type-token-value",
            "action_id": "type-token",
        },
    ]

    result = await client.run(
        actions,
        context={
            "confirmation_context": {
                "confirmed": True,
                "confirmation_id": "confirm-sensitive-inputs",
                "approved_action_ids": ["fill-password", "type-token"],
            }
        },
    )

    encoded_artifact = json.dumps(result["trace_artifact"], sort_keys=True)
    encoded_result = json.dumps(result, sort_keys=True)
    assert "raw-fill-password-with-token" not in encoded_artifact
    assert "raw-type-token-value" not in encoded_artifact
    assert "raw-fill-password-with-token" not in encoded_result
    assert "raw-type-token-value" not in encoded_result
    assert result["result"]["actions"][0]["value"] == "[REDACTED]"
    assert result["result"]["actions"][1]["text"] == "[REDACTED]"
    action_events = [
        event["payload"]
        for event in result["trace_artifact"]["events"]
        if event["type"] == "action_requested"
    ]
    assert action_events[0]["value"] == "[REDACTED]"
    assert action_events[1]["text"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_browser_runtime_enforces_session_timeout() -> None:
    limiter = BrowserAutomationConcurrencyLimiter(system_limit=2)
    client = BrowserAutomationRuntimeClient(
        approved_browser_policy(max_session_seconds=1),
        transport=SlowBrowserTransport(),
        limiter=limiter,
    )

    with pytest.raises(BrowserAutomationRuntimeError, match="SESSION_TIMEOUT"):
        await client.run([{"type": "navigate", "url": "https://example.com"}])

    assert limiter.evidence.active_system == 0
    assert limiter.evidence.cleanup_events[-1]["reason"] == "timeout"
    assert client.last_trace_artifact is not None


def test_browser_runtime_payload_carries_runtime_deadline_and_handler_enforces_it() -> None:
    client = BrowserAutomationRuntimeClient(approved_browser_policy(max_session_seconds=5))
    payload = client.build_runtime_payload([{"type": "navigate", "url": "https://example.com"}])

    assert payload["deadline_epoch_ms"] <= int((time.time() + 5.5) * 1000)
    runtime_service = _runtime_service_module()
    expired_deadline = runtime_service._session_deadline_seconds(
        {
            "max_session_seconds": 10,
            "deadline_epoch_ms": int((time.time() - 1) * 1000),
        }
    )

    with pytest.raises(ValueError, match="session deadline exceeded"):
        runtime_service._enforce_deadline(expired_deadline)


def test_browser_runtime_service_health_run_contract_and_blocked_host_path(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_service = _runtime_service_module()
    original_run_browser = runtime_service._run_browser

    def fake_run_browser(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "run_id": payload.get("run_id"), "evidence": []}

    monkeypatch.setattr(runtime_service, "_run_browser", fake_run_browser)
    server = runtime_service.ThreadingHTTPServer(("127.0.0.1", 0), runtime_service.RuntimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        request = urllib.request.Request(
            f"{base_url}/run",
            data=json.dumps({"run_id": "runtime-smoke"}).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            run_result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert health == {"ok": True, "runtime_kind": "isolated_browser"}
    assert run_result == {"ok": True, "run_id": "runtime-smoke", "evidence": []}

    with pytest.raises(ValueError, match="action_url"):
        original_run_browser(
            {
                "allowed_hosts": ["example.com"],
                "deny_private_networks": True,
                "max_session_seconds": 5,
                "deadline_epoch_ms": int((time.time() + 5) * 1000),
                "max_actions_per_run": 1,
                "confirmation": {},
                "write_confirmation_policy": {"mode": "before_each_external_write"},
                "profile": {"profile_id": "blocked-smoke", "ephemeral": True},
                "actions": [{"type": "navigate", "url": "http://127.0.0.1/admin"}],
            }
        )


def test_browser_runtime_denies_external_write_without_confirmation() -> None:
    client = BrowserAutomationRuntimeClient(approved_browser_policy())
    write_action = {"type": "submit", "url": "https://example.com/form", "external_write": True, "action_id": "write-1"}

    with pytest.raises(BrowserAutomationPolicyError, match="CONFIRMATION_REQUIRED"):
        client.build_runtime_payload([write_action], context={})

    with pytest.raises(BrowserAutomationPolicyError, match="ACTION_CONFIRMATION_REQUIRED"):
        client.build_runtime_payload(
            [write_action],
            context={"confirmation_context": {"confirmed": True, "confirmation_id": "confirm-1"}},
        )

    payload = client.build_runtime_payload(
        [write_action],
        context={
            "confirmation_context": {
                "confirmed": True,
                "confirmation_id": "confirm-1",
                "approved_action_ids": ["write-1"],
            }
        },
    )
    assert payload["actions"][0]["external_write"] is True
    assert payload["actions"][0]["action_id"] == "write-1"
    assert payload["confirmation"] == {
        "confirmed": True,
        "confirmation_id": "confirm-1",
        "approved_action_ids": ["write-1"],
    }

    runtime_service = _runtime_service_module()
    with pytest.raises(ValueError, match="approved_action_ids"):
        runtime_service._validate_write_confirmation(
            [dict(write_action)],
            {"confirmed": True, "confirmation_id": "confirm-1"},
            {"mode": "before_each_external_write"},
        )


def test_browser_runtime_cannot_access_docker_socket_host_fs_or_non_allowlisted_network() -> None:
    services, _ = _compose_services()
    service = services["browser-runtime"]

    assert service["networks"] == ["browser_runtime"]
    assert "volumes" not in service
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["mem_limit"] == "512m"
    assert service["cpus"] == 1.0
    assert service["pids_limit"] == 128
    assert "/var/run/docker.sock" not in json.dumps(service)
    assert service["environment"]["BROWSER_RUNTIME_NETWORK_MODE"] == "allowlist"
    assert service["environment"]["BROWSER_RUNTIME_DENY_PRIVATE_NETWORKS"] == "1"

    with pytest.raises(BrowserAutomationPolicyError, match="DOCKER_SOCKET_DENIED"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                network_policy={
                    "mode": "allowlist",
                    "allowed_hosts": ["example.com"],
                    "deny_private_networks": True,
                    "allow_docker_socket": True,
                    "allow_host_fs": False,
                    "mounts": [],
                }
            )
        )
    with pytest.raises(BrowserAutomationPolicyError, match="HOST_FS_DENIED"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                profile_storage_ref="/host/profile",
                profile_retention_policy={"mode": "ttl_days", "days": 1},
            )
        )
    with pytest.raises(BrowserAutomationPolicyError, match="NETWORK_POLICY_REQUIRED"):
        validate_browser_runtime_policy(
            approved_browser_policy(
                network_policy={
                    "mode": "open",
                    "allowed_hosts": ["example.com"],
                    "deny_private_networks": True,
                    "allow_docker_socket": False,
                    "allow_host_fs": False,
                    "mounts": [],
                }
            )
        )
    client = BrowserAutomationRuntimeClient(approved_browser_policy())
    with pytest.raises(BrowserAutomationPolicyError, match="PRIVATE_NETWORKS_DENIED"):
        client.build_runtime_payload([{"type": "navigate", "url": "http://127.0.0.1/admin"}])


def test_browser_runtime_request_guard_rejects_subresource_redirect_and_post_click_navigation() -> None:
    runtime_service = _runtime_service_module()

    for source, url in (
        ("subresource", "https://evil.example.net/tracker.js"),
        ("redirect", "https://evil.example.net/redirect-target"),
        ("post_click_navigation", "http://127.0.0.1/admin"),
    ):
        guard = runtime_service.RuntimeNetworkGuard(
            ["example.com"],
            deny_private_networks=True,
            deadline_epoch_s=time.time() + 5,
            resolve_dns=False,
        )

        assert guard.validate_url(url, source=source) is False
        with pytest.raises(ValueError, match=source):
            guard.raise_if_violations()

    class FakeRequest:
        url = "https://evil.example.net/pixel.gif"

    class FakeRoute:
        def __init__(self) -> None:
            self.request = FakeRequest()
            self.aborted = False
            self.continued = False

        def abort(self, error_code: str) -> None:
            self.aborted = error_code == "blockedbyclient"

        def continue_(self) -> None:
            self.continued = True

    guard = runtime_service.RuntimeNetworkGuard(
        ["example.com"],
        deny_private_networks=True,
        deadline_epoch_s=time.time() + 5,
        resolve_dns=False,
    )
    route = FakeRoute()

    guard.route(route)

    assert route.aborted is True
    assert route.continued is False


def test_browser_runtime_websocket_route_is_fail_closed_and_records_blocks() -> None:
    runtime_service = _runtime_service_module()

    class FakeContext:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, Any]] = []

        def route_web_socket(self, pattern: Any, handler: Any) -> None:
            self.calls.append((pattern, handler))

    guard = runtime_service.RuntimeNetworkGuard(
        ["example.com"],
        deny_private_networks=True,
        deadline_epoch_s=time.time() + 5,
        resolve_dns=False,
    )
    context = FakeContext()

    runtime_service._install_websocket_guard(context, guard)

    assert len(context.calls) == 1
    assert hasattr(context.calls[0][0], "match")
    assert context.calls[0][1] == guard.route_web_socket

    with pytest.raises(RuntimeError, match="playwright_route_web_socket_unavailable"):
        runtime_service._install_websocket_guard(object(), guard)

    class FakeWebSocket:
        def __init__(self, url: str) -> None:
            self.url = url
            self.close_code: int | None = None
            self.close_reason: str | None = None
            self.connected = False

        def close(self, *, code: int, reason: str) -> None:
            self.close_code = code
            self.close_reason = reason

        def connect_to_server(self) -> None:
            self.connected = True

    blocked = FakeWebSocket("wss://evil.example.net/socket")
    guard.route_web_socket(blocked)

    assert blocked.connected is False
    assert blocked.close_code == 1008
    assert blocked.close_reason == "browser runtime network policy"
    assert guard.violations[-1]["source"] == "websocket"
    assert guard.violations[-1]["url"] == "wss://evil.example.net/socket"
    assert guard.violations[-1]["reason"] == "host is not allowlisted"

    with pytest.raises(ValueError, match="websocket"):
        guard.raise_if_violations()

    expired_guard = runtime_service.RuntimeNetworkGuard(
        ["example.com"],
        deny_private_networks=True,
        deadline_epoch_s=time.time() - 1,
        resolve_dns=False,
    )
    expired = FakeWebSocket("wss://example.com/socket")
    expired_guard.route_web_socket(expired)

    assert expired.connected is False
    assert expired.close_code == 1008
    assert expired_guard.violations[-1]["reason"] == "session deadline exceeded"

    allowed_guard = runtime_service.RuntimeNetworkGuard(
        ["example.com"],
        deny_private_networks=True,
        deadline_epoch_s=time.time() + 5,
        resolve_dns=False,
    )
    allowed = FakeWebSocket("wss://example.com/socket")
    allowed_guard.route_web_socket(allowed)

    assert allowed.connected is True
    assert allowed.close_code is None
    assert allowed_guard.violations == []


def test_browser_runtime_run_fails_late_accumulated_network_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_service = _runtime_service_module()

    class FakeFrame:
        url = "https://evil.example.net/late-navigation"

    class FakePage:
        url = "https://example.com"

        def __init__(self) -> None:
            self.frame_callback: Any | None = None

        def on(self, event: str, callback: Any) -> None:
            if event == "framenavigated":
                self.frame_callback = callback

        def goto(self, url: str, **kwargs: Any) -> None:
            self.url = url

        def title(self) -> str:
            assert self.frame_callback is not None
            self.frame_callback(FakeFrame())
            return "late violation"

    class FakeContext:
        def __init__(self) -> None:
            self.page = FakePage()
            self.pages = [self.page]
            self.closed = False

        def route(self, pattern: str, handler: Any) -> None:
            return

        def route_web_socket(self, pattern: Any, handler: Any) -> None:
            return

        def new_page(self) -> FakePage:
            return self.page

        def close(self) -> None:
            self.closed = True

    class FakeChromium:
        def launch_persistent_context(self, *args: Any, **kwargs: Any) -> FakeContext:
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self) -> "FakePlaywright":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    def fake_sync_playwright() -> FakePlaywright:
        return FakePlaywright()

    monkeypatch.setattr(runtime_service, "sync_playwright", fake_sync_playwright)

    with pytest.raises(ValueError, match="navigation"):
        runtime_service._run_browser(
            {
                "allowed_hosts": ["example.com"],
                "deny_private_networks": False,
                "max_session_seconds": 5,
                "deadline_epoch_ms": int((time.time() + 5) * 1000),
                "max_actions_per_run": 1,
                "confirmation": {},
                "write_confirmation_policy": {"mode": "before_each_external_write"},
                "profile": {"profile_id": "late-violation", "ephemeral": True},
                "actions": [{"type": "navigate", "url": "https://example.com"}],
            }
        )


def test_browser_runtime_type_action_uses_text_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_service = _runtime_service_module()
    captured: dict[str, Any] = {}

    class FakePage:
        url = "https://example.com"

        def on(self, event: str, callback: Any) -> None:
            return

        def fill(self, selector: str, value: str, **kwargs: Any) -> None:
            captured["selector"] = selector
            captured["value"] = value
            captured["timeout"] = kwargs.get("timeout")

    class FakeContext:
        def __init__(self) -> None:
            self.page = FakePage()
            self.pages = [self.page]

        def route(self, pattern: str, handler: Any) -> None:
            return

        def route_web_socket(self, pattern: Any, handler: Any) -> None:
            return

        def new_page(self) -> FakePage:
            return self.page

        def close(self) -> None:
            captured["closed"] = True

    class FakeChromium:
        def launch_persistent_context(self, *args: Any, **kwargs: Any) -> FakeContext:
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self) -> "FakePlaywright":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(runtime_service, "sync_playwright", lambda: FakePlaywright())

    result = runtime_service._run_browser(
        {
            "allowed_hosts": ["example.com"],
            "deny_private_networks": True,
            "max_session_seconds": 5,
            "deadline_epoch_ms": int((time.time() + 5) * 1000),
            "max_actions_per_run": 1,
            "confirmation": {
                "confirmed": True,
                "confirmation_id": "confirm-type",
                "approved_action_ids": ["type-token"],
            },
            "write_confirmation_policy": {"mode": "before_each_external_write"},
            "profile": {"profile_id": "type-text", "ephemeral": True},
            "actions": [
                {
                    "type": "type",
                    "selector": "#token",
                    "text": "runtime-type-token-value",
                    "action_id": "type-token",
                }
            ],
        }
    )

    assert result["ok"] is True
    assert captured["selector"] == "#token"
    assert captured["value"] == "runtime-type-token-value"
    assert captured["closed"] is True


def test_browser_runtime_forbids_captcha_paywall_login_bypass_and_unauthorized_automation() -> None:
    client = BrowserAutomationRuntimeClient(approved_browser_policy())
    forbidden_actions = [
        {"type": "captcha_bypass", "url": "https://example.com"},
        {"type": "navigate", "url": "https://example.com", "intent": "paywall bypass"},
        {"type": "navigate", "url": "https://example.com", "intent": "login-bypass"},
        {"type": "navigate", "url": "https://example.com", "intent": "unauthorized automation"},
    ]

    for action in forbidden_actions:
        with pytest.raises(BrowserAutomationPolicyError, match="FORBIDDEN"):
            client.build_runtime_payload([action])


def test_browser_runtime_redacts_cookies_screenshots_and_trace_sensitive_values() -> None:
    recorder = BrowserAutomationTraceRecorder(
        max_trace_bytes=65536,
        redaction_policy={"sensitive_keys": ["email"]},
        trace_retention_days=7,
    )
    recorder.record_event(
        "runtime_response",
        {
            "headers": {"authorization": "Bearer raw-token"},
            "cookies": [{"name": "session", "value": "raw-cookie"}],
            "screenshot_bytes": b"raw-screenshot-bytes",
            "url": "https://example.com/path?secret=raw-query-secret",
            "email": "person@example.com",
            "safe_text": "visible evidence",
        },
    )
    artifact = recorder.artifact(run_id="trace-redaction")
    encoded = json.dumps(artifact, sort_keys=True)

    assert "raw-token" not in encoded
    assert "raw-cookie" not in encoded
    assert "raw-screenshot-bytes" not in encoded
    assert "raw-query-secret" not in encoded
    assert "person@example.com" not in encoded
    assert "visible evidence" in encoded
    assert artifact["redaction"]["cookies"] == 1
    assert artifact["redaction"]["screenshots"] == 1

    redacted, summary = redact_trace_value({"password": "secret-password", "body": "ok"})
    assert redacted["password"] == "[REDACTED]"
    assert summary.sensitive_values == 1

    action_redacted, action_summary = redact_trace_value({"type": "fill", "value": "not-trace-safe"})
    assert action_redacted["value"] == "[REDACTED]"
    assert action_summary.sensitive_values == 1

    configured_safe_action, configured_safe_summary = redact_trace_value(
        {"type": "fill", "value": "public-search-term"},
        policy={"safe_action_value_fields": ["value"]},
    )
    assert configured_safe_action["value"] == "[REDACTED]"
    assert configured_safe_summary.sensitive_values == 1


@pytest.mark.asyncio
async def test_browser_runtime_enforces_per_user_system_concurrency_max_actions_and_cleanup_releases_resources() -> None:
    max_action_client = BrowserAutomationRuntimeClient(approved_browser_policy(max_actions_per_run=1))
    with pytest.raises(BrowserAutomationPolicyError, match="MAX_ACTIONS_EXCEEDED"):
        max_action_client.build_runtime_payload(
            [
                {"type": "navigate", "url": "https://example.com"},
                {"type": "dom_snapshot", "url": "https://example.com"},
            ]
        )

    user_limiter = BrowserAutomationConcurrencyLimiter(system_limit=2)
    user_transport = BlockingBrowserTransport()
    policy = approved_browser_policy(concurrency_limit=1, system_concurrency_limit=2)
    first_client = BrowserAutomationRuntimeClient(policy, transport=user_transport, limiter=user_limiter)
    second_client = BrowserAutomationRuntimeClient(policy, transport=EchoBrowserTransport(), limiter=user_limiter)

    first_run = asyncio.create_task(first_client.run([{"type": "navigate", "url": "https://example.com"}]))
    await user_transport.started.wait()
    assert user_limiter.evidence.active_system == 1
    with pytest.raises(BrowserAutomationRuntimeError, match="USER_CONCURRENCY_LIMIT"):
        await second_client.run([{"type": "navigate", "url": "https://example.com"}])
    user_transport.release.set()
    await first_run
    assert user_limiter.evidence.active_system == 0
    assert user_limiter.evidence.active_by_user == {}
    assert user_limiter.evidence.cleanup_events[-1]["reason"] == "success"

    system_limiter = BrowserAutomationConcurrencyLimiter(system_limit=1)
    system_transport = BlockingBrowserTransport()
    first_policy = approved_browser_policy(system_concurrency_limit=1)
    second_policy = approved_browser_policy(
        tenant_id=first_policy.tenant_id,
        user_id=uuid.uuid4(),
        system_concurrency_limit=1,
    )
    first_system_client = BrowserAutomationRuntimeClient(first_policy, transport=system_transport, limiter=system_limiter)
    second_system_client = BrowserAutomationRuntimeClient(second_policy, transport=EchoBrowserTransport(), limiter=system_limiter)

    system_run = asyncio.create_task(first_system_client.run([{"type": "navigate", "url": "https://example.com"}]))
    await system_transport.started.wait()
    with pytest.raises(BrowserAutomationRuntimeError, match="SYSTEM_CONCURRENCY_LIMIT"):
        await second_system_client.run([{"type": "navigate", "url": "https://example.com"}])
    system_transport.release.set()
    await system_run
    assert system_limiter.evidence.active_system == 0


@pytest.mark.asyncio
async def test_activated_browser_target_registers_tool(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    target, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)

    async with _async_session_factory() as db:
        browser_tools = await get_browser_tool_definitions(db, tenant_id, user_id=user_id)
    agent_tools = await get_agent_tools(str(tenant_id), str(user_id))
    manifest_ref = browser_tool_name(config.name)

    assert target.activation_status == "active"
    assert config.enabled is True
    assert config.last_verified_at is not None
    assert target.activated_resource_ref["manifest_ref"] == manifest_ref
    assert target.activated_resource_ref["exposed_to_runtime"] is True
    assert target.activation_result["tool_manifest"]["status"] == "active"
    assert target.activation_result["tool_manifest"]["manifest_ref"] == manifest_ref
    assert [tool["function"]["name"] for tool in browser_tools] == [manifest_ref]
    assert manifest_ref in {tool["function"]["name"] for tool in agent_tools}


@pytest.mark.asyncio
async def test_unverified_browser_target_is_not_callable(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _browser_proposal(tenant_id, user_id)
    async with _async_session_factory() as db:
        target = ActivationTarget(
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            target_type="browser_automation",
            target_name="unverified browser probe",
            target_owner="core/browser_automation",
            target_payload=_browser_primary_target(name="unverified browser probe")["target_payload"],
            permission_bundle=_browser_permission_bundle(),
            verification_plan={"kind": "browser_contract"},
            rollback_plan={"disable": True},
            activation_status="active",
            activation_result={"phase": "active"},
            activated_resource_ref={
                "kind": "browser_automation_configuration",
                "manifest_ref": "browser__unverified_browser_probe",
                "tool_name": "browser__unverified_browser_probe",
                "exposed_to_runtime": True,
            },
        )
        db.add(target)
        await db.flush()
        config = BrowserAutomationConfiguration(
            tenant_id=tenant_id,
            user_id=user_id,
            activation_target_id=target.id,
            name="unverified browser probe",
            allowlisted_domains=["example.com"],
            runtime_service_name="browser-runtime",
            runtime_image_ref="chainless-browser-runtime:w6-1",
            runtime_health_check={"path": "/health"},
            network_policy={
                "mode": "allowlist",
                "allowed_hosts": ["example.com"],
                "deny_private_networks": True,
                "allow_docker_socket": False,
                "allow_host_fs": False,
                "mounts": [],
            },
            cookie_scope={"mode": "runtime_only", "persist_cookies": False},
            profile_policy={"isolation": "per_run", "allow_host_fs": False},
            profile_retention_policy={"mode": "discard_after_run"},
            max_session_seconds=10,
            max_actions_per_run=5,
            concurrency_limit=1,
            cpu_limit="1.0",
            memory_limit_mb=512,
            max_trace_bytes=65536,
            trace_retention_days=7,
            action_redaction_policy={},
            write_confirmation_policy={"mode": "before_each_external_write"},
            enabled=True,
            last_verified_at=None,
        )
        db.add(config)
        await db.commit()

    async with _async_session_factory() as db:
        assert await get_browser_tool_definitions(db, tenant_id, user_id=user_id) == []
        with pytest.raises(ValueError, match="Browser automation tool not found"):
            await execute_browser_tool(
                "browser__unverified_browser_probe",
                {"actions": [{"type": "navigate", "url": "https://example.com"}]},
                context={"tenant_id": tenant_id, "user_id": user_id, "db": db},
            )


@pytest.mark.asyncio
async def test_stale_snapshot_blocks_browser_activation(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, approved_hash = await _approved_browser_proposal(tenant_id, user_id)
    async with _async_session_factory() as db:
        proposal = (
            await db.execute(
                select(AcquisitionProposal).where(
                    AcquisitionProposal.tenant_id == tenant_id,
                    AcquisitionProposal.user_id == user_id,
                    AcquisitionProposal.id == proposal_id,
                )
            )
        ).scalar_one()
        proposal.activation_snapshot_hash = "sha256:stale-browser-snapshot"
        proposal.snapshot_created_at = datetime.now(timezone.utc)
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await run_activation_saga(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal_id,
                approved_hash=approved_hash,
                idempotency_key=f"browser-stale-{proposal_id}",
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["error"]["code"] == "VERIFIED_SNAPSHOT_HASH_REQUIRED"
        browser_config_count = (
            await db.execute(
                select(BrowserAutomationConfiguration).where(
                    BrowserAutomationConfiguration.tenant_id == tenant_id,
                    BrowserAutomationConfiguration.user_id == user_id,
                )
            )
        ).scalars().all()
        assert browser_config_count == []


@pytest.mark.asyncio
async def test_browser_target_bumps_tool_manifest_version_on_activation_and_rollback(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    target, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)
    active_manifest = target.activation_result["tool_manifest"]

    async with _async_session_factory() as db:
        result = await rollback_activation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            reason="W6.2 manifest rollback test",
            idempotency_key=f"browser-rollback-{proposal_id}",
        )
        await db.commit()

    rolled_back_target, rolled_back_config = await _activated_browser_rows(tenant_id, user_id, proposal_id)
    rollback_manifest = rolled_back_target.activation_result["rollback"]["manifest"]

    assert result.status == "rolled_back"
    assert active_manifest["status"] == "active"
    assert active_manifest["manifest_version"]
    assert active_manifest["manifest_ref"] == browser_tool_name(config.name)
    assert rolled_back_target.activation_status == "rolled_back"
    assert rolled_back_target.activated_resource_ref["hidden"] is True
    assert rolled_back_config.enabled is False
    assert rollback_manifest["status"] == "hidden"
    assert rollback_manifest["manifest_version"]
    assert rollback_manifest["manifest_version"] != active_manifest["manifest_version"]
    assert str(rolled_back_config.id) in rollback_manifest["disabled_config_ids"]


@pytest.mark.asyncio
async def test_browser_target_uses_runtime_confirmation_policy(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    _, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)
    tool_name = browser_tool_name(config.name)
    captured: dict[str, Any] = {}

    class FakeBrowserRuntimeClient:
        def __init__(self, policy: BrowserAutomationRuntimePolicy) -> None:
            captured["policy"] = policy

        async def run(
            self,
            actions: list[dict[str, Any]],
            *,
            context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            captured["actions"] = actions
            captured["context"] = context or {}
            return {
                "ok": True,
                "actions": actions,
                "confirmation": (context or {}).get("confirmation_context") or {},
            }

    monkeypatch.setattr("app.core.browser_automation.registry.BrowserAutomationRuntimeClient", FakeBrowserRuntimeClient)
    args = {
        "actions": [
            {
                "type": "submit",
                "url": "https://example.com/form",
                "selector": "#submit",
                "external_write": True,
                "action_id": "submit-form",
                "value": "raw-secret-form-value",
            }
        ],
        "purpose": "submit a user-approved public form",
    }

    async with _async_session_factory() as db:
        with pytest.raises(BrowserAutomationConfirmationRequired) as confirmation:
            await execute_browser_tool(
                tool_name,
                args,
                context={"tenant_id": tenant_id, "user_id": user_id, "db": db},
            )
        request = confirmation.value
        assert request.code == "RUNTIME_CONFIRMATION_REQUIRED"
        assert request.confirmation_context["target_type"] == "browser_automation"
        assert request.confirmation_context["action_category"] == "browser_external_write"
        assert "raw-secret-form-value" not in json.dumps(request.sanitized_args)

        confirmed_context = dict(request.confirmation_context)
        confirmed_context["confirmed"] = True
        result_payload = json.loads(
            await execute_browser_tool(
                tool_name,
                args,
                context={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "db": db,
                    "confirmation_context": confirmed_context,
                    "tool_call_id": "browser-call-1",
                },
            )
        )

    runtime_confirmation = captured["context"]["confirmation_context"]
    assert result_payload["ok"] is True
    assert captured["actions"][0]["action_id"] == "submit-form"
    assert runtime_confirmation["confirmed"] is True
    assert runtime_confirmation["confirmation_id"] == "browser-call-1"
    assert runtime_confirmation["approved_action_ids"] == ["submit-form"]


@pytest.mark.asyncio
async def test_browser_confirmation_redacts_public_args_but_replays_original(
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    _, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)
    tool_name = browser_tool_name(config.name)
    raw_secret = "raw-secret-form-value"
    captured: dict[str, Any] = {}

    class FakeBrowserRuntimeClient:
        def __init__(self, policy: BrowserAutomationRuntimePolicy) -> None:
            captured["policy"] = policy

        async def run(
            self,
            actions: list[dict[str, Any]],
            *,
            context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            captured["actions"] = actions
            captured["context"] = context or {}
            return {"ok": True, "submitted_value": actions[0]["value"]}

    monkeypatch.setattr("app.core.browser_automation.registry.BrowserAutomationRuntimeClient", FakeBrowserRuntimeClient)

    executable_args = {
        "actions": [
            {
                "type": "submit",
                "url": "https://example.com/form",
                "selector": "#submit",
                "external_write": True,
                "action_id": "submit-form",
                "value": raw_secret,
            }
        ]
    }
    async with _async_session_factory() as db:
        with pytest.raises(BrowserAutomationConfirmationRequired) as confirmation:
            await execute_browser_tool(
                tool_name,
                executable_args,
                context={"tenant_id": tenant_id, "user_id": user_id, "db": db},
            )
    confirmation_args = dict(confirmation.value.original_args)
    confirmation_args["__public_args"] = dict(confirmation.value.sanitized_args)
    confirmation_args["__acquisition_confirmation_context"] = confirmation.value.confirmation_context

    mapped = public_agent_event(
        {
            "type": "confirmation_required",
            "tool_call_id": "browser-confirm-raw",
            "tool_name": tool_name,
            "args": confirmation_args,
            "risk": confirmation.value.risk,
            "timeout_s": 30,
        }
    )
    assert mapped is not None
    _, public_data = mapped
    assert raw_secret not in json.dumps(public_data["args"])
    assert public_data["args"]["actions"][0]["value"] == "[REDACTED]"
    assert raw_secret in json.dumps(public_data["__persisted_args"])

    async with _async_session_factory() as db:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="browser confirmation")
        db.add(conversation)
        await db.commit()
        conversation_id = conversation.id
        await persist_confirmation_required(
            db,
            conversation_id,
            tool_call_id="browser-confirm-raw",
            tool_name=tool_name,
            args=public_data["__persisted_args"],
            risk=confirmation.value.risk,
            timeout_s=30,
        )
        claimed = await claim_confirmation(db, conversation_id, "browser-confirm-raw", "approve")

    assert raw_secret in json.dumps(claimed.args)
    assert "__public_args" not in claimed.args

    result = json.loads(
        await execute_confirmed_tool(
            tool_name,
            dict(claimed.args),
            sandbox=None,  # type: ignore[arg-type]
            gateway=None,  # type: ignore[arg-type]
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            tool_call_id="browser-confirm-raw",
            run_id="browser-confirm-replay",
            risk=confirmation.value.risk,
        )
    )

    assert result["ok"] is True
    assert result["submitted_value"] == raw_secret
    assert captured["actions"][0]["value"] == raw_secret
    assert captured["context"]["confirmation_context"]["approved_action_ids"] == ["submit-form"]


def test_browser_public_args_strip_url_query_and_fragment() -> None:
    raw_url = "https://example.com/path?token=raw-url-token#secret-fragment"
    raw_args = {
        "actions": [
            {
                "type": "navigate",
                "url": raw_url,
                "value": "raw-action-value",
            }
        ]
    }

    mapped = public_agent_event(
        {
            "type": "tool_call_start",
            "tool_call_id": "browser-tool-call",
            "name": "browser__public_browser_probe",
            "args": raw_args,
            "risk": "risky",
        }
    )

    assert mapped is not None
    _, public_data = mapped
    encoded_public = json.dumps(public_data, sort_keys=True)
    assert "raw-url-token" not in encoded_public
    assert "secret-fragment" not in encoded_public
    assert "raw-action-value" not in encoded_public
    assert public_data["args"]["actions"][0]["url"] == "https://example.com/path"
    assert public_data["args"]["actions"][0]["value"] == "[REDACTED]"

    message = build_confirmation_message(
        uuid.uuid4(),
        confirmation="pending",
        tool_call_id="browser-confirmation",
        tool_name="browser__public_browser_probe",
        args=raw_args,
    )
    encoded_meta = json.dumps(message.meta_data, sort_keys=True)
    assert "raw-url-token" not in encoded_meta
    assert "secret-fragment" not in encoded_meta
    assert "raw-action-value" not in encoded_meta
    assert message.meta_data["args"]["actions"][0]["url"] == "https://example.com/path"


def test_browser_public_args_with_explicit_public_payload_still_strip_url_userinfo() -> None:
    mapped = public_agent_event(
        {
            "type": "confirmation_required",
            "tool_call_id": "browser-confirm-userinfo",
            "tool_name": "browser__public_browser_probe",
            "args": {
                "actions": [
                    {
                        "type": "navigate",
                        "url": "https://user:pass@example.com/path?token=raw-url-token#secret-fragment",
                        "value": "raw-action-value",
                    }
                ],
                "__public_args": {
                    "actions": [
                        {
                            "type": "navigate",
                            "url": "https://user:pass@example.com/path",
                            "value": "[REDACTED]",
                        }
                    ]
                },
            },
            "risk": "risky",
            "timeout_s": 30,
        }
    )

    assert mapped is not None
    _, public_data = mapped
    encoded_public = json.dumps(public_data["args"], sort_keys=True)
    assert "user:pass" not in encoded_public
    assert "raw-url-token" not in encoded_public
    assert "secret-fragment" not in encoded_public
    assert "raw-action-value" not in encoded_public
    assert public_data["args"]["actions"][0]["url"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_browser_target_acquisition_egress_policy_blocks_host_expansion(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    target = _browser_primary_target(name="wide browser probe")
    target["target_payload"]["allowlisted_domains"] = ["example.com", "evil.example.net"]
    target["target_payload"]["network_policy"]["allowed_hosts"] = ["example.com", "evil.example.net"]
    proposal_id, approved_hash = await _approved_browser_proposal(tenant_id, user_id, target=target)

    async with _async_session_factory() as db:
        proposal = await run_activation_saga(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            approved_hash=approved_hash,
            idempotency_key=f"browser-wide-host-{proposal_id}",
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted_target = (
            await db.execute(
                select(ActivationTarget).where(
                    ActivationTarget.tenant_id == tenant_id,
                    ActivationTarget.user_id == user_id,
                    ActivationTarget.proposal_id == proposal_id,
                )
            )
        ).scalar_one()
        configs = (
            await db.execute(
                select(BrowserAutomationConfiguration).where(
                    BrowserAutomationConfiguration.tenant_id == tenant_id,
                    BrowserAutomationConfiguration.user_id == user_id,
                    BrowserAutomationConfiguration.activation_target_id == persisted_target.id,
                )
            )
        ).scalars().all()

    assert proposal.status == "activation_failed"
    assert persisted_target.activation_status == "activation_failed"
    assert persisted_target.activation_result["error_code"] == "INVALID_BROWSER_AUTOMATION_POLICY"
    assert configs == []


@pytest.mark.asyncio
async def test_browser_target_runtime_egress_policy_denies_legacy_broadened_config(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    _, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)
    tool_name = browser_tool_name(config.name)

    async with _async_session_factory() as db:
        persisted = (
            await db.execute(
                select(BrowserAutomationConfiguration).where(BrowserAutomationConfiguration.id == config.id)
            )
        ).scalar_one()
        persisted.allowlisted_domains = ["example.com", "evil.example.net"]
        persisted.network_policy = {
            **persisted.network_policy,
            "allowed_hosts": ["example.com", "evil.example.net"],
        }
        await db.commit()

    async with _async_session_factory() as db:
        result = json.loads(
            await execute_browser_tool(
                tool_name,
                {"actions": [{"type": "navigate", "url": "https://evil.example.net"}]},
                context={"tenant_id": tenant_id, "user_id": user_id, "db": db},
            )
        )

    assert result["ok"] is False
    assert result["error"]["code"] == "HOST_NOT_ALLOWLISTED"
    assert result["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_activated_browser_target_executes_against_compose_runtime(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal_id, _ = await _activate_browser_proposal(tenant_id, user_id)
    _, config = await _activated_browser_rows(tenant_id, user_id, proposal_id)

    async with _async_session_factory() as db:
        result = json.loads(
            await execute_browser_tool(
                browser_tool_name(config.name),
                {
                    "actions": [
                        {"type": "navigate", "url": "https://example.com"},
                        {"type": "dom_snapshot"},
                    ]
                },
                context={"tenant_id": tenant_id, "user_id": user_id, "db": db},
            )
        )

    assert result["ok"] is True
    assert result["result"]["ok"] is True
    assert result["result"]["evidence"][0]["type"] == "navigate"
    assert result["result"]["evidence"][0]["title"] == "Example Domain"
    assert result["result"]["evidence"][1]["type"] == "dom_snapshot"
    assert "Example Domain" in result["result"]["evidence"][1]["text"]
    assert result["profile"]["ephemeral"] is True
    assert result["trace_artifact"]["artifact_type"] == "browser_automation_trace"
