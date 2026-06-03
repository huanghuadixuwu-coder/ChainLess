"""ARQ background tasks for the memory system.

Jobs:
    compute_embedding — compute a pgvector embedding for a memory row.
"""


async def compute_embedding(ctx: dict, memory_id: str, content: str) -> None:
    """ARQ job: compute embedding and update the memory row.

    Called asynchronously by the ARQ worker after a memory is created.
    """
    from app.main import app_state
    from app.api.deps import engine
    from sqlalchemy import text

    gateway = app_state.llm_gateway
    embeddings = await gateway.embed("default", [content])

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE memories SET embedding = :emb WHERE id = CAST(:id AS uuid)"
            ),
            {"emb": embeddings[0], "id": memory_id},
        )


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
