"""add capability layer durable constraints

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "capability_candidates",
        "ck_capability_candidates_type",
        "candidate_type IN ('memory', 'skill', 'worker')",
    ),
    (
        "capability_candidates",
        "ck_capability_candidates_status",
        "status IN ('new', 'seen', 'accepted', 'edited_accepted', 'dismissed', 'snoozed', 'muted_pattern', 'merged', 'archived')",
    ),
    ("capability_candidates", "ck_capability_candidates_evidence_size", "octet_length(evidence::text) <= 8192"),
    ("capability_candidates", "ck_capability_candidates_payload_size", "octet_length(payload::text) <= 8192"),
    ("capability_candidates", "ck_capability_candidates_metadata_size", 'octet_length("metadata"::text) <= 8192'),
    (
        "capability_analysis_jobs",
        "ck_capability_analysis_jobs_status",
        "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped_duplicate')",
    ),
    ("capability_analysis_jobs", "ck_capability_analysis_jobs_payload_size", "octet_length(payload::text) <= 8192"),
    (
        "capability_analysis_jobs",
        "ck_capability_analysis_jobs_result_metadata_size",
        "octet_length(result_metadata::text) <= 8192",
    ),
    (
        "capability_analysis_jobs",
        "ck_capability_analysis_jobs_error_message_size",
        "error_message IS NULL OR char_length(error_message) <= 1024",
    ),
    ("workers", "ck_workers_status", "status IN ('draft', 'active', 'disabled', 'soft_deleted')"),
    ("workers", "ck_workers_trigger_size", "octet_length(trigger::text) <= 8192"),
    ("workers", "ck_workers_policy_size", "octet_length(policy::text) <= 8192"),
    ("workers", "ck_workers_activation_evidence_size", "octet_length(activation_evidence::text) <= 8192"),
    ("workers", "ck_workers_metadata_size", 'octet_length("metadata"::text) <= 8192'),
    (
        "worker_versions",
        "ck_worker_versions_status",
        "status IN ('draft', 'verified', 'active', 'archived', 'failed_verification')",
    ),
    ("worker_versions", "ck_worker_versions_definition_size", "octet_length(definition::text) <= 8192"),
    (
        "worker_versions",
        "ck_worker_versions_verification_plan_size",
        "octet_length(verification_plan::text) <= 8192",
    ),
    (
        "worker_versions",
        "ck_worker_versions_verification_evidence_size",
        "octet_length(verification_evidence::text) <= 8192",
    ),
    (
        "worker_runs",
        "ck_worker_runs_status",
        "status IN ('succeeded', 'failed', 'failed_fallback_succeeded', 'failed_fallback_failed', 'blocked_by_policy', 'cancelled', 'needs_user_confirmation')",
    ),
    ("worker_runs", "ck_worker_runs_input_payload_size", "octet_length(input_payload::text) <= 8192"),
    ("worker_runs", "ck_worker_runs_output_payload_size", "octet_length(output_payload::text) <= 8192"),
    (
        "worker_runs",
        "ck_worker_runs_confirmation_metadata_size",
        "octet_length(confirmation_metadata::text) <= 8192",
    ),
    (
        "worker_runs",
        "ck_worker_runs_error_message_size",
        "error_message IS NULL OR char_length(error_message) <= 1024",
    ),
    (
        "worker_match_feedback",
        "ck_worker_match_feedback_metadata_size",
        'octet_length("metadata"::text) <= 8192',
    ),
)


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.execute(sa.text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition}) NOT VALID"))


def downgrade() -> None:
    for table, name, _condition in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
