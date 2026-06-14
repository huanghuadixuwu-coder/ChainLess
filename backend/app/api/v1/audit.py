"""Admin audit log API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.core.audit.service import list_audit_logs
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/")
async def list_audit(
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """List tenant-scoped audit records for tenant administrators."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    effective_limit = max(1, min(limit, 100))
    effective_offset = max(0, offset)
    rows, total = await list_audit_logs(
        db,
        tenant_id=tenant_id,
        limit=effective_limit,
        offset=effective_offset,
    )
    return paginated_response(
        [_serialize(row) for row in rows],
        total=total,
        limit=effective_limit,
        offset=effective_offset,
        request=request,
    )


def _serialize(row: AuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "user_id": str(row.user_id) if row.user_id else None,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "method": row.method,
        "path": row.path,
        "status_code": row.status_code,
        "client_ip": row.client_ip,
        "user_agent": row.user_agent,
        "request_id": row.request_id,
        "details": row.details or {},
        "created_at": row.created_at.isoformat(),
    }
