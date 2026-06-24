"""Conversation CRUD and canonical SSE streaming endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.config import settings
from app.core.artifacts import (
    ARTIFACT_STATE_AVAILABLE,
    delete_artifacts_for_conversation,
    read_artifact_content,
    serialize_artifact,
)
from app.core.agent.prompt_builder import build_context
from app.core.llm.gateway import get_llm_gateway
from app.core.memory.layered import load_layered_instructions
from app.core.memory.persistent import build_memory_context, get_memories_for_session
from app.core.memory.short_term import append_short_term_context, cleanup_short_term_context
from app.core.sandbox.manager import get_sandbox_manager
from app.core.workspace_connectors.mounts import build_workspace_connector_runtime_context
from app.models.agent import Agent
from app.models.artifact import Artifact
from app.models.conversation import Conversation, Message
from app.models.llm_provider import LLMProvider
from app.services.conversation_stream_service import (
    build_chat_stream_response,
    build_confirmation_stream_response,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

SYSTEM_INSTRUCTIONS = (
    "You are Chainless, an AI assistant with access to tools. "
    "You can write and execute Python code in a sandbox, read/write files, "
    "fetch web content, search the web, check weather, and execute shell commands. "
    "Think step by step and use tools when appropriate. "
    "When asked to write code, use the code_as_action tool to execute it. "
    "When an answer uses persistent memory, cite the memory inline as [memory:<name>]. "
    "When an answer uses layered instructions, cite the layer inline as [context:<layer>]."
)

MEMORY_CONTEXT_LIMIT = 5


class _ChatRequest(BaseModel):
    content: str
    attachment_artifact_ids: list[uuid.UUID] = Field(default_factory=list)


class _CreateConversationRequest(BaseModel):
    title: str | None = None
    agent_id: uuid.UUID | None = None


class _UpdateConversationRequest(BaseModel):
    title: str


class ConfirmRequest(BaseModel):
    tool_call_id: str
    approved: bool | None = None
    decision: Literal["approve", "deny", "timeout"] | None = None
    tool_name: str | None = None
    args: dict | None = None


@router.post("/")
async def create_conversation(
    body: _CreateConversationRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new conversation for the authenticated user."""
    agent = await _resolve_requested_or_active_agent(
        db,
        current_user["tenant_id"],
        body.agent_id if body else None,
    )
    conv = Conversation(
        tenant_id=uuid.UUID(current_user["tenant_id"]),
        user_id=uuid.UUID(current_user["user_id"]),
        agent_id=agent.id if agent else None,
        title=(body.title.strip() if body and body.title and body.title.strip() else "New Conversation"),
        status="active",
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return _conversation_summary(conv)


@router.get("/")
async def list_conversations(
    limit: int = 20,
    offset: int = 0,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List conversations for the current tenant/user with pagination."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])

    count_q = (
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
            Conversation.status != "archived",
        )
    )
    total = (await db.execute(count_q)).scalar()

    rows_q = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
            Conversation.status != "archived",
        )
        .order_by(Conversation.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).scalars().all()

    items = [
        {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "agent_id": str(c.agent_id) if c.agent_id else None,
        }
        for c in rows
    ]

    return paginated_response(items, total, limit, offset, request)


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return a single conversation with its messages."""
    conv = await _get_owned_conversation(db, conv_id, current_user)
    if conv is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    rows: list[Message] = list(result.scalars().all())

    serialized_messages = []
    for message in rows:
        serialized_messages.append(
            await _serialize_message(db, message, current_user)
        )

    return {
        "id": str(conv.id),
        "title": conv.title,
        "status": conv.status,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "agent_id": str(conv.agent_id) if conv.agent_id else None,
        "messages": serialized_messages,
    }


@router.patch("/{conv_id}")
async def update_conversation(
    conv_id: uuid.UUID,
    body: _UpdateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Rename a conversation for the current tenant/user."""
    conv = await _get_owned_conversation(db, conv_id, current_user)
    if conv is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

    title = body.title.strip()
    if not title:
        raise validation_error("Conversation title cannot be empty")

    conv.title = title
    await db.commit()
    await db.refresh(conv)
    return _conversation_summary(conv)


@router.post("/{conv_id}/chat")
async def chat(
    conv_id: uuid.UUID,
    body: _ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Send a user message and stream the response with canonical SSE events."""
    conv = await _get_owned_conversation(db, conv_id, current_user)
    if conv is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

    attachments = await _validate_chat_attachments(db, conv_id, current_user, body.attachment_artifact_ids)
    llm_gateway = await get_llm_gateway()
    sandbox_manager = await get_sandbox_manager()
    db.add(
        Message(
            conversation_id=conv_id,
            role="user",
            content=body.content,
            meta_data={
                "attachment_artifact_ids": [str(artifact.id) for artifact in attachments],
            } if attachments else {},
        )
    )
    await db.commit()
    await append_short_term_context(
        current_user["tenant_id"],
        str(conv_id),
        role="user",
        content=body.content,
    )

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    db_messages: list[Message] = list(result.scalars().all())
    raw_messages = [
        {
            "role": m.role,
            "content": await _message_content_with_attachments(m, current_user),
        }
        for m in db_messages
    ]

    agent = await _resolve_conversation_agent(db, conv, current_user["tenant_id"])
    provider, system_prompt = await _resolve_agent_runtime_context(
        db,
        current_user["tenant_id"],
        agent,
    )

    session_context, context_summary = await _build_session_context(
        db,
        current_user["tenant_id"],
        current_user["user_id"],
        body.content,
    )
    if session_context:
        system_prompt = system_prompt + "\n\n" + session_context

    context_messages = build_context(system_prompt, raw_messages)
    connector_mount_context = await build_workspace_connector_runtime_context(
        db,
        tenant_id=uuid.UUID(current_user["tenant_id"]),
        user_id=uuid.UUID(current_user["user_id"]),
    )
    return await build_chat_stream_response(
        llm_gateway,
        sandbox_manager,
        db,
        conv_id,
        context_messages,
        request,
        tenant_id=current_user["tenant_id"],
        user_id=current_user["user_id"],
        provider=provider,
        context_summary={
            **context_summary,
            "agent": {
                "id": str(agent.id) if agent else None,
                "name": agent.name if agent else "default",
                "provider": provider,
            },
        },
        attachments=attachments,
        connector_mount_context=connector_mount_context,
    )


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: uuid.UUID,
    purge: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Archive a conversation, or permanently purge it when explicitly requested."""
    conv = await _get_owned_conversation(db, conv_id, current_user, include_archived=purge)
    if conv is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

    if purge:
        await delete_artifacts_for_conversation(
            db,
            tenant_id=current_user["tenant_id"],
            conversation_id=conv_id,
        )
        await cleanup_short_term_context(current_user["tenant_id"], str(conv_id))
        await db.delete(conv)
    else:
        conv.status = "archived"
    await db.commit()
    return None


@router.post("/{conv_id}/confirm")
async def confirm_tool(
    conv_id: str,
    req: ConfirmRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    gateway: LLMGateway = Depends(get_llm_gateway),
    sandbox: SandboxManager = Depends(get_sandbox_manager),
):
    """Resume a conversation that paused on a destructive tool confirmation."""
    if req.decision is not None:
        decision = req.decision
    elif req.approved is not None:
        decision = "approve" if req.approved else "deny"
    else:
        raise validation_error("Either decision or approved is required")

    conversation = await _get_owned_conversation(db, uuid.UUID(conv_id), user)
    if conversation is None:
        raise not_found("CONVERSATION_NOT_FOUND", "Conversation not found")

    agent = await _resolve_conversation_agent(db, conversation, user["tenant_id"])
    provider, system_prompt = await _resolve_agent_runtime_context(
        db,
        user["tenant_id"],
        agent,
    )
    connector_mount_context = await build_workspace_connector_runtime_context(
        db,
        tenant_id=uuid.UUID(user["tenant_id"]),
        user_id=uuid.UUID(user["user_id"]),
    )

    return await build_confirmation_stream_response(
        conv_id,
        user,
        decision,
        req.tool_call_id,
        req.tool_name,
        req.args,
        gateway,
        sandbox,
        provider=provider,
        system_prompt=system_prompt,
        connector_mount_context=connector_mount_context,
    )


async def _resolve_agent_runtime_context(
    db: AsyncSession,
    tenant_id: str,
    agent: Agent | None,
) -> tuple[str, str]:
    provider = await _resolve_default_provider_name(db, tenant_id)
    system_prompt = SYSTEM_INSTRUCTIONS
    if agent is None:
        return provider, system_prompt
    if agent.llm_provider:
        provider = (
            await _resolve_default_provider_name(db, tenant_id)
            if agent.llm_provider == "default"
            else agent.llm_provider
        )
    if agent.system_prompt:
        system_prompt = (
            system_prompt + "\n\nActive agent instructions:\n" + agent.system_prompt
        )
    return provider, system_prompt


async def _resolve_default_provider_name(db: AsyncSession, tenant_id: str) -> str:
    tenant_uuid = uuid.UUID(tenant_id)
    provider = (
        await db.execute(
            select(LLMProvider.name)
            .where(
                LLMProvider.tenant_id == tenant_uuid,
                LLMProvider.is_default.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return provider or "default"


async def _get_owned_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    current_user: dict,
    include_archived: bool = False,
) -> Conversation | None:
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    filters = [
        Conversation.id == conv_id,
        Conversation.tenant_id == tenant_id,
        Conversation.user_id == user_id,
    ]
    if not include_archived:
        filters.append(Conversation.status != "archived")
    result = await db.execute(select(Conversation).where(*filters))
    return result.scalar_one_or_none()


async def _build_session_context(
    db: AsyncSession,
    tenant_id: str,
    user_id: str,
    content: str,
) -> tuple[str, dict]:
    """Fetch relevant memories and layered instructions for the session."""
    parts: list[str] = []
    summary: dict = {
        "memory_count": 0,
        "memory_names": [],
        "has_layered_instructions": False,
        "instruction_preview": "",
    }

    try:
        memories = await get_memories_for_session(
            db,
            tenant_id,
            content,
            MEMORY_CONTEXT_LIMIT,
            user_id=user_id,
        )
        if memories:
            summary["memory_count"] = len(memories)
            summary["memory_names"] = [memory.name for memory in memories]
            lines = [
                "Relevant context from previous sessions. "
                "When using a memory fact, cite it as [memory:<name>]:"
            ]
            memory_context = build_memory_context(
                memories,
                budget_chars=settings.memory_injection_budget_chars,
            )
            if memory_context:
                lines.append(memory_context)
            parts.append("\n".join(lines))
    except Exception:
        pass

    try:
        instructions = load_layered_instructions(settings.memory_base_path, tenant_id)
        if instructions:
            summary["has_layered_instructions"] = True
            summary["instruction_preview"] = instructions[:240]
            parts.append(
                "Layered instructions for this session. "
                "When using these instructions, cite the relevant [context:<layer>] marker:\n"
                + instructions
            )
    except Exception:
        pass

    return "\n\n".join(parts), summary


async def _validate_chat_attachments(
    db: AsyncSession,
    conv_id: uuid.UUID,
    current_user: dict,
    attachment_ids: list[uuid.UUID],
) -> list[Artifact]:
    if len(attachment_ids) > 10:
        raise validation_error("At most 10 attachments are supported per message")
    if len(set(attachment_ids)) != len(attachment_ids):
        raise validation_error("Duplicate attachment IDs are not allowed")

    attachments: list[Artifact] = []
    for artifact_id in attachment_ids:
        artifact = (
            await db.execute(
                select(Artifact)
                .join(Conversation, Artifact.conversation_id == Conversation.id)
                .where(
                    Artifact.id == artifact_id,
                    Artifact.tenant_id == uuid.UUID(current_user["tenant_id"]),
                    Artifact.conversation_id == conv_id,
                    Conversation.user_id == uuid.UUID(current_user["user_id"]),
                    Conversation.status != "archived",
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise not_found("ARTIFACT_NOT_FOUND", "Attachment artifact not found")
        if not _is_attachable_upload_artifact(artifact):
            raise api_error(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_NOT_ATTACHABLE",
                _attachment_not_attachable_message(artifact),
            )
        attachments.append(artifact)
    return attachments


def _is_attachable_upload_artifact(artifact: Artifact) -> bool:
    return artifact.state == ARTIFACT_STATE_AVAILABLE and artifact.operation == "upload"


def _attachment_not_attachable_message(artifact: Artifact) -> str:
    if artifact.state != ARTIFACT_STATE_AVAILABLE:
        return f"Attachment artifact is {artifact.state}"
    return "Only uploaded artifacts can be attached to chat messages"


async def _serialize_message(
    db: AsyncSession,
    message: Message,
    current_user: dict,
) -> dict:
    serialized = {
        "id": str(message.id),
        "role": message.role,
        "content": message.content or "",
        "created_at": message.created_at.isoformat(),
    }
    attachments = [
        serialize_artifact(artifact)
        for artifact in await _get_message_attachment_artifacts(db, message, current_user)
    ]
    if attachments:
        serialized["attachments"] = attachments
    return serialized


async def _get_message_attachment_artifacts(
    db: AsyncSession,
    message: Message,
    current_user: dict,
) -> list[Artifact]:
    meta = message.meta_data or {}
    attachment_ids = meta.get("attachment_artifact_ids") or []
    if message.role != "user" or not attachment_ids:
        return []

    artifacts: list[Artifact] = []
    for attachment_id in attachment_ids:
        try:
            parsed_artifact_id = uuid.UUID(str(attachment_id))
        except (TypeError, ValueError):
            continue
        artifact = (
            await db.execute(
                select(Artifact)
                .join(Conversation, Artifact.conversation_id == Conversation.id)
                .where(
                    Artifact.id == parsed_artifact_id,
                    Artifact.tenant_id == uuid.UUID(current_user["tenant_id"]),
                    Artifact.conversation_id == message.conversation_id,
                    Conversation.user_id == uuid.UUID(current_user["user_id"]),
                    Conversation.status != "archived",
                )
            )
        ).scalar_one_or_none()
        if artifact is not None and _is_attachable_upload_artifact(artifact):
            artifacts.append(artifact)
    return artifacts


async def _message_content_with_attachments(
    message: Message,
    current_user: dict,
) -> str:
    content = message.content or ""
    meta = message.meta_data or {}
    attachment_ids = meta.get("attachment_artifact_ids") or []
    if message.role != "user" or not attachment_ids:
        return content

    from app.api.deps import _async_session_factory

    attachment_blocks: list[str] = []
    async with _async_session_factory() as session:
        for artifact in await _get_message_attachment_artifacts(
            session,
            message,
            current_user,
        ):
            try:
                attachment_content = await read_artifact_content(artifact, content_kind="content")
            except Exception:
                attachment_content = "[attachment content unavailable]"
            serialized = serialize_artifact(artifact)
            clipped = attachment_content[:12000]
            if len(attachment_content) > len(clipped):
                clipped += "\n[attachment truncated]"
            attachment_blocks.append(
                "\n".join(
                    [
                        f"Attachment artifact {serialized['id']}: {serialized['path']}",
                        "```",
                        clipped,
                        "```",
                    ]
                )
            )

    if not attachment_blocks:
        return content
    return content + "\n\nAttached files:\n" + "\n\n".join(attachment_blocks)


async def _resolve_requested_or_active_agent(
    db: AsyncSession,
    tenant_id: str,
    requested_agent_id: uuid.UUID | None,
) -> Agent | None:
    tenant_uuid = uuid.UUID(tenant_id)
    if requested_agent_id is not None:
        agent = (
            await db.execute(
                select(Agent).where(
                    Agent.id == requested_agent_id,
                    Agent.tenant_id == tenant_uuid,
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise not_found("AGENT_NOT_FOUND", "Agent not found")
        return agent
    return await _get_active_agent(db, tenant_uuid)


async def _resolve_conversation_agent(
    db: AsyncSession,
    conv: Conversation,
    tenant_id: str,
) -> Agent | None:
    tenant_uuid = uuid.UUID(tenant_id)
    if conv.agent_id is not None:
        agent = (
            await db.execute(
                select(Agent).where(
                    Agent.id == conv.agent_id,
                    Agent.tenant_id == tenant_uuid,
                )
            )
        ).scalar_one_or_none()
        if agent is not None:
            return agent
    agent = await _get_active_agent(db, tenant_uuid)
    if agent is not None and conv.agent_id != agent.id:
        conv.agent_id = agent.id
        await db.commit()
    return agent


async def _get_active_agent(db: AsyncSession, tenant_id: uuid.UUID) -> Agent | None:
    return (
        await db.execute(
            select(Agent)
            .where(Agent.tenant_id == tenant_id, Agent.is_active.is_(True))
            .order_by(Agent.updated_at.desc(), Agent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _conversation_summary(conv: Conversation) -> dict:
    return {
        "id": str(conv.id),
        "title": conv.title,
        "status": conv.status,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "agent_id": str(conv.agent_id) if conv.agent_id else None,
    }
