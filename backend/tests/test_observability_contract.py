"""W8 observability metrics contract."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.core.observability import summarize_eval_outcomes
from app.core.ops import health
from app.api.v1 import system

pytestmark = pytest.mark.asyncio


async def test_metrics_include_w8_runtime_signals_without_prompt_or_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_health(sandbox_manager=None):
        return {
            "checks": {
                "db": {"status": "connected"},
                "redis": {"status": "connected"},
                "worker": {"status": "ok"},
                "sandbox": {"status": "ok", "pool_size": 2, "total_containers": 2},
            }
        }

    async def fake_proactive_summary():
        return {
            "total": 3,
            "blocked": 1,
            "delivery_failed": 1,
            "error": 0,
            "completed": 2,
        }

    monkeypatch.setattr(system, "collect_operational_health", fake_health)
    monkeypatch.setattr(system, "summarize_run_records", fake_proactive_summary)
    monkeypatch.setattr(
        system,
        "get_runtime_metric_snapshot",
        lambda: {
            "subagent_lifecycle_events": 7,
            "sse_disconnects": 2,
            "sse_errors": 1,
            "artifact_failures": 3,
            "artifact_quota_rejections": 4,
        },
    )
    monkeypatch.setattr(
        system,
        "summarize_eval_outcomes",
        lambda: {"pass": 12, "fail": 1, "error": 2},
    )

    response = await system.system_metrics(_current_user={"role": "admin"}, sandbox_manager=None)
    body = response.body.decode("utf-8")

    assert "chainless_proactive_blocked_tools_total 1" in body
    assert "chainless_proactive_delivery_failures_total 1" in body
    assert "chainless_subagent_lifecycle_events_total 7" in body
    assert "chainless_sse_disconnect_total 2" in body
    assert "chainless_sse_errors_total 1" in body
    assert "chainless_artifact_failures_total 3" in body
    assert "chainless_artifact_quota_rejections_total 4" in body
    assert 'chainless_eval_outcomes_total{status="pass"} 12' in body
    assert 'chainless_eval_outcomes_total{status="fail"} 1' in body
    assert 'chainless_eval_outcomes_total{status="error"} 2' in body
    assert "secret" not in body.lower()
    assert "prompt" not in body.lower()
    assert "webhook" not in body.lower()


async def test_eval_outcome_metrics_are_summarized_from_result_files(tmp_path) -> None:
    (tmp_path / "basic_results.json").write_text(
        json.dumps({"summary": {"pass": 2, "fail": 1, "error": 0}}),
        encoding="utf-8",
    )
    (tmp_path / "spec_complete_results.json").write_text(
        json.dumps({"summary": {"pass": 4, "fail": 0, "error": 1}}),
        encoding="utf-8",
    )
    (tmp_path / "ignored.txt").write_text("not json", encoding="utf-8")

    assert summarize_eval_outcomes(tmp_path) == {"pass": 6, "fail": 1, "error": 1}


async def test_operational_health_bounds_slow_sandbox_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowSandboxManager:
        pool_size = 4

        async def get_proxy_health(self):
            await asyncio.sleep(5)
            return {"pool_size": 4, "total_containers": 4}

    async def ok_db():
        return {"status": "connected"}

    async def ok_redis():
        return {"status": "connected"}

    async def ok_worker():
        return {"status": "ok"}

    monkeypatch.setattr(health, "_check_db", ok_db)
    monkeypatch.setattr(health, "_check_redis", ok_redis)
    monkeypatch.setattr(health, "_check_worker", ok_worker)

    started = time.perf_counter()
    result = await health.collect_operational_health(SlowSandboxManager())
    elapsed = time.perf_counter() - started

    assert elapsed < 1.5
    assert result["status"] == "degraded"
    assert result["checks"]["sandbox"]["status"] == "degraded"
    assert result["sandbox_pool"] == 4


async def test_db_health_uses_bounded_pool_acquire_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquire_timeouts: list[float] = []
    queries: list[str] = []

    class FakeConnection:
        async def execute(self, query: str):
            queries.append(query)

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self, *, timeout: float):
            acquire_timeouts.append(timeout)
            return FakeAcquire()

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(health, "_get_db_pool", fake_pool)

    assert await health._check_db() == {"status": "connected"}
    assert acquire_timeouts == [health.DB_HEALTH_BUDGET_SECONDS]
    assert queries == ["SELECT 1"]
