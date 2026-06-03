"""Test script for the litellm-based LLMGateway.

Usage:
    docker-compose exec -T backend python test_llm_gateway.py

Expected output: streaming chunks from GLM-4.5 Air.
"""

import asyncio
import sys

from app.config import settings
from app.core.llm.gateway import LLMGateway


async def main():
    print("=== LLMGateway smoke test ===")
    print(f"API base: {settings.default_llm_api_base}")
    print(f"Model:    {settings.default_llm_model}")

    gateway = LLMGateway()
    gateway.register(
        "default",
        settings.default_llm_api_base,
        settings.glm_api_key,
        settings.default_llm_model,
        settings.embedding_model,
    )

    messages = [{"role": "user", "content": "Say hello in one word"}]

    print("\n--- Streaming response ---")
    chunk_count = 0
    async for chunk in gateway.chat_stream("default", messages):
        if chunk["type"] == "text":
            print(chunk["content"], end="", flush=True)
            chunk_count += 1
        elif chunk["type"] == "tool_call":
            print(f"\n[TOOL_CALL id={chunk['id']} name={chunk['name']}]")

    print()
    print(f"\n--- Received {chunk_count} text chunks ---")

    if chunk_count > 0:
        print("\nSUCCESS: Streaming response received from GLM-4.5 Air")
    else:
        print("\nFAILURE: No streaming chunks received")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
