"""Passive skill metadata CRUD and trigger matching contract tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.api.deps import _async_session_factory
from app.core.capabilities.service import create_candidate
from app.models.skill import Skill
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> dict[str, str]:
    return decode_token(headers["Authorization"].split(" ", 1)[1])


async def _promote(headers: dict[str, str]) -> None:
    payload = _identity(headers)
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()


async def _register_same_tenant_user(
    client: AsyncClient,
    tenant_name: str,
) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": tenant_name,
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_skill_candidate(headers: dict[str, str], trigger: str) -> uuid.UUID:
    identity = _identity(headers)
    async with _async_session_factory() as db:
        candidate = await create_candidate(
            db,
            tenant_id=uuid.UUID(identity["tenant_id"]),
            user_id=uuid.UUID(identity["user_id"]),
            candidate_type="skill",
            title=f"Private accepted skill {uuid.uuid4().hex}",
            body="A private passive skill.",
            source_run_id=f"run-{uuid.uuid4().hex}",
            source_kind="conversation",
            dedupe_key=f"skill:{uuid.uuid4().hex}",
            evidence={"source_evidence": ["owner asked for a reusable skill"]},
            payload={"trigger_terms": [trigger]},
        )
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


async def test_skill_crud_and_trigger_matching_are_tenant_scoped(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote(tenant_a_headers)
    await _promote(tenant_b_headers)

    suffix = uuid.uuid4().hex
    created = await client.post(
        "/api/v1/skills/",
        headers=tenant_a_headers,
        json={
            "name": f"handoff-{suffix}",
            "description": "Escalate a conversation to a human operator.",
            "trigger_terms": ["handoff", "human operator", "HANDOFF"],
            "enabled": True,
        },
    )
    disabled = await client.post(
        "/api/v1/skills/",
        headers=tenant_a_headers,
        json={
            "name": f"disabled-{suffix}",
            "trigger_terms": ["silent-match"],
            "enabled": False,
        },
    )
    tenant_b = await client.post(
        "/api/v1/skills/",
        headers=tenant_b_headers,
        json={
            "name": f"tenant-b-{suffix}",
            "trigger_terms": ["handoff"],
            "enabled": True,
        },
    )

    assert created.status_code == 201, created.text
    assert disabled.status_code == 201, disabled.text
    assert tenant_b.status_code == 201, tenant_b.text
    skill = created.json()
    assert skill["trigger_terms"] == ["handoff", "human operator"]

    listed = await client.get("/api/v1/skills/?limit=100", headers=tenant_a_headers)
    assert listed.status_code == 200
    listed_names = {item["name"] for item in listed.json()["items"]}
    assert f"handoff-{suffix}" in listed_names
    assert f"tenant-b-{suffix}" not in listed_names

    matched = await client.post(
        "/api/v1/skills/match",
        headers=tenant_a_headers,
        json={"text": "Please HANDOFF this customer to a human operator."},
    )
    assert matched.status_code == 200, matched.text
    matches = matched.json()["items"]
    assert [item["skill"]["name"] for item in matches] == [f"handoff-{suffix}"]
    assert matches[0]["matched_terms"] == ["handoff", "human operator"]

    tenant_b_match = await client.post(
        "/api/v1/skills/match",
        headers=tenant_b_headers,
        json={"text": "Please handoff this customer."},
    )
    assert tenant_b_match.status_code == 200
    assert [item["skill"]["name"] for item in tenant_b_match.json()["items"]] == [
        f"tenant-b-{suffix}"
    ]

    updated = await client.put(
        f"/api/v1/skills/{skill['id']}",
        headers=tenant_a_headers,
        json={
            "name": f"handoff-updated-{suffix}",
            "description": None,
            "trigger_terms": ["updated trigger"],
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == f"handoff-updated-{suffix}"
    assert updated.json()["description"] is None

    deleted = await client.delete(
        f"/api/v1/skills/{skill['id']}",
        headers=tenant_a_headers,
    )
    missing = await client.get(
        f"/api/v1/skills/{skill['id']}",
        headers=tenant_a_headers,
    )
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SKILL_NOT_FOUND"


async def test_skill_duplicate_name_is_tenant_local(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    await _promote(tenant_a_headers)
    await _promote(tenant_b_headers)
    name = f"shared-skill-{uuid.uuid4().hex}"

    first = await client.post(
        "/api/v1/skills/",
        headers=tenant_a_headers,
        json={"name": name, "trigger_terms": ["a"]},
    )
    duplicate = await client.post(
        "/api/v1/skills/",
        headers=tenant_a_headers,
        json={"name": name, "trigger_terms": ["b"]},
    )
    other_tenant = await client.post(
        "/api/v1/skills/",
        headers=tenant_b_headers,
        json={"name": name, "trigger_terms": ["b"]},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SKILL_EXISTS"
    assert other_tenant.status_code == 201


async def test_accepted_private_skill_match_is_user_scoped_and_legacy_scope_is_explicit(
    client: AsyncClient,
) -> None:
    tenant_name = f"accepted-skill-{uuid.uuid4().hex}"
    owner_headers = await _register_same_tenant_user(client, tenant_name)
    same_tenant_other = await _register_same_tenant_user(client, tenant_name)
    await _promote(owner_headers)
    await _promote(same_tenant_other)
    owner = _identity(owner_headers)
    tenant_id = uuid.UUID(owner["tenant_id"])
    private_trigger = f"private-trigger-{uuid.uuid4().hex}"
    hidden_trigger = f"hidden-trigger-{uuid.uuid4().hex}"
    legacy_trigger = f"legacy-trigger-{uuid.uuid4().hex}"
    candidate_id = await _seed_skill_candidate(owner_headers, private_trigger)

    accepted = await client.post(
        f"/api/v1/capability-candidates/{candidate_id}/accept",
        headers=owner_headers,
    )
    assert accepted.status_code == 200, accepted.text
    skill_id = accepted.json()["metadata"]["target"]["skill_id"]

    async with _async_session_factory() as db:
        db.add_all(
            [
                Skill(
                    tenant_id=tenant_id,
                    user_id=None,
                    scope="tenant_draft",
                    name=f"non-shared-null-user-{uuid.uuid4().hex}",
                    trigger_terms=[hidden_trigger],
                ),
                Skill(
                    tenant_id=tenant_id,
                    user_id=None,
                    scope="shared_legacy",
                    name=f"explicit-legacy-{uuid.uuid4().hex}",
                    trigger_terms=[legacy_trigger],
                ),
            ]
        )
        await db.commit()

    owner_match = await client.post(
        "/api/v1/skills/match",
        headers=owner_headers,
        json={"text": f"{private_trigger} {hidden_trigger} {legacy_trigger}"},
    )
    other_match = await client.post(
        "/api/v1/skills/match",
        headers=same_tenant_other,
        json={"text": f"{private_trigger} {hidden_trigger} {legacy_trigger}"},
    )
    other_list = await client.get("/api/v1/skills/?limit=100", headers=same_tenant_other)

    assert owner_match.status_code == 200, owner_match.text
    assert skill_id in {item["skill"]["id"] for item in owner_match.json()["items"]}
    assert other_match.status_code == 200, other_match.text
    other_names = {item["skill"]["name"] for item in other_match.json()["items"]}
    assert any(name.startswith("explicit-legacy-") for name in other_names)
    assert not any(item["skill"]["id"] == skill_id for item in other_match.json()["items"])
    assert not any(
        name.startswith("non-shared-null-user-")
        for name in {item["name"] for item in other_list.json()["items"]}
    )
