"""Tenant-scoped canonical LLM provider configuration."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, gen_uuid


class LLMProvider(Base, TimestampMixin):
    __tablename__ = "llm_providers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_llm_providers_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_base: Mapped[str] = mapped_column(String(1000), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
