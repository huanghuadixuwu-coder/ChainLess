"""Passive skill metadata CRUD and trigger matching contract tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.api.deps import _async_session_factory
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _promote(headers: dict[str, str]) -> None:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()


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
