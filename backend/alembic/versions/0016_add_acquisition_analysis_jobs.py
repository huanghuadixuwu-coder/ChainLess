"""Add durable acquisition analysis jobs.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition_analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'timed_out', 'skipped_duplicate')",
            name="ck_acquisition_analysis_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_acquisition_analysis_jobs_attempts_non_negative"),
        sa.CheckConstraint("octet_length(payload::text) <= 8192", name="ck_acquisition_analysis_jobs_payload_size"),
        sa.CheckConstraint(
            "octet_length(result_metadata::text) <= 8192",
            name="ck_acquisition_analysis_jobs_result_metadata_size",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 1024",
            name="ck_acquisition_analysis_jobs_error_message_size",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "source_run_id", name="uq_acquisition_analysis_jobs_run"),
    )
    op.create_index(
        "ix_acquisition_analysis_jobs_tenant_user_status",
        "acquisition_analysis_jobs",
        ["tenant_id", "user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_acquisition_analysis_jobs_tenant_user_source_run",
        "acquisition_analysis_jobs",
        ["tenant_id", "user_id", "source_run_id"],
        unique=False,
    )
    op.alter_column("acquisition_analysis_jobs", "status", server_default=None)
    op.alter_column("acquisition_analysis_jobs", "attempts", server_default=None)
    op.alter_column("acquisition_analysis_jobs", "payload", server_default=None)
    op.alter_column("acquisition_analysis_jobs", "result_metadata", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_acquisition_analysis_jobs_tenant_user_source_run", table_name="acquisition_analysis_jobs")
    op.drop_index("ix_acquisition_analysis_jobs_tenant_user_status", table_name="acquisition_analysis_jobs")
    op.drop_table("acquisition_analysis_jobs")
