"""Tenant model."""

import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, gen_uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=gen_uuid,
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict, nullable=True)

    # relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")  # noqa: F821
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="tenant", cascade="all, delete-orphan")  # noqa: F821
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="tenant", cascade="all, delete-orphan")  # noqa: F821
    memories: Mapped[list["Memory"]] = relationship("Memory", back_populates="tenant", cascade="all, delete-orphan")  # noqa: F821
