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


def upgrade() -> None:
    op.add_column(
        "workers",
        sa.Column("activation_requested_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
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
