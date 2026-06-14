"""Conversation-scoped file artifact metadata."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, gen_uuid


class Artifact(Base, TimestampMixin):
    """Tenant-owned artifact metadata with bounded content stored on disk."""

    __tablename__ = "artifacts"

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
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, default="file")
    operation: Mapped[str] = mapped_column(String(50), nullable=False, default="write")
    workspace_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="available")
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_bytes_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diff_bytes_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_path: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    diff_path: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    conversation: Mapped["Conversation"] = relationship("Conversation")  # noqa: F821
