"""Database-backed registry helpers for active generic API tools."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import approved_snapshot_hash
from app.core.acquisition.facade import runtime_capability_enabled
from app.core.acquisition.policy import (
    RuntimePermissionRequest,
    TargetPolicyDecision,
    build_runtime_confirmation_context,
    evaluate_runtime_permission,
)
from app.core.credentials.service import resolve_credential_secret
from app.core.tools.manifest import assert_user_tool_manifest_current
from app.models.acquisition import APIToolConfiguration, ActivationTarget, AcquisitionProposal, CredentialConnection

from .client import APIToolRuntimeClient, APIToolRuntimeError
from .policy import APIToolRuntimePolicy, APIToolPolicyError, validate_api_runtime_policy


class APIToolConfirmationRequired(RuntimeError):
    """Trusted backend confirmation request for an acquired API tool."""

    def __init__(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        risk: str,
        confirmation_context: Mapping[str, Any],
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.sanitized_args = dict(args)
        self.risk = risk
        self.confirmation_context = dict(confirmation_context)
        self.code = code
        self.message = message


def api_tool_definition(policy: APIToolRuntimePolicy) -> dict[str, Any]:
    """Return an OpenAI function-tool definition without secret material."""

    validate_api_runtime_policy(policy)
    return {
        "type": "function",
        "risk": policy.risk_level,
        "function": {
            "name": policy.tool_name,
            "description": f"Acquired API tool: {policy.name}",
            "parameters": policy.input_schema or {"type": "object", "properties": {}},
        },
    }


async def get_api_tool_definitions(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    *,
    user_id: str | uuid.UUID,
) -> list[dict[str, Any]]:
    """List enabled and verified API tools visible to the current tenant/user."""

    if not runtime_capability_enabled("api_tool"):
        return []

    records = await _visible_records(db, tenant_id=_uuid(tenant_id), user_id=_uuid(user_id))
    tools: list[dict[str, Any]] = []
    for record in records:
        try:
            tools.append(api_tool_definition(APIToolRuntimePolicy.from_model(record)))
        except APIToolPolicyError:
            continue
    return tools


async def execute_api_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> str:
    """Execute one active API tool from agent/router context."""

    context = context or {}
    tenant_id = context.get("tenant_id")
    user_id = context.get("user_id")
    if tenant_id is None or user_id is None:
        raise ValueError("API tool execution requires tenant_id and user_id")
    if not runtime_capability_enabled("api_tool"):
        raise ValueError("API tool runtime is disabled")

    db = context.get("db")
    if db is not None:
        result = await _execute_api_tool_with_db(tool_name, args, context=context, db=db)
        return json.dumps(result, ensure_ascii=False)

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as session:
        result = await _execute_api_tool_with_db(tool_name, args, context=context, db=session)
    return json.dumps(result, ensure_ascii=False)


async def _execute_api_tool_with_db(
    tool_name: str,
    args: dict[str, Any],
    *,
    context: Mapping[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    tenant_id = _uuid(context["tenant_id"])
    user_id = _uuid(context["user_id"])
    await assert_user_tool_manifest_current(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        expected_version=context.get("acquired_tool_manifest_version"),
    )
    record = await _record_for_tool_name(db, tool_name, tenant_id=tenant_id, user_id=user_id)
    if record is None:
        raise ValueError(f"API tool not found: {tool_name}")

    policy = APIToolRuntimePolicy.from_model(record)
    try:
        target_decision = TargetPolicyDecision(
            allowed=True,
            confirmation_required=policy.requires_confirmation,
            code="CONFIRMATION_REQUIRED",
            message="API tool requires runtime confirmation",
        )
        permission_request = await _runtime_permission_request_for_config(
            db,
            record,
            policy=policy,
            tool_context={
                "tool_name": tool_name,
                "method": policy.method.upper(),
                "base_url": policy.base_url,
                "path_template": policy.path_template,
            },
            confirmation_context=context.get("confirmation_context"),
        )
        decision = await evaluate_runtime_permission(db, permission_request, target_policy=target_decision)
        if decision.confirmation_required:
            confirmation_context = decision.context or build_runtime_confirmation_context(permission_request)
            raise APIToolConfirmationRequired(
                tool_name=tool_name,
                args=_sanitize_confirmation_args(args),
                risk=str(confirmation_context.get("risk_level") or policy.risk_level),
                confirmation_context=confirmation_context,
                code=decision.code,
                message=decision.message,
            )
        elif not decision.allowed:
            raise APIToolRuntimeError(decision.code, decision.message)

        async def credential_resolver(credential_connection_id: uuid.UUID) -> str:
            await _validate_credential_generation(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                credential_connection_id=credential_connection_id,
                expected_generation=policy.credential_generation,
            )
            return await resolve_credential_secret(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                credential_connection_id=credential_connection_id,
                target_type="api_tool",
                target_ref=_credential_target_ref(record, policy=policy),
            )

        client = APIToolRuntimeClient(policy, credential_resolver=credential_resolver)
        return await client.execute(args, context=context)
    except APIToolRuntimeError as exc:
        return exc.to_contract(policy.error_contract)


async def _runtime_permission_request_for_config(
    db: AsyncSession,
    record: APIToolConfiguration,
    *,
    policy: APIToolRuntimePolicy,
    tool_context: Mapping[str, Any],
    confirmation_context: Mapping[str, Any] | None,
) -> RuntimePermissionRequest:
    if record.activation_target_id is None:
        raise APIToolRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "API tool execution requires activation target permission evidence",
        )
    target = (
        await db.execute(
            select(ActivationTarget).where(
                ActivationTarget.id == record.activation_target_id,
                ActivationTarget.tenant_id == record.tenant_id,
                ActivationTarget.user_id == record.user_id,
                ActivationTarget.target_type == "api_tool",
            )
        )
    ).scalar_one_or_none()
    if target is None or target.activation_status != "active":
        raise APIToolRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "API tool execution requires an active activation target",
        )
    resource_ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, Mapping) else {}
    if resource_ref.get("hidden") is True or resource_ref.get("exposed_to_runtime") is False:
        raise APIToolRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "API tool execution requires a visible activation target",
        )
    proposal = (
        await db.execute(
            select(AcquisitionProposal).where(
                AcquisitionProposal.id == target.proposal_id,
                AcquisitionProposal.tenant_id == record.tenant_id,
                AcquisitionProposal.user_id == record.user_id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise APIToolRuntimeError("PERMISSION_EVIDENCE_REQUIRED", "API tool execution requires proposal evidence")
    approved_hash = approved_snapshot_hash(proposal)
    current_hash = proposal.activation_snapshot_hash
    if not approved_hash or not current_hash:
        raise APIToolRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "API tool execution requires verified and approved activation snapshot evidence",
        )
    bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
    default_action_category = "external_write" if policy.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else "read"
    action_category = str(
        policy.idempotency_policy.get("action_category")
        or policy.idempotency_policy.get("side_effect_category")
        or bundle.get("action_category")
        or bundle.get("side_effect_category")
        or default_action_category
    )
    return RuntimePermissionRequest(
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        proposal_id=proposal.id,
        target_id=target.id,
        target_type=target.target_type,
        permission_bundle=bundle,
        approved_snapshot_hash=approved_hash,
        current_snapshot_hash=current_hash,
        permission_scope=bundle.get("permission_scope") if isinstance(bundle.get("permission_scope"), Mapping) else None,
        risk_level=policy.risk_level,
        action_category=action_category,
        tool_context=tool_context,
        confirmation_context=confirmation_context,
    )


def _sanitize_confirmation_args(args: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted_keys = {"authorization", "api_key", "password", "secret", "token"}

    def sanitize(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): "[REDACTED]" if str(key).lower() in redacted_keys else sanitize(item)
                for key, item in value.items()
                if not str(key).startswith("__")
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    sanitized = sanitize(args or {})
    return sanitized if isinstance(sanitized, dict) else {}


def _credential_target_ref(record: APIToolConfiguration, *, policy: APIToolRuntimePolicy) -> dict[str, str]:
    target_id = record.activation_target_id
    return {
        "id": str(policy.id),
        "configuration_id": str(policy.id),
        "target_id": str(target_id) if target_id is not None else "",
        "activation_target_id": str(target_id) if target_id is not None else "",
        "ref": policy.tool_name,
        "manifest_ref": policy.tool_name,
        "tool_name": policy.tool_name,
        "name": policy.name,
        "target_name": policy.name,
    }


async def _record_for_tool_name(
    db: AsyncSession,
    tool_name: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> APIToolConfiguration | None:
    for record in await _visible_records(db, tenant_id=tenant_id, user_id=user_id):
        if record.tool_name == tool_name:
            return record
    return None


async def _visible_records(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[APIToolConfiguration]:
    records = list(
        (
            await db.execute(
                select(APIToolConfiguration)
                .where(
                    APIToolConfiguration.tenant_id == tenant_id,
                    APIToolConfiguration.user_id == user_id,
                    APIToolConfiguration.enabled.is_(True),
                    APIToolConfiguration.last_verified_at.is_not(None),
                )
                .order_by(APIToolConfiguration.created_at.asc())
            )
        ).scalars()
    )
    visible: list[APIToolConfiguration] = []
    for record in records:
        if record.activation_target_id is None:
            continue
        target = (
            await db.execute(
                select(ActivationTarget).where(
                    ActivationTarget.id == record.activation_target_id,
                    ActivationTarget.tenant_id == tenant_id,
                    ActivationTarget.user_id == user_id,
                    ActivationTarget.target_type == "api_tool",
                    ActivationTarget.activation_status == "active",
                )
            )
        ).scalar_one_or_none()
        resource_ref = target.activated_resource_ref if target and isinstance(target.activated_resource_ref, Mapping) else {}
        if target is None or resource_ref.get("hidden") is True or resource_ref.get("exposed_to_runtime") is False:
            continue
        visible.append(record)
    return visible


async def _validate_credential_generation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    credential_connection_id: uuid.UUID,
    expected_generation: int | None,
) -> None:
    if expected_generation is None:
        return
    credential = (
        await db.execute(
            select(CredentialConnection).where(
                CredentialConnection.id == credential_connection_id,
                CredentialConnection.tenant_id == tenant_id,
                CredentialConnection.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if credential is None or credential.secret_generation != expected_generation:
        raise APIToolRuntimeError("CREDENTIAL_GENERATION_MISMATCH", "API tool credential generation is stale")


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
