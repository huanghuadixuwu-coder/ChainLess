"""Activation hook that materializes acquired API tools."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import TargetActivationResult
from app.models.acquisition import APIToolConfiguration, ActivationTarget, AcquisitionProposal, CredentialConnection

from .policy import APIToolPolicyError, APIToolRuntimePolicy, api_tool_name, validate_api_runtime_policy


def _now() -> datetime:
    return datetime.now(timezone.utc)


RUNTIME_RESOLVABLE_CREDENTIAL_STORAGE_KINDS = frozenset({"encrypted_db"})


class _ActivationValidationFailure(RuntimeError):
    def __init__(self, result: TargetActivationResult) -> None:
        super().__init__(result.error_message or result.error_code or "API tool activation validation failed")
        self.result = result


class APIToolActivationHooks:
    """Runtime activation owner for generic API tools."""

    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        if target.target_type != "api_tool":
            return TargetActivationResult(
                success=False,
                error_code="UNSUPPORTED_TARGET_TYPE",
                error_message="API tool activation hook only supports api_tool targets",
                evidence={"hook": "api_tool_activation", "target_type": target.target_type},
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
                select(APIToolConfiguration)
                .where(
                    APIToolConfiguration.tenant_id == target.tenant_id,
                    APIToolConfiguration.user_id == target.user_id,
                    APIToolConfiguration.activation_target_id == target.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if config is None:
            config = APIToolConfiguration(
                tenant_id=target.tenant_id,
                user_id=target.user_id,
                activation_target_id=target.id,
                name=name,
                tool_name=api_tool_name(name),
                base_url="https://example.invalid",
                method="GET",
                path_template="/",
                headers_schema={},
                auth_scheme="none",
                input_schema={},
                output_schema={},
                allowed_hosts=[],
                deny_private_networks=True,
                redirect_policy={"follow": False},
                allowed_content_types=["application/json"],
                max_request_bytes=1,
                max_response_bytes=1,
                idempotency_policy={},
                response_redaction_policy={},
                rate_limit={},
                timeout_s=1,
                retry_policy={},
                error_contract={},
                enabled=False,
                risk_level="safe",
            )

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
                        TargetActivationResult(
                            success=False,
                            error_code="API_TOOL_NAME_COLLISION",
                            error_message="An active API tool with this runtime name already exists for this user",
                            evidence={
                                "hook": "api_tool_activation",
                                "tool_name": config.tool_name,
                                "existing_configuration_id": str(collision.id),
                            },
                        )
                    )
                config.credential_ref = credential_ref
                config.credential_generation = credential.secret_generation if credential is not None else None
                config.last_verified_at = _now()
                validate_api_runtime_policy(APIToolRuntimePolicy.from_model(config))
                config.enabled = True
                await db.flush()
        except _ActivationValidationFailure as exc:
            return exc.result
        except IntegrityError:
            return _activation_failure(
                "API_TOOL_NAME_COLLISION",
                "An active API tool with this runtime name already exists for this user",
                {"hook": "api_tool_activation", "tool_name": api_tool_name(name)},
            )
        except (APIToolPolicyError, ValueError) as exc:
            return _activation_failure(
                "INVALID_API_TOOL_POLICY",
                "API tool activation payload failed runtime policy validation",
                {"hook": "api_tool_activation", "reason": exc.__class__.__name__},
            )

        manifest_ref = config.tool_name
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": "api_tool_configuration",
                "configuration_id": str(config.id),
                "activation_target_id": str(target.id),
                "manifest_ref": manifest_ref,
                "tool_name": manifest_ref,
                "exposed_to_runtime": True,
            },
            evidence={
                "hook": "api_tool_activation",
                "runtime_side_effects": True,
                "configuration_id": str(config.id),
                "approved_snapshot_hash": approved_hash,
                "idempotency_key": idempotency_key,
            },
        )


def _apply_payload(
    config: APIToolConfiguration,
    *,
    payload: Mapping[str, Any],
    bundle: Mapping[str, Any],
    proposal: AcquisitionProposal,
    credential_ref: uuid.UUID | None,
) -> None:
    egress_policy = bundle.get("egress_policy") if isinstance(bundle.get("egress_policy"), Mapping) else {}
    config.name = str(payload.get("name") or config.name)
    config.tool_name = api_tool_name(config.name)
    config.base_url = str(payload.get("base_url") or config.base_url)
    config.method = str(payload.get("method") or config.method).upper()
    config.path_template = str(payload.get("path_template") or "/")
    config.headers_schema = _dict(payload.get("headers_schema"))
    config.auth_scheme = str(payload.get("auth_scheme") or ("bearer" if credential_ref else "none"))
    config.input_schema = _dict(payload.get("input_schema")) or {"type": "object", "properties": {}}
    config.output_schema = _dict(payload.get("output_schema"))
    config.allowed_hosts = _strings(payload.get("allowed_hosts") or egress_policy.get("allow_hosts"))
    config.deny_private_networks = bool(payload.get("deny_private_networks", egress_policy.get("deny_private_networks", True)))
    config.redirect_policy = _dict(payload.get("redirect_policy")) or _dict(egress_policy.get("redirect_policy")) or {"follow": False}
    config.allowed_content_types = _strings(payload.get("allowed_content_types")) or ["application/json"]
    config.max_request_bytes = int(payload.get("max_request_bytes") or 65536)
    config.max_response_bytes = int(payload.get("max_response_bytes") or egress_policy.get("max_response_bytes") or 1048576)
    config.idempotency_policy = _dict(payload.get("idempotency_policy"))
    config.response_redaction_policy = _dict(payload.get("response_redaction_policy"))
    config.rate_limit = _dict(payload.get("rate_limit"))
    config.timeout_s = int(payload.get("timeout_s") or 10)
    config.retry_policy = _dict(payload.get("retry_policy"))
    config.error_contract = _dict(payload.get("error_contract"))
    config.risk_level = str(payload.get("risk_level") or bundle.get("risk_level") or proposal.risk_level)


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


async def _tool_name_collision(db: AsyncSession, config: APIToolConfiguration) -> APIToolConfiguration | None:
    query = select(APIToolConfiguration).where(
        APIToolConfiguration.tenant_id == config.tenant_id,
        APIToolConfiguration.user_id == config.user_id,
        APIToolConfiguration.tool_name == config.tool_name,
    )
    if config.id is not None:
        query = query.where(APIToolConfiguration.id != config.id)
    with db.no_autoflush:
        return (await db.execute(query.limit(1))).scalar_one_or_none()


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
            "API tool credential connection was not found for this user",
            {"hook": "api_tool_activation", "credential_ref": str(credential_ref)},
        )
    if credential.status != "active":
        return None, _activation_failure(
            "CREDENTIAL_NOT_ACTIVE",
            "API tool credential connection is not active",
            {"hook": "api_tool_activation", "credential_ref": str(credential_ref), "status": credential.status},
        )
    if credential.expires_at is not None and credential.expires_at <= _now():
        return None, _activation_failure(
            "CREDENTIAL_EXPIRED",
            "API tool credential connection is expired",
            {"hook": "api_tool_activation", "credential_ref": str(credential_ref)},
        )
    if credential.secret_storage_kind not in RUNTIME_RESOLVABLE_CREDENTIAL_STORAGE_KINDS:
        return None, _activation_failure(
            "CREDENTIAL_SECRET_NOT_RESOLVABLE",
            "API tool credential connection is not resolvable by the current runtime",
            {
                "hook": "api_tool_activation",
                "credential_ref": str(credential_ref),
                "secret_storage_kind": credential.secret_storage_kind,
            },
        )
    if credential.allowed_target_types and "api_tool" not in credential.allowed_target_types:
        return None, _activation_failure(
            "CREDENTIAL_NOT_ALLOWED_FOR_API_TOOL",
            "API tool credential connection is not allowed for api_tool targets",
            {"hook": "api_tool_activation", "credential_ref": str(credential_ref)},
        )
    return credential, None


def _credential_target_ref_failure(
    credential: CredentialConnection | None,
    *,
    config: APIToolConfiguration,
    target: ActivationTarget,
) -> TargetActivationResult | None:
    if credential is None or not credential.allowed_target_refs:
        return None
    target_ref = _credential_target_ref(config=config, target=target)
    if any(_target_ref_matches(allowed_ref, target_ref) for allowed_ref in credential.allowed_target_refs):
        return None
    return _activation_failure(
        "CREDENTIAL_TARGET_NOT_ALLOWED",
        "API tool credential connection is not allowed for this API tool target",
        {
            "hook": "api_tool_activation",
            "credential_ref": str(credential.id),
            "tool_name": config.tool_name,
            "activation_target_id": str(target.id),
        },
    )


def _credential_target_ref(*, config: APIToolConfiguration, target: ActivationTarget) -> dict[str, str]:
    return {
        "id": str(config.id),
        "configuration_id": str(config.id),
        "target_id": str(target.id),
        "activation_target_id": str(target.id),
        "ref": config.tool_name,
        "manifest_ref": config.tool_name,
        "tool_name": config.tool_name,
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
