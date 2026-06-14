"""Tenant-scoped tool activation and risk override configuration."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid


class ToolConfiguration(Base, TimestampMixin):
    __tablename__ = "tool_configurations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_tool_configurations_tenant_name",
        ),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_type: Mapped[str] = mapped_column(String(50), nullable=False, default="builtin")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    risk_override: Mapped[str | None] = mapped_column(String(50), nullable=True)
