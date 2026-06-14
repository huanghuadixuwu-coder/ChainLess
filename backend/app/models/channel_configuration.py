"""Tenant-scoped canonical delivery channel configuration."""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid


class ChannelConfiguration(Base, TimestampMixin):
    __tablename__ = "channel_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel_type", name="uq_channel_configs_tenant_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(80), nullable=False)
    public_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_secrets: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
