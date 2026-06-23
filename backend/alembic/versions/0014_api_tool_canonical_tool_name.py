"""Persist canonical API tool names.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-23
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _api_tool_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_") or "tool"
    return f"api__{slug}"[:120]


def upgrade() -> None:
    op.drop_constraint("ck_api_tool_configurations_method", "api_tool_configurations", type_="check")
    op.create_check_constraint(
        "ck_api_tool_configurations_method",
        "api_tool_configurations",
        "method IN ('GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE')",
    )
    op.add_column("api_tool_configurations", sa.Column("tool_name", sa.String(length=120), nullable=True))
    conn = op.get_bind()
    rows = list(
        conn.execute(
            sa.text(
                "SELECT id, tenant_id, user_id, name "
                "FROM api_tool_configurations "
                "ORDER BY tenant_id, user_id, created_at, id"
            )
        ).mappings()
    )
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        base = _api_tool_name(str(row["name"]))
        tool_name = base
        key_prefix = (str(row["tenant_id"]), str(row["user_id"]))
        suffix = 1
        while (*key_prefix, tool_name) in seen:
            suffix_token = f"_{suffix}"
            tool_name = f"{base[: 120 - len(suffix_token)]}{suffix_token}"
            suffix += 1
        seen.add((*key_prefix, tool_name))
        conn.execute(
            sa.text("UPDATE api_tool_configurations SET tool_name = :tool_name WHERE id = :id"),
            {"tool_name": tool_name, "id": row["id"]},
        )

    op.alter_column("api_tool_configurations", "tool_name", nullable=False)
    op.create_unique_constraint(
        "uq_api_tool_configurations_tenant_user_tool_name",
        "api_tool_configurations",
        ["tenant_id", "user_id", "tool_name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_api_tool_configurations_tenant_user_tool_name",
        "api_tool_configurations",
        type_="unique",
    )
    op.drop_column("api_tool_configurations", "tool_name")
    op.drop_constraint("ck_api_tool_configurations_method", "api_tool_configurations", type_="check")
    op.create_check_constraint(
        "ck_api_tool_configurations_method",
        "api_tool_configurations",
        "method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
    )
