#!/usr/bin/env python3
"""Prove migrations plus idempotent seed produce a login-ready database."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.agent import Agent
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import verify_password
from scripts.seed import seed


def migrate() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


async def probe() -> None:
    await seed()
    await seed()

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.name == "default"))
        ).scalar_one()
        admin = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.username == "admin",
                    User.role == "admin",
                )
            )
        ).scalar_one()
        agent_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Agent)
                    .where(Agent.tenant_id == tenant.id, Agent.name == "Chainless Assistant")
                )
            ).scalar()
            or 0
        )
        if not verify_password(settings.bootstrap_admin_password, admin.password_hash):
            raise RuntimeError("Seeded admin credentials are not login-ready")
        if agent_count != 1:
            raise RuntimeError(f"Expected one default agent after idempotent seed, got {agent_count}")
    await engine.dispose()
    print('{"ok": true, "migrations": "head", "seed": "idempotent", "login_ready": true}')


if __name__ == "__main__":
    migrate()
    asyncio.run(probe())
