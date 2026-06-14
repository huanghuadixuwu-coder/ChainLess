"""Admin-only passive skill metadata and trigger matching API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.models.skill import Skill

router = APIRouter(prefix="/skills", tags=["skills"])
Admin = Depends(require_role("admin"))


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    trigger_terms: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name cannot be blank")
        return name

    @field_validator("trigger_terms")
    @classmethod
    def _terms_are_bounded(cls, value: list[str]) -> list[str]:
        return _normalize_terms(value)


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    trigger_terms: list[str] | None = Field(default=None, max_length=100)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("name cannot be blank")
        return name

    @field_validator("trigger_terms")
    @classmethod
    def _terms_are_bounded(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_terms(value)


class TriggerMatchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16000)


def _tenant_id(user: dict) -> uuid.UUID:
    return uuid.UUID(user["tenant_id"])


def _normalize_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for term in terms:
        if not isinstance(term, str):
            raise ValueError("trigger_terms must contain strings")
        cleaned = " ".join(term.strip().split())
        if not cleaned:
            continue
        if len(cleaned) > 120:
            raise ValueError("trigger_terms entries must be 120 characters or less")
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(cleaned)
    return normalized


async def _skill_or_404(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    skill_id: uuid.UUID,
) -> Skill:
    skill = (
        await db.execute(
            select(Skill).where(
                Skill.id == skill_id,
                Skill.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if skill is None:
        raise not_found("SKILL_NOT_FOUND", "Skill not found")
    return skill


def _serialize(skill: Skill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "tenant_id": str(skill.tenant_id),
        "name": skill.name,
        "description": skill.description,
        "trigger_terms": list(skill.trigger_terms or []),
        "enabled": skill.enabled,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """Create passive skill metadata for the current tenant."""
    tenant_id = _tenant_id(user)
    skill = Skill(
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        trigger_terms=body.trigger_terms,
        enabled=body.enabled,
    )
    db.add(skill)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "SKILL_EXISTS", "Skill name already exists") from exc
    await db.refresh(skill)
    return _serialize(skill)


@router.get("/")
async def list_skills(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """List passive skill metadata for the current tenant."""
    tenant_id = _tenant_id(user)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Skill).where(Skill.tenant_id == tenant_id)
            )
        ).scalar()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(Skill)
                .where(Skill.tenant_id == tenant_id)
                .order_by(Skill.name)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return paginated_response(
        [_serialize(skill) for skill in rows],
        total,
        limit,
        offset,
        request,
    )


@router.post("/match")
async def match_skills(
    body: TriggerMatchRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """Return enabled tenant skills whose trigger terms appear in the text."""
    tenant_id = _tenant_id(user)
    rows = list(
        (
            await db.execute(
                select(Skill)
                .where(
                    Skill.tenant_id == tenant_id,
                    Skill.enabled.is_(True),
                )
                .order_by(Skill.name)
            )
        ).scalars()
    )
    normalized_text = body.text.casefold()
    matches: list[dict[str, Any]] = []
    for skill in rows:
        matched_terms = [
            term
            for term in skill.trigger_terms or []
            if term and term.casefold() in normalized_text
        ]
        if matched_terms:
            matches.append(
                {
                    "skill": _serialize(skill),
                    "matched_terms": matched_terms,
                }
            )
    return {"items": matches, "total": len(matches)}


@router.get("/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    return _serialize(await _skill_or_404(db, _tenant_id(user), skill_id))


@router.put("/{skill_id}")
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    skill = await _skill_or_404(db, _tenant_id(user), skill_id)
    if body.name is not None:
        skill.name = body.name
    if "description" in body.model_fields_set:
        skill.description = body.description
    if body.trigger_terms is not None:
        skill.trigger_terms = body.trigger_terms
    if body.enabled is not None:
        skill.enabled = body.enabled
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "SKILL_EXISTS", "Skill name already exists") from exc
    await db.refresh(skill)
    return _serialize(skill)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    skill = await _skill_or_404(db, _tenant_id(user), skill_id)
    await db.delete(skill)
    await db.commit()
    return None
