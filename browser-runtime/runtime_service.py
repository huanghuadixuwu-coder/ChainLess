from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None


FORBIDDEN = re.compile(
    r"captcha|recaptcha|hcaptcha|paywall|login[_ -]?bypass|credential[_ -]?stuffing|account[_ -]?takeover|unauthori[sz]ed",
    re.IGNORECASE,
)
WRITE_ACTIONS = {
    "click",
    "delete",
    "fill",
    "form_submit",
    "order",
    "payment",
    "purchase",
    "send",
    "submit",
    "type",
    "upload",
}
WRITE_CONFIRMATION_POLICY_MODES = {
    "always",
    "before_each_browser_submit",
    "before_each_external_write",
    "before_run",
}
ALLOWED_NON_NETWORK_SCHEMES = {"about", "data"}


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _host_matches(host: str, allowed: str) -> bool:
    allowed = _normalize_host(allowed)
    if allowed.startswith("*."):
        suffix = allowed[1:]
        return host.endswith(suffix) and host != allowed[2:]
    return host == allowed


def _host_allowed(url: str, allowed_hosts: list[str], *, allowed_schemes: set[str] | None = None) -> bool:
    schemes = allowed_schemes or {"http", "https"}
    parsed = urlsplit(url)
    if parsed.scheme not in schemes or not parsed.hostname:
        return False
    host = _normalize_host(parsed.hostname)
    return any(_host_matches(host, str(allowed)) for allowed in allowed_hosts)


def _private_ip(value: str) -> bool:
    try:
        parsed = ipaddress.ip_address(value)
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


def _resolved_private_host(host: str) -> bool:
    if _private_ip(host):
        return True
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return True
    return any(_private_ip(record[4][0]) for record in records)


def _network_violation(
    url: str,
    allowed_hosts: list[str],
    *,
    deny_private_networks: bool = True,
    resolve_dns: bool = True,
    allowed_schemes: set[str] | None = None,
) -> str | None:
    schemes = allowed_schemes or {"http", "https"}
    if url.startswith("blob:"):
        inner_url = url.removeprefix("blob:")
        if inner_url.startswith(("http://", "https://")):
            return _network_violation(
                inner_url,
                allowed_hosts,
                deny_private_networks=deny_private_networks,
                resolve_dns=resolve_dns,
                allowed_schemes=schemes,
            )
        return "blob URL has no allowlisted origin"
    parsed = urlsplit(url)
    if parsed.scheme in ALLOWED_NON_NETWORK_SCHEMES:
        return None
    if parsed.scheme not in schemes or not parsed.hostname:
        return "URL scheme is not allowed"
    host = _normalize_host(parsed.hostname)
    if deny_private_networks and (_private_ip(host) or (resolve_dns and _resolved_private_host(host))):
        return "host resolves to a private network"
    if not _host_allowed(url, allowed_hosts, allowed_schemes=schemes):
        return "host is not allowlisted"
    return None


class RuntimeNetworkGuard:
    """Fail-closed Playwright request guard for all browser network activity."""

    def __init__(
        self,
        allowed_hosts: list[str],
        *,
        deny_private_networks: bool,
        deadline_epoch_s: float,
        resolve_dns: bool = True,
    ) -> None:
        self.allowed_hosts = [_normalize_host(str(host)) for host in allowed_hosts if str(host).strip()]
        self.deny_private_networks = deny_private_networks
        self.deadline_epoch_s = deadline_epoch_s
        self.resolve_dns = resolve_dns
        self.violations: list[dict[str, str]] = []

    def route(self, route) -> None:
        url = str(route.request.url)
        if self.validate_url(url, source="request"):
            route.continue_()
            return
        route.abort("blockedbyclient")

    def route_web_socket(self, ws) -> None:
        url = str(getattr(ws, "url", ""))
        if not self.validate_url(url, source="websocket", allowed_schemes={"ws", "wss"}):
            _close_web_socket_route(ws, "browser runtime network policy")
            return
        connect_to_server = getattr(ws, "connect_to_server", None)
        if not callable(connect_to_server):
            self.violations.append(
                {
                    "source": "websocket",
                    "url": url,
                    "reason": "WebSocket pass-through unavailable",
                }
            )
            _close_web_socket_route(ws, "browser runtime WebSocket pass-through unavailable")
            return
        connect_to_server()

    def validate_url(self, url: str, *, source: str, allowed_schemes: set[str] | None = None) -> bool:
        try:
            self.enforce_deadline()
        except ValueError as exc:
            self.violations.append({"source": source, "url": url, "reason": str(exc)})
            return False
        reason = _network_violation(
            url,
            self.allowed_hosts,
            deny_private_networks=self.deny_private_networks,
            resolve_dns=self.resolve_dns,
            allowed_schemes=allowed_schemes,
        )
        if reason:
            self.violations.append({"source": source, "url": url, "reason": reason})
            return False
        return True

    def enforce_deadline(self) -> None:
        _enforce_deadline(self.deadline_epoch_s)

    def raise_if_violations(self) -> None:
        if self.violations:
            first = self.violations[0]
            raise ValueError(
                "network policy violation: "
                f"{first['source']} blocked {first['url']} ({first['reason']})"
            )


def _close_web_socket_route(ws, reason: str) -> None:
    close = getattr(ws, "close", None)
    if not callable(close):
        return
    try:
        close(code=1008, reason=reason)
    except TypeError:
        close()


def _install_websocket_guard(context, guard: RuntimeNetworkGuard) -> None:
    route_web_socket = getattr(context, "route_web_socket", None)
    if not callable(route_web_socket):
        raise RuntimeError("playwright_route_web_socket_unavailable")
    route_web_socket(re.compile(r".*"), guard.route_web_socket)


def _session_deadline_seconds(payload: dict) -> float:
    max_session_seconds = max(float(payload.get("max_session_seconds") or 1), 0.001)
    deadline = time.time() + max_session_seconds
    try:
        payload_deadline = float(payload.get("deadline_epoch_ms")) / 1000.0
    except (TypeError, ValueError):
        return deadline
    return min(deadline, payload_deadline)


def _enforce_deadline(deadline_epoch_s: float) -> None:
    if time.time() >= deadline_epoch_s:
        raise ValueError("session deadline exceeded")


def _remaining_timeout_ms(deadline_epoch_s: float, *, cap_ms: int | None = None) -> int:
    _enforce_deadline(deadline_epoch_s)
    remaining_ms = max(1, int((deadline_epoch_s - time.time()) * 1000))
    return min(remaining_ms, cap_ms) if cap_ms is not None else remaining_ms


def _forbidden(action: dict) -> bool:
    haystack = " ".join(str(action.get(key, "")) for key in ("type", "kind", "intent", "purpose", "description"))
    return bool(FORBIDDEN.search(haystack))


def _external_write(action: dict) -> bool:
    kind = str(action.get("type") or action.get("kind") or "navigate").lower()
    category = str(action.get("category") or action.get("action_category") or "").lower()
    return bool(
        action.get("external_write") is True
        or action.get("writes_external") is True
        or kind in WRITE_ACTIONS
        or category == "external_write"
    )


def _action_id(action: dict, index: int) -> str:
    return str(action.get("action_id") or action.get("id") or f"action-{index}")


def _write_confirmation_mode(policy: dict) -> str:
    return str((policy or {}).get("mode") or "before_each_external_write").lower()


def _validate_write_confirmation(actions: list[dict], confirmation: dict, policy: dict) -> None:
    mode = _write_confirmation_mode(policy)
    if mode not in WRITE_CONFIRMATION_POLICY_MODES:
        raise ValueError("write_confirmation_policy.mode is not supported")
    approved_action_ids = confirmation.get("approved_action_ids", [])
    if not isinstance(approved_action_ids, list):
        approved_action_ids = []
    approved = {str(action_id) for action_id in approved_action_ids}
    for index, action in enumerate(actions):
        action["action_id"] = _action_id(action, index)
        if not _external_write(action):
            continue
        if confirmation.get("confirmed") is not True or not str(confirmation.get("confirmation_id") or "").strip():
            raise ValueError("external write requires trusted confirmation")
        if mode in {"before_each_external_write", "before_each_browser_submit"} and action["action_id"] not in approved:
            raise ValueError("external write requires approved_action_ids for each write action")


class RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "chainless-browser-runtime/0.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"ok": True, "runtime_kind": "isolated_browser"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("content-length", "0"))
            if content_length > 1048576:
                raise ValueError("runtime payload exceeds 1MiB")
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8") or "{}")
            self._json(HTTPStatus.OK, _run_browser(payload))
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": exc.__class__.__name__})

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _run_browser(payload: dict) -> dict:
    allowed_hosts = payload.get("allowed_hosts")
    actions = payload.get("actions")
    confirmation = payload.get("confirmation") or {}
    write_confirmation_policy = payload.get("write_confirmation_policy") or {}
    profile = payload.get("profile") or {}
    if not isinstance(allowed_hosts, list) or not allowed_hosts:
        raise ValueError("allowed_hosts is required")
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    if not isinstance(confirmation, dict):
        confirmation = {}
    if not isinstance(write_confirmation_policy, dict):
        write_confirmation_policy = {}
    deadline_epoch_s = _session_deadline_seconds(payload)
    _enforce_deadline(deadline_epoch_s)
    max_actions = int(payload.get("max_actions_per_run") or 1)
    if len(actions) > max_actions:
        raise ValueError("max_actions_per_run exceeded")
    guard = RuntimeNetworkGuard(
        allowed_hosts,
        deny_private_networks=payload.get("deny_private_networks") is not False,
        deadline_epoch_s=deadline_epoch_s,
    )
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or _forbidden(action):
            raise ValueError("forbidden automation boundary")
        action["action_id"] = _action_id(action, index)
    _validate_write_confirmation(actions, confirmation, write_confirmation_policy)
    for action in actions:
        url = action.get("url")
        if url and not guard.validate_url(str(url), source="action_url"):
            guard.raise_if_violations()
    if sync_playwright is None:
        raise RuntimeError("playwright_unavailable")

    profile_root = os.environ.get("BROWSER_RUNTIME_PROFILE_ROOT", "/tmp/browser-profiles")
    os.makedirs(profile_root, exist_ok=True)
    user_data_dir = tempfile.mkdtemp(prefix=str(profile.get("profile_id") or "run")[:48], dir=profile_root)
    evidence = []
    context = None
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
                service_workers="block",
            )
            try:
                context.route("**/*", guard.route)
                _install_websocket_guard(context, guard)
                page = context.pages[0] if context.pages else context.new_page()
                page.on("framenavigated", lambda frame: guard.validate_url(str(frame.url), source="navigation"))
                for index, action in enumerate(actions):
                    guard.enforce_deadline()
                    kind = str(action.get("type") or action.get("kind") or "navigate").lower()
                    if kind in {"goto", "navigate"}:
                        try:
                            page.goto(
                                str(action["url"]),
                                wait_until="domcontentloaded",
                                timeout=_remaining_timeout_ms(deadline_epoch_s),
                            )
                        except Exception:
                            guard.raise_if_violations()
                            raise
                        guard.raise_if_violations()
                        evidence.append({"index": index, "type": kind, "url": page.url, "title": page.title()})
                    elif kind == "screenshot":
                        screenshot = page.screenshot(full_page=bool(action.get("full_page", True)))
                        guard.raise_if_violations()
                        evidence.append(
                            {
                                "index": index,
                                "type": kind,
                                "sha256": hashlib.sha256(screenshot).hexdigest(),
                                "redacted": True,
                            }
                        )
                    elif kind in {"dom_snapshot", "extract_text"}:
                        text = page.locator("body").inner_text(
                            timeout=_remaining_timeout_ms(deadline_epoch_s, cap_ms=3000)
                        )[:4096]
                        guard.raise_if_violations()
                        evidence.append({"index": index, "type": kind, "url": page.url, "text": text})
                    elif kind == "click":
                        try:
                            page.click(str(action["selector"]), timeout=_remaining_timeout_ms(deadline_epoch_s, cap_ms=3000))
                            try:
                                page.wait_for_load_state(
                                    "domcontentloaded",
                                    timeout=_remaining_timeout_ms(deadline_epoch_s, cap_ms=1000),
                                )
                            except PlaywrightTimeoutError:
                                pass
                        except Exception:
                            guard.raise_if_violations()
                            raise
                        guard.raise_if_violations()
                        evidence.append({"index": index, "type": kind, "selector": str(action.get("selector"))})
                    elif kind in {"fill", "type"}:
                        input_value = action.get("text") if kind == "type" else action.get("value")
                        page.fill(
                            str(action["selector"]),
                            str(input_value or ""),
                            timeout=_remaining_timeout_ms(deadline_epoch_s, cap_ms=3000),
                        )
                        guard.raise_if_violations()
                        evidence.append({"index": index, "type": kind, "selector": str(action.get("selector"))})
                    else:
                        raise ValueError(f"unsupported action: {kind}")
            finally:
                if context is not None:
                    context.close()
                    context = None
    finally:
        if context is not None:
            context.close()
        if profile.get("ephemeral", True):
            shutil.rmtree(user_data_dir, ignore_errors=True)
    guard.raise_if_violations()
    return {"ok": True, "evidence": evidence}


if __name__ == "__main__":
    port = int(os.environ.get("BROWSER_RUNTIME_PORT", "9222"))
    ThreadingHTTPServer(("0.0.0.0", port), RuntimeHandler).serve_forever()
