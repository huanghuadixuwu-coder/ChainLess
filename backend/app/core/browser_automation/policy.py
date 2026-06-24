"""Policy validation for compose-managed browser automation sessions."""

from __future__ import annotations

import ipaddress
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit


class BrowserAutomationPolicyError(ValueError):
    """Raised when browser automation would violate runtime policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


TOOL_NAME_PREFIX = "browser__"
WRITE_ACTIONS = frozenset(
    {
        "click",
        "delete",
        "fill",
        "form_submit",
        "order",
        "payment",
        "press",
        "purchase",
        "send",
        "submit",
        "type",
        "upload",
    }
)
WRITE_CONFIRMATION_POLICY_MODES = frozenset(
    {
        "always",
        "before_each_browser_submit",
        "before_each_external_write",
        "before_run",
    }
)
FORBIDDEN_AUTOMATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"captcha|recaptcha|hcaptcha", re.IGNORECASE), "CAPTCHA_BYPASS_FORBIDDEN"),
    (re.compile(r"paywall", re.IGNORECASE), "PAYWALL_BYPASS_FORBIDDEN"),
    (re.compile(r"login[_ -]?bypass|credential[_ -]?stuffing|account[_ -]?takeover", re.IGNORECASE), "LOGIN_BYPASS_FORBIDDEN"),
    (re.compile(r"unauthori[sz]ed|scrape[_ -]?private|abuse", re.IGNORECASE), "UNAUTHORIZED_AUTOMATION_FORBIDDEN"),
)


@dataclass(frozen=True)
class BrowserAutomationRuntimePolicy:
    """Approved policy bundle handed to the browser automation runtime client."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    activation_target_id: uuid.UUID | None
    name: str
    allowlisted_domains: list[str]
    credential_ref: uuid.UUID | None
    credential_generation: int | None
    runtime_service_name: str
    runtime_url: str
    runtime_image_ref: str
    runtime_health_check: dict[str, Any]
    network_policy: dict[str, Any]
    cookie_scope: dict[str, Any]
    profile_policy: dict[str, Any]
    profile_storage_ref: str | None
    profile_retention_policy: dict[str, Any]
    max_session_seconds: int
    max_actions_per_run: int
    concurrency_limit: int
    system_concurrency_limit: int
    cpu_limit: str
    memory_limit_mb: int
    max_trace_bytes: int
    trace_retention_days: int
    action_redaction_policy: dict[str, Any]
    write_confirmation_policy: dict[str, Any]
    enabled: bool = False

    @classmethod
    def from_model(
        cls,
        config: Any,
        *,
        runtime_url: str | None = None,
        system_concurrency_limit: int | None = None,
    ) -> "BrowserAutomationRuntimePolicy":
        """Normalize a durable BrowserAutomationConfiguration model."""

        network_policy = dict(getattr(config, "network_policy", {}) or {})
        return cls(
            id=getattr(config, "id"),
            tenant_id=getattr(config, "tenant_id"),
            user_id=getattr(config, "user_id"),
            activation_target_id=getattr(config, "activation_target_id", None),
            name=getattr(config, "name"),
            allowlisted_domains=list(getattr(config, "allowlisted_domains", []) or []),
            credential_ref=getattr(config, "credential_ref", None),
            credential_generation=getattr(config, "credential_generation", None),
            runtime_service_name=getattr(config, "runtime_service_name"),
            runtime_url=(runtime_url or str(network_policy.get("runtime_url") or "http://browser-runtime:9222")).rstrip("/"),
            runtime_image_ref=getattr(config, "runtime_image_ref"),
            runtime_health_check=dict(getattr(config, "runtime_health_check", {}) or {}),
            network_policy=network_policy,
            cookie_scope=dict(getattr(config, "cookie_scope", {}) or {}),
            profile_policy=dict(getattr(config, "profile_policy", {}) or {}),
            profile_storage_ref=getattr(config, "profile_storage_ref", None),
            profile_retention_policy=dict(getattr(config, "profile_retention_policy", {}) or {}),
            max_session_seconds=int(getattr(config, "max_session_seconds")),
            max_actions_per_run=int(getattr(config, "max_actions_per_run")),
            concurrency_limit=int(getattr(config, "concurrency_limit")),
            system_concurrency_limit=int(system_concurrency_limit or network_policy.get("system_concurrency_limit") or 8),
            cpu_limit=str(getattr(config, "cpu_limit")),
            memory_limit_mb=int(getattr(config, "memory_limit_mb")),
            max_trace_bytes=int(getattr(config, "max_trace_bytes")),
            trace_retention_days=int(getattr(config, "trace_retention_days")),
            action_redaction_policy=dict(getattr(config, "action_redaction_policy", {}) or {}),
            write_confirmation_policy=dict(getattr(config, "write_confirmation_policy", {}) or {}),
            enabled=bool(getattr(config, "enabled", False)),
        )

    @property
    def allowed_hosts(self) -> list[str]:
        configured = self.network_policy.get("allowed_hosts")
        if configured is None:
            configured = self.network_policy.get("allow_hosts")
        if not isinstance(configured, list):
            return []
        return [_normalize_host(str(host)) for host in configured if str(host).strip()]


def browser_tool_name(name: str) -> str:
    """Return a deterministic OpenAI-compatible runtime tool name."""

    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
    if not slug:
        slug = "tool"
    return f"{TOOL_NAME_PREFIX}{slug}"[:120]


def validate_browser_runtime_policy(policy: BrowserAutomationRuntimePolicy) -> None:
    """Validate invariant browser runtime policy fields before execution."""

    if policy.enabled is not True:
        raise BrowserAutomationPolicyError("BROWSER_AUTOMATION_DISABLED", "browser automation policy is disabled")
    _validate_runtime_url(policy.runtime_url)
    if not policy.allowlisted_domains:
        raise BrowserAutomationPolicyError("ALLOWED_HOSTS_REQUIRED", "allowlisted_domains is required")
    if not policy.allowed_hosts:
        raise BrowserAutomationPolicyError("ALLOWED_HOSTS_REQUIRED", "network_policy.allowed_hosts is required")
    allowlisted_domains = [_normalize_host(str(host)) for host in policy.allowlisted_domains if str(host).strip()]
    for host in allowlisted_domains + policy.allowed_hosts:
        if _is_private_host_pattern(host):
            raise BrowserAutomationPolicyError("PRIVATE_NETWORKS_DENIED", "browser automation cannot allow private hosts")
    for host in policy.allowed_hosts:
        if not any(_host_pattern_is_subset(host, allowlisted) for allowlisted in allowlisted_domains):
            raise BrowserAutomationPolicyError(
                "ALLOWED_HOSTS_SCOPE_INVALID",
                "network_policy.allowed_hosts must be equal to or a subset of allowlisted_domains",
            )
    if policy.network_policy.get("mode") != "allowlist":
        raise BrowserAutomationPolicyError("NETWORK_POLICY_REQUIRED", "browser runtime network_policy.mode must be allowlist")
    if policy.network_policy.get("deny_private_networks") is not True:
        raise BrowserAutomationPolicyError("PRIVATE_NETWORKS_DENIED", "browser runtime must deny private networks")
    if policy.network_policy.get("allow_docker_socket") is not False:
        raise BrowserAutomationPolicyError("DOCKER_SOCKET_DENIED", "browser runtime must deny docker socket access")
    if policy.network_policy.get("allow_host_fs") is not False:
        raise BrowserAutomationPolicyError("HOST_FS_DENIED", "browser runtime must deny host filesystem access")
    if any(str(path).startswith(("/", "\\")) for path in policy.network_policy.get("mounts", []) or []):
        raise BrowserAutomationPolicyError("HOST_FS_DENIED", "browser runtime cannot receive host filesystem mounts")

    if not policy.runtime_service_name or "gstack" in policy.runtime_service_name.lower():
        raise BrowserAutomationPolicyError("DEDICATED_RUNTIME_REQUIRED", "browser automation must use a dedicated runtime service")
    if not policy.runtime_image_ref.startswith("chainless-browser-runtime:"):
        raise BrowserAutomationPolicyError("DEDICATED_IMAGE_REQUIRED", "browser automation must use the approved browser runtime image")
    if "gstack" in policy.runtime_image_ref.lower():
        raise BrowserAutomationPolicyError("DEDICATED_IMAGE_REQUIRED", "product browser automation cannot use the gstack QA browser")

    profile_isolation = str(policy.profile_policy.get("isolation") or "").lower()
    if profile_isolation not in {"per_run", "per_user"}:
        raise BrowserAutomationPolicyError("PROFILE_ISOLATION_REQUIRED", "profile_policy.isolation must be per_run or per_user")
    if policy.profile_policy.get("allow_host_fs") is not False:
        raise BrowserAutomationPolicyError("PROFILE_HOST_FS_DENIED", "browser profiles cannot access host filesystem")
    if policy.profile_storage_ref and _looks_like_host_path(policy.profile_storage_ref):
        raise BrowserAutomationPolicyError("PROFILE_HOST_FS_DENIED", "profile_storage_ref must not be a host path")

    retention_mode = str(policy.profile_retention_policy.get("mode") or "").lower()
    if retention_mode not in {"discard_after_run", "ttl_days"}:
        raise BrowserAutomationPolicyError("PROFILE_RETENTION_REQUIRED", "profile_retention_policy.mode is required")

    confirmation_mode = _write_confirmation_mode(policy)
    if confirmation_mode not in WRITE_CONFIRMATION_POLICY_MODES:
        raise BrowserAutomationPolicyError(
            "WRITE_CONFIRMATION_POLICY_INVALID",
            "write_confirmation_policy.mode must require runtime confirmation for external writes",
        )

    for key, value in {
        "max_session_seconds": policy.max_session_seconds,
        "max_actions_per_run": policy.max_actions_per_run,
        "concurrency_limit": policy.concurrency_limit,
        "system_concurrency_limit": policy.system_concurrency_limit,
        "memory_limit_mb": policy.memory_limit_mb,
        "max_trace_bytes": policy.max_trace_bytes,
        "trace_retention_days": policy.trace_retention_days,
    }.items():
        if not isinstance(value, int) or value < 1:
            raise BrowserAutomationPolicyError("INVALID_RESOURCE_LIMIT", f"{key} must be positive")


def validate_browser_actions(
    policy: BrowserAutomationRuntimePolicy,
    actions: Sequence[Mapping[str, Any]],
    *,
    context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate and normalize a browser action list for one runtime session."""

    validate_browser_runtime_policy(policy)
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        raise BrowserAutomationPolicyError("ACTIONS_REQUIRED", "browser actions must be a sequence")
    if len(actions) > policy.max_actions_per_run:
        raise BrowserAutomationPolicyError("MAX_ACTIONS_EXCEEDED", "browser action count exceeds max_actions_per_run")

    normalized: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            raise BrowserAutomationPolicyError("INVALID_ACTION", "browser action entries must be objects")
        action_dict = dict(action)
        action_dict["action_id"] = _action_id(action_dict, index)
        _forbid_automation_boundary(action_dict)
        if action_requires_confirmation(action_dict):
            _validate_write_confirmation(policy, action_dict, context)
        url = action_dict.get("url")
        if url is not None:
            validate_allowed_url(policy, str(url))
        normalized.append(action_dict)
    return normalized


def validate_allowed_url(policy: BrowserAutomationRuntimePolicy, url: str) -> str:
    """Validate that an action URL targets an allowlisted public host."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserAutomationPolicyError("INVALID_URL", "browser automation URL must be absolute HTTP(S)")
    host = _normalize_host(parsed.hostname)
    if _is_private_host(host):
        raise BrowserAutomationPolicyError("PRIVATE_NETWORKS_DENIED", "browser automation cannot target private networks")
    if not any(_host_matches(host, allowed) for allowed in policy.allowed_hosts):
        raise BrowserAutomationPolicyError("HOST_NOT_ALLOWLISTED", "browser automation target host is not allowlisted")
    return host


def _validate_runtime_url(runtime_url: str) -> None:
    expected = "http://browser-runtime:9222"
    parsed = urlsplit(str(runtime_url or "").strip())
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or _normalize_host(parsed.hostname or "") != "browser-runtime"
        or port != 9222
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise BrowserAutomationPolicyError(
            "BROWSER_AUTOMATION_RUNTIME_URL_INVALID",
            f"browser automation runtime_url must be the internal compose URL {expected}",
        )


def action_requires_confirmation(action: Mapping[str, Any]) -> bool:
    """Return whether an action can create an external side effect."""

    if action.get("external_write") is True or action.get("writes_external") is True:
        return True
    kind = str(action.get("type") or action.get("kind") or action.get("action") or "").lower()
    category = str(action.get("category") or action.get("action_category") or "").lower()
    return kind in WRITE_ACTIONS or category in {"external_write", "non_idempotent_side_effect"}


def build_profile_scope(policy: BrowserAutomationRuntimePolicy, *, run_id: str) -> dict[str, Any]:
    """Return the isolated profile payload sent to browser-runtime."""

    isolation = str(policy.profile_policy.get("isolation") or "per_run").lower()
    tenant_hex = str(policy.tenant_id).replace("-", "")[:12]
    user_hex = str(policy.user_id).replace("-", "")[:12]
    profile_id = f"ba-{tenant_hex}-{user_hex}-{run_id}"
    retention_mode = str(policy.profile_retention_policy.get("mode") or "discard_after_run")
    return {
        "profile_id": profile_id,
        "isolation": isolation,
        "ephemeral": retention_mode == "discard_after_run",
        "storage_ref": None if retention_mode == "discard_after_run" else policy.profile_storage_ref,
        "retention_policy": dict(policy.profile_retention_policy),
    }


def _forbid_automation_boundary(action: Mapping[str, Any]) -> None:
    haystack = " ".join(
        str(action.get(key, ""))
        for key in ("type", "kind", "action", "intent", "purpose", "description", "category")
    )
    for pattern, code in FORBIDDEN_AUTOMATION_PATTERNS:
        if pattern.search(haystack):
            raise BrowserAutomationPolicyError(code, "browser automation cannot bypass captcha, paywalls, login, or authorization")


def _validate_write_confirmation(
    policy: BrowserAutomationRuntimePolicy,
    action: Mapping[str, Any],
    context: Mapping[str, Any] | None,
) -> None:
    confirmation = (context or {}).get("confirmation_context")
    if not isinstance(confirmation, Mapping) or confirmation.get("confirmed") is not True:
        raise BrowserAutomationPolicyError(
            "CONFIRMATION_REQUIRED",
            "browser automation external writes require explicit runtime confirmation",
        )
    if not str(confirmation.get("confirmation_id") or "").strip():
        raise BrowserAutomationPolicyError(
            "CONFIRMATION_REQUIRED",
            "browser automation external write confirmation must include confirmation_id",
        )
    mode = _write_confirmation_mode(policy)
    if mode in {"before_each_external_write", "before_each_browser_submit"}:
        approved_ids = confirmation.get("approved_action_ids")
        if isinstance(approved_ids, Sequence) and not isinstance(approved_ids, (str, bytes)):
            approved = {str(action_id) for action_id in approved_ids}
        else:
            approved = set()
        if str(action.get("action_id") or "") not in approved:
            raise BrowserAutomationPolicyError(
                "ACTION_CONFIRMATION_REQUIRED",
                "browser automation external write confirmation must approve each write action_id",
            )


def _write_confirmation_mode(policy: BrowserAutomationRuntimePolicy) -> str:
    return str(policy.write_confirmation_policy.get("mode") or "before_each_external_write").lower()


def _action_id(action: Mapping[str, Any], index: int) -> str:
    return str(action.get("action_id") or action.get("id") or f"action-{index}")


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _host_matches(host: str, allowed: str) -> bool:
    allowed = _normalize_host(allowed)
    if allowed.startswith("*."):
        suffix = allowed[1:]
        return host.endswith(suffix) and host != allowed[2:]
    return host == allowed


def host_pattern_is_subset(candidate: str, allowed: str) -> bool:
    """Return whether one host/host-pattern stays inside another pattern."""

    return _host_pattern_is_subset(candidate, allowed)


def _host_pattern_is_subset(candidate: str, allowed: str) -> bool:
    candidate = _normalize_host(candidate)
    allowed = _normalize_host(allowed)
    if candidate.startswith("*."):
        candidate_base = candidate[2:]
        if allowed == candidate:
            return True
        if allowed.startswith("*."):
            allowed_base = allowed[2:]
            return candidate_base == allowed_base or candidate_base.endswith(f".{allowed_base}")
        return False
    return _host_matches(candidate, allowed)


def _is_private_host_pattern(host: str) -> bool:
    host = _normalize_host(host)
    if host.startswith("*."):
        return False
    return _is_private_host(host)


def _is_private_host(host: str) -> bool:
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _looks_like_host_path(value: str) -> bool:
    if value.startswith(("/", "\\")):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))
