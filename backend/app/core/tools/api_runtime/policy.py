"""Policy normalization for generic API-backed acquired tools."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for

from app.core.security.egress_policy import EgressPolicy
from app.models.acquisition import APIToolConfiguration


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOOL_NAME_PREFIX = "api__"
NO_CONFIRMATION_POLICIES = frozenset({"none", "not_required_verified", "safe_read_only_verified"})
SUPPORTED_AUTH_SCHEMES = frozenset({"none", "bearer", "api_key_header", "header"})


class APIToolPolicyError(ValueError):
    """Raised when an API tool configuration is not runtime-safe."""


@dataclass(frozen=True)
class APIToolRuntimePolicy:
    """Approved policy bundle handed to the generic API runtime client."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    activation_target_id: uuid.UUID | None
    name: str
    canonical_tool_name: str
    base_url: str
    method: str
    path_template: str
    headers_schema: dict[str, Any]
    auth_scheme: str
    credential_ref: uuid.UUID | None
    credential_generation: int | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_hosts: list[str]
    deny_private_networks: bool
    redirect_policy: dict[str, Any]
    allowed_content_types: list[str]
    max_request_bytes: int
    max_response_bytes: int
    idempotency_policy: dict[str, Any]
    response_redaction_policy: dict[str, Any]
    rate_limit: dict[str, Any]
    timeout_s: int
    retry_policy: dict[str, Any]
    error_contract: dict[str, Any]
    risk_level: str

    @classmethod
    def from_model(cls, config: APIToolConfiguration) -> "APIToolRuntimePolicy":
        return cls(
            id=config.id,
            tenant_id=config.tenant_id,
            user_id=config.user_id,
            activation_target_id=config.activation_target_id,
            name=config.name,
            canonical_tool_name=config.tool_name,
            base_url=config.base_url,
            method=config.method,
            path_template=config.path_template,
            headers_schema=dict(config.headers_schema or {}),
            auth_scheme=config.auth_scheme,
            credential_ref=config.credential_ref,
            credential_generation=config.credential_generation,
            input_schema=dict(config.input_schema or {}),
            output_schema=dict(config.output_schema or {}),
            allowed_hosts=list(config.allowed_hosts or []),
            deny_private_networks=bool(config.deny_private_networks),
            redirect_policy=dict(config.redirect_policy or {}),
            allowed_content_types=list(config.allowed_content_types or []),
            max_request_bytes=config.max_request_bytes,
            max_response_bytes=config.max_response_bytes,
            idempotency_policy=dict(config.idempotency_policy or {}),
            response_redaction_policy=dict(config.response_redaction_policy or {}),
            rate_limit=dict(config.rate_limit or {}),
            timeout_s=config.timeout_s,
            retry_policy=dict(config.retry_policy or {}),
            error_contract=dict(config.error_contract or {}),
            risk_level=config.risk_level,
        )

    @property
    def tool_name(self) -> str:
        return self.canonical_tool_name

    @property
    def egress_policy(self) -> EgressPolicy:
        return EgressPolicy(
            allow_hosts=self.allowed_hosts,
            redirect_policy=self.redirect_policy,
            deny_private_networks=self.deny_private_networks,
            max_response_bytes=self.max_response_bytes,
        )

    @property
    def write_like(self) -> bool:
        action = str(self.idempotency_policy.get("action_category", "")).lower()
        return self.method.upper() in WRITE_METHODS or action in {
            "external_write",
            "non_idempotent_side_effect",
            "send",
            "message_send",
            "submit",
            "delete",
            "payment",
            "order",
        }

    @property
    def requires_confirmation(self) -> bool:
        confirmation_policy = str(self.idempotency_policy.get("confirmation_policy") or "").lower()
        if confirmation_policy in NO_CONFIRMATION_POLICIES:
            return False
        if self.method.upper() in WRITE_METHODS:
            return True
        if self.idempotency_policy.get("requires_confirmation") is True:
            return True
        return self.write_like


def api_tool_name(name: str) -> str:
    """Return a deterministic OpenAI-compatible runtime tool name."""

    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
    if not slug:
        slug = "tool"
    return f"{TOOL_NAME_PREFIX}{slug}"[:120]


def validate_api_runtime_policy(policy: APIToolRuntimePolicy) -> None:
    """Validate invariant policy fields before exposing or executing a tool."""

    if not policy.tool_name.startswith(TOOL_NAME_PREFIX) or len(policy.tool_name) > 120:
        raise APIToolPolicyError("tool_name must be a canonical API tool name")
    if policy.method.upper() not in SAFE_METHODS | WRITE_METHODS:
        raise APIToolPolicyError("method must be an allowed HTTP method")
    if policy.max_request_bytes < 1:
        raise APIToolPolicyError("max_request_bytes must be positive")
    if policy.max_response_bytes < 1:
        raise APIToolPolicyError("max_response_bytes must be positive")
    if policy.timeout_s < 1:
        raise APIToolPolicyError("timeout_s must be positive")
    if not policy.allowed_hosts:
        raise APIToolPolicyError("allowed_hosts is required")
    if not policy.allowed_content_types:
        raise APIToolPolicyError("allowed_content_types is required")
    _validate_schema_definition(policy.input_schema or {"type": "object"}, "input_schema")
    if policy.output_schema:
        _validate_schema_definition(policy.output_schema, "output_schema")

    parsed = urlsplit(policy.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise APIToolPolicyError("base_url must be absolute HTTP(S)")
    if policy.credential_ref is not None and policy.auth_scheme == "none":
        raise APIToolPolicyError("credential_ref requires a non-none auth_scheme")
    if policy.credential_ref is None and policy.auth_scheme != "none":
        raise APIToolPolicyError("auth_scheme requires credential_ref")
    if policy.auth_scheme.lower() not in SUPPORTED_AUTH_SCHEMES:
        raise APIToolPolicyError("auth_scheme is unsupported")


def _validate_schema_definition(schema: dict[str, Any], field: str) -> None:
    if not isinstance(schema, dict) or not schema:
        return
    try:
        validator_for(schema).check_schema(schema)
    except SchemaError:
        raise APIToolPolicyError(f"{field} must be valid JSON Schema")
