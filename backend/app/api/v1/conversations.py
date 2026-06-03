"""Conversation CRUD and SSE streaming chat endpoints.

POST   /                     — create a new conversation
GET    /                     — list conversations (paginated)
POST   /{conv_id}/chat       — send message, stream agent response via SSE
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.pagination import paginated_response
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.agent.engine import run_agent
from app.core.agent.prompt_builder import build_context
from app.core.llm.gateway import LLMGateway, get_llm_gateway
from app.core.memory.persistent import get_memories_for_session
from app.core.sandbox.manager import SandboxManager, get_sandbox_manager
from app.core.tools.builtin import ALL_TOOLS
from app.models.conversation import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = (
    "You are Chainless, an AI assistant with access to tools. "
    "You can write and execute Python code in a sandbox, read/write files, "
    "fetch web content, search the web, and execute shell commands. "
    "Think step by step and use tools when appropriate. "
    "When asked to write code, use the code_as_action tool to execute it."
)

# Number of relevant memories to inject into the system prompt at session start.
MEMORY_CONTEXT_LIMIT = 5

# Tools exposed to the agent: builtin tools plus the code_as_action tool.
AGENT_TOOLS = ALL_TOOLS + [CODE_AS_ACTION_TOOL]

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _ChatRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/")
async def create_conversation(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new conversation for the authenticated user.

    Returns the conversation id, title and creation timestamp.
    """
    conv = Conversation(
        tenant_id=uuid.UUID(current_user["tenant_id"]),
        user_id=uuid.UUID(current_user["user_id"]),
        title="New Conversation",
        status="active",
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {
        "id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
    }


@router.get("/")
async def list_conversations(
    limit: int = 20,
    offset: int = 0,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # The Request parameter is injected by FastAPI via type annotation;
    # the None default is never used at runtime but keeps the signature
    # stable when the endpoint is called without an explicit request.
    """List conversations for the current tenant/user with pagination."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])

    # Total count
    count_q = (
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
    )
    total = (await db.execute(count_q)).scalar()

    # Paginated items
    rows_q = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
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
        }
        for c in rows
    ]

    return paginated_response(items, total, limit, offset, request)


@router.post("/{conv_id}/chat")
async def chat(
    conv_id: uuid.UUID,
    body: _ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    llm_gateway: LLMGateway = Depends(get_llm_gateway),
    sandbox_manager: SandboxManager = Depends(get_sandbox_manager),
):
    """Send a user message and stream the agent response via SSE.

    SSE event types:
        event: text                 -> data: {"delta": "..."}
        event: tool_call_start      -> data: {"name": "...", "args": {...}}
        event: tool_result          -> data: {"name": "...", "result": "..."}
        event: tool_error           -> data: {"name": "...", "error": "..."}
        event: confirmation_required -> data: {"tool_name": "...", "args": {...}, "risk": "destructive", "timeout_s": 30}
        event: heartbeat            -> data: {}
        event: error                -> data: {"error": {"code": "...", "message": "..."}}
        event: done                 -> data: {"tokens_used": N}
    """
    tenant_id = uuid.UUID(current_user["tenant_id"])

    # Validate conversation exists and belongs to the tenant
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Save user message
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.commit()

    # Load full message history
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    db_messages: list[Message] = list(result.scalars().all())

    # Convert to litellm-friendly format
    raw_messages = [
        {"role": m.role, "content": m.content or ""} for m in db_messages
    ]

    # Inject relevant memories into the system prompt at session start.
    # Only do this for the first user message (when history has only one user message).
    system_prompt = SYSTEM_INSTRUCTIONS
    memory_note = await _build_memory_context(db, str(tenant_id), body.content)
    if memory_note:
        system_prompt = system_prompt + "\n\n" + memory_note

    # Build token-aware context
    context_messages = build_context(system_prompt, raw_messages)

    return await _build_sse_stream(
        llm_gateway,
        sandbox_manager,
        db,
        conv_id,
        context_messages,
    )


# ---------------------------------------------------------------------------
# Memory context helper
# ---------------------------------------------------------------------------


async def _build_memory_context(
    db: AsyncSession,
    tenant_id: str,
    content: str,
) -> str:
    """Fetch relevant memories and format them as a context note.

    Returns an empty string when no memories are found or when the
    memory service is unavailable.
    """
    try:
        memories = await get_memories_for_session(
            db, tenant_id, content, MEMORY_CONTEXT_LIMIT
        )
        if not memories:
            return ""
        lines = ["Relevant context from previous sessions:"]
        for m in memories:
            tag_str = " ".join(f"#{t}" for t in (m.tags or []))
            lines.append(
                f"- {m.name}: {m.content or ''} {tag_str}".strip()
            )
        return "\n".join(lines)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


async def _build_sse_stream(
    gateway: LLMGateway,
    sandbox_manager: SandboxManager,
    db: AsyncSession,
    conv_id: uuid.UUID,
    messages: list[dict],
) -> StreamingResponse:
    """Run the agent with a concurrent heartbeat and wrap it as SSE.

    Coordination is done via an ``asyncio.Queue``:

    * ``_run_agent_stream``   -> puts ``text``/``tool_call_start``/etc. events
    * ``_heartbeat_loop``     -> puts ``heartbeat`` events every 15 seconds
    * The async generator reads from the queue and yields SSE-formatted lines.
    """
    queue: asyncio.Queue = asyncio.Queue()

    agent_task = asyncio.create_task(
        _run_agent_stream(gateway, sandbox_manager, messages, queue)
    )
    heartbeat_task = asyncio.create_task(_heartbeat_loop(queue))

    async def _generate():
        full_content = ""
        tokens_used = 0
        errored = False

        try:
            while True:
                event_type, data = await queue.get()

                if event_type == "done":
                    tokens_used = data.get("tokens_used", 0)
                    break

                if event_type == "error":
                    errored = True
                    yield f"event: error\ndata: {json.dumps(data)}\n\n"
                    return

                if event_type == "text":
                    delta = data["delta"]
                    full_content += delta
                    yield f"event: text\ndata: {json.dumps({'delta': delta})}\n\n"

                elif event_type == "tool_call_start":
                    yield (
                        "event: tool_call_start\n"
                        f"data: {json.dumps({'name': data['name'], 'args': data['args']})}\n\n"
                    )

                elif event_type == "tool_result":
                    yield (
                        "event: tool_result\n"
                        f"data: {json.dumps({'name': data['name'], 'result': data['result']})}\n\n"
                    )

                elif event_type == "tool_error":
                    yield (
                        "event: tool_error\n"
                        f"data: {json.dumps({'name': data['name'], 'error': data['error']})}\n\n"
                    )

                elif event_type == "confirmation_required":
                    yield (
                        "event: confirmation_required\n"
                        f"data: {json.dumps({'tool_name': data['tool_name'], 'args': data['args'], 'risk': data['risk'], 'timeout_s': data['timeout_s']})}\n\n"
                    )

                elif event_type == "heartbeat":
                    yield f"event: heartbeat\ndata: {json.dumps({})}\n\n"

        except asyncio.CancelledError:
            pass

        finally:
            # Stop the heartbeat
            heartbeat_task.cancel()
            for t in (heartbeat_task, agent_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            # Persist the assistant message
            if not errored and full_content:
                msg = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=full_content,
                )
                db.add(msg)
                await db.commit()

            # Always emit the done event
            yield f"event: done\ndata: {json.dumps({'tokens_used': tokens_used})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


async def _heartbeat_loop(queue: asyncio.Queue) -> None:
    """Put a heartbeat event on the queue every 15 seconds."""
    try:
        while True:
            await asyncio.sleep(15)
            await queue.put(("heartbeat", {}))
    except asyncio.CancelledError:
        pass


async def _run_agent_stream(
    gateway: LLMGateway,
    sandbox_manager: SandboxManager,
    messages: list[dict],
    queue: asyncio.Queue,
) -> None:
    """Iterate over the agent ReAct loop and push events to the queue."""
    try:
        async for event in run_agent(
            gateway,
            sandbox_manager,
            "default",
            messages,
            tools=AGENT_TOOLS,
        ):
            if event["type"] == "text":
                await queue.put(("text", {"delta": event["content"]}))
            elif event["type"] == "tool_call_start":
                await queue.put((
                    "tool_call_start",
                    {"name": event["name"], "args": event["args"]},
                ))
            elif event["type"] == "tool_result":
                await queue.put((
                    "tool_result",
                    {"name": event["name"], "result": event["result"]},
                ))
            elif event["type"] == "tool_error":
                await queue.put((
                    "tool_error",
                    {
                        "name": event["name"],
                        "error": event["error"],
                        "consecutive": event.get("consecutive", 0),
                    },
                ))
            elif event["type"] == "error":
                await queue.put((
                    "error",
                    {
                        "error": {
                            "code": event.get("code", "AGENT_ERROR"),
                            "message": event.get("message", str(event)),
                        }
                    },
                ))
            elif event["type"] == "confirmation_required":
                await queue.put((
                    "confirmation_required",
                    {
                        "tool_name": event["tool_name"],
                        "args": event["args"],
                        "risk": event["risk"],
                        "timeout_s": event["timeout_s"],
                    },
                ))
            elif event["type"] == "done":
                await queue.put((
                    "done",
                    {"tokens_used": event.get("tokens_used", 0)},
                ))

    except Exception as exc:
        await queue.put((
            "error",
            {"error": {"code": "AGENT_STREAM_ERROR", "message": str(exc)}},
        ))
