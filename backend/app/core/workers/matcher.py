"""Semantic Worker matching for Agent-callable capabilities."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities.policy import input_schema_for, risk_for, validate_input_schema
from app.models.worker import Worker, WorkerMatchFeedback, WorkerRun, WorkerVersion

EmbeddingFn = Callable[[str], list[float]] | Callable[[str], Awaitable[list[float]]]

AUTO_NOTICE_THRESHOLD = 0.78
SUGGEST_THRESHOLD = 0.58
MIN_SEMANTIC_THRESHOLD = 0.50


@dataclass(frozen=True)
class WorkerMatchDecision:
    worker_id: uuid.UUID
    version_id: uuid.UUID
    decision: str
    score: float
    semantic_score: float
    keyword_score: float
    reasons: list[str]


async def match_workers(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: str,
    input_payload: dict[str, Any] | None = None,
    gateway: Any | None = None,
    embedding_fn: EmbeddingFn | None = None,
    limit: int = 5,
) -> list[WorkerMatchDecision]:
    """Return ordered Worker match decisions.

    Semantic similarity is primary. Keyword/example overlap can raise or lower
    confidence slightly, but cannot produce an auto/suggest decision by itself.
    """

    input_payload = input_payload or {}
    rows = (
        await db.execute(
            select(Worker, WorkerVersion)
            .join(WorkerVersion, WorkerVersion.id == Worker.active_version_id)
            .where(
                Worker.tenant_id == tenant_id,
                Worker.user_id == user_id,
                Worker.enabled.is_(True),
                Worker.status == "active",
                Worker.soft_deleted_at.is_(None),
                WorkerVersion.status == "active",
            )
        )
    ).all()
    if not rows:
        return []

    query_embedding = await _embed_text(request, tenant_id=tenant_id, gateway=gateway, embedding_fn=embedding_fn)
    decisions: list[WorkerMatchDecision] = []
    for worker, version in rows:
        match_text = _worker_match_text(worker, version)
        worker_embedding = await _embed_text(match_text, tenant_id=tenant_id, gateway=gateway, embedding_fn=embedding_fn)
        semantic_score = _cosine_similarity(query_embedding, worker_embedding)
        keyword_score = _keyword_score(request, worker, version)
        score = semantic_score
        if semantic_score >= MIN_SEMANTIC_THRESHOLD:
            score += min(0.08, keyword_score * 0.08)
        score += await _feedback_modifier(db, worker.id)
        score -= _risk_penalty(worker, version)
        score = _clamp(score)

        reasons = [
            f"semantic_score={semantic_score:.3f}",
            f"keyword_score={keyword_score:.3f}",
        ]
        schema_decision = validate_input_schema(input_payload, input_schema_for(worker, version))
        if schema_decision.action == "block" and semantic_score >= AUTO_NOTICE_THRESHOLD:
            decision = "blocked_missing_input"
            reasons.append(schema_decision.reason)
        elif semantic_score < MIN_SEMANTIC_THRESHOLD:
            decision = "no_match"
            reasons.append("semantic_score_below_minimum")
        elif risk_for(worker, version) in {"high", "destructive"} or (worker.policy or {}).get("requires_confirmation"):
            decision = "needs_confirmation"
            reasons.append("risk_requires_confirmation")
        elif score >= AUTO_NOTICE_THRESHOLD:
            decision = "auto_notice"
        elif score >= SUGGEST_THRESHOLD:
            decision = "skip_and_suggest_after"
        else:
            decision = "no_match"

        decisions.append(
            WorkerMatchDecision(
                worker_id=worker.id,
                version_id=version.id,
                decision=decision,
                score=score,
                semantic_score=semantic_score,
                keyword_score=keyword_score,
                reasons=reasons,
            )
        )

    return sorted(decisions, key=lambda decision: decision.score, reverse=True)[:limit]


async def _embed_text(
    text: str,
    *,
    tenant_id: uuid.UUID,
    gateway: Any | None,
    embedding_fn: EmbeddingFn | None,
) -> list[float]:
    if embedding_fn is not None:
        value = embedding_fn(text)
        if hasattr(value, "__await__"):
            return await value  # type: ignore[no-any-return]
        return value  # type: ignore[return-value]
    if gateway is not None:
        return (await gateway.embed("default", [text], tenant_id=str(tenant_id)))[0]
    from app.main import app_state

    return (await app_state.llm_gateway.embed("default", [text], tenant_id=str(tenant_id)))[0]


def _worker_match_text(worker: Worker, version: WorkerVersion) -> str:
    trigger = worker.trigger if isinstance(worker.trigger, dict) else {}
    definition = version.definition if isinstance(version.definition, dict) else {}
    parts: list[str] = [worker.name or "", worker.description or ""]
    for key in ("examples", "keywords", "trigger_terms"):
        value = trigger.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, str):
            parts.append(value)
    for key in ("instructions", "description", "goal"):
        value = definition.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(part for part in parts if part)


def _keyword_score(request: str, worker: Worker, version: WorkerVersion) -> float:
    request_tokens = _tokens(request)
    if not request_tokens:
        return 0.0
    trigger = worker.trigger if isinstance(worker.trigger, dict) else {}
    explicit = set()
    for key in ("keywords", "trigger_terms"):
        values = trigger.get(key)
        if isinstance(values, list):
            explicit.update(token for value in values for token in _tokens(str(value)))
    candidate_tokens = explicit or _tokens(_worker_match_text(worker, version))
    if not candidate_tokens:
        return 0.0
    return len(request_tokens & candidate_tokens) / max(1, len(candidate_tokens))


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]+", text)}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size]))
    right_norm = math.sqrt(sum(value * value for value in right[:size]))
    if not left_norm or not right_norm:
        return 0.0
    return _clamp(dot / (left_norm * right_norm))


async def _feedback_modifier(db: AsyncSession, worker_id: uuid.UUID) -> float:
    feedback_rows = list(
        (
            await db.execute(
                select(WorkerMatchFeedback.feedback).where(WorkerMatchFeedback.worker_id == worker_id).limit(20)
            )
        ).scalars()
    )
    runs = list(
        (
            await db.execute(select(WorkerRun.status).where(WorkerRun.worker_id == worker_id).limit(20))
        ).scalars()
    )
    modifier = 0.0
    modifier += min(0.15, 0.04 * sum(1 for item in feedback_rows if item in {"accepted", "positive", "success"}))
    modifier -= min(0.20, 0.06 * sum(1 for item in feedback_rows if item in {"rejected", "negative", "failure"}))
    modifier += min(0.08, 0.02 * sum(1 for item in runs if item == "succeeded"))
    modifier -= min(0.15, 0.05 * sum(1 for item in runs if str(item).startswith("failed")))
    return modifier


def _risk_penalty(worker: Worker, version: WorkerVersion) -> float:
    return 0.08 if risk_for(worker, version) in {"high", "destructive"} else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
