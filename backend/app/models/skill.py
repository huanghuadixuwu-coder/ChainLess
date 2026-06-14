"""Passive skill metadata model."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid


class Skill(Base, TimestampMixin):
    """Tenant-owned passive skill metadata.

    The model intentionally stores metadata only. Runtime skill execution and
    code precipitation are out of scope for the W5 backend contract.
    """

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_skills_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=gen_uuid,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_terms: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=True,
    )
