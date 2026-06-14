"""Authoritative destructive-tool confirmation records."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid


class ToolConfirmation(Base, TimestampMixin):
    __tablename__ = "tool_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "tool_call_id",
            name="uq_tool_confirmations_conversation_call",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=gen_uuid,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    risk: Mapped[str] = mapped_column(String(50), nullable=False, default="destructive")
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
