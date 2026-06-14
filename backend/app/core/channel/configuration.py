"""Runtime resolution for tenant-scoped delivery channel configuration."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select

from app.core.secrets import decrypt_secret
from app.models.channel_configuration import ChannelConfiguration


class ChannelConfigurationError(ValueError):
    """Raised without exposing channel secret material."""


async def resolve_channel_configuration(tenant_id: str, channel_type: str) -> dict:
    """Resolve an enabled channel from the canonical PostgreSQL owner."""
    from app.api.deps import _async_session_factory

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(ChannelConfiguration).where(
                    ChannelConfiguration.tenant_id == UUID(tenant_id),
                    ChannelConfiguration.channel_type == channel_type,
                    ChannelConfiguration.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise ChannelConfigurationError("Enabled channel configuration was not found")
    try:
        secrets = json.loads(decrypt_secret(row.encrypted_secrets))
    except (TypeError, ValueError) as exc:
        raise ChannelConfigurationError("Channel configuration could not be resolved") from exc
    if not isinstance(secrets, dict):
        raise ChannelConfigurationError("Channel configuration could not be resolved")
    return {
        "channel_type": row.channel_type,
        "public_config": dict(row.public_config or {}),
        "secrets": secrets,
    }
