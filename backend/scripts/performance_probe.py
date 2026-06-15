#!/usr/bin/env python3
"""Measure final Code-as-Action performance gates with sandbox evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from html import unescape
from typing import Any

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from app.config import settings
from app.core.agent.code_executor import stream_code_as_action
from app.core.sandbox.manager import SandboxManager


class _NoChildGateway:
    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        yield {"type": "text", "content": "no child agents are used by this probe"}


def _extract_hackernews_top10(html: str) -> list[dict[str, str]]:
    rows = re.findall(
        r'<tr[^>]*class=["\'][^"\']*\bathing\b[^"\']*["\'][\s\S]*?<span class=["\']titleline["\']>\s*<a href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE,
    )
    top = []
    for url, title in rows[:10]:
        text = re.sub(r"<[^>]+>", "", title)
        top.append({"title": unescape(text).strip(), "url": unescape(url).strip()})
    return top


async def _fetch_hackernews_fixture(base_url: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        health = await client.get(f"{base_url.rstrip('/')}/api/v1/health")
        health.raise_for_status()
        response = await client.get("https://news.ycombinator.com/news")
        response.raise_for_status()
    top10 = _extract_hackernews_top10(response.text)
    if len(top10) != 10:
        raise RuntimeError(f"Expected 10 HackerNews rows, got {len(top10)}")
    return top10


async def _run_code(script: str, *, sandbox_manager: SandboxManager) -> dict[str, Any]:
    started = time.perf_counter()
    events = [
        event
        async for event in stream_code_as_action(
            script,
            sandbox_manager,
            gateway=_NoChildGateway(),
            tenant_id="performance-probe",
            parent_budget=100_000,
        )
    ]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    stdout = "".join(
        event.get("data", "")
        for event in events
        if event.get("type") == "sandbox_output" and event.get("stream") == "stdout"
    ).strip()
    phases = [
        event.get("phase")
        for event in events
        if event.get("type") == "sandbox" and event.get("phase")
    ]
    errors = [
        event.get("data", "")
        for event in events
        if event.get("type") == "sandbox_output" and event.get("stream") == "error"
    ]
    return {
        "elapsed_ms": elapsed_ms,
        "stdout": stdout,
        "phases": phases,
        "errors": errors,
        "event_count": len(events),
        "sandbox_evidence": {
            "allocated": "allocated" in phases,
            "completed": "completed" in phases,
            "deleted": "deleted" in phases,
        },
    }


def _hackernews_script(top10: list[dict[str, str]]) -> str:
    payload = json.dumps(top10, ensure_ascii=False)
    return f"""
import json

html_rows = {payload!r}
items = json.loads(html_rows)
assert len(items) == 10, len(items)
print(json.dumps({{"count": len(items), "titles": [item["title"] for item in items]}}, ensure_ascii=False, sort_keys=True))
""".strip()


def _fibonacci_script() -> str:
    return """
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

print(fibonacci(10))
""".strip()


async def run_probe(base_url: str, scenario: str, max_ms: int, measured_runs: int) -> dict[str, Any]:
    manager = SandboxManager(settings)
    try:
        if scenario == "fibonacci":
            run = await _run_code(_fibonacci_script(), sandbox_manager=manager)
            return {
                "ok": run["stdout"] == "55" and not run["errors"],
                "scenario": scenario,
                "expected_output": "55",
                "run": run,
            }

        if scenario != "hackernews-code-action":
            raise ValueError(f"Unsupported scenario: {scenario}")

        top10 = await _fetch_hackernews_fixture(base_url)
        script = _hackernews_script(top10)
        warmup = await _run_code(script, sandbox_manager=manager)
        measured = [
            await _run_code(script, sandbox_manager=manager)
            for _ in range(measured_runs)
        ]
        latencies = [run["elapsed_ms"] for run in measured]
        parsed = [json.loads(run["stdout"]) for run in measured if run["stdout"]]
        runs_ok = all(
            run["elapsed_ms"] < max_ms
            and not run["errors"]
            and run["sandbox_evidence"]["allocated"]
            and run["sandbox_evidence"]["completed"]
            and run["sandbox_evidence"]["deleted"]
            for run in measured
        )
        output_ok = all(item.get("count") == 10 for item in parsed) and len(parsed) == measured_runs
        return {
            "ok": runs_ok and output_ok,
            "scenario": scenario,
            "provider_model_recorded": "GLM-4.5 Air",
            "live_llm_provider_verified": False,
            "live_llm_provider_note": (
                "This probe measures HackerNews egress plus sandbox Code-as-Action "
                "execution; it does not call a live GLM API provider."
            ),
            "network_boundary": (
                "backend fetched HackerNews over egress; sandbox Code-as-Action parsed "
                "the captured top-10 payload under the default network-none sandbox policy"
            ),
            "max_ms": max_ms,
            "warmup": warmup,
            "measured_runs": measured,
            "latencies_ms": latencies,
            "p50_ms": round(statistics.median(latencies), 2) if latencies else None,
            "max_observed_ms": max(latencies) if latencies else None,
            "hackernews_count": len(top10),
            "sample_titles": [item["title"] for item in top10[:3]],
        }
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://chainless-nginx")
    parser.add_argument("--scenario", choices=["hackernews-code-action", "fibonacci"], default="hackernews-code-action")
    parser.add_argument("--max-ms", type=int, default=5000)
    parser.add_argument("--measured-runs", type=int, default=5)
    args = parser.parse_args()
    result = asyncio.run(
        run_probe(
            args.base_url.rstrip("/"),
            args.scenario,
            args.max_ms,
            args.measured_runs,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
