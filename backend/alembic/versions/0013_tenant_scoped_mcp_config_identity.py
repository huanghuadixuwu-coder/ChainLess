"""tenant scoped mcp config identity

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MCP_TENANT_NAME_ENABLED_INDEX = "uq_mcp_server_configurations_tenant_name_enabled"


def _dedupe_enabled_mcp_configurations(bind) -> None:
    """Keep one enabled tenant/name MCP config before adding the unique index."""
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY tenant_id, name
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS row_number
                FROM mcp_server_configurations
                WHERE enabled IS TRUE
            )
            UPDATE mcp_server_configurations AS config
            SET
                enabled = FALSE,
                disabled_at = now(),
                updated_at = now()
            FROM ranked
            WHERE config.id = ranked.id
              AND ranked.row_number > 1
            """
        )
    )


def upgrade() -> None:
    _dedupe_enabled_mcp_configurations(op.get_bind())
    op.create_index(
        MCP_TENANT_NAME_ENABLED_INDEX,
        "mcp_server_configurations",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index(
        MCP_TENANT_NAME_ENABLED_INDEX,
        table_name="mcp_server_configurations",
    )
