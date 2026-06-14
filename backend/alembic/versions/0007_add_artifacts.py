"""add conversation artifacts

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("tool_call_id", sa.String(length=255), nullable=True),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("workspace_path", sa.String(length=2000), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_bytes_stored", sa.Integer(), nullable=False),
        sa.Column("diff_bytes_stored", sa.Integer(), nullable=False),
        sa.Column("content_path", sa.String(length=2000), nullable=True),
        sa.Column("diff_path", sa.String(length=2000), nullable=True),
        sa.Column("before_sha256", sa.String(length=64), nullable=True),
        sa.Column("after_sha256", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_conversation_id"), "artifacts", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_artifacts_expires_at"), "artifacts", ["expires_at"], unique=False)
    op.create_index(op.f("ix_artifacts_run_id"), "artifacts", ["run_id"], unique=False)
    op.create_index(op.f("ix_artifacts_tenant_id"), "artifacts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_artifacts_tool_call_id"), "artifacts", ["tool_call_id"], unique=False)
    op.create_index(op.f("ix_artifacts_user_id"), "artifacts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_artifacts_user_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_tool_call_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_tenant_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_run_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_expires_at"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_conversation_id"), table_name="artifacts")
    op.drop_table("artifacts")
