"""add authoritative tool confirmations

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk", sa.String(length=50), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "tool_call_id",
            name="uq_tool_confirmations_conversation_call",
        ),
    )
    op.create_index(
        op.f("ix_tool_confirmations_conversation_id"),
        "tool_confirmations",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tool_confirmations_conversation_id"), table_name="tool_confirmations")
    op.drop_table("tool_confirmations")
