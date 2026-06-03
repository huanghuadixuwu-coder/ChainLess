#!/usr/bin/env python3
"""Seed the database with default data.

Idempotent — safe to run multiple times.  Creates:

- Default tenant  (name: "default")
- Admin user      (username: "admin", password: "admin123")
- Default agent   (name: "Chainless Assistant")
- Sample memory entries
"""

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the backend directory is on sys.path so that ``app`` can be imported.
# When running via ``python scripts/seed.py`` from the ``backend/`` directory
# the app package is importable via the current working directory.
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from app.config import settings  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.memory import Memory  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402

logger = logging.getLogger(__name__)


async def seed(db: AsyncSession | None = None) -> None:
    """Run the seeding logic.

    Accepts an optional *db* session for callers that already have one
    (e.g. from the FastAPI lifespan).  When *db* is ``None`` a fresh
    engine and session are created.
    """
    if db is not None:
        await _seed_inner(db)
        return

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory()  as session:
        await _seed_inner(session)
    await engine.dispose()


async def _seed_inner(db: AsyncSession) -> None:
    """Core seeding logic — all changes are committed together."""

    # ── Default tenant ──────────────────────────────────────────────
    result = await db.execute(select(Tenant).where(Tenant.name == "default"))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="default")
        db.add(tenant)
        await db.flush()
        logger.info("Created default tenant")
    else:
        logger.info("Default tenant already exists — skipped")

    # ── Admin user ──────────────────────────────────────────────────
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == "admin",
        )
    )
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = User(
            tenant_id=tenant.id,
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        db.add(admin)
        await db.flush()
        logger.info("Created admin user (admin / admin123)")
    else:
        logger.info("Admin user already exists — skipped")

    # ── Default agent ───────────────────────────────────────────────
    result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == tenant.id,
            Agent.name == "Chainless Assistant",
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        agent = Agent(
            tenant_id=tenant.id,
            name="Chainless Assistant",
            system_prompt=(
                "You are Chainless, an AI assistant with access to tools. "
                "You can write and execute Python code in a sandbox, "
                "read/write files, fetch web content, search the web, "
                "and execute shell commands."
            ),
            is_active=True,
        )
        db.add(agent)
        await db.flush()
        logger.info("Created default agent 'Chainless Assistant'")
    else:
        logger.info("Default agent already exists — skipped")

    # ── Sample memories ─────────────────────────────────────────────
    existing = await db.execute(
        select(Memory).where(
            Memory.tenant_id == tenant.id,
            Memory.name == "Welcome Memory",
        )
    )
    if existing.scalar_one_or_none() is None:
        sample_memories = [
            Memory(
                tenant_id=tenant.id,
                type="user",
                name="Welcome Memory",
                content=(
                    "Welcome to Chainless! This is your first memory. "
                    "Memories help the AI remember important context "
                    "across conversations."
                ),
                tags=["welcome", "introduction"],
            ),
            Memory(
                tenant_id=tenant.id,
                type="reference",
                name="System Capabilities",
                content=(
                    "Chainless supports: conversational AI, code execution "
                    "in a sandbox, memory with semantic search, web search, "
                    "file operations, and MCP tool integration."
                ),
                tags=["system", "capabilities"],
            ),
        ]
        for mem in sample_memories:
            db.add(mem)
        await db.flush()
        logger.info("Created sample memory entries")
    else:
        logger.info("Sample memory entries already exist — skipped")

    await db.commit()
    logger.info("Seed completed successfully")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(seed())
    logger.info("Done.")


if __name__ == "__main__":
    main()
