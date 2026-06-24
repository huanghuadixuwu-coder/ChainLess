"""ARQ-compatible acquisition analysis workers."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.acquisition.facade import process_pending_runtime_analysis


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def process_acquisition_analysis(
    ctx: dict[str, Any],
    tenant_id: str | None = None,
    user_id: str | None = None,
    limit: int = 10,
) -> dict[str, int]:
    """Claim and process pending acquisition analysis jobs from an ARQ worker."""

    _ = ctx
    from app.api.deps import _async_session_factory

    async with _async_session_factory() as db:
        try:
            processed = await process_pending_runtime_analysis(
                db,
                tenant_id=_uuid_or_none(tenant_id),
                user_id=_uuid_or_none(user_id),
                batch_limit=limit,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {
        "claimed": len(processed),
        "succeeded": sum(1 for job in processed if job.status == "succeeded"),
        "failed": sum(1 for job in processed if job.status == "failed"),
        "timed_out": sum(1 for job in processed if job.status == "timed_out"),
    }
