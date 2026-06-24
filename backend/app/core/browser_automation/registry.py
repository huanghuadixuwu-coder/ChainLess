"""Database-backed registry helpers for active browser automation tools."""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.activation import approved_snapshot_hash
from app.core.acquisition.policy import (
    RuntimePermissionRequest,
    TargetPolicyDecision,
    build_runtime_confirmation_context,
    evaluate_runtime_permission,
)
from app.models.acquisition import ActivationTarget, AcquisitionProposal, BrowserAutomationConfiguration

from .client import BrowserAutomationRuntimeClient, BrowserAutomationRuntimeError
from .policy import (
    BrowserAutomationPolicyError,
    BrowserAutomationRuntimePolicy,
    action_requires_confirmation,
    browser_tool_name,
    validate_browser_runtime_policy,
)


class BrowserAutomationConfirmationRequired(RuntimeError):
    """Trusted backend confirmation request for an acquired browser tool."""

    def __init__(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        original_args: Mapping[str, Any] | None = None,
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
        self.original_args = dict(original_args or args)
        self.code = code
        self.message = message


def browser_tool_definition(
    policy: BrowserAutomationRuntimePolicy,
    *,
    risk_level: str = "risky",
) -> dict[str, Any]:
    """Return an OpenAI function-tool definition without secrets or raw actions."""

    validate_browser_runtime_policy(policy)
    allowed_hosts = ", ".join(policy.allowed_hosts[:5])
    return {
        "type": "function",
        "risk": risk_level,
        "function": {
            "name": browser_tool_name(policy.name),
            "description": (
                f"Acquired browser automation: {policy.name}. "
                f"Runs approved actions in an isolated browser for: {allowed_hosts}."
            ),
            "parameters": {
                "type": "object",
                "required": ["actions"],
                "properties": {
                    "actions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "object", "additionalProperties": True},
                        "description": "Ordered browser actions to run in the isolated runtime.",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Short user-facing reason for this browser automation run.",
                    },
                },
                "additionalProperties": False,
            },
        },
    }


async def get_browser_tool_definitions(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    *,
    user_id: str | uuid.UUID,
) -> list[dict[str, Any]]:
    """List active verified browser automation tools for the current tenant/user."""

    records = await _active_records(db, tenant_id=_uuid(tenant_id), user_id=_uuid(user_id))
    tools: list[dict[str, Any]] = []
    for record, target in records:
        try:
            risk_level = _target_risk(target)
            tools.append(
                browser_tool_definition(
                    BrowserAutomationRuntimePolicy.from_model(record),
                    risk_level=risk_level,
                )
            )
        except BrowserAutomationPolicyError:
            continue
    return tools


async def execute_browser_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> str:
    """Execute one active browser automation tool from agent/router context."""

    context = context or {}
    tenant_id = context.get("tenant_id")
    user_id = context.get("user_id")
    if tenant_id is None or user_id is None:
        raise ValueError("Browser automation execution requires tenant_id and user_id")

    db = context.get("db")
    if db is not None:
        result = await _execute_browser_tool_with_db(tool_name, args, context=context, db=db)
        return json.dumps(result, ensure_ascii=False)

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as session:
        result = await _execute_browser_tool_with_db(tool_name, args, context=context, db=session)
    return json.dumps(result, ensure_ascii=False)


async def _execute_browser_tool_with_db(
    tool_name: str,
    args: dict[str, Any],
    *,
    context: Mapping[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    tenant_id = _uuid(context["tenant_id"])
    user_id = _uuid(context["user_id"])
    record, target = await _record_for_tool_name(db, tool_name, tenant_id=tenant_id, user_id=user_id)
    if record is None or target is None:
        raise ValueError(f"Browser automation tool not found: {tool_name}")

    actions = _actions_from_args(args)
    policy = BrowserAutomationRuntimePolicy.from_model(record)
    try:
        permission_request = await _runtime_permission_request_for_config(
            db,
            record,
            target,
            policy=policy,
            actions=actions,
            confirmation_context=context.get("confirmation_context"),
        )
        decision, decision_request = await _evaluate_browser_runtime_permission(
            db,
            permission_request,
            actions=actions,
        )
        if decision.confirmation_required:
            confirmation_context = decision.context or build_runtime_confirmation_context(decision_request)
            raise BrowserAutomationConfirmationRequired(
                tool_name=tool_name,
                args=_sanitize_confirmation_args(args),
                original_args=args,
                risk=str(confirmation_context.get("risk_level") or decision_request.risk_level or _target_risk(target)),
                confirmation_context=confirmation_context,
                code=decision.code,
                message=decision.message,
            )
        if not decision.allowed:
            raise BrowserAutomationRuntimeError(decision.code, decision.message)

        client = BrowserAutomationRuntimeClient(policy)
        runtime_context = _runtime_context_for_browser(
            context,
            write_action_ids=_write_action_ids(actions),
        )
        return await client.run(actions, context=runtime_context)
    except BrowserAutomationRuntimeError as exc:
        return exc.to_contract()
    except BrowserAutomationPolicyError as exc:
        return {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": False,
            },
        }


async def _runtime_permission_request_for_config(
    db: AsyncSession,
    record: BrowserAutomationConfiguration,
    target: ActivationTarget,
    *,
    policy: BrowserAutomationRuntimePolicy,
    actions: Sequence[Mapping[str, Any]],
    confirmation_context: Mapping[str, Any] | None,
) -> RuntimePermissionRequest:
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
        raise BrowserAutomationRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "Browser automation execution requires proposal evidence",
        )
    approved_hash = approved_snapshot_hash(proposal)
    current_hash = proposal.activation_snapshot_hash
    if not approved_hash or not current_hash:
        raise BrowserAutomationRuntimeError(
            "PERMISSION_EVIDENCE_REQUIRED",
            "Browser automation execution requires verified and approved activation snapshot evidence",
        )
    bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
    has_write = any(action_requires_confirmation(action) for action in actions)
    action_category = str(
        "browser_external_write"
        if has_write
        else bundle.get("action_category")
        or bundle.get("side_effect_category")
        or "read"
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
        risk_level=_target_risk(target),
        action_category=action_category,
        tool_context=_tool_context(policy=policy, actions=actions),
        confirmation_context=confirmation_context,
    )


async def _evaluate_browser_runtime_permission(
    db: AsyncSession,
    base_request: RuntimePermissionRequest,
    *,
    actions: Sequence[Mapping[str, Any]],
) -> tuple[Any, RuntimePermissionRequest]:
    target_policy = TargetPolicyDecision(
        allowed=True,
        confirmation_required=False,
        code="BROWSER_TARGET_POLICY_ALLOWED",
        message="Browser automation target policy allowed",
    )
    confirmation: tuple[Any, RuntimePermissionRequest] | None = None
    last_allowed: tuple[Any, RuntimePermissionRequest] | None = None
    requests = await _egress_permission_requests(base_request, actions=actions)

    for request in requests:
        decision = await evaluate_runtime_permission(db, request, target_policy=target_policy)
        if not decision.allowed and not decision.confirmation_required:
            return decision, request
        if decision.confirmation_required and confirmation is None:
            confirmation = (decision, request)
            continue
        last_allowed = (decision, request)

    if confirmation is not None:
        return confirmation
    if last_allowed is not None:
        return last_allowed
    decision = await evaluate_runtime_permission(db, base_request, target_policy=target_policy)
    return decision, base_request


async def _egress_permission_requests(
    base_request: RuntimePermissionRequest,
    *,
    actions: Sequence[Mapping[str, Any]],
) -> list[RuntimePermissionRequest]:
    urls = _action_urls(actions)
    if not urls:
        return [base_request]
    requests: list[RuntimePermissionRequest] = []
    for url in urls:
        requests.append(
            replace(
                base_request,
                egress_url=url,
                resolved_ips=await _resolved_ips_for_url(url),
            )
        )
    return requests


def _action_urls(actions: Sequence[Mapping[str, Any]]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for action in actions:
        url = action.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        if url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


async def _resolved_ips_for_url(url: str) -> list[str]:
    host = urlsplit(url).hostname
    if not host:
        return []
    return await _resolve_host_ips(host)


async def _resolve_host_ips(host: str) -> list[str]:
    def resolve() -> list[str]:
        try:
            results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return []
        ips: list[str] = []
        for result in results:
            ip = result[4][0]
            if ip not in ips:
                ips.append(ip)
        return ips

    import asyncio

    return await asyncio.to_thread(resolve)


async def _active_records(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[tuple[BrowserAutomationConfiguration, ActivationTarget]]:
    rows = (
        await db.execute(
            select(BrowserAutomationConfiguration, ActivationTarget)
            .join(ActivationTarget, BrowserAutomationConfiguration.activation_target_id == ActivationTarget.id)
            .where(
                BrowserAutomationConfiguration.tenant_id == tenant_id,
                BrowserAutomationConfiguration.user_id == user_id,
                BrowserAutomationConfiguration.enabled.is_(True),
                BrowserAutomationConfiguration.last_verified_at.is_not(None),
                ActivationTarget.tenant_id == tenant_id,
                ActivationTarget.user_id == user_id,
                ActivationTarget.target_type == "browser_automation",
                ActivationTarget.activation_status == "active",
            )
            .order_by(BrowserAutomationConfiguration.created_at.asc())
        )
    ).all()
    active: list[tuple[BrowserAutomationConfiguration, ActivationTarget]] = []
    for record, target in rows:
        resource_ref = target.activated_resource_ref if isinstance(target.activated_resource_ref, Mapping) else {}
        if resource_ref.get("hidden") is True:
            continue
        if resource_ref.get("exposed_to_runtime") is not True:
            continue
        if resource_ref.get("manifest_ref") != browser_tool_name(record.name):
            continue
        active.append((record, target))
    return active


async def _record_for_tool_name(
    db: AsyncSession,
    tool_name: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[BrowserAutomationConfiguration | None, ActivationTarget | None]:
    for record, target in await _active_records(db, tenant_id=tenant_id, user_id=user_id):
        if browser_tool_name(record.name) == tool_name:
            return record, target
    return None, None


def _actions_from_args(args: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    actions = args.get("actions") if isinstance(args, Mapping) else None
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        raise BrowserAutomationRuntimeError("ACTIONS_REQUIRED", "browser automation requires an actions array")
    return [dict(action) if isinstance(action, Mapping) else {"invalid_action": True} for action in actions]


def _tool_context(
    *,
    policy: BrowserAutomationRuntimePolicy,
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "tool_name": browser_tool_name(policy.name),
        "browser_name": policy.name,
        "allowed_hosts": policy.allowed_hosts,
        "action_count": len(actions),
        "write_action_ids": _write_action_ids(actions),
        "actions": [_action_summary(action, index) for index, action in enumerate(actions)],
    }


def _action_summary(action: Mapping[str, Any], index: int) -> dict[str, Any]:
    url = action.get("url")
    host = ""
    if url is not None:
        try:
            host = urlsplit(str(url)).hostname or ""
        except ValueError:
            host = ""
    return {
        "action_id": _action_id(action, index),
        "type": str(action.get("type") or action.get("kind") or action.get("action") or ""),
        "category": str(action.get("category") or action.get("action_category") or ""),
        "url_host": host.lower(),
        "external_write": action_requires_confirmation(action),
    }


def _write_action_ids(actions: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        _action_id(action, index)
        for index, action in enumerate(actions)
        if action_requires_confirmation(action)
    ]


def _action_id(action: Mapping[str, Any], index: int) -> str:
    return str(action.get("action_id") or action.get("id") or f"action-{index}")


def _runtime_context_for_browser(
    context: Mapping[str, Any],
    *,
    write_action_ids: Sequence[str],
) -> dict[str, Any]:
    runtime_context = dict(context)
    if not write_action_ids:
        return runtime_context
    confirmation = dict(context.get("confirmation_context") or {})
    if confirmation.get("confirmed") is True:
        confirmation.setdefault(
            "confirmation_id",
            str(context.get("tool_call_id") or context.get("run_id") or uuid.uuid4()),
        )
        confirmation["approved_action_ids"] = [str(action_id) for action_id in write_action_ids]
        runtime_context["confirmation_context"] = confirmation
    return runtime_context


def _sanitize_confirmation_args(args: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted_keys = {
        "authorization",
        "api_key",
        "cookie",
        "cookies",
        "password",
        "screenshot",
        "secret",
        "text",
        "token",
        "value",
    }

    def sanitize(value: Any, *, key: str = "") -> Any:
        if key.lower() in redacted_keys:
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {
                str(child_key): sanitize(item, key=str(child_key))
                for child_key, item in value.items()
                if not str(child_key).startswith("__")
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if key.lower() == "url" and isinstance(value, str):
            return _sanitize_url(value)
        return value

    sanitized = sanitize(args or {})
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED]"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _target_risk(target: ActivationTarget) -> str:
    bundle = target.permission_bundle if isinstance(target.permission_bundle, Mapping) else {}
    return str(bundle.get("risk_level") or "risky")


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
