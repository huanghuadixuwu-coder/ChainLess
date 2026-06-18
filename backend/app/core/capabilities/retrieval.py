"""Source-traced capability retrieval for Agent planning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory.persistent import get_memories_for_session
from app.core.workers.matcher import match_workers
from app.models.memory import Memory
from app.models.skill import Skill
from app.models.worker import Worker, WorkerVersion

SHARED_SKILL_SCOPES = ("shared_legacy",)
DEFAULT_MEMORY_LIMIT = 5
DEFAULT_SKILL_LIMIT = 5
DEFAULT_WORKER_LIMIT = 3
SKILL_CANDIDATE_SCAN_LIMIT = 50
MAX_FIELD_CHARS = 700
MAX_SOURCE_VALUE_CHARS = 240


@dataclass(frozen=True)
class CapabilityMemory:
    id: uuid.UUID
    name: str
    content: str
    memory_type: str
    scope: str
    source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilitySkill:
    id: uuid.UUID
    name: str
    description: str
    scope: str
    trigger_terms: list[str]
    matched_terms: list[str]
    source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityWorkerMatch:
    worker_id: uuid.UUID
    version_id: uuid.UUID
    worker_name: str
    description: str
    decision: str
    score: float
    semantic_score: float
    keyword_score: float
    reasons: list[str]
    source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityContext:
    task_text: str
    memories: list[CapabilityMemory]
    skills: list[CapabilitySkill]
    workers: list[CapabilityWorkerMatch]
    hard_guards: list[str]


async def get_capability_context(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    task_text: str,
    gateway: Any | None = None,
    memory_limit: int = DEFAULT_MEMORY_LIMIT,
    skill_limit: int = DEFAULT_SKILL_LIMIT,
    worker_limit: int = DEFAULT_WORKER_LIMIT,
) -> CapabilityContext:
    """Return accepted, user-scoped capabilities for one planning turn.

    Capability Candidates are intentionally not queried here. They remain inert
    until accepted into Memory, Skill, or Worker source-of-truth tables.
    """

    tenant_uuid = _as_uuid(tenant_id)
    user_uuid = _as_uuid(user_id)
    bounded_task = _bound(task_text)
    memories = await _retrieve_memories(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        task_text=task_text,
        limit=memory_limit,
    )
    skills = await _retrieve_skills(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        task_text=task_text,
        limit=skill_limit,
    )
    workers = await _retrieve_workers(
        db,
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        task_text=task_text,
        gateway=gateway,
        limit=worker_limit,
    )
    return CapabilityContext(
        task_text=bounded_task,
        memories=memories,
        skills=skills,
        workers=workers,
        hard_guards=_hard_guards(),
    )


async def _retrieve_memories(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    task_text: str,
    limit: int,
) -> list[CapabilityMemory]:
    rows = await get_memories_for_session(
        db,
        str(tenant_id),
        task_text,
        limit=max(0, min(limit, DEFAULT_MEMORY_LIMIT)),
        user_id=str(user_id),
        include_userless=False,
    )
    return [_memory_record(memory, user_id=user_id) for memory in rows]


async def _retrieve_skills(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    task_text: str,
    limit: int,
) -> list[CapabilitySkill]:
    rows = list(
        (
            await db.execute(
                select(Skill)
                .where(
                    Skill.tenant_id == tenant_id,
                    Skill.enabled.is_(True),
                    _visible_skill_condition(user_id),
                )
                .order_by(Skill.name)
                .limit(SKILL_CANDIDATE_SCAN_LIMIT)
            )
        ).scalars()
    )
    normalized_text = task_text.casefold()
    matches: list[CapabilitySkill] = []
    for skill in rows:
        matched_terms = [
            term
            for term in skill.trigger_terms or []
            if term and term.casefold() in normalized_text
        ]
        if not matched_terms:
            continue
        matches.append(_skill_record(skill, matched_terms=matched_terms))
        if len(matches) >= max(0, min(limit, DEFAULT_SKILL_LIMIT)):
            break
    return matches


async def _retrieve_workers(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    task_text: str,
    gateway: Any | None,
    limit: int,
) -> list[CapabilityWorkerMatch]:
    if not task_text.strip():
        return []
    decisions = await match_workers(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        request=task_text,
        input_payload={"request": task_text},
        gateway=gateway,
        limit=max(0, min(limit, DEFAULT_WORKER_LIMIT)),
    )
    records: list[CapabilityWorkerMatch] = []
    for decision in decisions:
        if decision.decision == "no_match":
            continue
        worker = await db.get(Worker, decision.worker_id)
        version = await db.get(WorkerVersion, decision.version_id)
        if worker is None or version is None:
            continue
        records.append(
            CapabilityWorkerMatch(
                worker_id=decision.worker_id,
                version_id=decision.version_id,
                worker_name=_bound(worker.name),
                description=_bound(worker.description or ""),
                decision=decision.decision,
                score=round(float(decision.score), 3),
                semantic_score=round(float(decision.semantic_score), 3),
                keyword_score=round(float(decision.keyword_score), 3),
                reasons=[_bound(reason, 160) for reason in decision.reasons[:5]],
                source={
                    "source_type": "worker",
                    "worker_id": str(worker.id),
                    "worker_version_id": str(version.id),
                    "semantic_score": round(float(decision.semantic_score), 3),
                    "keyword_score": round(float(decision.keyword_score), 3),
                },
            )
        )
    return records


def _memory_record(memory: Memory, *, user_id: uuid.UUID) -> CapabilityMemory:
    metadata = memory.meta_data if isinstance(memory.meta_data, dict) else {}
    source = _source_from_metadata(
        metadata,
        defaults={
            "source_type": "memory",
            "memory_id": str(memory.id),
            "scope": "private" if memory.user_id == user_id else "tenant_legacy",
        },
    )
    return CapabilityMemory(
        id=memory.id,
        name=_bound(memory.name, 180),
        content=_bound(memory.content or ""),
        memory_type=memory.type,
        scope=str(source.get("scope") or ("private" if memory.user_id else "tenant_legacy")),
        source=source,
    )


def _skill_record(skill: Skill, *, matched_terms: list[str]) -> CapabilitySkill:
    metadata = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
    source = _source_from_metadata(
        metadata,
        defaults={
            "source_type": "skill",
            "skill_id": str(skill.id),
            "scope": skill.scope,
        },
    )
    return CapabilitySkill(
        id=skill.id,
        name=_bound(skill.name, 180),
        description=_bound(skill.description or ""),
        scope=skill.scope,
        trigger_terms=[_bound(term, 120) for term in skill.trigger_terms or []],
        matched_terms=[_bound(term, 120) for term in matched_terms],
        source=source,
    )


def _visible_skill_condition(user_id: uuid.UUID):
    return ((Skill.user_id == user_id) & (Skill.scope == "private")) | (
        Skill.user_id.is_(None) & Skill.scope.in_(SHARED_SKILL_SCOPES)
    )


def _source_from_metadata(metadata: dict[str, Any], *, defaults: dict[str, Any]) -> dict[str, Any]:
    source = metadata.get("source") if isinstance(metadata.get("source"), dict) else {}
    merged = {**defaults, **source}
    return {
        str(key): _bound(str(value), MAX_SOURCE_VALUE_CHARS)
        for key, value in merged.items()
        if value is not None
    }


def _hard_guards() -> list[str]:
    return [
        "The current user request has priority over Memory and Skill guidance when they conflict.",
        "Workers are executable only when active, enabled, version-active, verified, and user-confirmed.",
        "Hard guards are non-overridable: tenant/user isolation, allowed tools, risk confirmation, and destructive confirmations.",
        "Inactive Capability Candidates are inert until explicitly accepted by the user.",
    ]


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _bound(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 15)] + " [truncated]"
