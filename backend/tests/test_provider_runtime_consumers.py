"""Runtime consumers must pass trusted tenant scope to the DB-backed provider."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.core.memory import persistent
from app.main import app_state
from app.services.conversation_stream_service import run_agent_stream

pytestmark = pytest.mark.asyncio


class CapturingGateway:
    def __init__(self) -> None:
        self.chat_tenants: list[str | None] = []
        self.embed_tenants: list[str | None] = []

    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        self.chat_tenants.append(tenant_id)
        yield {"type": "text", "content": "runtime-ok"}

    async def embed(self, provider, texts, *, tenant_id=None):
        self.embed_tenants.append(tenant_id)
        return [[0.0] * 1536 for _ in texts]


async def test_chat_and_memory_consumers_pass_tenant_scope(monkeypatch) -> None:
    gateway = CapturingGateway()
    queue: asyncio.Queue = asyncio.Queue()
    tenant_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(app_state, "llm_gateway", gateway)

    await run_agent_stream(
        gateway,
        object(),
        [{"role": "user", "content": "hi"}],
        queue,
        tenant_id,
        "default",
    )
    embedding = await persistent._compute_embedding_best_effort(tenant_id, "remember")

    assert gateway.chat_tenants == [tenant_id]
    assert gateway.embed_tenants == [tenant_id]
    assert embedding is not None


async def test_eval_consumer_passes_tenant_scope() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run-eval.py"
    spec = importlib.util.spec_from_file_location("chainless_run_eval", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    gateway = CapturingGateway()
    tenant_id = "22222222-2222-2222-2222-222222222222"

    result = await module.run_single_task(
        gateway,
        object(),
        {
            "id": "provider-owner",
            "prompt": "prove tenant scope",
            "pass_criteria": "output_match",
            "expected_output_contains": "runtime-ok",
        },
        tenant_id,
        use_judge=False,
    )

    assert result["passed"] is True
    assert gateway.chat_tenants == [tenant_id]
