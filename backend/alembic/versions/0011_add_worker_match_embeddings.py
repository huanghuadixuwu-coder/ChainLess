"""add worker match embeddings

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("worker_versions", sa.Column("match_embedding", Vector(1536), nullable=True))
    op.execute(
        sa.text(
            """
            CREATE INDEX ix_worker_versions_match_embedding
            ON worker_versions
            USING ivfflat (match_embedding vector_cosine_ops)
            WITH (lists = 100)
            WHERE match_embedding IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_worker_versions_match_embedding", table_name="worker_versions")
    op.drop_column("worker_versions", "match_embedding")
