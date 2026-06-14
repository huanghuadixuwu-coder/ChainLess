"""Live local-Docker proof for W4 real sub-agent artifacts and cleanup."""

from __future__ import annotations

import os

import pytest

from app.core.sandbox.manager import SandboxManager
from scripts.run_eval_support import run_parallel_subagent_probe


@pytest.mark.live_docker
@pytest.mark.asyncio
async def test_w4_live_parallel_subagents_artifacts_logs_and_cleanup() -> None:
    if os.environ.get("CHAINLESS_LIVE_DOCKER") != "1":
        pytest.skip("set CHAINLESS_LIVE_DOCKER=1 inside backend-test-live")

    class LiveSettings:
        sandbox_proxy_url = os.environ["SANDBOX_PROXY_URL"]
        proxy_auth_token = os.environ["PROXY_AUTH_TOKEN"]
        sandbox_pool_min = 0
        sandbox_pool_max = 0

    manager = SandboxManager(LiveSettings())
    try:
        evidence = await run_parallel_subagent_probe(
            manager,
            tenant_id="w4-live-proof",
        )
    finally:
        await manager.close()

    assert evidence["passed"] is True, evidence
    assert evidence["max_parallel_children"] == 2
    assert len(evidence["artifacts"]) == 2
    assert evidence["checks"]["artifact_cleanup"] is True
    assert evidence["checks"]["run_cleanup"] is True
    assert evidence["checks"]["control_socket_cleanup"] is True
