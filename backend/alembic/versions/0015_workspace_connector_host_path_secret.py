"""Store encrypted workspace connector host path source.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_connectors",
        sa.Column("host_path_secret_ref", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_connectors", "host_path_secret_ref")
