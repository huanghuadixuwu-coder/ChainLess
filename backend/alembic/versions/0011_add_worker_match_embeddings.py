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


def _index_exists(index_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = :index_name
                LIMIT 1
                """
            ),
            {"index_name": index_name},
        )
        .scalar()
    )


def upgrade() -> None:
    if not _column_exists("worker_versions", "match_embedding"):
        op.add_column("worker_versions", sa.Column("match_embedding", Vector(1536), nullable=True))
    if not _index_exists("ix_worker_versions_match_embedding"):
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
