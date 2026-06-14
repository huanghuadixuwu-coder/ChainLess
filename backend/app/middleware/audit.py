"""Request audit middleware for security-sensitive mutations."""

from __future__ import annotations

import logging
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import _async_session_factory
from app.core.audit.service import AuditRecord, write_audit_log
from app.services.auth_service import decode_token

logger = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"}


class AuditMiddleware(BaseHTTPMiddleware):
    """Record tenant-scoped mutations without persisting request bodies."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if _should_audit(request):
            await _record_request(request, response.status_code)
        return response


def _should_audit(request: Request) -> bool:
    if request.url.path.startswith("/api/v1/audit"):
        return False
    return request.method.upper() in MUTATING_METHODS or request.url.path in AUTH_PATHS


async def _record_request(request: Request, status_code: int) -> None:
    try:
        tenant_id, user_id = _identity_from_request(request)
        path = _audit_path(request)
        async with _async_session_factory() as db:
            await write_audit_log(
                db,
                AuditRecord(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=_action_for(request.method, path),
                    resource_type=_resource_type(path),
                    method=request.method.upper(),
                    path=path,
                    status_code=status_code,
                    client_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    request_id=request.headers.get("x-request-id"),
                    details={
                        "query_present": bool(request.url.query),
                        "query_parameter_count": len(request.query_params.multi_items()),
                        "audited_without_body": True,
                    },
                ),
            )
    except Exception:
        logger.warning("Failed to write audit log for %s %s", request.method, request.url.path)


def _identity_from_request(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    state_tenant_id = getattr(request.state, "audit_tenant_id", None)
    state_user_id = getattr(request.state, "audit_user_id", None)
    if state_tenant_id is not None:
        return uuid.UUID(str(state_tenant_id)), (
            uuid.UUID(str(state_user_id)) if state_user_id is not None else None
        )

    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None, None
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
        user_id = uuid.UUID(str(payload["user_id"]))
        return tenant_id, user_id
    except Exception:
        return None, None


def _audit_path(request: Request) -> str:
    """Use the matched route template, never attacker-controlled path parameters."""
    route_path = getattr(request.scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else "/unmatched"


def _action_for(method: str, path: str) -> str:
    return f"{method.upper()} {path.removeprefix('/api/v1/')}"


def _resource_type(path: str) -> str | None:
    parts = [part for part in path.removeprefix("/api/v1/").split("/") if part]
    return parts[0] if parts else None
