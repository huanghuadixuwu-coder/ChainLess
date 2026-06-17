"""add capability candidates and worker owners

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "skills",
        sa.Column("scope", sa.String(length=40), server_default="shared_legacy", nullable=False),
    )
    op.create_foreign_key(
        "fk_skills_user_id_users",
        "skills",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_skills_private_requires_user",
        "skills",
        "scope != 'private' OR user_id IS NOT NULL",
    )
    op.drop_constraint("uq_skills_tenant_name", "skills", type_="unique")
    op.create_index(op.f("ix_skills_user_id"), "skills", ["user_id"], unique=False)
    op.create_index(
        "uq_skills_private_scope_name",
        "skills",
        ["tenant_id", "user_id", "scope", "name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_skills_shared_scope_name",
        "skills",
        ["tenant_id", "scope", "name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )

    op.create_table(
        "workers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("trigger", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activation_token", sa.String(length=128), nullable=True),
        sa.Column("activation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activation_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activation_evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("soft_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["activation_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "name", name="uq_workers_user_name"),
    )
    op.create_index("ix_workers_tenant_user_status", "workers", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index(
        "ix_workers_tenant_user_enabled_soft_deleted",
        "workers",
        ["tenant_id", "user_id", "enabled", "soft_deleted_at"],
        unique=False,
    )

    op.create_table(
        "worker_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("verification_plan", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("verification_evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", "version", name="uq_worker_versions_worker_version"),
    )
    op.create_index(
        "ix_worker_versions_tenant_user_status",
        "worker_versions",
        ["tenant_id", "user_id", "status"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_workers_active_version_id",
        "workers",
        "worker_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "capability_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="new", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("source_run_id", sa.String(length=255), nullable=True),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column("source_message_id", sa.String(length=255), nullable=True),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("merge_target_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("merge_reason", sa.Text(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mute_pattern", sa.String(length=255), nullable=True),
        sa.Column("muted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merge_target_candidate_id"], ["capability_candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capability_candidates_tenant_user_status", "capability_candidates", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_capability_candidates_tenant_user_dedupe", "capability_candidates", ["tenant_id", "user_id", "dedupe_key"], unique=False)
    op.create_index("ix_capability_candidates_tenant_user_source_run", "capability_candidates", ["tenant_id", "user_id", "source_run_id"], unique=False)

    op.create_table(
        "capability_analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "source_run_id", name="uq_capability_analysis_jobs_run"),
    )
    op.create_index("ix_capability_analysis_jobs_tenant_user_status", "capability_analysis_jobs", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_capability_analysis_jobs_tenant_user_source_run", "capability_analysis_jobs", ["tenant_id", "user_id", "source_run_id"], unique=False)

    op.create_table(
        "worker_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_run_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmation_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["worker_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_runs_tenant_user_status", "worker_runs", ["tenant_id", "user_id", "status"], unique=False)
    op.create_index("ix_worker_runs_tenant_user_source_run", "worker_runs", ["tenant_id", "user_id", "source_run_id"], unique=False)

    op.create_table(
        "worker_match_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", sa.String(length=255), nullable=True),
        sa.Column("feedback", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_match_feedback_tenant_user_worker", "worker_match_feedback", ["tenant_id", "user_id", "worker_id"], unique=False)


def downgrade() -> None:
    # Scoped Skill rows can validly contain duplicate Skill names within a
    # tenant. Downgrading to the legacy uq_skills_tenant_name shape would lose
    # scope/user_id and then fail late, so preflight and stop before data-shape
    # changes when duplicates would violate the old uniqueness contract.
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT tenant_id, name, count(*) AS row_count
            FROM skills
            GROUP BY tenant_id, name
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade capability layer: duplicate Skill names exist "
            "within a tenant and would violate uq_skills_tenant_name after "
            "dropping scope/user_id."
        )

    op.drop_index("ix_worker_match_feedback_tenant_user_worker", table_name="worker_match_feedback")
    op.drop_table("worker_match_feedback")
    op.drop_index("ix_worker_runs_tenant_user_source_run", table_name="worker_runs")
    op.drop_index("ix_worker_runs_tenant_user_status", table_name="worker_runs")
    op.drop_table("worker_runs")
    op.drop_index("ix_capability_analysis_jobs_tenant_user_source_run", table_name="capability_analysis_jobs")
    op.drop_index("ix_capability_analysis_jobs_tenant_user_status", table_name="capability_analysis_jobs")
    op.drop_table("capability_analysis_jobs")
    op.drop_index("ix_capability_candidates_tenant_user_source_run", table_name="capability_candidates")
    op.drop_index("ix_capability_candidates_tenant_user_dedupe", table_name="capability_candidates")
    op.drop_index("ix_capability_candidates_tenant_user_status", table_name="capability_candidates")
    op.drop_table("capability_candidates")
    op.drop_constraint("fk_workers_active_version_id", "workers", type_="foreignkey")
    op.drop_index("ix_worker_versions_tenant_user_status", table_name="worker_versions")
    op.drop_table("worker_versions")
    op.drop_index("ix_workers_tenant_user_enabled_soft_deleted", table_name="workers")
    op.drop_index("ix_workers_tenant_user_status", table_name="workers")
    op.drop_table("workers")
    op.drop_index("uq_skills_shared_scope_name", table_name="skills")
    op.drop_index("uq_skills_private_scope_name", table_name="skills")
    op.drop_index(op.f("ix_skills_user_id"), table_name="skills")
    op.drop_constraint("ck_skills_private_requires_user", "skills", type_="check")
    op.drop_constraint("fk_skills_user_id_users", "skills", type_="foreignkey")
    op.drop_column("skills", "scope")
    op.drop_column("skills", "user_id")
    op.create_unique_constraint("uq_skills_tenant_name", "skills", ["tenant_id", "name"])
