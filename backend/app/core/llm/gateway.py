import hashlib
import logging
import math
import re
import time
from typing import AsyncIterator

import litellm
from sqlalchemy import select

from app.core.secrets import decrypt_secret
from app.models.llm_provider import LLMProvider

logger = logging.getLogger(__name__)
_EMBEDDING_DIMENSIONS = 1536
_EMBEDDING_BACKOFF_SECONDS = 600


class LLMGateway:
    def __init__(self):
        self._embed_clients: dict[str, "AsyncOpenAI"] = {}
        self._embed_backoff_until: dict[str, float] = {}

    async def get_config(self, tenant_id: str, name: str) -> dict:
        """Resolve the tenant's provider from the canonical database owner."""
        from app.api.deps import _async_session_factory

        async with _async_session_factory() as db:
            query = select(LLMProvider).where(LLMProvider.tenant_id == tenant_id)
            if name == "default":
                query = query.where(LLMProvider.is_default.is_(True))
            else:
                query = query.where(LLMProvider.name == name)
            provider = (await db.execute(query)).scalar_one_or_none()
        if provider is None:
            raise ValueError("Configured LLM provider was not found")
        return {
            "name": provider.name,
            "model": f"openai/{provider.model}",
            "api_base": provider.api_base,
            "api_key": decrypt_secret(provider.encrypted_api_key),
            "embedding_model": provider.embedding_model or "embedding-3",
        }

    async def chat_stream(
        self,
        provider_name: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        tenant_id: str | None = None,
    ) -> AsyncIterator[dict]:
        if tenant_id is None:
            raise ValueError("Tenant scope is required for LLM provider resolution")
        cfg = await self.get_config(tenant_id, provider_name)
        kwargs = {
            "model": cfg["model"],
            "messages": messages,
            "api_base": cfg["api_base"],
            "api_key": cfg["api_key"],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools

        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield {"type": "text", "content": content}
            tool_calls = getattr(delta, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    function = getattr(tc, "function", None)
                    yield {
                        "type": "tool_call",
                        "index": getattr(tc, "index", 0) or 0,
                        "id": getattr(tc, "id", None) or "",
                        "name": getattr(function, "name", None) or "",
                        "arguments": getattr(function, "arguments", None) or "",
                    }

    async def embed(
        self, provider_name: str, texts: list[str], *, tenant_id: str | None = None
    ) -> list[list[float]]:
        if tenant_id is None:
            raise ValueError("Tenant scope is required for LLM provider resolution")
        cfg = await self.get_config(tenant_id, provider_name)
        from openai import AsyncOpenAI

        cache_key = f"{cfg['api_base']}|{cfg['api_key']}"
        if time.time() < self._embed_backoff_until.get(cache_key, 0):
            return self._local_embed(texts)

        try:
            if cache_key not in self._embed_clients:
                self._embed_clients[cache_key] = AsyncOpenAI(
                    base_url=cfg["api_base"],
                    api_key=cfg["api_key"],
                )
            client = self._embed_clients[cache_key]
            resp = await client.embeddings.create(
                model=cfg["embedding_model"],
                input=texts,
            )
            return [d.embedding for d in resp.data]
        except Exception:
            self._embed_backoff_until[cache_key] = (
                time.time() + _EMBEDDING_BACKOFF_SECONDS
            )
            logger.warning(
                "Embedding provider unavailable for '%s'; falling back to local embeddings",
                cfg["name"],
            )
            return self._local_embed(texts)

    def _local_embed(self, texts: list[str]) -> list[list[float]]:
        return [self._local_embed_one(text) for text in texts]

    def _local_embed_one(self, text: str) -> list[float]:
        vector = [0.0] * _EMBEDDING_DIMENSIONS
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            token_weight = 1.0 + min(len(token), 12) / 12.0
            for offset in range(0, 32, 4):
                chunk = digest[offset : offset + 4]
                index = int.from_bytes(chunk[:2], "big") % _EMBEDDING_DIMENSIONS
                sign = 1.0 if chunk[2] % 2 == 0 else -1.0
                magnitude = 0.5 + (chunk[3] / 255.0)
                vector[index] += sign * magnitude * token_weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())


async def get_llm_gateway() -> LLMGateway:
    """FastAPI dependency. Returns the configured gateway from app state."""
    from app.main import app_state

    return app_state.llm_gateway
