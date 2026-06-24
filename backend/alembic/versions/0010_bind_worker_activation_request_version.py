"""bind worker activation requests to versions

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table, "column_name": column},
        )
        .scalar()
    )


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT 1
                FROM pg_constraint constraint_row
                JOIN pg_class table_row
                  ON table_row.oid = constraint_row.conrelid
                WHERE table_row.relname = :table_name
                  AND constraint_row.conname = :constraint_name
                LIMIT 1
                """
            ),
            {"table_name": table, "constraint_name": name},
        )
        .scalar()
    )


def upgrade() -> None:
    if not _column_exists("workers", "activation_requested_version_id"):
        op.add_column(
            "workers",
            sa.Column("activation_requested_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _constraint_exists("workers", "fk_workers_activation_requested_version_id"):
        op.create_foreign_key(
            "fk_workers_activation_requested_version_id",
            "workers",
            "worker_versions",
            ["activation_requested_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_workers_activation_requested_version_id", "workers", type_="foreignkey")
    op.drop_column("workers", "activation_requested_version_id")
