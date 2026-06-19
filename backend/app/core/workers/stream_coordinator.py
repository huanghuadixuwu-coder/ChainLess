"""Worker stream coordination for normal chat runs."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.api.deps import _async_session_factory
from app.core.capabilities.orchestration import evaluate_stream_worker_policy
from app.core.capabilities.retrieval import CapabilityContext, CapabilityWorkerMatch
from app.core.llm.gateway import LLMGateway
from app.core.sandbox.manager import SandboxManager
from app.core.workers.runtime import execute_worker_run
from app.models.worker import Worker, WorkerVersion

PublicEventMapper = Callable[[dict], tuple[str, dict] | None]


async def maybe_execute_worker_for_stream(
    *,
    gateway: LLMGateway,
    sandbox_manager: SandboxManager,
    provider: str,
    messages: list[dict],
    queue: asyncio.Queue,
    matched_request: str,
    tenant_id: str,
    user_id: str,
    source_run_id: str | None,
    tools: list[dict],
    capability_context: CapabilityContext | None,
    public_event_mapper: PublicEventMapper,
) -> bool:
    input_payload = _worker_input_payload(matched_request)

    async with _async_session_factory() as worker_db:
        decisions = list(capability_context.workers if capability_context else [])
        selected = _selected_worker_decision(decisions)
        if selected is None:
            return False

        worker = await worker_db.get(Worker, selected.worker_id)
        version = await worker_db.get(WorkerVersion, selected.version_id)
        if worker is None or version is None:
            return False

        if selected.decision == "needs_confirmation":
            await queue.put(
                (
                    "worker_notice",
                    _worker_selection_notice(
                        worker=worker,
                        decision=selected,
                        status="needs_confirmation",
                        message=(
                            f"Worker '{worker.name}' matched this request but requires confirmation; "
                            "continuing with the normal Agent path."
                        ),
                    ),
                )
            )
            return False

        policy = evaluate_stream_worker_policy(worker, version, input_payload=input_payload)
        if policy.action == "confirm":
            await queue.put(
                (
                    "worker_notice",
                    _worker_selection_notice(
                        worker=worker,
                        decision=selected,
                        status="needs_confirmation",
                        message=(
                            f"Worker '{worker.name}' requires confirmation before execution; "
                            "continuing with the normal Agent path."
                        ),
                        reason=policy.reason,
                    ),
                )
            )
            return False
        if policy.action != "allow":
            return False

        await queue.put(
            (
                "worker_notice",
                _worker_selection_notice(
                    worker=worker,
                    decision=selected,
                    status="started",
                    message=f"Worker '{worker.name}' matched this request and is running.",
                ),
            )
        )
        result = await execute_worker_run(
            worker_db,
            gateway=gateway,
            sandbox_manager=sandbox_manager,
            provider=provider,
            worker=worker,
            version=version,
            messages=messages,
            input_payload=input_payload,
            matched_request=matched_request,
            match_score=selected.score,
            source_run_id=source_run_id,
            tools=tools,
        )

    for event in result.get("events", []):
        mapped = public_event_mapper(event)
        if mapped is not None:
            await queue.put(mapped)
    return True


def _worker_input_payload(request: str) -> dict[str, str]:
    return {"request": request}


def _selected_worker_decision(
    decisions: list[CapabilityWorkerMatch],
) -> CapabilityWorkerMatch | None:
    for decision in decisions:
        if decision.decision in {"auto_notice", "needs_confirmation"}:
            return decision
    return None


def _worker_selection_notice(
    *,
    worker: Worker,
    decision: CapabilityWorkerMatch,
    status: str,
    message: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "worker_id": str(decision.worker_id),
        "version_id": str(decision.version_id),
        "worker_name": worker.name,
        "status": status,
        "decision": decision.decision,
        "score": decision.score,
        "semantic_score": decision.semantic_score,
        "keyword_score": decision.keyword_score,
        "reason": reason or "; ".join(decision.reasons),
        "message": message,
    }
