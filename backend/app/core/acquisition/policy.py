"""Final permission gate for acquired runtime targets."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import increment_acquisition_metric
from app.core.security.egress_policy import EgressPolicy, validate_egress_request
from app.models.acquisition import StandingPermission


STANDING_PERMISSION_DURATIONS = frozenset({"until_revoked", "expires_at"})
CONFIRMATION_REQUIRED_ACTIONS = frozenset(
    {
        "send",
        "message_send",
        "submit",
        "form_submit",
        "booking",
        "payment",
        "order",
        "delete",
        "deletion",
        "overwrite",
        "production_config",
        "production_deploy",
        "non_idempotent_side_effect",
        "browser_external_write",
        "external_write",
    }
)
_ACTION_CATEGORY_RISK_ORDER = {
    "read": 0,
    "safe": 0,
    "low": 1,
    "medium": 2,
    "send": 3,
    "message_send": 3,
    "submit": 3,
    "form_submit": 3,
    "booking": 3,
    "browser_external_write": 3,
    "external_write": 3,
    "non_idempotent_side_effect": 3,
    "overwrite": 4,
    "production_config": 4,
    "production_deploy": 4,
    "order": 5,
    "delete": 5,
    "deletion": 5,
    "payment": 5,
}
_ACTION_CATEGORY_ALIASES = {
    "sends": "message_send",
    "send_message": "message_send",
    "message_send": "message_send",
    "submits": "form_submit",
    "submit_form": "form_submit",
    "form_submit": "form_submit",
    "bookings": "booking",
    "booking": "booking",
    "payments": "payment",
    "payment": "payment",
    "ordering": "order",
    "order": "order",
    "deleting": "delete",
    "delete": "delete",
    "deletion": "delete",
    "overwriting": "overwrite",
    "overwrite": "overwrite",
    "deployment": "production_deploy",
    "deploy": "production_deploy",
    "production_deployment": "production_deploy",
    "production_deploy": "production_deploy",
    "browser_external_write": "browser_external_write",
    "browser_external_writes": "browser_external_write",
    "non_idempotent": "non_idempotent_side_effect",
    "non_idempotent_side_effect": "non_idempotent_side_effect",
    "side_effect": "non_idempotent_side_effect",
}
_BOUNDARY_SNAPSHOT_KEY = "_standing_permission_boundary"
_BOUNDARY_BUNDLE_FIELDS = (
    "credential_scope",
    "credential_connection_refs",
    "data_scope",
    "network_scope",
    "egress_policy",
    "write_scope",
    "execution_scope",
)
_TOOL_CONFIG_FIELDS = (
    "tool_config",
    "tool_configuration",
    "runtime_config",
    "execution_config",
    "mcp_server_config",
    "api_tool_config",
)
_HOST_PATH_FIELDS = (
    "host_path",
    "host_paths",
    "allowed_host_paths",
    "mount_paths",
    "filesystem_paths",
)
RISK_ORDER = {"safe": 0, "risky": 1, "high_risk": 2, "blocked": 3}
_REQUIRED_BUNDLE_FIELDS = frozenset(
    {
        "target_type",
        "permission_scope",
        "risk_level",
        "confirmation_policy",
        "credential_scope",
        "data_scope",
        "network_scope",
        "egress_policy",
        "write_scope",
        "execution_scope",
        "duration",
        "revocation_plan",
    }
)


@dataclass(frozen=True)
class PermissionDecision:
    """Structured policy result; callers decide how to surface it."""

    allowed: bool
    confirmation_required: bool
    code: str
    message: str
    standing_permission_id: uuid.UUID | None = None
    reasons: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimePermissionRequest:
    """Runtime evidence required to evaluate standing permission boundaries."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    proposal_id: uuid.UUID
    target_id: uuid.UUID
    target_type: str
    permission_bundle: Mapping[str, Any]
    approved_snapshot_hash: str
    current_snapshot_hash: str
    permission_scope: Mapping[str, Any] | None = None
    risk_level: str | None = None
    action_category: str = "read"
    tool_context: Mapping[str, Any] = field(default_factory=dict)
    confirmation_context: Mapping[str, Any] | None = None
    egress_url: str | None = None
    resolved_ips: Sequence[str] | None = None


@dataclass(frozen=True)
class TargetPolicyDecision:
    """Runtime-owner policy result that can only narrow this owner."""

    allowed: bool
    confirmation_required: bool = False
    code: str = "TARGET_POLICY_ALLOWED"
    message: str = "Target policy allowed"


async def evaluate_runtime_permission(
    db: AsyncSession,
    request: RuntimePermissionRequest,
    *,
    target_policy: TargetPolicyDecision | None = None,
    now: datetime | None = None,
) -> PermissionDecision:
    """Evaluate final acquisition permission for one runtime attempt."""

    base_decision = await _evaluate_acquisition_permission(db, request, now=now or _now())
    decision = apply_target_policy_narrowing(base_decision, target_policy)
    if not decision.allowed and not decision.confirmation_required:
        increment_acquisition_metric("acquisition_policy_blocks")
    return decision


def validate_permission_bundle(
    bundle: Mapping[str, Any] | None,
    *,
    target_type: str | None = None,
    now: datetime | None = None,
) -> PermissionDecision:
    """Validate permission bundle shape and explicit duration semantics."""

    if not isinstance(bundle, Mapping) or not bundle:
        return _deny("PERMISSION_BUNDLE_REQUIRED", "ActivationTarget requires its own permission bundle")

    missing = sorted(field for field in _REQUIRED_BUNDLE_FIELDS if field not in bundle)
    if missing:
        return _deny(
            "PERMISSION_BUNDLE_INCOMPLETE",
            "Permission bundle is missing required fields",
            reasons=tuple(missing),
        )

    if target_type is not None and str(bundle.get("target_type")) != target_type:
        return _deny(
            "PERMISSION_TARGET_MISMATCH",
            "Permission bundle target_type must match the activation target",
        )

    duration = bundle.get("duration")
    if duration not in {"one_run", "until_revoked", "expires_at", "per_worker_run_confirmation"}:
        return _deny("INVALID_PERMISSION_DURATION", "Permission duration must be explicit and bounded")
    if duration == "expires_at":
        expires_at = normalize_permission_expires_at(bundle)
        if expires_at is None:
            return _deny("PERMISSION_EXPIRY_REQUIRED", "expires_at is required when duration is expires_at")
        if expires_at <= (now or _now()):
            return _deny("PERMISSION_BUNDLE_EXPIRED", "Permission bundle expiry is already in the past")

    if not isinstance(bundle.get("permission_scope"), Mapping):
        return _deny("INVALID_PERMISSION_SCOPE", "permission_scope must be an object")
    if not isinstance(bundle.get("egress_policy"), Mapping):
        return _deny("INVALID_EGRESS_POLICY", "egress_policy must be an object")
    if not isinstance(bundle.get("revocation_plan"), Mapping):
        return _deny("INVALID_REVOCATION_PLAN", "revocation_plan must be an object")

    return PermissionDecision(True, False, "PERMISSION_BUNDLE_VALID", "Permission bundle is valid")


def normalize_permission_expires_at(bundle: Mapping[str, Any]) -> datetime | None:
    """Return the normalized permission expiry for persistence and policy checks."""

    return _coerce_datetime(bundle.get("expires_at"))


def require_runtime_confirmation(request: RuntimePermissionRequest) -> PermissionDecision:
    """Validate that runtime confirmation is specific to this policy request."""

    expected = build_runtime_confirmation_context(request)
    provided = dict(request.confirmation_context or {})
    missing_or_mismatched = tuple(
        key for key, expected_value in expected.items() if provided.get(key) != expected_value
    )
    if missing_or_mismatched:
        return _confirm(
            "RUNTIME_CONFIRMATION_REQUIRED",
            "Runtime confirmation must match proposal, target, snapshot, boundary, risk, and tool context",
            reasons=missing_or_mismatched,
            context=expected,
        )
    if provided.get("confirmed") is not True:
        return _confirm(
            "RUNTIME_CONFIRMATION_REQUIRED",
            "Runtime confirmation context must include an explicit confirmation",
            reasons=("confirmed",),
            context=expected,
        )
    return PermissionDecision(True, False, "RUNTIME_CONFIRMATION_VALID", "Runtime confirmation context is valid")


def build_runtime_confirmation_context(request: RuntimePermissionRequest) -> dict[str, Any]:
    """Build the exact context a runtime confirmation must prove."""

    permission_scope = request.permission_scope or _bundle_scope(request.permission_bundle)
    risk_level = request.risk_level or str(request.permission_bundle.get("risk_level") or "")
    return {
        "proposal_id": str(request.proposal_id),
        "target_id": str(request.target_id),
        "target_type": request.target_type,
        "approved_snapshot_hash": request.approved_snapshot_hash,
        "current_snapshot_hash": request.current_snapshot_hash,
        "permission_scope_hash": _stable_hashable(permission_scope),
        "risk_level": risk_level,
        "tool_context_hash": _stable_hashable(request.tool_context),
        "action_category": effective_action_category(request),
    }


def apply_target_policy_narrowing(
    acquisition_decision: PermissionDecision,
    target_policy: TargetPolicyDecision | None,
) -> PermissionDecision:
    """Apply target policy without letting it widen acquisition decisions."""

    if target_policy is None:
        return acquisition_decision
    if not acquisition_decision.allowed or acquisition_decision.confirmation_required:
        return acquisition_decision
    if target_policy.confirmation_required:
        return _confirm(target_policy.code, target_policy.message)
    if not target_policy.allowed:
        return _deny(target_policy.code, target_policy.message)
    return acquisition_decision


async def _evaluate_acquisition_permission(
    db: AsyncSession,
    request: RuntimePermissionRequest,
    *,
    now: datetime,
) -> PermissionDecision:
    bundle_decision = validate_permission_bundle(request.permission_bundle, target_type=request.target_type, now=now)
    if not bundle_decision.allowed:
        return bundle_decision

    if request.egress_url:
        egress_decision = _evaluate_egress(request)
        if not egress_decision.allowed:
            return egress_decision

    permission = await _lookup_standing_permission(db, request)
    if permission is None:
        return _confirm(
            "STANDING_PERMISSION_REQUIRED",
            "Runtime execution is outside standing permission and requires confirmation",
            context=build_runtime_confirmation_context(request),
        )

    permission_decision = _validate_standing_permission(permission, request, now=now)
    if not permission_decision.allowed:
        return permission_decision

    action_category = effective_action_category(request)
    if (
        _is_unknown_action_category(action_category)
        or action_category in CONFIRMATION_REQUIRED_ACTIONS
        or permission.duration == "per_worker_run_confirmation"
    ):
        confirmation_decision = require_runtime_confirmation(request)
        if not confirmation_decision.allowed:
            return confirmation_decision

    return PermissionDecision(
        True,
        False,
        "ALLOWED",
        "Runtime execution is within standing permission and acquisition policy",
        standing_permission_id=permission.id,
    )


async def _lookup_standing_permission(
    db: AsyncSession,
    request: RuntimePermissionRequest,
) -> StandingPermission | None:
    return (
        await db.execute(
            select(StandingPermission)
            .where(
                StandingPermission.tenant_id == request.tenant_id,
                StandingPermission.user_id == request.user_id,
                StandingPermission.proposal_id == request.proposal_id,
                StandingPermission.target_id == request.target_id,
                StandingPermission.target_type == request.target_type,
            )
            .order_by(StandingPermission.created_at.desc())
        )
    ).scalars().first()


def _validate_standing_permission(
    permission: StandingPermission,
    request: RuntimePermissionRequest,
    *,
    now: datetime,
) -> PermissionDecision:
    if permission.status == "revoked" or permission.revoked_at is not None:
        return _deny("STANDING_PERMISSION_REVOKED", "Standing permission has been revoked")
    if permission.status != "active":
        return _deny("STANDING_PERMISSION_INACTIVE", "Standing permission is not active")
    if permission.duration == "expires_at" and permission.expires_at is not None and permission.expires_at <= now:
        return _deny("STANDING_PERMISSION_EXPIRED", "Standing permission has expired")
    if permission.duration not in STANDING_PERMISSION_DURATIONS and permission.duration != "per_worker_run_confirmation":
        return _confirm(
            "RUNTIME_CONFIRMATION_REQUIRED",
            "Standing permission duration does not allow automatic runtime execution",
            context=build_runtime_confirmation_context(request),
        )
    if permission.approved_snapshot_hash != request.approved_snapshot_hash:
        return _deny("REAPPROVAL_REQUIRED", "Approved snapshot hash no longer matches standing permission")
    if request.current_snapshot_hash != permission.approved_snapshot_hash:
        return _deny("REAPPROVAL_REQUIRED", "Activation snapshot changed after approval")

    approved_scope = _legacy_permission_scope(permission.permission_scope)
    current_scope = dict(request.permission_scope or _bundle_scope(request.permission_bundle))
    if not _scope_is_subset(current_scope, approved_scope):
        return _deny("REAPPROVAL_REQUIRED", "Permission boundary expanded after activation")

    bundle_scope = _bundle_scope(request.permission_bundle)
    if not _scope_is_subset(bundle_scope, approved_scope):
        return _deny("REAPPROVAL_REQUIRED", "Permission bundle boundary expanded after activation")

    approved_boundary = _standing_permission_boundary(permission.permission_scope)
    if approved_boundary is not None:
        runtime_boundary = build_permission_boundary_snapshot(
            request.permission_bundle,
            permission_scope=current_scope,
        )
        if not _scope_is_subset(runtime_boundary, approved_boundary):
            return _deny("REAPPROVAL_REQUIRED", "Standing permission boundary expanded after activation")

    request_risk = request.risk_level or str(request.permission_bundle.get("risk_level") or permission.risk_level)
    if RISK_ORDER.get(request_risk, 999) > RISK_ORDER.get(permission.risk_level, 999):
        return _deny("REAPPROVAL_REQUIRED", "Runtime risk exceeds standing permission risk")

    return PermissionDecision(
        True,
        False,
        "STANDING_PERMISSION_VALID",
        "Standing permission is active and within boundary",
        standing_permission_id=permission.id,
    )


def _evaluate_egress(request: RuntimePermissionRequest) -> PermissionDecision:
    policy_payload = dict(request.permission_bundle.get("egress_policy") or {})
    decision = validate_egress_request(
        EgressPolicy(
            allow_hosts=tuple(policy_payload.get("allow_hosts") or ()),
            redirect_policy=dict(policy_payload.get("redirect_policy") or {"follow": False}),
            deny_private_networks=bool(policy_payload.get("deny_private_networks", True)),
            max_response_bytes=policy_payload.get("max_response_bytes"),
        ),
        request.egress_url or "",
        network_scope=str(request.permission_bundle.get("network_scope") or "none"),
        target_type=request.target_type,
        activated_target=True,
        resolved_ips=request.resolved_ips,
    )
    if decision.allowed:
        return PermissionDecision(True, False, "EGRESS_ALLOWED", "Egress policy allows request")
    return _deny(decision.code, decision.message)


def _bundle_scope(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = bundle.get("permission_scope")
    return dict(value) if isinstance(value, Mapping) else {}


def build_standing_permission_scope(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Store legacy scope plus the bounded fields that define standing approval."""

    scope = _bundle_scope(bundle)
    return {
        **scope,
        _BOUNDARY_SNAPSHOT_KEY: build_permission_boundary_snapshot(bundle, permission_scope=scope),
    }


def build_permission_boundary_snapshot(
    bundle: Mapping[str, Any],
    *,
    permission_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical bounded permission boundary stored inside StandingPermission.permission_scope."""

    snapshot: dict[str, Any] = {
        "permission_scope": _canonical_json(permission_scope if permission_scope is not None else _bundle_scope(bundle)),
    }
    for field_name in _BOUNDARY_BUNDLE_FIELDS:
        snapshot[field_name] = _canonical_json(bundle.get(field_name))
    snapshot["credential_connection_refs"] = sorted(str(ref) for ref in _as_sequence(bundle.get("credential_connection_refs")))
    snapshot["egress_policy"] = _canonical_json(bundle.get("egress_policy") or {})
    snapshot["tool_config"] = _canonical_json(
        {field_name: bundle.get(field_name) for field_name in _TOOL_CONFIG_FIELDS if field_name in bundle}
    )
    snapshot["host_paths"] = sorted(
        str(path)
        for field_name in _HOST_PATH_FIELDS
        for path in _as_sequence(bundle.get(field_name) or snapshot["permission_scope"].get(field_name))
    )
    raw_action = bundle.get("action_category") or bundle.get("side_effect_category") or "read"
    snapshot["action_category"] = _normalize_action_category(str(raw_action))
    return snapshot


def effective_action_category(request: RuntimePermissionRequest) -> str:
    """Return the highest-risk action category declared by the request or bundle."""

    candidates = (
        request.action_category,
        request.permission_bundle.get("action_category"),
        request.permission_bundle.get("side_effect_category"),
    )
    normalized = tuple(
        _normalize_action_category(str(candidate))
        for candidate in candidates
        if candidate not in (None, "")
    )
    if not normalized:
        return "read"
    return max(normalized, key=_action_category_risk_score)


def _standing_permission_boundary(permission_scope: Mapping[str, Any]) -> dict[str, Any] | None:
    boundary = permission_scope.get(_BOUNDARY_SNAPSHOT_KEY)
    return dict(boundary) if isinstance(boundary, Mapping) else None


def _legacy_permission_scope(permission_scope: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in permission_scope.items() if key != _BOUNDARY_SNAPSHOT_KEY}


def _scope_is_subset(candidate: Mapping[str, Any], approved: Mapping[str, Any]) -> bool:
    for key, candidate_value in candidate.items():
        if key not in approved:
            if candidate_value in (None, "", [], {}, ()):
                continue
            return False
        if not _value_is_subset(candidate_value, approved[key]):
            return False
    return True


def _value_is_subset(candidate: Any, approved: Any) -> bool:
    if isinstance(candidate, Mapping):
        if not isinstance(approved, Mapping):
            return False
        return _scope_is_subset(candidate, approved)
    if isinstance(candidate, (list, tuple, set)):
        if not isinstance(approved, (list, tuple, set)):
            return False
        return {_stable_hashable(item) for item in candidate}.issubset(
            {_stable_hashable(item) for item in approved}
        )
    return candidate == approved


def _canonical_json(value: Any) -> Any:
    return json.loads(_stable_hashable(value))


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value in (None, "", [], {}, ()):
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return (value,)
    return tuple(value)


def _normalize_action_category(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _ACTION_CATEGORY_ALIASES.get(normalized, normalized)


def _action_category_risk_score(value: str) -> tuple[int, int]:
    normalized = _normalize_action_category(value)
    confirmation_rank = 3 if normalized in CONFIRMATION_REQUIRED_ACTIONS else 0
    return (confirmation_rank, _ACTION_CATEGORY_RISK_ORDER.get(normalized, 2))


def _is_unknown_action_category(value: str) -> bool:
    normalized = _normalize_action_category(value)
    return normalized not in _ACTION_CATEGORY_RISK_ORDER


def _stable_hashable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _deny(
    code: str,
    message: str,
    *,
    reasons: Sequence[str] = (),
    context: dict[str, Any] | None = None,
) -> PermissionDecision:
    return PermissionDecision(False, False, code, message, reasons=tuple(reasons), context=context or {})


def _confirm(
    code: str,
    message: str,
    *,
    reasons: Sequence[str] = (),
    context: dict[str, Any] | None = None,
) -> PermissionDecision:
    return PermissionDecision(False, True, code, message, reasons=tuple(reasons), context=context or {})
