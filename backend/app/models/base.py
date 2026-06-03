"""Base SQLAlchemy declarations: DeclarativeBase, TimestampMixin, gen_uuid."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> uuid.UUID:
    """Return a new UUID v4."""
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Mixin that adds created_at / updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
