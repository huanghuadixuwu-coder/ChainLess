"""Adapters from V3 acquisition targets to V2 Memory, Skill, and Worker owners."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import TargetActivationResult
from app.core.acquisition.rollback import RollbackHookResult
from app.core.capabilities.bounds import validate_bounded_json
from app.core.capabilities.service import activate_skill_from_acquisition, disable_skill_from_acquisition
from app.core.memory.persistent import create_memory, delete_memory_from_acquisition
from app.core.workers.service import activate_worker_from_acquisition, rollback_worker_from_acquisition
from app.models.acquisition import AcquisitionProposal, ActivationTarget


V2_TARGET_TYPES = {"worker", "skill", "memory"}
_RUNTIME_PERMISSION_KEYS = {
    "allowed_tools",
    "api_tool_config",
    "browser_session",
    "credential_connection_refs",
    "egress_policy",
    "execution_scope",
    "mcp_server_config",
    "permission_bundle",
    "runtime_permission",
    "tool_config",
    "workspace_mounts",
}
_SECRET_KEY_PARTS = ("api_key", "authorization", "bearer", "client_secret", "cookie", "password", "secret", "token")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(api[_-]?key|secret|token|password)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{10,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{12,}"),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _target_specs(proposal: AcquisitionProposal) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if isinstance(proposal.primary_target, dict):
        specs.append(proposal.primary_target)
    specs.extend(item for item in (proposal.secondary_targets or []) if isinstance(item, dict))
    return specs


def _payload(spec_or_target: dict[str, Any] | ActivationTarget) -> dict[str, Any]:
    if isinstance(spec_or_target, ActivationTarget):
        value = spec_or_target.target_payload
    else:
        value = spec_or_target.get("target_payload")
    return dict(value) if isinstance(value, dict) else {}


def _target_type(spec_or_target: dict[str, Any] | ActivationTarget) -> str:
    if isinstance(spec_or_target, ActivationTarget):
        return str(spec_or_target.target_type)
    return str(spec_or_target.get("target_type") or "")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        term = " ".join(item.strip().split())
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
    return cleaned


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _optional_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _uuid_optional(value: Any, *, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _uuid_required(value: Any, *, field: str) -> uuid.UUID:
    parsed = _uuid_optional(value, field=field)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _has_raw_secret(value: Any, *, key: str = "") -> bool:
    normalized_key = key.casefold()
    if any(part in normalized_key for part in _SECRET_KEY_PARTS):
        return True
    if isinstance(value, dict):
        return any(_has_raw_secret(item, key=str(child_key)) for child_key, item in value.items())
    if isinstance(value, list):
        return any(_has_raw_secret(item, key=key) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    return False


def _validation_error(target_type: str, code: str, message: str) -> dict[str, Any]:
    return {"target_type": target_type, "code": code, "message": message}


def _validate_worker_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    definition = _dict_value(payload.get("definition"))
    policy = _dict_value(payload.get("policy"))
    input_schema = _dict_value(definition.get("input_schema")) or _dict_value(policy.get("input_schema"))
    if not input_schema or input_schema.get("type", "object") != "object":
        errors.append(
            _validation_error(
                "worker",
                "WORKER_TARGET_INPUT_SCHEMA_REQUIRED",
                "Worker targets require an object input_schema before activation",
            )
        )
    allowed_tools = _string_list(policy.get("allowed_tools")) or _string_list(definition.get("allowed_tools"))
    if not allowed_tools:
        errors.append(
            _validation_error(
                "worker",
                "WORKER_TARGET_ALLOWED_TOOLS_REQUIRED",
                "Worker targets require an explicit allowed_tools list",
            )
        )
    return errors


def _skill_trigger_terms(payload: dict[str, Any]) -> list[str]:
    terms = _string_list(payload.get("trigger_terms"))
    if terms:
        return terms
    semantic_match = _dict_value(payload.get("semantic_match"))
    query = _first_text(
        semantic_match.get("query"),
        semantic_match.get("text"),
        semantic_match.get("intent"),
        default="",
    )
    return [query] if query else []


def _validate_skill_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    embedded = sorted(key for key in payload if key in _RUNTIME_PERMISSION_KEYS)
    if embedded:
        errors.append(
            _validation_error(
                "skill",
                "SKILL_TARGET_EMBEDDED_RUNTIME_PERMISSION",
                "Skill targets are passive methods and cannot embed runtime permission or tool configuration",
            )
        )
    if not _skill_trigger_terms(payload):
        errors.append(
            _validation_error(
                "skill",
                "SKILL_TARGET_TRIGGER_OR_SEMANTIC_MATCH_REQUIRED",
                "Skill targets require trigger_terms or semantic_match evidence",
            )
        )
    return errors


def _validate_memory_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    scope = str(payload.get("scope") or "private")
    if scope != "private":
        errors.append(
            _validation_error(
                "memory",
                "MEMORY_TARGET_PRIVATE_SCOPE_REQUIRED",
                "Memory targets must activate as private user memories",
            )
        )
    evidence = payload.get("source_evidence")
    if not isinstance(evidence, list) or not any(isinstance(item, dict) for item in evidence):
        errors.append(
            _validation_error(
                "memory",
                "MEMORY_TARGET_SOURCE_EVIDENCE_REQUIRED",
                "Memory targets require explicit source_evidence",
            )
        )
    content = _first_text(payload.get("content"), payload.get("memory_text"), default="")
    if not content:
        errors.append(
            _validation_error("memory", "MEMORY_TARGET_CONTENT_REQUIRED", "Memory targets require content")
        )
    if _has_raw_secret(payload):
        errors.append(
            _validation_error(
                "memory",
                "MEMORY_TARGET_RAW_SECRET_FORBIDDEN",
                "Memory targets cannot persist raw secrets; redact or reference credentials instead",
            )
        )
    return errors


def validate_v2_target_specs(proposal: AcquisitionProposal) -> list[dict[str, Any]]:
    """Return target validation errors for V2 acquisition targets."""

    errors: list[dict[str, Any]] = []
    for spec in _target_specs(proposal):
        errors.extend(validate_v2_activation_target_spec(spec))
    return errors


def validate_v2_activation_target_spec(spec_or_target: dict[str, Any] | ActivationTarget) -> list[dict[str, Any]]:
    """Validate one V2 target spec or materialized ActivationTarget."""

    target_type = _target_type(spec_or_target)
    if target_type == "worker":
        return _validate_worker_payload(_payload(spec_or_target))
    if target_type == "skill":
        return _validate_skill_payload(_payload(spec_or_target))
    if target_type == "memory":
        return _validate_memory_payload(_payload(spec_or_target))
    return []


def _failure_result(code: str, message: str, *, evidence: dict[str, Any] | None = None) -> TargetActivationResult:
    return TargetActivationResult(
        success=False,
        error_code=code,
        error_message=message,
        evidence=validate_bounded_json(_jsonable(evidence or {}), field="target_activation_evidence"),
    )


def _exception_result(exc: Exception) -> TargetActivationResult:
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        error = exc.detail.get("error") if isinstance(exc.detail.get("error"), dict) else {}
        code = str(error.get("code") or exc.__class__.__name__)
        message = str(error.get("message") or exc.detail or exc)
    else:
        code = exc.__class__.__name__
        message = str(exc)
    return _failure_result(code, message, evidence={"hook_exception": exc.__class__.__name__})


def _resource_metadata(
    *,
    proposal: AcquisitionProposal,
    target: ActivationTarget,
    approved_hash: str,
    source_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return validate_bounded_json(
        _jsonable(
            {
                "source": {
                    "source_type": "acquisition",
                    "proposal_id": str(proposal.id),
                    "target_id": str(target.id),
                    "target_type": target.target_type,
                    "approved_snapshot_hash": approved_hash,
                },
                "source_evidence": source_evidence or [],
            }
        ),
        field="metadata",
    )


class V2CapabilityActivationHooks:
    """Activate V2-owned Worker, Skill, and Memory targets."""

    async def activate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
        idempotency_key: str | None,
    ) -> TargetActivationResult:
        errors = validate_v2_activation_target_spec(target)
        if errors:
            return _failure_result(
                str(errors[0]["code"]),
                str(errors[0]["message"]),
                evidence={"validation_errors": errors},
            )
        try:
            async with db.begin_nested():
                if target.target_type == "worker":
                    return await self._activate_worker(db, proposal=proposal, target=target, approved_hash=approved_hash)
                if target.target_type == "skill":
                    return await self._activate_skill(db, proposal=proposal, target=target, approved_hash=approved_hash)
                if target.target_type == "memory":
                    return await self._activate_memory(db, proposal=proposal, target=target, approved_hash=approved_hash)
        except Exception as exc:
            return _exception_result(exc)
        return _failure_result("UNSUPPORTED_V2_TARGET_TYPE", "Unsupported V2 target type")

    async def _activate_worker(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
    ) -> TargetActivationResult:
        payload = _payload(target)
        worker_id = _uuid_optional(payload.get("worker_id"), field="worker_id")
        definition = _dict_value(payload.get("definition"))
        policy = _dict_value(payload.get("policy"))
        verification_evidence = {
            "source": "acquisition",
            "proposal_id": str(proposal.id),
            "target_id": str(target.id),
            "approved_snapshot_hash": approved_hash,
            "verification_plan": target.verification_plan or {},
        }
        activation_evidence = {
            "source": "acquisition",
            "proposal_id": str(proposal.id),
            "target_id": str(target.id),
            "approved_snapshot_hash": approved_hash,
            "permission_bundle": target.permission_bundle or {},
        }
        worker, version, restore_state = await activate_worker_from_acquisition(
            db,
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            worker_id=worker_id,
            name=_first_text(payload.get("name"), target.target_name, default="Acquired Worker"),
            description=_optional_text(payload.get("description")),
            trigger=_dict_value(payload.get("trigger")) or {"type": "semantic", "source": "acquisition"},
            policy=policy,
            definition=definition,
            verification_plan=_dict_value(payload.get("verification_plan")) or target.verification_plan or {},
            verification_evidence=verification_evidence,
            activation_evidence=activation_evidence,
        )
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": "worker",
                "worker_id": str(worker.id),
                "worker_version_id": str(version.id),
                "manifest_ref": f"worker:{worker.id}:{version.id}",
                "exposed_to_runtime": True,
                "rollback_restore": restore_state,
            },
            evidence={
                "hook": "v2_worker",
                "worker_status": worker.status,
                "version_status": version.status,
                "runtime_side_effects": True,
                "durable_side_effects": True,
            },
        )

    async def _activate_skill(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
    ) -> TargetActivationResult:
        payload = _payload(target)
        skill = await activate_skill_from_acquisition(
            db,
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            name=_first_text(payload.get("name"), target.target_name, default="Acquired Skill"),
            description=_optional_text(payload.get("description"), payload.get("body")),
            trigger_terms=_skill_trigger_terms(payload),
            metadata=_resource_metadata(proposal=proposal, target=target, approved_hash=approved_hash),
        )
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": "skill",
                "skill_id": str(skill.id),
                "exposed_to_runtime": True,
            },
            evidence={
                "hook": "v2_skill",
                "scope": skill.scope,
                "enabled": skill.enabled,
                "runtime_side_effects": True,
                "durable_side_effects": True,
            },
        )

    async def _activate_memory(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        approved_hash: str,
    ) -> TargetActivationResult:
        payload = _payload(target)
        source_evidence = [item for item in payload.get("source_evidence") or [] if isinstance(item, dict)]
        memory = await create_memory(
            db=db,
            tenant_id=str(target.tenant_id),
            user_id=str(target.user_id),
            memory_type=_first_text(payload.get("memory_type"), payload.get("type"), default="user"),
            name=_first_text(payload.get("name"), target.target_name, default="Acquired Memory"),
            content=_first_text(payload.get("content"), payload.get("memory_text"), default=""),
            tags=_string_list(payload.get("tags")),
            description=_optional_text(payload.get("description")),
            metadata=_resource_metadata(
                proposal=proposal,
                target=target,
                approved_hash=approved_hash,
                source_evidence=source_evidence,
            ),
            commit=False,
            write_source=False,
            compute_inline_embedding=False,
        )
        return TargetActivationResult(
            success=True,
            activated_resource_ref={
                "kind": "memory",
                "memory_id": str(memory.id),
                "exposed_to_runtime": True,
            },
            evidence={
                "hook": "v2_memory",
                "scope": "private",
                "runtime_side_effects": True,
                "durable_side_effects": True,
            },
        )


class V2CapabilityRollbackHooks:
    """Rollback compensation for V2-owned acquisition targets."""

    async def terminate_session(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        if target.activation_status == "rolled_back":
            return RollbackHookResult(
                success=True,
                evidence={"hook": "v2_targets", "already_rolled_back": True, "session_terminated": False},
            )
        return RollbackHookResult(success=True, evidence={"hook": "v2_targets", "session_terminated": True})

    async def compensate_target(
        self,
        db: AsyncSession,
        *,
        proposal: AcquisitionProposal,
        target: ActivationTarget,
        resource_ref: dict[str, Any],
        idempotency_key: str | None,
    ) -> RollbackHookResult:
        if target.activation_status == "rolled_back":
            return RollbackHookResult(
                success=True,
                evidence={"hook": "v2_targets", "already_rolled_back": True, "compensated": False},
            )
        if not resource_ref and target.activation_status != "active":
            return RollbackHookResult(success=True, evidence={"hook": "v2_targets", "compensated": False})
        try:
            async with db.begin_nested():
                if target.target_type == "worker":
                    worker = await rollback_worker_from_acquisition(
                        db,
                        tenant_id=target.tenant_id,
                        user_id=target.user_id,
                        worker_id=_uuid_required(resource_ref.get("worker_id"), field="worker_id"),
                        version_id=_uuid_required(resource_ref.get("worker_version_id"), field="worker_version_id"),
                        reason="Acquisition rollback",
                        restore_state=_dict_value(resource_ref.get("rollback_restore")),
                    )
                    return RollbackHookResult(
                        success=True,
                        evidence={"hook": "v2_worker", "worker_id": str(worker.id), "status": worker.status},
                    )
                if target.target_type == "skill":
                    skill = await disable_skill_from_acquisition(
                        db,
                        tenant_id=target.tenant_id,
                        user_id=target.user_id,
                        skill_id=_uuid_required(resource_ref.get("skill_id"), field="skill_id"),
                    )
                    return RollbackHookResult(
                        success=True,
                        evidence={"hook": "v2_skill", "skill_id": str(skill.id), "enabled": skill.enabled},
                    )
                if target.target_type == "memory":
                    await delete_memory_from_acquisition(
                        db,
                        tenant_id=target.tenant_id,
                        user_id=target.user_id,
                        memory_id=_uuid_required(resource_ref.get("memory_id"), field="memory_id"),
                    )
                    return RollbackHookResult(
                        success=True,
                        evidence={"hook": "v2_memory", "deleted": True},
                    )
        except Exception as exc:
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
                error = exc.detail.get("error") if isinstance(exc.detail.get("error"), dict) else {}
                code = str(error.get("code") or exc.__class__.__name__)
                message = str(error.get("message") or exc.detail or exc)
            else:
                code = exc.__class__.__name__
                message = str(exc)
            return RollbackHookResult(
                success=False,
                error_code=code,
                error_message=message,
                evidence={"hook_exception": exc.__class__.__name__},
            )
        return RollbackHookResult(success=True, evidence={"hook": "v2_targets", "compensated": False})
