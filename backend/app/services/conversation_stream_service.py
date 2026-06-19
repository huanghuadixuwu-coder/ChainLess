"""Conversation streaming orchestration and persistence."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import validation_error
from app.api.sse import sse_error, sse_event
from app.core.artifacts import (
    ToolExecutionResult,
    cleanup_run_workspace,
    prepare_run_workspace,
)
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL, execute_code_as_action
from app.core.agent.engine import run_agent
from app.core.agent.prompt_builder import build_context, merge_capability_context_into_messages
from app.core.agent.tool_router import execute_tool
from app.core.capabilities.orchestration import (
    require_confirmed_worker_tool_policy,
    unpack_confirmed_tool_args,
)
from app.core.capabilities.retrieval import CapabilityContext, get_capability_context
from app.core.capabilities.service import analyze_run_tail_for_candidates
from app.core.tools.configuration import (
    apply_tool_configuration,
    filter_enabled_tools,
    get_tool_configurations,
)
from app.core.llm.gateway import LLMGateway
from app.core.memory.short_term import append_short_term_context
from app.core.observability import increment_runtime_metric
from app.core.secrets import safe_error_message
from app.core.sandbox.manager import SandboxManager
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.builtin.sandbox import execute as execute_shell_exec
from app.core.tools.mcp.manager import mcp_manager
from app.core.workers.control_intent import (
    WORKER_DELETE_TOOL_NAME,
    execute_confirmed_worker_delete,
    queue_worker_delete_confirmation,
)
from app.core.workers.stream_coordinator import maybe_execute_worker_for_stream
from app.models.conversation import Conversation, Message
from app.models.artifact import Artifact
from app.models.tool_confirmation import ToolConfirmation


DEFAULT_CONFIRMATION_TIMEOUT_S = 30


async def get_agent_tools(tenant_id: str) -> list[dict]:
    from app.api.deps import _async_session_factory

    async with _async_session_factory() as db:
        configs = await get_tool_configurations(db, tenant_id)
    tools = ALL_TOOLS + mcp_manager.get_all_tools(tenant_id) + [CODE_AS_ACTION_TOOL]
    return filter_enabled_tools(
        [apply_tool_configuration(tool, configs.get(_tool_name(tool))) for tool in tools]
    )


def _tool_name(tool: dict) -> str:
    return tool.get("function", {}).get("name", "")


def build_confirmation_message(
    conversation_id: uuid.UUID | str,
    *,
    confirmation: str,
    tool_call_id: str,
    tool_name: str | None = None,
    args: dict | None = None,
    risk: str = "destructive",
    timeout_s: int = DEFAULT_CONFIRMATION_TIMEOUT_S,
    content: str | None = None,
) -> Message:
    event_at = datetime.now(timezone.utc).isoformat()
    meta_data = {
        "confirmation": confirmation,
        "tool_call_id": tool_call_id,
        "risk": risk,
        "timeout_s": timeout_s,
    }
    if tool_name:
        meta_data["tool_name"] = tool_name
    if args is not None:
        meta_data["args"] = args

    if content is None:
        if confirmation == "pending":
            content = f"Confirmation required before running destructive tool '{tool_name}'."
            meta_data["requested_at"] = event_at
        elif confirmation == "approved":
            content = f"User approved destructive tool '{tool_name}'."
            meta_data["resolved_at"] = event_at
        elif confirmation == "denied":
            content = f"User denied destructive tool '{tool_name or tool_call_id}'."
            meta_data["resolved_at"] = event_at
        elif confirmation == "timeout":
            content = f"Confirmation timed out for destructive tool '{tool_name or tool_call_id}'."
            meta_data["resolved_at"] = event_at
        else:
            content = f"Confirmation state '{confirmation}' recorded for destructive tool '{tool_name or tool_call_id}'."
            meta_data["resolved_at"] = event_at

    return Message(
        conversation_id=conversation_id,
        role="tool",
        content=content,
        meta_data=meta_data,
    )


async def persist_confirmation_required(
    db: AsyncSession,
    conversation_id: uuid.UUID | str,
    *,
    tool_call_id: str,
    tool_name: str,
    args: dict,
    risk: str,
    timeout_s: int,
    worker_policy_context: dict | None = None,
) -> None:
    persisted_args = dict(args or {})
    if worker_policy_context:
        persisted_args["__worker_policy_context"] = worker_policy_context
    db.add(
        ToolConfirmation(
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=persisted_args,
            risk=risk,
            timeout_s=timeout_s,
            status="pending",
        )
    )
    db.add(
        build_confirmation_message(
            conversation_id,
            confirmation="pending",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=persisted_args,
            risk=risk,
            timeout_s=timeout_s,
        )
    )
    await db.commit()


async def claim_confirmation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    tool_call_id: str,
    decision: Literal["approve", "deny", "timeout"],
) -> ToolConfirmation:
    pending = (
        await db.execute(
            select(ToolConfirmation).where(
                ToolConfirmation.conversation_id == conversation_id,
                ToolConfirmation.tool_call_id == tool_call_id,
                ToolConfirmation.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if pending is None:
        raise validation_error("Confirmation is missing or has already been resolved")

    resolved_decision = decision
    if decision == "approve":
        created_at = pending.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= created_at + timedelta(seconds=pending.timeout_s):
            resolved_decision = "timeout"

    claimed = (
        await db.execute(
            update(ToolConfirmation)
            .where(
                ToolConfirmation.id == pending.id,
                ToolConfirmation.status == "pending",
            )
            .values(
                status={"approve": "approved", "deny": "denied"}.get(
                    resolved_decision,
                    resolved_decision,
                ),
                resolved_at=datetime.now(timezone.utc),
            )
            .returning(ToolConfirmation)
        )
    ).scalar_one_or_none()
    if claimed is None:
        await db.rollback()
        raise validation_error("Confirmation is missing or has already been resolved")
    await db.commit()
    return claimed


def find_latest_confirmation_request(
    messages: list[Message],
    tool_call_id: str,
) -> Message | None:
    for message in reversed(messages):
        meta = message.meta_data or {}
        if meta.get("tool_call_id") == tool_call_id and meta.get("confirmation") == "pending":
            return message
    return None


def is_confirmation_expired(message: Message | None) -> bool:
    if message is None or message.created_at is None:
        return False

    meta = message.meta_data or {}
    timeout_s = meta.get("timeout_s") or DEFAULT_CONFIRMATION_TIMEOUT_S
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc) >= created_at + timedelta(seconds=timeout_s)


def public_agent_event(event: dict) -> tuple[str, dict] | None:
    """Map internal agent events to the public canonical SSE contract."""
    event_type = event.get("type")
    if event_type == "text":
        return "text", {"delta": event.get("content", "")}
    if event_type == "tool_call_start":
        return "tool_call", {
            "id": event.get("tool_call_id", ""),
            "name": event.get("name", ""),
            "args": event.get("args") or {},
            "risk": event.get("risk", "risky"),
            "status": "started",
        }
    if event_type == "tool_result":
        data = {
            "id": event.get("tool_call_id", ""),
            "name": event.get("name", ""),
            "result": event.get("result", ""),
            "status": "completed",
        }
        if event.get("artifacts"):
            data["artifacts"] = event["artifacts"]
        return "tool_result", data
    if event_type == "tool_error":
        return "tool_result", {
            "id": event.get("tool_call_id", ""),
            "name": event.get("name", ""),
            "error": event.get("error", "Tool error"),
            "consecutive": event.get("consecutive", 0),
            "status": "error",
        }
    if event_type == "sandbox":
        return "sandbox", {
            "phase": event.get("phase", "unknown"),
            "container_id": event.get("container_id", ""),
        }
    if event_type == "sandbox_output":
        return "sandbox_output", {
            "stream": event.get("stream", "stdout"),
            "data": event.get("data", ""),
            "container_id": event.get("container_id", ""),
        }
    if event_type == "confirmation_required":
        return "confirmation_required", {
            "tool_call_id": event.get("tool_call_id", ""),
            "tool_name": event.get("tool_name", ""),
            "args": event.get("args") or {},
            "risk": event.get("risk", "destructive"),
            "timeout_s": event.get("timeout_s", DEFAULT_CONFIRMATION_TIMEOUT_S),
            "worker_policy_context": event.get("worker_policy_context"),
        }
    if event_type == "worker_notice":
        return "worker_notice", {
            key: value
            for key, value in event.items()
            if key != "type"
        }
    if event_type == "done":
        return "done", {"tokens_used": event.get("tokens_used", 0)}
    if event_type == "error":
        return "error", {
            "code": event.get("code", "AGENT_ERROR"),
            "message": event.get("message", "Agent stream error"),
        }
    return None


async def build_chat_stream_response(
    gateway: LLMGateway,
    sandbox_manager: SandboxManager,
    db: AsyncSession,
    conv_id: uuid.UUID,
    messages: list[dict],
    request: Request | None = None,
    *,
    tenant_id: str,
    user_id: str | None = None,
    provider: str = "default",
    context_summary: dict | None = None,
    attachments: list[Artifact] | None = None,
) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    run_id = str(uuid.uuid4())
    run_workspace = None
    workspace_base = None
    if attachments:
        try:
            run_workspace = await prepare_run_workspace(
                run_id=run_id,
                artifacts=attachments,
            )
            workspace_base = str(run_workspace.base_path)
            messages = [
                *messages,
                {
                    "role": "system",
                    "content": run_workspace.summary_for_prompt,
                },
            ]
        except Exception as exc:
            failure_reason = safe_error_message(exc, "Attachment materialization")

            async def generate_materialization_error():
                event_index = 0
                if context_summary:
                    event_index += 1
                    yield sse_event("context", context_summary, event_id=str(event_index))
                event_index += 1
                yield sse_error(
                    "ATTACHMENT_MATERIALIZATION_FAILED",
                    "Attached files are unavailable. Please retry, wait for upload completion, or re-upload the file.",
                    {"reason": failure_reason},
                    event_id=str(event_index),
                )
                event_index += 1
                yield sse_event("done", {"tokens_used": 0}, event_id=str(event_index))

            return StreamingResponse(
                generate_materialization_error(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    agent_task = asyncio.create_task(
        run_agent_stream(
            gateway,
            sandbox_manager,
            messages,
            queue,
            tenant_id,
            provider,
            conversation_id=str(conv_id),
            user_id=user_id,
            run_id=run_id,
            workspace_base=workspace_base,
        )
    )
    heartbeat_task = asyncio.create_task(heartbeat_loop(queue))

    async def generate():
        full_content = ""
        tokens_used = 0
        errored = False
        cancelled = False
        event_index = 0
        capability_hint: dict | None = None

        try:
            if context_summary:
                event_index += 1
                yield sse_event("context", context_summary, event_id=str(event_index))

            while True:
                if request is not None and await request.is_disconnected():
                    cancelled = True
                    increment_runtime_metric("sse_disconnects")
                    break

                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(),
                        timeout=0.25,
                    )
                except asyncio.TimeoutError:
                    continue
                event_index += 1

                if event_type == "done":
                    tokens_used = data.get("tokens_used", 0)
                    break

                if event_type == "error":
                    errored = True
                    increment_runtime_metric("sse_errors")
                    yield sse_error(
                        data.get("code", "AGENT_STREAM_ERROR"),
                        data.get("message", "Agent stream error"),
                        event_id=str(event_index),
                    )
                    return

                if event_type == "text":
                    full_content += data.get("delta", "")

                if event_type == "confirmation_required":
                    await persist_confirmation_required(
                        db,
                        conv_id,
                        tool_call_id=data.get("tool_call_id", ""),
                        tool_name=data["tool_name"],
                        args=data["args"],
                        risk=data["risk"],
                        timeout_s=data["timeout_s"],
                        worker_policy_context=data.get("worker_policy_context"),
                    )

                yield sse_event(event_type, data, event_id=str(event_index))

        except asyncio.CancelledError:
            cancelled = True
            increment_runtime_metric("sse_disconnects")
        finally:
            heartbeat_task.cancel()
            if cancelled and not agent_task.done():
                agent_task.cancel()
            for task in (heartbeat_task, agent_task):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            if not errored and not cancelled and full_content:
                db.add(Message(conversation_id=conv_id, role="assistant", content=full_content))
                await db.commit()
                await append_short_term_context(
                    tenant_id,
                    str(conv_id),
                    role="assistant",
                    content=full_content,
                )
                if user_id:
                    try:
                        capability_hint = await analyze_run_tail_for_candidates(
                            db,
                            gateway=gateway,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            conversation_id=str(conv_id),
                            source_run_id=run_id,
                            user_messages=_user_messages_for_analysis(messages),
                            assistant_content=full_content,
                            provider=provider,
                            artifacts=_artifact_refs_for_analysis(attachments or []),
                        )
                    except Exception:
                        increment_runtime_metric("capability_analysis_failures")

            if not cancelled:
                if capability_hint is not None:
                    event_index += 1
                    yield sse_event("capability_candidate", capability_hint, event_id=str(event_index))
                event_index += 1
                yield sse_event("done", {"tokens_used": tokens_used}, event_id=str(event_index))
            if run_workspace is not None:
                cleanup_run_workspace(run_id=run_workspace.run_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _user_messages_for_analysis(messages: list[dict]) -> list[str]:
    user_messages: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            user_messages.append(content)
    return user_messages[-5:]


def _artifact_refs_for_analysis(artifacts: list[Artifact]) -> list[dict[str, str]]:
    return [
        {"id": str(artifact.id), "path": artifact.workspace_path}
        for artifact in artifacts
    ]


async def heartbeat_loop(queue: asyncio.Queue) -> None:
    try:
        while True:
            await asyncio.sleep(15)
            await queue.put(("heartbeat", {}))
    except asyncio.CancelledError:
        pass


async def run_agent_stream(
    gateway: LLMGateway,
    sandbox_manager: SandboxManager,
    messages: list[dict],
    queue: asyncio.Queue,
    tenant_id: str,
    provider: str,
    conversation_id: str | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    workspace_base: str | None = None,
) -> None:
    try:
        tools = await get_agent_tools(tenant_id)
        capability_context = await _capability_context_for_stream(
            gateway=gateway,
            tenant_id=tenant_id,
            user_id=user_id,
            messages=messages,
        )
        messages = merge_capability_context_into_messages(messages, capability_context)
        worker_executed = False
        matched_request = _latest_user_request(messages)
        if matched_request and user_id and conversation_id:
            from app.api.deps import _async_session_factory

            async with _async_session_factory() as worker_db:
                worker_control = await queue_worker_delete_confirmation(
                    worker_db,
                    queue=queue,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    request=matched_request,
                    timeout_s=DEFAULT_CONFIRMATION_TIMEOUT_S,
                )
            if worker_control == "queued":
                worker_executed = True
            elif worker_control != "bypass_worker":
                worker_executed = await maybe_execute_worker_for_stream(
                    gateway=gateway,
                    sandbox_manager=sandbox_manager,
                    provider=provider,
                    messages=messages,
                    queue=queue,
                    matched_request=matched_request,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    source_run_id=run_id,
                    tools=tools,
                    capability_context=capability_context,
                    public_event_mapper=public_agent_event,
                )
        if worker_executed:
            return
        async for event in run_agent(
            gateway,
            sandbox_manager,
            provider,
            messages,
            tools=tools,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            workspace_base=workspace_base,
        ):
            mapped = public_agent_event(event)
            if mapped is not None:
                await queue.put(mapped)
    except Exception as exc:
        increment_runtime_metric("sse_errors")
        await queue.put(
            ("error", {"code": "AGENT_STREAM_ERROR", "message": safe_error_message(exc, "Agent stream")})
        )


async def _capability_context_for_stream(
    *,
    gateway: LLMGateway,
    tenant_id: str,
    user_id: str | None,
    messages: list[dict],
) -> CapabilityContext | None:
    if not user_id:
        return None
    matched_request = _latest_user_request(messages)
    if not matched_request:
        return None
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        return None

    try:
        from app.api.deps import _async_session_factory

        async with _async_session_factory() as db:
            return await get_capability_context(
                db,
                tenant_id=tenant_uuid,
                user_id=user_uuid,
                task_text=matched_request,
                gateway=gateway,
            )
    except Exception:
        return None


def _latest_user_request(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


async def execute_confirmed_tool(
    tool_name: str,
    args: dict,
    sandbox: SandboxManager,
    *,
    gateway: LLMGateway,
    tenant_id: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    tool_call_id: str | None = None,
    run_id: str | None = None,
    worker_context: dict | None = None,
    risk: str | None = None,
) -> str | ToolExecutionResult:
    args, persisted_worker_context = unpack_confirmed_tool_args(args)
    effective_worker_context = worker_context or persisted_worker_context
    require_confirmed_worker_tool_policy(tool_name, effective_worker_context, risk=risk)
    if tool_name == WORKER_DELETE_TOOL_NAME:
        return await execute_confirmed_worker_delete(
            args,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    if tool_name == "code_as_action":
        return await execute_code_as_action(
            args.get("script", ""),
            sandbox,
            gateway=gateway,
            tenant_id=tenant_id,
            parent_budget=100_000,
        )
    if tool_name == "shell_exec":
        return await execute_shell_exec(tool_name, args, sandbox)
    result = await execute_tool(
        tool_name,
        args,
        context={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "tool_call_id": tool_call_id,
            "run_id": run_id,
            "worker_context": effective_worker_context,
        },
    )
    return result


async def build_confirmation_stream_response(
    conv_id: str,
    user: dict,
    decision: Literal["approve", "deny", "timeout"],
    tool_call_id: str,
    tool_name: str | None,
    args: dict | None,
    gateway: LLMGateway,
    sandbox: SandboxManager,
    provider: str = "default",
    system_prompt: str = "You are a helpful AI assistant.",
) -> StreamingResponse:
    from app.api.deps import _async_session_factory

    conv_uuid = uuid.UUID(str(conv_id))
    tenant_uuid = uuid.UUID(user["tenant_id"])
    user_uuid = uuid.UUID(user["user_id"])

    async with _async_session_factory() as db:
        conv = (await db.execute(select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.tenant_id == tenant_uuid,
            Conversation.user_id == user_uuid,
            Conversation.status != "archived",
        ))).scalar_one_or_none()
        if not conv:
            from app.api.contracts import not_found

            raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

        claimed = await claim_confirmation(db, conv_uuid, tool_call_id, decision)
        resolved_decision = {"approved": "approve", "denied": "deny"}.get(
            claimed.status,
            claimed.status,
        )
        resolved_tool_name = claimed.tool_name
        resolved_args, resolved_worker_context = unpack_confirmed_tool_args(claimed.args)
        timeout_s = claimed.timeout_s
        risk = claimed.risk

        result = await db.execute(select(Message).where(
            Message.conversation_id == conv.id).order_by(Message.created_at))
        db_messages: list[Message] = list(result.scalars().all())
        resolution_message = build_confirmation_message(
            conv_uuid,
            confirmation=claimed.status,
            tool_call_id=tool_call_id,
            tool_name=resolved_tool_name,
            args=resolved_args,
            risk=risk,
            timeout_s=timeout_s,
        )
        db.add(resolution_message)
        await db.commit()
        db_messages.append(resolution_message)

        history = [{"role": m.role, "content": m.content} for m in db_messages]
        context_msgs = build_context(system_prompt, history)

    async def event_stream():
        full_response = ""
        confirmed_result = None
        resume_messages = list(context_msgs)
        event_index = 0
        try:
            if resolved_decision in {"deny", "timeout"}:
                yield sse_event("done", {"tokens_used": 0}, event_id="1")
                return

            if resolved_decision == "approve" and resolved_tool_name:
                confirmed_execution = await execute_confirmed_tool(
                    resolved_tool_name,
                    resolved_args,
                    sandbox,
                    gateway=gateway,
                    tenant_id=user["tenant_id"],
                    user_id=user["user_id"],
                    conversation_id=str(conv_uuid),
                    tool_call_id=tool_call_id,
                    run_id=str(uuid.uuid4()),
                    worker_context=resolved_worker_context,
                    risk=risk,
                )
                confirmed_artifacts: list[dict] = []
                if isinstance(confirmed_execution, ToolExecutionResult):
                    confirmed_artifacts = confirmed_execution.artifacts
                    confirmed_result = confirmed_execution.content
                else:
                    confirmed_result = confirmed_execution
                event_index += 1
                tool_result_data = {
                        "id": tool_call_id,
                        "name": resolved_tool_name,
                        "result": str(confirmed_result)[:2000],
                        "status": "completed",
                }
                if confirmed_artifacts:
                    tool_result_data["artifacts"] = confirmed_artifacts
                yield sse_event("tool_result", tool_result_data, event_id=str(event_index))
                resume_messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": resolved_tool_name,
                                    "arguments": json.dumps(resolved_args),
                                },
                            }
                        ],
                    }
                )
                resume_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": str(confirmed_result),
                    }
                )

            async for event in run_agent(
                gateway,
                sandbox,
                provider,
                resume_messages,
                await get_agent_tools(user["tenant_id"]),
                tenant_id=user["tenant_id"],
                user_id=user["user_id"],
                conversation_id=str(conv_uuid),
                worker_context=resolved_worker_context,
            ):
                mapped = public_agent_event(event)
                if mapped is None:
                    continue
                event_name, data = mapped
                event_index += 1
                if event_name == "text":
                    full_response += data.get("delta", "")
                elif event_name == "confirmation_required":
                    from app.api.deps import _async_session_factory

                    async with _async_session_factory() as s:
                        await persist_confirmation_required(
                            s,
                            conv_uuid,
                            tool_call_id=data.get("tool_call_id", ""),
                            tool_name=data["tool_name"],
                            args=data["args"],
                            risk=data["risk"],
                            timeout_s=data["timeout_s"],
                            worker_policy_context=data.get("worker_policy_context"),
                        )
                elif event_name == "error":
                    increment_runtime_metric("sse_errors")
                    yield sse_error(
                        data.get("code", "LLM_PROVIDER_ERROR"),
                        data.get("message", "Stream error"),
                        event_id=str(event_index),
                    )
                    return

                yield sse_event(event_name, data, event_id=str(event_index))
        except Exception as exc:
            event_index += 1
            increment_runtime_metric("sse_errors")
            yield sse_error(
                "LLM_PROVIDER_ERROR",
                safe_error_message(exc, "LLM provider"),
                event_id=str(event_index),
            )
        finally:
            from app.api.deps import _async_session_factory

            async with _async_session_factory() as s:
                if full_response:
                    s.add(Message(conversation_id=conv_uuid, role="assistant", content=full_response))
                await s.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
