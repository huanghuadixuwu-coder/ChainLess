"""Minimal Worker execution policy facade.

W4 keeps this intentionally small: it prevents unguarded executable Workers
while leaving richer hook behavior to later workstreams.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.models.worker import Worker, WorkerVersion

PolicyAction = Literal["allow", "confirm", "block"]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    detail: dict[str, Any] | None = None


class WorkerPolicyError(RuntimeError):
    """Raised when Worker policy blocks a runtime action."""

    def __init__(
        self,
        reason: str,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.detail = detail or {}


def allow(reason: str = "allowed", detail: dict[str, Any] | None = None) -> PolicyDecision:
    return PolicyDecision("allow", reason, detail or {})


def confirm(reason: str = "confirmation_required", detail: dict[str, Any] | None = None) -> PolicyDecision:
    return PolicyDecision("confirm", reason, detail or {})


def block(reason: str, detail: dict[str, Any] | None = None) -> PolicyDecision:
    return PolicyDecision("block", reason, detail or {})


def require_worker_activated(worker: Worker, version: WorkerVersion | None) -> PolicyDecision:
    if worker.soft_deleted_at is not None or worker.status == "soft_deleted":
        return block("worker_soft_deleted")
    if not worker.enabled or worker.status != "active":
        return block("worker_not_active")
    if version is None or worker.active_version_id != version.id or version.status != "active":
        return block("worker_version_not_active")
    if not worker.activation_evidence or worker.activation_confirmed_at is None:
        return block("worker_activation_not_confirmed")
    return allow()


def validate_input_schema(input_payload: dict[str, Any], schema: dict[str, Any] | None) -> PolicyDecision:
    schema = schema or {}
    if not schema:
        return allow()
    if schema.get("type") not in (None, "object"):
        return block("unsupported_input_schema", {"schema_type": schema.get("type")})
    required = [item for item in schema.get("required", []) if isinstance(item, str)]
    missing = [
        field
        for field in required
        if field not in input_payload or input_payload.get(field) in (None, "")
    ]
    if missing:
        return block("missing_required_input", {"missing": missing})
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for field, rules in properties.items():
        if field not in input_payload or not isinstance(rules, dict):
            continue
        expected_type = rules.get("type")
        if expected_type and not _json_type_matches(input_payload[field], expected_type):
            return block("invalid_input_type", {"field": field, "expected": expected_type})
    return allow()


def input_schema_for(worker: Worker, version: WorkerVersion | None) -> dict[str, Any]:
    definition = version.definition if version is not None and isinstance(version.definition, dict) else {}
    policy = worker.policy if isinstance(worker.policy, dict) else {}
    return _dict_value(definition.get("input_schema")) or _dict_value(policy.get("input_schema"))


def allowed_tools_for(worker: Worker, version: WorkerVersion | None = None) -> set[str]:
    policy = worker.policy if isinstance(worker.policy, dict) else {}
    definition = version.definition if version is not None and isinstance(version.definition, dict) else {}
    values = policy.get("allowed_tools")
    if values is None:
        values = definition.get("allowed_tools")
    return {item for item in values or [] if isinstance(item, str) and item}


def risk_for(worker: Worker, version: WorkerVersion | None = None) -> str:
    policy = worker.policy if isinstance(worker.policy, dict) else {}
    definition = version.definition if version is not None and isinstance(version.definition, dict) else {}
    value = policy.get("risk") or definition.get("risk") or "low"
    return str(value).casefold()


def requires_worker_confirmation(worker: Worker, version: WorkerVersion | None = None) -> bool:
    policy = worker.policy if isinstance(worker.policy, dict) else {}
    definition = version.definition if version is not None and isinstance(version.definition, dict) else {}
    return (
        risk_for(worker, version) in {"high", "destructive"}
        or _truthy(policy.get("requires_confirmation"))
        or _truthy(definition.get("requires_confirmation"))
        or _truthy(policy.get("external_delivery"))
        or _truthy(definition.get("external_delivery"))
        or _truthy(policy.get("requires_external_confirmation"))
        or _truthy(definition.get("requires_external_confirmation"))
    )


def evaluate_worker_policy(
    worker: Worker,
    version: WorkerVersion | None,
    *,
    input_payload: dict[str, Any],
) -> PolicyDecision:
    activation = require_worker_activated(worker, version)
    if activation.action == "block":
        return activation
    schema = validate_input_schema(input_payload, input_schema_for(worker, version))
    if schema.action == "block":
        return schema
    if requires_worker_confirmation(worker, version):
        return confirm("worker_risk_requires_confirmation")
    return allow()


def evaluate_worker_tool_policy(
    tool_name: str,
    worker_context: dict[str, Any] | None,
    *,
    risk: str | None = None,
    confirmed: bool = False,
    confirmation_context: dict[str, Any] | None = None,
) -> PolicyDecision:
    if not worker_context:
        return allow()
    allowed_present = "allowed_tool_names" in worker_context or "allowed_tools" in worker_context
    allowed = _allowed_tool_names(worker_context)
    if allowed_present and tool_name not in allowed:
        return block(
            "worker_tool_not_allowed",
            {
                "tool_name": tool_name,
                "worker_run_id": worker_context.get("worker_run_id"),
                "worker_id": worker_context.get("worker_id"),
            },
        )
    effective_confirmation = confirmation_context or _dict_value(
        worker_context.get("confirmation_context")
    )
    if confirmed and effective_confirmation:
        expected_tool = effective_confirmation.get("tool_name")
        if expected_tool and expected_tool != tool_name:
            return block(
                "worker_confirmation_tool_mismatch",
                {"tool_name": tool_name, "expected_tool_name": expected_tool},
            )
    normalized_risk = _risk_value(risk)
    if (
        confirmed
        and normalized_risk in {"destructive", "external_delivery"}
        and not effective_confirmation
    ):
        return block(
            "worker_confirmation_context_missing",
            {
                "tool_name": tool_name,
                "risk": normalized_risk,
                "worker_run_id": worker_context.get("worker_run_id"),
                "worker_id": worker_context.get("worker_id"),
            },
        )
    if normalized_risk in {"destructive", "external_delivery"} and not confirmed:
        return confirm(
            "worker_tool_requires_confirmation",
            {
                "tool_name": tool_name,
                "risk": normalized_risk,
                "worker_run_id": worker_context.get("worker_run_id"),
                "worker_id": worker_context.get("worker_id"),
            },
        )
    return allow()


def enforce_worker_tool_policy(
    tool_name: str,
    worker_context: dict[str, Any] | None,
    *,
    risk: str | None = None,
    confirmed: bool = False,
    confirmation_context: dict[str, Any] | None = None,
) -> PolicyDecision:
    return evaluate_worker_tool_policy(
        tool_name,
        worker_context,
        risk=risk,
        confirmed=confirmed,
        confirmation_context=confirmation_context,
    )


def require_worker_tool_policy(
    tool_name: str,
    worker_context: dict[str, Any] | None,
    *,
    risk: str | None = None,
    confirmed: bool = False,
    confirmation_context: dict[str, Any] | None = None,
) -> None:
    decision = enforce_worker_tool_policy(
        tool_name,
        worker_context,
        risk=risk,
        confirmed=confirmed,
        confirmation_context=confirmation_context,
    )
    if decision.action == "block":
        raise WorkerPolicyError(
            decision.reason,
            f"Worker policy disallows tool: {tool_name}",
            decision.detail,
        )


def worker_context_for_confirmation(
    worker_context: dict[str, Any] | None,
    *,
    tool_name: str | None = None,
    risk: str | None = None,
) -> dict[str, Any] | None:
    if not worker_context:
        return None
    allowed = sorted(_allowed_tool_names(worker_context))
    context = {
        "worker_id": worker_context.get("worker_id"),
        "worker_version_id": worker_context.get("worker_version_id"),
        "worker_run_id": worker_context.get("worker_run_id"),
        "depth": worker_context.get("depth", 0),
        "max_depth": worker_context.get("max_depth"),
        "worker_stack": list(worker_context.get("worker_stack") or []),
        "allowed_tool_names": [item for item in allowed if isinstance(item, str)],
        "risk_decision": worker_context.get("risk_decision"),
    }
    if tool_name or risk:
        context["confirmation_context"] = {
            "tool_name": tool_name,
            "risk": _risk_value(risk),
            "requires_confirmation": True,
        }
    elif isinstance(worker_context.get("confirmation_context"), dict):
        context["confirmation_context"] = dict(worker_context["confirmation_context"])
    return context


def pack_confirmation_args(args: dict[str, Any], worker_context: dict[str, Any] | None) -> dict[str, Any]:
    context = worker_context_for_confirmation(worker_context)
    if not context:
        return args
    return {**args, "__worker_policy_context": context}


def unpack_confirmation_args(args: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    args = dict(args or {})
    context = args.pop("__worker_policy_context", None)
    return args, context if isinstance(context, dict) else None


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _allowed_tool_names(worker_context: dict[str, Any]) -> set[str]:
    values = worker_context.get("allowed_tool_names")
    if values is None:
        values = worker_context.get("allowed_tools")
    return {item for item in values or [] if isinstance(item, str) and item}


def _risk_value(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw).casefold()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.casefold() in {"1", "true", "yes", "on"}
    return bool(value)
