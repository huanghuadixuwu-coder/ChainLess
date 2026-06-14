"""Test script for the litellm-based LLMGateway.

Usage:
    docker-compose exec -T backend python test_llm_gateway.py

Expected output: streaming chunks from GLM-4.5 Air.
"""

import asyncio
import sys

from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.llm.gateway import LLMGateway
from app.models.tenant import Tenant


async def main():
    print("=== LLMGateway smoke test ===")
    gateway = LLMGateway()
    async with _async_session_factory() as db:
        tenant_id = str(
            (
                await db.execute(select(Tenant.id).where(Tenant.name == "default"))
            ).scalar_one()
        )
    config = await gateway.get_config(tenant_id, "default")
    print(f"API base: {config['api_base']}")
    print(f"Model:    {config['model']}")

    messages = [{"role": "user", "content": "Say hello in one word"}]

    print("\n--- Streaming response ---")
    chunk_count = 0
    async for chunk in gateway.chat_stream("default", messages, tenant_id=tenant_id):
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
