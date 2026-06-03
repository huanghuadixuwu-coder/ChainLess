from typing import AsyncIterator
import litellm


class LLMGateway:
    def __init__(self):
        self._providers: dict[str, dict] = {}

    def register(self, name: str, api_base: str, api_key: str, model: str,
                 embedding_model: str | None = None):
        self._providers[name] = {
            "model": f"openai/{model}",  # litellm provider/model format
            "api_base": api_base,
            "api_key": api_key,
            "embedding_model": embedding_model or "text-embedding-3-small",
        }

    def get_config(self, name: str) -> dict:
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        return self._providers[name]

    async def chat_stream(self, provider_name: str, messages: list[dict],
                          tools: list[dict] | None = None,
                          max_tokens: int = 4096) -> AsyncIterator[dict]:
        cfg = self.get_config(provider_name)
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
            if delta.content:
                yield {"type": "text", "content": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield {"type": "tool_call", "id": tc.id, "name": tc.function.name,
                           "arguments": tc.function.arguments}

    async def embed(self, provider_name: str, texts: list[str]) -> list[list[float]]:
        cfg = self.get_config(provider_name)
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=cfg["api_base"], api_key=cfg["api_key"])
        resp = await client.embeddings.create(model=cfg["embedding_model"], input=texts)
        return [d.embedding for d in resp.data]


async def get_llm_gateway() -> LLMGateway:
    """FastAPI dependency. Returns the configured gateway from app state."""
    from app.main import app_state
    return app_state.llm_gateway
