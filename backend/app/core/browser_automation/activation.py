"""Activation hook that materializes acquired browser automation targets."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import TargetActivationResult
from app.core.acquisition.tool_manifest import active_target_manifest_evidence
from app.models.acquisition import (
    ActivationTarget,
    AcquisitionProposal,
    BrowserAutomationConfiguration,
    CredentialConnection,
)

from .policy import (
    BrowserAutomationPolicyError,
    BrowserAutomationRuntimePolicy,
    browser_tool_name,
    host_pattern_is_subset,
    validate_browser_runtime_policy,
)


RUNTIME_RESOLVABLE_CREDENTIAL_STORAGE_KINDS = frozenset({"encrypted_db"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _ActivationValidationFailure(RuntimeError):
    def __init__(self, result: TargetActivationResult) -> None:
        super().__init__(result.error_message or result.error_code or "Browser automation activation failed")
        self.result = result


class BrowserAutomationActivationHooks:
    """Runtime activation owner for browser automation targets."""

    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        if target.target_type != "browser_automation":
            return _activation_failure(
                "UNSUPPORTED_TARGET_TYPE",
                "Browser automation activation hook only supports browser_automation targets",
                {"hook": "browser_automation_activation", "target_type": target.target_type},
            )

        payload = target.target_payload if isinstance(target.target_payload, Mapping) else {}
        bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
        name = str(payload.get("name") or target.target_name)
        credential_ref = _credential_ref(payload, bundle)
        credential, credential_failure = await _credential_for_activation(
            db,
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            credential_ref=credential_ref,
        )
        if credential_failure is not None:
            return credential_failure

        config = (
            await db.execute(
                select(BrowserAutomationConfiguration)
                .where(
                    BrowserAutomationConfiguration.tenant_id == target.tenant_id,
                    BrowserAutomationConfiguration.user_id == target.user_id,
                    BrowserAutomationConfiguration.activation_target_id == target.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if config is None:
            config = _default_config(target=target, name=name)

        try:
            async with db.begin_nested():
                if config not in db:
                    db.add(config)
                _apply_payload(config, payload=payload, bundle=bundle, proposal=proposal, credential_ref=credential_ref)
                if config.id is None:
                    config.id = uuid.uuid4()
                credential_ref_failure = _credential_target_ref_failure(credential, config=config, target=target)
                if credential_ref_failure is not None:
                    raise _ActivationValidationFailure(credential_ref_failure)
                collision = await _tool_name_collision(db, config)
                if collision is not None:
                    raise _ActivationValidationFailure(
                        _activation_failure(
                            "BROWSER_TOOL_NAME_COLLISION",
                            "An active browser automation tool with this runtime name already exists for this user",
                            {
                                "hook": "browser_automation_activation",
                                "tool_name": browser_tool_name(config.name),
                                "existing_configuration_id": str(collision.id),
                            },
                        )
                    )
                config.credential_ref = credential_ref
                config.credential_generation = credential.secret_generation if credential is not None else None
                config.last_verified_at = _now()
                config.enabled = True
                validate_browser_runtime_policy(BrowserAutomationRuntimePolicy.from_model(config))
                await db.flush()
        except _ActivationValidationFailure as exc:
            return exc.result
        except (BrowserAutomationPolicyError, ValueError) as exc:
            return _activation_failure(
                "INVALID_BROWSER_AUTOMATION_POLICY",
                "Browser automation activation payload failed runtime policy validation",
                {"hook": "browser_automation_activation", "reason": exc.__class__.__name__},
            )

        manifest_ref = browser_tool_name(config.name)
        activated_resource_ref = {
            "kind": "browser_automation_configuration",
            "configuration_id": str(config.id),
            "activation_target_id": str(target.id),
            "manifest_ref": manifest_ref,
            "tool_name": manifest_ref,
            "exposed_to_runtime": True,
        }
        tool_manifest = active_target_manifest_evidence(
            resource_ref=activated_resource_ref,
            target=target,
            idempotency_key=idempotency_key,
        )
        return TargetActivationResult(
            success=True,
            activated_resource_ref=activated_resource_ref,
            evidence={
                "hook": "browser_automation_activation",
                "runtime_side_effects": False,
                "durable_side_effects": True,
                "configuration_id": str(config.id),
                "approved_snapshot_hash": approved_hash,
                "idempotency_key": idempotency_key,
                "tool_manifest": tool_manifest,
            },
        )


def _default_config(*, target: ActivationTarget, name: str) -> BrowserAutomationConfiguration:
    return BrowserAutomationConfiguration(
        tenant_id=target.tenant_id,
        user_id=target.user_id,
        activation_target_id=target.id,
        name=name,
        allowlisted_domains=[],
        credential_ref=None,
        credential_generation=None,
        runtime_service_name="browser-runtime",
        runtime_image_ref="chainless-browser-runtime:w6-1",
        runtime_health_check={"path": "/health", "interval_seconds": 10},
        network_policy={
            "mode": "allowlist",
            "allowed_hosts": [],
            "deny_private_networks": True,
            "allow_docker_socket": False,
            "allow_host_fs": False,
            "mounts": [],
        },
        cookie_scope={"mode": "runtime_only", "persist_cookies": False},
        profile_policy={"isolation": "per_run", "allow_host_fs": False},
        profile_storage_ref=None,
        profile_retention_policy={"mode": "discard_after_run"},
        max_session_seconds=10,
        max_actions_per_run=10,
        concurrency_limit=1,
        cpu_limit="1.0",
        memory_limit_mb=512,
        max_trace_bytes=65536,
        trace_retention_days=7,
        action_redaction_policy={},
        write_confirmation_policy={"mode": "before_each_external_write"},
        enabled=False,
    )


def _apply_payload(
    config: BrowserAutomationConfiguration,
    *,
    payload: Mapping[str, Any],
    bundle: Mapping[str, Any],
    proposal: AcquisitionProposal,
    credential_ref: uuid.UUID | None,
) -> None:
    egress_policy = bundle.get("egress_policy") if isinstance(bundle.get("egress_policy"), Mapping) else {}
    permission_scope = bundle.get("permission_scope") if isinstance(bundle.get("permission_scope"), Mapping) else {}
    network_policy = _dict(payload.get("network_policy")) or _dict(egress_policy)

    allowed_hosts = (
        _strings(network_policy.get("allowed_hosts"))
        or _strings(network_policy.get("allow_hosts"))
        or _strings(payload.get("allowed_hosts"))
        or _strings(payload.get("allowlisted_domains"))
        or _strings(permission_scope.get("hosts"))
        or _strings(egress_policy.get("allow_hosts"))
    )
    if allowed_hosts:
        network_policy["allowed_hosts"] = allowed_hosts
    _validate_allowed_hosts_within_egress(allowed_hosts, bundle)
    network_policy["mode"] = str(network_policy.get("mode") or "allowlist")
    network_policy["deny_private_networks"] = True
    network_policy["allow_docker_socket"] = False
    network_policy["allow_host_fs"] = False
    network_policy["mounts"] = []
    if payload.get("runtime_url"):
        network_policy["runtime_url"] = str(payload["runtime_url"])

    config.name = str(payload.get("name") or config.name)
    config.allowlisted_domains = (
        _strings(payload.get("allowlisted_domains"))
        or _strings(payload.get("allowed_domains"))
        or allowed_hosts
    )
    config.runtime_service_name = str(payload.get("runtime_service_name") or config.runtime_service_name)
    config.runtime_image_ref = str(payload.get("runtime_image_ref") or config.runtime_image_ref)
    config.runtime_health_check = _dict(payload.get("runtime_health_check")) or config.runtime_health_check
    config.network_policy = network_policy
    config.cookie_scope = _dict(payload.get("cookie_scope")) or config.cookie_scope
    config.profile_policy = _dict(payload.get("profile_policy")) or config.profile_policy
    config.profile_storage_ref = _optional_text(payload.get("profile_storage_ref"))
    config.profile_retention_policy = _dict(payload.get("profile_retention_policy")) or config.profile_retention_policy
    config.max_session_seconds = _positive_int(payload.get("max_session_seconds"), config.max_session_seconds)
    config.max_actions_per_run = _positive_int(payload.get("max_actions_per_run"), config.max_actions_per_run)
    config.concurrency_limit = _positive_int(payload.get("concurrency_limit"), config.concurrency_limit)
    config.cpu_limit = str(payload.get("cpu_limit") or config.cpu_limit)
    config.memory_limit_mb = _positive_int(payload.get("memory_limit_mb"), config.memory_limit_mb)
    config.max_trace_bytes = _positive_int(
        payload.get("max_trace_bytes") or egress_policy.get("max_response_bytes"),
        config.max_trace_bytes,
    )
    config.trace_retention_days = _positive_int(payload.get("trace_retention_days"), config.trace_retention_days)
    config.action_redaction_policy = _dict(payload.get("action_redaction_policy")) or config.action_redaction_policy
    config.write_confirmation_policy = (
        _dict(payload.get("write_confirmation_policy"))
        or _dict(bundle.get("write_confirmation_policy"))
        or config.write_confirmation_policy
    )
    config.credential_ref = credential_ref
    config.credential_generation = None

    if not config.allowlisted_domains and allowed_hosts:
        config.allowlisted_domains = allowed_hosts
    if str(bundle.get("risk_level") or proposal.risk_level) == "blocked":
        raise ValueError("blocked browser automation targets cannot be activated")


def _credential_ref(payload: Mapping[str, Any], bundle: Mapping[str, Any]) -> uuid.UUID | None:
    raw = payload.get("credential_ref")
    if raw is None:
        refs = bundle.get("credential_connection_refs")
        if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)) and refs:
            raw = refs[0]
    if raw in (None, ""):
        return None
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _activation_failure(code: str, message: str, evidence: Mapping[str, Any] | None = None) -> TargetActivationResult:
    return TargetActivationResult(
        success=False,
        error_code=code,
        error_message=message,
        evidence=dict(evidence or {}),
    )


async def _tool_name_collision(
    db: AsyncSession,
    config: BrowserAutomationConfiguration,
) -> BrowserAutomationConfiguration | None:
    query = select(BrowserAutomationConfiguration).where(
        BrowserAutomationConfiguration.tenant_id == config.tenant_id,
        BrowserAutomationConfiguration.user_id == config.user_id,
        BrowserAutomationConfiguration.enabled.is_(True),
    )
    if config.id is not None:
        query = query.where(BrowserAutomationConfiguration.id != config.id)
    records = (await db.execute(query)).scalars().all()
    tool_name = browser_tool_name(config.name)
    return next((record for record in records if browser_tool_name(record.name) == tool_name), None)


async def _credential_for_activation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_ref: uuid.UUID | None,
) -> tuple[CredentialConnection | None, TargetActivationResult | None]:
    if credential_ref is None:
        return None, None
    credential = (
        await db.execute(
            select(CredentialConnection).where(
                CredentialConnection.id == credential_ref,
                CredentialConnection.tenant_id == tenant_id,
                CredentialConnection.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if credential is None:
        return None, _activation_failure(
            "CREDENTIAL_NOT_FOUND",
            "Browser automation credential connection was not found for this user",
            {"hook": "browser_automation_activation", "credential_ref": str(credential_ref)},
        )
    if credential.status != "active":
        return None, _activation_failure(
            "CREDENTIAL_NOT_ACTIVE",
            "Browser automation credential connection is not active",
            {"hook": "browser_automation_activation", "credential_ref": str(credential_ref), "status": credential.status},
        )
    if credential.expires_at is not None and credential.expires_at <= _now():
        return None, _activation_failure(
            "CREDENTIAL_EXPIRED",
            "Browser automation credential connection is expired",
            {"hook": "browser_automation_activation", "credential_ref": str(credential_ref)},
        )
    if credential.secret_storage_kind not in RUNTIME_RESOLVABLE_CREDENTIAL_STORAGE_KINDS:
        return None, _activation_failure(
            "CREDENTIAL_SECRET_NOT_RESOLVABLE",
            "Browser automation credential connection is not resolvable by the current runtime",
            {
                "hook": "browser_automation_activation",
                "credential_ref": str(credential_ref),
                "secret_storage_kind": credential.secret_storage_kind,
            },
        )
    if credential.allowed_target_types and "browser_automation" not in credential.allowed_target_types:
        return None, _activation_failure(
            "CREDENTIAL_NOT_ALLOWED_FOR_BROWSER_AUTOMATION",
            "Credential connection is not allowed for browser_automation targets",
            {"hook": "browser_automation_activation", "credential_ref": str(credential_ref)},
        )
    return credential, None


def _credential_target_ref_failure(
    credential: CredentialConnection | None,
    *,
    config: BrowserAutomationConfiguration,
    target: ActivationTarget,
) -> TargetActivationResult | None:
    if credential is None or not credential.allowed_target_refs:
        return None
    target_ref = _credential_target_ref(config=config, target=target)
    if any(_target_ref_matches(allowed_ref, target_ref) for allowed_ref in credential.allowed_target_refs):
        return None
    return _activation_failure(
        "CREDENTIAL_TARGET_NOT_ALLOWED",
        "Browser automation credential connection is not allowed for this target",
        {
            "hook": "browser_automation_activation",
            "credential_ref": str(credential.id),
            "tool_name": browser_tool_name(config.name),
            "activation_target_id": str(target.id),
        },
    )


def _credential_target_ref(*, config: BrowserAutomationConfiguration, target: ActivationTarget) -> dict[str, str]:
    tool_name = browser_tool_name(config.name)
    return {
        "id": str(config.id),
        "configuration_id": str(config.id),
        "target_id": str(target.id),
        "activation_target_id": str(target.id),
        "ref": tool_name,
        "manifest_ref": tool_name,
        "tool_name": tool_name,
        "name": config.name,
        "target_name": target.target_name,
    }


def _target_ref_matches(allowed_ref: Any, target_ref: Mapping[str, str]) -> bool:
    if not isinstance(allowed_ref, Mapping):
        return False
    return all(str(target_ref.get(str(key))) == str(value) for key, value in allowed_ref.items())


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if value in (None, "", [], {}, ()):
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return [str(value)]
    return [str(item) for item in value]


def _validate_allowed_hosts_within_egress(allowed_hosts: Sequence[str], bundle: Mapping[str, Any]) -> None:
    egress_policy = bundle.get("egress_policy") if isinstance(bundle.get("egress_policy"), Mapping) else {}
    egress_hosts = _strings(egress_policy.get("allow_hosts")) or _strings(egress_policy.get("allowed_hosts"))
    if not allowed_hosts:
        return
    if not egress_hosts:
        raise ValueError("browser automation activation requires permission_bundle.egress_policy.allow_hosts")
    for host in allowed_hosts:
        if not any(host_pattern_is_subset(str(host), str(allowed)) for allowed in egress_hosts):
            raise ValueError("browser automation network hosts must stay within permission_bundle.egress_policy.allow_hosts")


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _positive_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)
