#!/usr/bin/env python3
"""Delete only known QA conversation-title prefixes."""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from app.config import settings
from app.models.conversation import Conversation

QA_TITLE_PREFIXES = (
    "WS10 QA ",
    "W10 production boundary probe ",
    "sse-probe",
)


async def cleanup() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        result = await db.execute(
            delete(Conversation).where(
                or_(*(Conversation.title.like(f"{prefix}%") for prefix in QA_TITLE_PREFIXES))
            )
        )
        await db.commit()
        print(f"deleted_qa_conversations={result.rowcount or 0}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(cleanup())
