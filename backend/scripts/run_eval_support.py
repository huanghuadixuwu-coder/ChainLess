"""Deterministic runtime probes used by spec-complete eval and live Docker tests."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.core.agent.code_executor import stream_code_as_action


class _ParallelProbeGateway:
    def __init__(self) -> None:
        self.started = 0
        self.active = 0
        self.max_active = 0
        self.both_started = asyncio.Event()
        self.intervals: list[tuple[float, float]] = []

    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        assert tools == []
        prompt = messages[-1]["content"]
        started_at = time.monotonic()
        self.started += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.started == 2:
            self.both_started.set()
        try:
            await asyncio.wait_for(self.both_started.wait(), timeout=5)
            await asyncio.sleep(0.05)
            yield {"type": "text", "content": f"probe-child:{prompt}"}
        finally:
            self.active -= 1
            self.intervals.append((started_at, time.monotonic()))


async def run_parallel_subagent_probe(sandbox_manager, *, tenant_id: str) -> dict:
    """Run two real parallel UDS child calls and return hard runtime evidence."""
    gateway = _ParallelProbeGateway()
    script = """
import concurrent.futures
import json

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [
        executor.submit(spawn_sub_agent, prompt, "spec-complete deterministic probe")
        for prompt in ("alpha", "beta")
    ]
    print(json.dumps([future.result() for future in futures], sort_keys=True))
""".strip()
    events = [
        event
        async for event in stream_code_as_action(
            script,
            sandbox_manager,
            gateway=gateway,
            tenant_id=tenant_id,
            parent_budget=20_000,
        )
    ]
    phases = [
        event["phase"]
        for event in events
        if event.get("type") == "sandbox" and event.get("phase")
    ]
    artifact_payloads = [
        json.loads(event["data"])
        for event in events
        if event.get("type") == "sandbox_output"
        and event.get("stream") == "artifact"
    ]
    stdout_events = [
        event["data"]
        for event in events
        if event.get("type") == "sandbox_output"
        and event.get("stream") == "stdout"
    ]
    parent_aggregation = _find_parent_aggregation(stdout_events)
    parent_run_id = next(
        event["container_id"]
        for event in events
        if event.get("type") == "sandbox" and event.get("phase") == "allocated"
    )
    artifact_paths = [artifact["artifact_path"] for artifact in artifact_payloads]
    outputs = sorted(artifact["output"] for artifact in artifact_payloads)
    statuses = sorted(artifact["status"] for artifact in artifact_payloads)
    control_root = Path("/run/chainless-control")
    checks = {
        "two_started": phases.count("sub_agent_started") == 2,
        "two_completed": phases.count("sub_agent_completed") == 2,
        "real_parallel_overlap": gateway.max_active == 2,
        "two_artifacts_observed": len(artifact_payloads) == 2,
        "aggregated_outputs": outputs == ["probe-child:alpha", "probe-child:beta"],
        "success_statuses": statuses == ["success", "success"],
        "parent_aggregated_two_results": sorted(
            result.get("output") for result in parent_aggregation
        )
        == ["probe-child:alpha", "probe-child:beta"],
        "artifact_cleanup": all(not Path(path).exists() for path in artifact_paths),
        "run_cleanup": not Path("/workspace/runs", parent_run_id).exists(),
        "control_socket_cleanup": not (
            control_root / parent_run_id / "subagent.sock"
        ).exists(),
        "parent_terminal": "completed" in phases and "deleted" in phases,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "parent_run_id": parent_run_id,
        "phases": phases,
        "artifacts": artifact_payloads,
        "artifact_paths": artifact_paths,
        "parent_aggregation": parent_aggregation,
        "max_parallel_children": gateway.max_active,
        "intervals": gateway.intervals,
    }


def _find_parent_aggregation(stdout_events: list[str]) -> list[dict]:
    for output in stdout_events:
        try:
            payload = json.loads(output)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, list)
            and len(payload) == 2
            and all(isinstance(item, dict) for item in payload)
        ):
            if all(
                item.get("ok") is True and isinstance(item.get("result"), dict)
                for item in payload
            ):
                return [item["result"] for item in payload]
            return payload
    return []
