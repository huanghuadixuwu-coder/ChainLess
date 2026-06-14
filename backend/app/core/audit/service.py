"""Audit log write/read helpers."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.secrets import redact_sensitive_data
from app.models.audit_log import AuditLog


@dataclass(frozen=True)
class AuditRecord:
    action: str
    method: str
    path: str
    status_code: int
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    details: dict[str, Any] | None = None


SENSITIVE_DETAIL_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
}


def sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Remove secret-like values from audit metadata."""
    if not details:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in SENSITIVE_DETAIL_KEYS:
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return redact_sensitive_data(sanitized)


def audit_field_fingerprint(value: str | None, *, field: str) -> str | None:
    """Return bounded, domain-separated observability metadata for untrusted text."""
    if not value:
        return None
    bounded = value.encode("utf-8", errors="replace")[:4096]
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        b"chainless/audit-field/v1\0" + field.encode("ascii") + b"\0" + bounded,
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"hmac-sha256:{digest}"


async def write_audit_log(db: AsyncSession, record: AuditRecord) -> AuditLog:
    """Persist one audit record without storing request or response bodies."""
    row = AuditLog(
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        action=record.action,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        method=record.method,
        path=record.path,
        status_code=record.status_code,
        client_ip=record.client_ip,
        user_agent=audit_field_fingerprint(record.user_agent, field="user-agent"),
        request_id=audit_field_fingerprint(record.request_id, field="request-id"),
        details=sanitize_details(record.details),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_audit_logs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[AuditLog], int]:
    """Return tenant-scoped audit logs and total count."""
    filters = [AuditLog.tenant_id == tenant_id]
    total_q = select(func.count()).select_from(AuditLog).where(*filters)
    total = int((await db.execute(total_q)).scalar() or 0)
    rows_q = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(rows_q)).scalars().all())
    return rows, total
