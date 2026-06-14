"""add canonical provider and channel settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("api_base", sa.String(1000), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_llm_providers_tenant_name"),
    )
    op.create_index(op.f("ix_llm_providers_tenant_id"), "llm_providers", ["tenant_id"])
    op.create_index(
        "uq_llm_providers_one_default_per_tenant",
        "llm_providers",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "channel_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(80), nullable=False),
        sa.Column("public_config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "channel_type", name="uq_channel_configs_tenant_type"),
    )
    op.create_index(op.f("ix_channel_configurations_tenant_id"), "channel_configurations", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_channel_configurations_tenant_id"), table_name="channel_configurations")
    op.drop_table("channel_configurations")
    op.drop_index("uq_llm_providers_one_default_per_tenant", table_name="llm_providers")
    op.drop_index(op.f("ix_llm_providers_tenant_id"), table_name="llm_providers")
    op.drop_table("llm_providers")
