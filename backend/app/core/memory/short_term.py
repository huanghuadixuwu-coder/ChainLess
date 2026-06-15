"""Tenant-scoped short-term conversation context backed by Redis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

MAX_SHORT_TERM_MESSAGES = 40


def short_term_context_key(tenant_id: str, conversation_id: str) -> str:
    """Return the tenant-scoped Redis key for one conversation context."""
    return f"chainless:short-context:{tenant_id}:{conversation_id}"


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def append_short_term_context(
    tenant_id: str,
    conversation_id: str,
    *,
    role: str,
    content: str | None,
    max_messages: int = MAX_SHORT_TERM_MESSAGES,
    ttl_seconds: int | None = None,
) -> None:
    """Append one message to the bounded Redis short-term context."""
    if content is None:
        return
    client = await _redis()
    key = short_term_context_key(tenant_id, conversation_id)
    try:
        await client.rpush(
            key,
            json.dumps(
                {
                    "role": role,
                    "content": content,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
        )
        await client.ltrim(key, -max_messages, -1)
        await client.expire(key, ttl_seconds or settings.short_term_context_ttl_seconds)
    finally:
        await client.aclose()


async def load_short_term_context(
    tenant_id: str,
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Load the current short-term context for a tenant conversation."""
    client = await _redis()
    try:
        rows = await client.lrange(short_term_context_key(tenant_id, conversation_id), 0, -1)
    finally:
        await client.aclose()
    messages: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = json.loads(row)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            messages.append(value)
    return messages


async def cleanup_short_term_context(tenant_id: str, conversation_id: str) -> int:
    """Delete one tenant-scoped short-term context key."""
    client = await _redis()
    try:
        return int(await client.delete(short_term_context_key(tenant_id, conversation_id)))
    finally:
        await client.aclose()
