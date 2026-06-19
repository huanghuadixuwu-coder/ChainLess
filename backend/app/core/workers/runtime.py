"""Executable Worker runtime wrapper around the existing Agent engine."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.engine import run_agent
from app.core.capabilities.bounds import validate_bounded_json
from app.core.capabilities.hooks import emit_capability_hook
from app.core.capabilities.policy import (
    allowed_tools_for,
    evaluate_worker_policy,
    pack_confirmation_args,
    risk_for,
    worker_context_for_confirmation,
)
from app.models.capability import CapabilityCandidate
from app.models.worker import Worker, WorkerRun, WorkerVersion

DEFAULT_MAX_WORKER_DEPTH = 2
MAX_CAPTURED_EVENTS = 40
TERMINAL_EVENT_TYPES = {"done", "error"}


async def execute_worker_run(
    db: AsyncSession,
    *,
    gateway: Any,
    sandbox_manager: Any,
    provider: str,
    worker: Worker,
    version: WorkerVersion | None = None,
    messages: list[dict[str, Any]],
    input_payload: dict[str, Any],
    matched_request: str,
    match_score: float,
    source_run_id: str | None = None,
    worker_context: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    fallback_on_failure: bool = True,
) -> dict[str, Any]:
    """Run an activated Worker through the normal Agent runtime."""

    if version is None and worker.active_version_id is not None:
        version = await db.get(WorkerVersion, worker.active_version_id)

    await emit_capability_hook(
        "before_worker_run",
        {
            "worker_id": str(worker.id),
            "worker_version_id": str(version.id) if version is not None else None,
            "source_run_id": source_run_id,
            "match_score": float(match_score),
        },
    )

    blocked_reason = _recursion_block_reason(worker, worker_context)
    if blocked_reason is not None:
        result = await _record_blocked_run(
            db,
            worker=worker,
            version=version,
            input_payload=input_payload,
            matched_request=matched_request,
            match_score=match_score,
            source_run_id=source_run_id,
            reason=blocked_reason,
        )
        await _emit_after_worker_run(worker=worker, result=result, policy_action="block")
        return result

    policy = evaluate_worker_policy(worker, version, input_payload=input_payload)
    if policy.action == "block":
        result = await _record_blocked_run(
            db,
            worker=worker,
            version=version,
            input_payload=input_payload,
            matched_request=matched_request,
            match_score=match_score,
            source_run_id=source_run_id,
            reason=policy.reason,
        )
        await _emit_after_worker_run(worker=worker, result=result, policy_action="block")
        return result
    if policy.action == "confirm":
        result = await _record_blocked_run(
            db,
            worker=worker,
            version=version,
            input_payload=input_payload,
            matched_request=matched_request,
            match_score=match_score,
            source_run_id=source_run_id,
            reason=policy.reason,
            status="needs_user_confirmation",
        )
        await _emit_after_worker_run(worker=worker, result=result, policy_action="confirm")
        return result

    allowed_tool_names = sorted(allowed_tools_for(worker, version))
    run = WorkerRun(
        tenant_id=worker.tenant_id,
        user_id=worker.user_id,
        worker_id=worker.id,
        version_id=version.id if version is not None else None,
        source_run_id=source_run_id,
        status="blocked_by_policy",
        input_payload=validate_bounded_json(
            {
                "input": input_payload,
                "matched_request": matched_request,
                "match_score": float(match_score),
                "worker_id": str(worker.id),
                "version_id": str(version.id) if version is not None else None,
            },
            field="input_payload",
        ),
        output_payload={},
        confirmation_metadata=validate_bounded_json(
            {
                "allowed_tool_names": allowed_tool_names,
                "risk_decision": risk_for(worker, version),
                "policy_action": policy.action,
                "recursion": _next_worker_context(
                    worker,
                    version,
                    None,
                    worker_context,
                    allowed_tool_names,
                ),
            },
            field="confirmation_metadata",
        ),
    )
    db.add(run)
    await db.flush()

    runtime_context = _next_worker_context(worker, version, run.id, worker_context, allowed_tool_names)
    wrapped_messages = _worker_messages(worker, version, messages, input_payload=input_payload)
    events, error = await _capture_agent_events(
        gateway=gateway,
        sandbox_manager=sandbox_manager,
        provider=provider,
        messages=wrapped_messages,
        tools=tools,
        tenant_id=str(worker.tenant_id),
        user_id=str(worker.user_id),
        run_id=str(run.id),
        worker_context=runtime_context,
    )
    fallback = {"attempted": False, "status": None, "reason": None}
    status, error_code, error_message = _status_from_events(events, error)

    if status == "failed" and fallback_on_failure:
        fallback["attempted"] = True
        worker_failure_notice = _worker_fallback_notice(
            worker=worker,
            run_id=run.id,
            error_code=error_code,
            error_message=error_message,
        )
        fallback_events, fallback_error = await _capture_agent_events(
            gateway=gateway,
            sandbox_manager=sandbox_manager,
            provider=provider,
            messages=list(messages),
            tools=tools,
            tenant_id=str(worker.tenant_id),
            user_id=str(worker.user_id),
            run_id=str(uuid.uuid4()),
            worker_context=None,
        )
        fallback_status, _, fallback_message = _status_from_events(fallback_events, fallback_error)
        fallback["status"] = fallback_status
        fallback["reason"] = fallback_message
        worker_events = _without_terminal_events(events)
        if fallback_status == "succeeded":
            status = "failed_fallback_succeeded"
            events = [worker_failure_notice, *worker_events, *fallback_events]
        else:
            status = "failed_fallback_failed"
            error_code = "WORKER_FALLBACK_FAILED"
            error_message = fallback_message or "Worker failed and the normal Agent fallback also failed."
            events = [worker_failure_notice, *worker_events, *fallback_events]

    run.status = status
    run.error_code = error_code
    run.error_message = error_message[:1024] if error_message else None
    live_events = _live_events_for_status(
        events,
        status=status,
        error_code=error_code,
        error_message=error_message,
        fallback=fallback,
    )
    persisted_events = _bounded_events(live_events)
    run.output_payload = validate_bounded_json(
        {
            "events": persisted_events,
            "tool_trace": _tool_trace(events),
            "fallback": fallback,
        },
        field="output_payload",
    )
    run.confirmation_metadata = validate_bounded_json(
        {
            **(run.confirmation_metadata or {}),
            "worker_context": _confirmation_worker_context(live_events, runtime_context),
        },
        field="confirmation_metadata",
    )

    await _record_runtime_feedback(db, worker=worker, run=run, status=status, source_run_id=source_run_id)
    await db.commit()
    await db.refresh(run)
    result = {
        "worker_run_id": str(run.id),
        "status": run.status,
        "events": live_events,
        "reason": run.error_code,
    }
    await _emit_after_worker_run(worker=worker, result=result, policy_action=policy.action)
    return result


def _worker_fallback_notice(
    *,
    worker: Worker,
    run_id: uuid.UUID,
    error_code: str | None,
    error_message: str | None,
) -> dict[str, Any]:
    return {
        "type": "worker_notice",
        "status": "fallback_started",
        "worker_id": str(worker.id),
        "worker_name": worker.name,
        "worker_run_id": str(run_id),
        "code": error_code or "WORKER_FAILED",
        "message": (
            f"Worker '{worker.name}' failed; continuing with the normal Agent fallback."
        ),
        "reason": error_message,
    }


async def _record_blocked_run(
    db: AsyncSession,
    *,
    worker: Worker,
    version: WorkerVersion | None,
    input_payload: dict[str, Any],
    matched_request: str,
    match_score: float,
    source_run_id: str | None,
    reason: str,
    status: str = "blocked_by_policy",
) -> dict[str, Any]:
    run = WorkerRun(
        tenant_id=worker.tenant_id,
        user_id=worker.user_id,
        worker_id=worker.id,
        version_id=version.id if version is not None else None,
        source_run_id=source_run_id,
        status=status,
        input_payload=validate_bounded_json(
            {
                "input": input_payload,
                "matched_request": matched_request,
                "match_score": float(match_score),
            },
            field="input_payload",
        ),
        output_payload=validate_bounded_json(
            {"events": [{"type": "error", "code": reason}], "tool_trace": [], "fallback": {"attempted": False}},
            field="output_payload",
        ),
        error_code=reason,
        confirmation_metadata={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"worker_run_id": str(run.id), "status": status, "reason": reason, "events": run.output_payload["events"]}


def _recursion_block_reason(worker: Worker, worker_context: dict[str, Any] | None) -> str | None:
    context = worker_context or {}
    stack = {str(item) for item in context.get("worker_stack") or []}
    if str(worker.id) in stack:
        return "worker_recursion_blocked"
    depth = int(context.get("depth") or 0)
    max_depth = int(context.get("max_depth") or DEFAULT_MAX_WORKER_DEPTH)
    if depth >= max_depth:
        return "worker_max_depth_exceeded"
    return None


def _next_worker_context(
    worker: Worker,
    version: WorkerVersion | None,
    worker_run_id: uuid.UUID | None,
    parent_context: dict[str, Any] | None,
    allowed_tool_names: list[str],
) -> dict[str, Any]:
    parent_context = parent_context or {}
    stack = [str(item) for item in parent_context.get("worker_stack") or []]
    return {
        "worker_id": str(worker.id),
        "worker_version_id": str(version.id) if version is not None else None,
        "worker_run_id": str(worker_run_id) if worker_run_id is not None else None,
        "depth": int(parent_context.get("depth") or 0) + 1,
        "max_depth": int(parent_context.get("max_depth") or DEFAULT_MAX_WORKER_DEPTH),
        "worker_stack": [*stack, str(worker.id)],
        "allowed_tool_names": allowed_tool_names,
        "risk_decision": risk_for(worker, version),
    }


def _worker_messages(
    worker: Worker,
    version: WorkerVersion | None,
    messages: list[dict[str, Any]],
    *,
    input_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    definition = version.definition if version is not None and isinstance(version.definition, dict) else {}
    instructions = definition.get("instructions") or worker.description or worker.name
    system = {
        "role": "system",
        "content": (
            "You are executing an activated Chainless Worker. "
            f"Worker: {worker.name}. Instructions: {instructions}. "
            f"Validated input: {input_payload}."
        ),
    }
    return [system, *messages]


async def _capture_agent_events(
    *,
    gateway: Any,
    sandbox_manager: Any,
    provider: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tenant_id: str,
    user_id: str,
    run_id: str,
    worker_context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None]:
    events: list[dict[str, Any]] = []
    try:
        async for event in run_agent(
            gateway,
            sandbox_manager,
            provider,
            messages,
            tools=tools,
            tenant_id=tenant_id,
            user_id=user_id,
            run_id=run_id,
            worker_context=worker_context,
        ):
            if event.get("type") == "confirmation_required":
                event["args"] = pack_confirmation_args(
                    event.get("args") or {},
                    worker_context_for_confirmation(
                        worker_context,
                        tool_name=event.get("tool_name"),
                        risk=event.get("risk"),
                    ),
                )
                event["worker_policy_context"] = worker_context_for_confirmation(
                    worker_context,
                    tool_name=event.get("tool_name"),
                    risk=event.get("risk"),
                )
            events.append(event)
    except Exception as exc:
        return events, str(exc)
    return events, None


def _status_from_events(events: list[dict[str, Any]], error: str | None) -> tuple[str, str | None, str | None]:
    if error is not None:
        return "failed", "WORKER_RUNTIME_ERROR", error
    if any(event.get("type") == "confirmation_required" for event in events):
        return "needs_user_confirmation", None, None
    failed = next((event for event in events if event.get("type") in {"error", "tool_error"}), None)
    if failed is not None:
        return "failed", str(failed.get("code") or "WORKER_TOOL_ERROR"), str(failed.get("error") or failed.get("message"))
    return "succeeded", None, None


def _bounded_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(events) <= MAX_CAPTURED_EVENTS:
        return [_safe_event(event) for event in events]

    captured = [_safe_event(event) for event in events[:MAX_CAPTURED_EVENTS]]
    terminal = _last_terminal_event(events)
    if terminal is not None:
        captured[-1] = _safe_event(terminal)
    return captured


def _live_events_for_status(
    events: list[dict[str, Any]],
    *,
    status: str,
    error_code: str | None,
    error_message: str | None,
    fallback: dict[str, Any],
) -> list[dict[str, Any]]:
    live_events = [_safe_event(event) for event in events]
    if status == "failed_fallback_failed":
        return [
            *_without_terminal_events(live_events),
            _final_runtime_error_event(
                status=status,
                error_code=error_code,
                error_message=error_message,
                fallback=fallback,
            ),
        ]
    if status == "failed":
        without_done = [event for event in live_events if event.get("type") != "done"]
        if any(event.get("type") == "error" for event in without_done):
            return without_done
        return [
            *without_done,
            _final_runtime_error_event(
                status=status,
                error_code=error_code,
                error_message=error_message,
                fallback=fallback,
            ),
        ]
    if not status.startswith("failed") or _last_terminal_event(live_events) is not None:
        return live_events

    return [
        *live_events,
        _final_runtime_error_event(
            status=status,
            error_code=error_code,
            error_message=error_message,
            fallback=fallback,
        ),
    ]


def _final_runtime_error_event(
    *,
    status: str,
    error_code: str | None,
    error_message: str | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    code = (
        "WORKER_FALLBACK_FAILED"
        if status == "failed_fallback_failed"
        else error_code or "WORKER_FAILED"
    )
    message = (
        fallback.get("reason")
        if status == "failed_fallback_failed" and fallback.get("reason")
        else error_message
    )
    return {
        "type": "error",
        "code": code,
        "message": _terminal_error_message(
            status=status,
            code=code,
            detail=str(message) if message else None,
        ),
    }


def _last_terminal_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("type") in TERMINAL_EVENT_TYPES:
            return event
    return None


def _without_terminal_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("type") not in TERMINAL_EVENT_TYPES]


def _terminal_error_message(*, status: str, code: str, detail: str | None) -> str:
    if status == "failed_fallback_failed":
        base = "Worker failed and the normal Agent fallback also failed."
    else:
        base = "Worker execution failed."
    if detail:
        return f"{base} {detail}"
    return f"{base} ({code})"


def _tool_trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") in {"tool_call_start", "tool_result", "tool_error"}:
            trace.append(_safe_event(event))
    return trace[:MAX_CAPTURED_EVENTS]


def _confirmation_worker_context(
    events: list[dict[str, Any]],
    runtime_context: dict[str, Any],
) -> dict[str, Any] | None:
    for event in events:
        context = event.get("worker_policy_context")
        if isinstance(context, dict):
            return context
    return worker_context_for_confirmation(runtime_context)


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in event.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, (dict, list)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


async def _record_runtime_feedback(
    db: AsyncSession,
    *,
    worker: Worker,
    run: WorkerRun,
    status: str,
    source_run_id: str | None,
) -> None:
    metadata = dict(worker.metadata_ or {})
    feedback = dict(metadata.get("runtime_feedback") or {})
    confidence = float(feedback.get("confidence", 0.5))
    if status == "succeeded":
        confidence = min(1.0, confidence + 0.05)
    elif str(status).startswith("failed"):
        confidence = max(0.0, confidence - 0.15)
        await emit_capability_hook(
            "on_worker_failure",
            {
                "worker_id": str(worker.id),
                "worker_run_id": str(run.id),
                "status": status,
                "source_run_id": source_run_id,
            },
        )
        if not await _existing_improvement_candidate(db, worker.id, source_run_id):
            candidate = CapabilityCandidate(
                tenant_id=worker.tenant_id,
                user_id=worker.user_id,
                candidate_type="worker",
                title=f"Improve Worker: {worker.name}",
                body=f"Worker run {run.id} ended with status {status}.",
                source_run_id=source_run_id,
                source_kind="worker_run",
                dedupe_key=f"worker-improvement:{worker.id}:{source_run_id or run.id}",
                worker_id=worker.id,
                evidence={"worker_run_id": str(run.id), "status": status},
                payload={
                    "worker_id": str(worker.id),
                    "definition": {"requires_review": True},
                    "verification_plan": {"reason": "worker_runtime_failure"},
                },
            )
            db.add(candidate)
            await db.flush()
            await emit_capability_hook(
                "on_capability_candidate_created",
                {
                    "candidate_id": str(candidate.id),
                    "candidate_type": candidate.candidate_type,
                    "tenant_id": str(candidate.tenant_id),
                    "user_id": str(candidate.user_id),
                    "source_run_id": candidate.source_run_id,
                    "worker_id": str(candidate.worker_id) if candidate.worker_id else None,
                },
            )
    feedback["confidence"] = confidence
    metadata["runtime_feedback"] = feedback
    worker.metadata_ = validate_bounded_json(metadata, field="metadata")


async def _emit_after_worker_run(
    *,
    worker: Worker,
    result: dict[str, Any],
    policy_action: str,
) -> None:
    await emit_capability_hook(
        "after_worker_run",
        {
            "worker_id": str(worker.id),
            "worker_run_id": result.get("worker_run_id"),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "policy_action": policy_action,
        },
        policy_action=policy_action,
    )


async def _existing_improvement_candidate(
    db: AsyncSession,
    worker_id: uuid.UUID,
    source_run_id: str | None,
) -> bool:
    if source_run_id is None:
        return False
    return (
        await db.execute(
            select(CapabilityCandidate.id).where(
                CapabilityCandidate.worker_id == worker_id,
                CapabilityCandidate.source_run_id == source_run_id,
            )
        )
    ).scalar_one_or_none() is not None
