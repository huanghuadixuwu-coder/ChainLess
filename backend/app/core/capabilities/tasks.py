"""ARQ-compatible entrypoints for capability analysis jobs."""

from __future__ import annotations

from typing import Any

from app.core.capabilities.service import process_pending_capability_analysis


async def process_capability_analysis(
    ctx: dict[str, Any],
    tenant_id: str | None = None,
    user_id: str | None = None,
    limit: int = 10,
) -> dict[str, int]:
    """Claim and process pending capability-analysis jobs from an ARQ worker."""

    return await process_pending_capability_analysis(
        ctx,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=limit,
    )
