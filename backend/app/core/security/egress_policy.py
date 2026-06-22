"""Reusable network egress validation for acquired runtime targets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

ACTIVATED_RUNTIME_TARGETS = frozenset(
    {"api_tool", "mcp_tool", "browser_automation", "worker", "code_as_action"}
)
DEFAULT_HTTP_PORTS = {"http": 80, "https": 443}
METADATA_ENDPOINT_IPS = frozenset({"169.254.169.254"})
NETWORK_SCOPES_REQUIRING_EXPLICIT_EGRESS = frozenset(
    {"public_web", "allowlisted_domains", "configured_api_base"}
)


@dataclass(frozen=True)
class EgressPolicy:
    """Declarative egress constraints shared by acquired network runtimes."""

    allow_hosts: Sequence[str] = field(default_factory=tuple)
    redirect_policy: dict = field(default_factory=lambda: {"follow": False})
    deny_private_networks: bool = True
    max_response_bytes: int | None = None


@dataclass(frozen=True)
class EgressDecision:
    """Pure validation result; callers decide whether to raise or log."""

    allowed: bool
    code: str
    message: str
    normalized_host: str | None = None
    normalized_url: str | None = None
    resolved_ips: tuple[str, ...] = ()


@dataclass(frozen=True)
class EgressRuntimeGuard:
    """Runtime-ready egress evidence callers must pin before connecting."""

    normalized_host: str
    normalized_url: str
    approved_resolved_ips: tuple[str, ...]
    max_response_bytes: int
    allowed: bool = True
    code: str = "ALLOWED"
    message: str = "Runtime egress guard is prepared"


Resolver = Callable[[str], Sequence[str]]


def validate_egress_request(
    policy: EgressPolicy,
    url: str,
    *,
    network_scope: str,
    target_type: str | None = None,
    activated_target: bool = False,
    resolved_ips: Sequence[str] | None = None,
    validated_resolved_ips: Sequence[str] | None = None,
    resolver: Resolver | None = None,
    response_content_length: int | None = None,
    redirect_url: str | None = None,
    redirect_resolved_ips: Sequence[str] | None = None,
) -> EgressDecision:
    """Validate one request plus optional redirect/response metadata.

    This function intentionally performs no HTTP I/O. Runtime owners provide DNS
    answers from their resolver and can re-call it after connect to detect
    rebinding.
    """

    if _response_cap_required(
        target_type=target_type,
        activated_target=activated_target,
    ) and policy.max_response_bytes is None:
        return _deny(
            "RESPONSE_SIZE_CAP_REQUIRED",
            "Activated runtime targets must define a response byte cap",
        )

    request_decision = _validate_single_url(
        policy,
        url,
        network_scope=network_scope,
        target_type=target_type,
        activated_target=activated_target,
        resolved_ips=resolved_ips,
        validated_resolved_ips=validated_resolved_ips,
        resolver=resolver,
        is_redirect=False,
    )
    if not request_decision.allowed:
        return request_decision

    if response_content_length is not None and policy.max_response_bytes is not None:
        if response_content_length > policy.max_response_bytes:
            return _deny(
                "RESPONSE_TOO_LARGE",
                "Response content length exceeds the egress policy contract",
                normalized_host=request_decision.normalized_host,
                normalized_url=request_decision.normalized_url,
                resolved_ips=request_decision.resolved_ips,
            )

    if redirect_url is None:
        return request_decision

    if not _redirects_allowed(policy.redirect_policy):
        return _deny(
            "REDIRECT_DENIED",
            "Redirects are disabled by the egress policy",
            normalized_host=request_decision.normalized_host,
            normalized_url=request_decision.normalized_url,
            resolved_ips=request_decision.resolved_ips,
        )

    return _validate_single_url(
        policy,
        redirect_url,
        network_scope=network_scope,
        target_type=target_type,
        activated_target=activated_target,
        resolved_ips=redirect_resolved_ips,
        resolver=resolver,
        is_redirect=True,
    )


def prepare_egress_runtime_guard(
    policy: EgressPolicy,
    url: str,
    *,
    network_scope: str,
    target_type: str | None = None,
    activated_target: bool = True,
    resolved_ips: Sequence[str] | None = None,
    resolver: Resolver | None = None,
) -> EgressRuntimeGuard | EgressDecision:
    """Prepare runtime egress evidence that HTTP owners must pin/connect to.

    The guard intentionally performs no HTTP I/O. Runtime owners should resolve
    DNS, call this helper, connect only to one of ``approved_resolved_ips``, and
    then call ``validate_runtime_egress`` with the actual connected peer IPs.
    """

    decision = validate_egress_request(
        policy,
        url,
        network_scope=network_scope,
        target_type=target_type,
        activated_target=activated_target,
        resolved_ips=resolved_ips,
        resolver=resolver,
    )
    if not decision.allowed:
        return decision
    if policy.max_response_bytes is None:
        return _deny(
            "RESPONSE_SIZE_CAP_REQUIRED",
            "Runtime egress guard requires a response byte cap",
            normalized_host=decision.normalized_host,
            normalized_url=decision.normalized_url,
            resolved_ips=decision.resolved_ips,
        )
    return EgressRuntimeGuard(
        normalized_host=decision.normalized_host or "",
        normalized_url=decision.normalized_url or "",
        approved_resolved_ips=decision.resolved_ips,
        max_response_bytes=policy.max_response_bytes,
    )


def validate_runtime_egress(
    guard: EgressRuntimeGuard | EgressDecision,
    *,
    connected_ips: Sequence[str] | None,
) -> EgressDecision:
    """Validate post-connect peer IP evidence against a prepared guard."""

    if isinstance(guard, EgressDecision):
        if not guard.allowed:
            return guard
        return _deny(
            "INVALID_RUNTIME_GUARD",
            "Runtime validation requires a prepared egress guard",
            normalized_host=guard.normalized_host,
            normalized_url=guard.normalized_url,
            resolved_ips=guard.resolved_ips,
        )

    try:
        normalized_connected_ips = _normalize_ips(connected_ips or ())
    except ValueError:
        return _deny(
            "INVALID_DNS_RESOLUTION",
            "Connected IP evidence must contain valid IP addresses",
            normalized_host=guard.normalized_host,
            normalized_url=guard.normalized_url,
            resolved_ips=guard.approved_resolved_ips,
        )
    if not normalized_connected_ips:
        return _deny(
            "DNS_RESOLUTION_REQUIRED",
            "Post-connect IP evidence is required for runtime egress validation",
            normalized_host=guard.normalized_host,
            normalized_url=guard.normalized_url,
            resolved_ips=guard.approved_resolved_ips,
        )
    if set(normalized_connected_ips) - set(guard.approved_resolved_ips):
        return _deny(
            "DNS_REBINDING_DENIED",
            "Connected IPs differ from the approved DNS answers",
            normalized_host=guard.normalized_host,
            normalized_url=guard.normalized_url,
            resolved_ips=normalized_connected_ips,
        )
    return EgressDecision(
        allowed=True,
        code="ALLOWED",
        message="Runtime egress connection is allowed",
        normalized_host=guard.normalized_host,
        normalized_url=guard.normalized_url,
        resolved_ips=normalized_connected_ips,
    )


def validate_egress_response_chunk(
    policy: EgressPolicy,
    *,
    bytes_received: int,
    chunk_size: int,
    normalized_host: str | None = None,
    normalized_url: str | None = None,
    resolved_ips: Sequence[str] = (),
) -> EgressDecision:
    """Validate streaming response byte accounting when content length is absent."""

    if policy.max_response_bytes is None:
        return _deny(
            "RESPONSE_SIZE_CAP_REQUIRED",
            "Streaming response validation requires a response byte cap",
            normalized_host=normalized_host,
            normalized_url=normalized_url,
            resolved_ips=resolved_ips,
        )
    if bytes_received < 0 or chunk_size < 0:
        return _deny(
            "INVALID_RESPONSE_BYTE_COUNT",
            "Streaming response byte counts must be non-negative",
            normalized_host=normalized_host,
            normalized_url=normalized_url,
            resolved_ips=resolved_ips,
        )
    if bytes_received + chunk_size > policy.max_response_bytes:
        return _deny(
            "RESPONSE_TOO_LARGE",
            "Streaming response bytes exceed the egress policy contract",
            normalized_host=normalized_host,
            normalized_url=normalized_url,
            resolved_ips=resolved_ips,
        )
    return EgressDecision(
        allowed=True,
        code="ALLOWED",
        message="Streaming response bytes are within the egress policy contract",
        normalized_host=normalized_host,
        normalized_url=normalized_url,
        resolved_ips=tuple(resolved_ips),
    )


def normalize_host(value: str, *, scheme: str | None = None) -> str:
    """Normalize URL hosts and allowlist entries for case-insensitive matching."""

    raw = value.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        port = parsed.port
        entry_scheme = parsed.scheme
    else:
        host, port = _split_host_port(raw)
        entry_scheme = scheme

    normalized = host.strip("[]").rstrip(".").lower()
    try:
        normalized = normalized.encode("idna").decode("ascii")
    except UnicodeError:
        pass

    default_port = DEFAULT_HTTP_PORTS.get(entry_scheme or "")
    if entry_scheme is None and port in DEFAULT_HTTP_PORTS.values():
        default_port = port
    if port is not None and default_port != port:
        return f"{normalized}:{port}"
    return normalized


def _validate_single_url(
    policy: EgressPolicy,
    url: str,
    *,
    network_scope: str,
    target_type: str | None,
    activated_target: bool,
    resolved_ips: Sequence[str] | None,
    validated_resolved_ips: Sequence[str] | None = None,
    resolver: Resolver | None,
    is_redirect: bool,
) -> EgressDecision:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return _deny("INVALID_EGRESS_URL", "Egress URL port must be valid")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return _deny("INVALID_EGRESS_URL", "Egress URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        return _deny("INVALID_EGRESS_URL", "Egress URL cannot include userinfo")
    if port is not None and not (1 <= port <= 65535):
        return _deny("INVALID_EGRESS_URL", "Egress URL port must be valid")

    host = normalize_host(parsed.netloc, scheme=parsed.scheme)
    dns_host = normalize_host(parsed.hostname, scheme=parsed.scheme)
    normalized_url = parsed.geturl()

    if _is_non_canonical_numeric_ipv4_host(parsed.hostname):
        return _deny(
            "INVALID_EGRESS_URL",
            "Numeric IPv4 hosts must use canonical dotted-decimal form",
            normalized_host=host,
            normalized_url=normalized_url,
        )

    if _activated_arbitrary_network_forbidden(
        network_scope=network_scope,
        target_type=target_type,
        activated_target=activated_target,
    ):
        return _deny(
            "ARBITRARY_NETWORK_FORBIDDEN",
            "Activated runtime targets must use an explicit egress policy",
            normalized_host=host,
            normalized_url=normalized_url,
        )

    if network_scope in NETWORK_SCOPES_REQUIRING_EXPLICIT_EGRESS and not _host_allowed(policy.allow_hosts, host):
        return _deny(
            "HOST_NOT_ALLOWLISTED",
            "Host is not allowed by the egress policy",
            normalized_host=host,
            normalized_url=normalized_url,
        )

    try:
        ips = _resolve_host(dns_host, resolved_ips=resolved_ips, resolver=resolver)
    except ValueError:
        return _deny(
            "INVALID_DNS_RESOLUTION",
            "Resolved IP evidence must contain valid IP addresses",
            normalized_host=host,
            normalized_url=normalized_url,
        )
    if not ips:
        return _deny(
            "DNS_RESOLUTION_REQUIRED",
            "DNS resolution evidence is required for egress validation",
            normalized_host=host,
            normalized_url=normalized_url,
        )

    if validated_resolved_ips is not None:
        try:
            validated_ips = _normalize_ips(validated_resolved_ips)
        except ValueError:
            return _deny(
                "INVALID_DNS_RESOLUTION",
                "Previously validated IP evidence must contain valid IP addresses",
                normalized_host=host,
                normalized_url=normalized_url,
                resolved_ips=ips,
            )
        if set(ips) - set(validated_ips):
            return _deny(
                "DNS_REBINDING_DENIED",
                "Resolved IPs differ from the previously validated DNS answers",
                normalized_host=host,
                normalized_url=normalized_url,
                resolved_ips=ips,
            )

    ip_decision = _validate_ips(policy, ips, host=host, normalized_url=normalized_url)
    if not ip_decision.allowed:
        return ip_decision

    return EgressDecision(
        allowed=True,
        code="ALLOWED",
        message="Egress request is allowed" if not is_redirect else "Redirect target is allowed",
        normalized_host=host,
        normalized_url=normalized_url,
        resolved_ips=ips,
    )


def _validate_ips(policy: EgressPolicy, ips: tuple[str, ...], *, host: str, normalized_url: str) -> EgressDecision:
    for ip in ips:
        if ip in METADATA_ENDPOINT_IPS:
            return _deny(
                "METADATA_ENDPOINT_DENIED",
                "Cloud metadata endpoints are forbidden",
                normalized_host=host,
                normalized_url=normalized_url,
                resolved_ips=ips,
            )
        parsed_ip = ip_address(ip)
        if policy.deny_private_networks and _is_private_network_address(parsed_ip):
            return _deny(
                "PRIVATE_NETWORK_DENIED",
                "Private, local, reserved, multicast, and link-local networks are forbidden",
                normalized_host=host,
                normalized_url=normalized_url,
                resolved_ips=ips,
            )
    return EgressDecision(True, "ALLOWED", "Resolved IPs are allowed", host, normalized_url, ips)


def _resolve_host(host: str, *, resolved_ips: Sequence[str] | None, resolver: Resolver | None) -> tuple[str, ...]:
    if resolved_ips is not None:
        return _normalize_ips(resolved_ips)
    try:
        ip_address(host)
        return (host,)
    except ValueError:
        pass
    if resolver is None:
        return ()
    return _normalize_ips(resolver(host))


def _normalize_ips(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        parsed = ip_address(value.strip("[]"))
        normalized.append(str(parsed))
    return tuple(normalized)


def _is_private_network_address(parsed_ip) -> bool:
    return (
        parsed_ip.is_private
        or parsed_ip.is_loopback
        or parsed_ip.is_link_local
        or parsed_ip.is_multicast
        or parsed_ip.is_reserved
        or parsed_ip.is_unspecified
    )


def _is_non_canonical_numeric_ipv4_host(host: str) -> bool:
    normalized = host.strip("[]").rstrip(".").lower()
    try:
        parsed = ip_address(normalized)
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed.version == 4 and str(parsed) != normalized
    labels = normalized.split(".")
    if 1 <= len(labels) < 4 and all(label for label in labels):
        return all(_is_legacy_numeric_ipv4_label(label) for label in labels)
    if len(labels) == 4 and all(label for label in labels):
        return all(_is_legacy_numeric_ipv4_label(label) for label in labels)
    return False


def _is_legacy_numeric_ipv4_label(label: str) -> bool:
    if label.startswith("0x"):
        return len(label) > 2 and all(char in "0123456789abcdef" for char in label[2:])
    return label.isdigit()


def _host_allowed(allow_hosts: Sequence[str], host: str) -> bool:
    for entry in allow_hosts:
        normalized = normalize_host(entry)
        if normalized.startswith("*."):
            suffix = normalized[2:]
            if host != suffix and host.endswith(f".{suffix}"):
                return True
        elif host == normalized:
            return True
    return False


def _split_host_port(value: str) -> tuple[str, int | None]:
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return value, None
        host = value[1:end]
        remainder = value[end + 1 :]
        if remainder.startswith(":") and remainder[1:].isdigit():
            return host, int(remainder[1:])
        return host, None
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            return host, int(port)
    return value, None


def _redirects_allowed(redirect_policy: dict) -> bool:
    return bool(redirect_policy.get("follow"))


def _activated_arbitrary_network_forbidden(
    *, network_scope: str, target_type: str | None, activated_target: bool
) -> bool:
    return (
        activated_target
        and network_scope == "arbitrary_network"
        and (target_type is None or target_type in ACTIVATED_RUNTIME_TARGETS)
    )


def _response_cap_required(*, target_type: str | None, activated_target: bool) -> bool:
    return activated_target and (target_type is None or target_type in ACTIVATED_RUNTIME_TARGETS)


def _deny(
    code: str,
    message: str,
    *,
    normalized_host: str | None = None,
    normalized_url: str | None = None,
    resolved_ips: Sequence[str] = (),
) -> EgressDecision:
    return EgressDecision(
        allowed=False,
        code=code,
        message=message,
        normalized_host=normalized_host,
        normalized_url=normalized_url,
        resolved_ips=tuple(resolved_ips),
    )
