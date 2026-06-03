"""ARQ background tasks for the memory system.

Jobs:
    compute_embedding — compute a pgvector embedding for a memory row.
"""


async def compute_embedding(ctx: dict, memory_id: str, content: str) -> None:
    """ARQ job: compute embedding and update the memory row.

    Uses the ORM to ensure pgvector Vector type serialization is correct.
    """
    from app.main import app_state
    from app.api.deps import _async_session_factory
    from sqlalchemy import update
    from app.models.memory import Memory

    gateway = app_state.llm_gateway
    embeddings = await gateway.embed("default", [content])

    async with _async_session_factory() as session:
        await session.execute(
            update(Memory)
            .where(Memory.id == memory_id)
            .values(embedding=embeddings[0])
        )
        await session.commit()


async def enqueue_embedding(memory_id: str, content: str) -> None:
    """Enqueue embedding computation to the ARQ worker.

    This is a non-blocking best-effort operation — failures are silently
    ignored so they don't disrupt the API response.
    """
    try:
        from arq import create_pool
        from app.config import settings

        redis = await create_pool(settings.redis_url)
        await redis.enqueue_job("compute_embedding", memory_id, content)
    except Exception:
        pass  # Will backfill later
