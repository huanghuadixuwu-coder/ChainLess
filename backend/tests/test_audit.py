"""Audit persistence, access control, isolation, and redaction tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.api.deps import _async_session_factory
from app.core.audit.service import AuditRecord, write_audit_log
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _promote_to_admin(headers: dict[str, str]) -> None:
    token = headers["Authorization"].split(" ", 1)[1]
    payload = decode_token(token)
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(str(payload["user_id"])))
            .values(role="admin")
        )
        await db.commit()


async def test_mutation_is_audited_without_secret_body(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    title = f"audit-secret-not-stored-{uuid.uuid4().hex}"

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": title},
    )
    assert created.status_code == 200, created.text

    response = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    assert response.status_code == 200, response.text
    mutation = next(
        item
        for item in response.json()["items"]
        if item["path"] == "/api/v1/conversations/" and item["method"] == "POST"
    )
    assert mutation["status_code"] == 200
    assert mutation["details"]["audited_without_body"] is True
    assert title not in str(mutation)


async def test_mutation_audit_never_persists_or_returns_raw_query_secrets(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _promote_to_admin(tenant_a_headers)
    api_key = f"raw-api-key-{uuid.uuid4().hex}"
    client_secret = f"raw-client-secret-{uuid.uuid4().hex}"

    created = await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        params={"api_key": api_key, "client_secret": client_secret, "safe": "visible"},
        json={"title": "query metadata only"},
    )
    assert created.status_code == 200, created.text

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.path == "/api/v1/conversations/")
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().first()
    response = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    combined = f"{row.details if row else ''} {response.text} {caplog.text}"

    assert row is not None
    assert row.details == {
        "query_present": True,
        "query_parameter_count": 3,
        "audited_without_body": True,
    }
    assert api_key not in combined
    assert client_secret not in combined
    assert "visible" not in combined


async def test_mutation_audit_hashes_controllable_headers_without_raw_secret(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _promote_to_admin(tenant_a_headers)
    user_agent_secret = f"ua-secret-{uuid.uuid4().hex}"
    request_id_secret = f"request-id-secret-{uuid.uuid4().hex}"
    headers = {
        **tenant_a_headers,
        "User-Agent": user_agent_secret,
        "X-Request-ID": request_id_secret,
    }

    created = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"title": "header audit metadata"},
    )
    assert created.status_code == 200, created.text

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.path == "/api/v1/conversations/")
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().first()
    response = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    combined = f"{row.user_agent if row else ''} {row.request_id if row else ''} {response.text} {caplog.text}"

    assert row is not None
    assert row.user_agent.startswith("hmac-sha256:")
    assert row.request_id.startswith("hmac-sha256:")
    assert len(row.user_agent) <= 40
    assert len(row.request_id) <= 40
    assert user_agent_secret not in combined
    assert request_id_secret not in combined


async def test_audit_service_hashes_header_fields_at_persistence_boundary() -> None:
    raw_user_agent = f"service-ua-secret-{uuid.uuid4().hex}"
    raw_request_id = f"service-request-secret-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        row = await write_audit_log(
            db,
            AuditRecord(
                action="TEST audit-sanitize",
                method="POST",
                path="/internal/test",
                status_code=200,
                user_agent=raw_user_agent,
                request_id=raw_request_id,
            ),
        )

    assert row.user_agent.startswith("hmac-sha256:")
    assert row.request_id.startswith("hmac-sha256:")
    assert raw_user_agent not in row.user_agent
    assert raw_request_id not in row.request_id


async def test_audit_api_is_admin_only_and_tenant_scoped(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    tenant_b_headers: dict[str, str],
) -> None:
    forbidden = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    assert forbidden.status_code == 403

    await _promote_to_admin(tenant_a_headers)
    await _promote_to_admin(tenant_b_headers)
    await client.post(
        "/api/v1/conversations/",
        headers=tenant_a_headers,
        json={"title": "tenant-a-audit-only"},
    )

    tenant_a = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    tenant_b = await client.get("/api/v1/audit/", headers=tenant_b_headers)
    assert tenant_a.status_code == 200
    assert tenant_b.status_code == 200
    tenant_a_id = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])["tenant_id"]
    assert all(item["tenant_id"] == tenant_a_id for item in tenant_a.json()["items"])
    assert all(item["tenant_id"] != tenant_a_id for item in tenant_b.json()["items"])


async def test_admin_mutations_on_provider_default_agent_and_tool_configuration_are_body_free(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    provider_secret = f"audit-secret-{uuid.uuid4().hex}"

    created_default = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "audit-primary",
            "api_base": "https://provider.example/v1",
            "api_key": provider_secret,
            "model": "audit-model",
            "is_default": True,
        },
    )
    assert created_default.status_code == 201, created_default.text

    created_secondary = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "audit-secondary",
            "api_base": "https://provider.example/v2",
            "api_key": f"other-{provider_secret}",
            "model": "audit-model",
        },
    )
    assert created_secondary.status_code == 201, created_secondary.text

    default_switched = await client.post(
        "/api/v1/llm-providers/audit-secondary/default",
        headers=tenant_a_headers,
    )
    assert default_switched.status_code == 200, default_switched.text

    created_agent = await client.post(
        "/api/v1/agents/",
        headers=tenant_a_headers,
        json={
            "name": "audit-agent",
            "system_prompt": "Use safe defaults.",
            "llm_provider": "audit-secondary",
            "is_active": True,
        },
    )
    assert created_agent.status_code == 200, created_agent.text

    tool_update = await client.patch(
        "/api/v1/tools/shell_exec/configuration",
        headers=tenant_a_headers,
        json={"enabled": True, "risk_override": "safe"},
    )
    assert tool_update.status_code == 200, tool_update.text

    audit_rows = (await client.get("/api/v1/audit/", headers=tenant_a_headers)).json()["items"]
    default_row = next(
        (row for row in audit_rows if row["path"] == "/api/v1/llm-providers/{name}/default"),
        None,
    )
    agent_row = next(
        (row for row in audit_rows if row["path"] == "/api/v1/agents/"),
        None,
    )
    tool_row = next(
        (row for row in audit_rows if row["path"] == "/api/v1/tools/{name}/configuration"),
        None,
    )

    assert default_row is not None
    assert agent_row is not None
    assert tool_row is not None

    assert default_row["method"] == "POST"
    assert agent_row["method"] == "POST"
    assert tool_row["method"] == "PATCH"
    assert default_row["details"]["audited_without_body"] is True
    assert agent_row["details"]["audited_without_body"] is True
    assert tool_row["details"]["audited_without_body"] is True

    combined = f"{default_row}{agent_row}{tool_row}"
    assert provider_secret not in combined
    assert f"other-{provider_secret}" not in combined
    for secret_meta in (
        created_default.json()["api_key"],
        created_secondary.json()["api_key"],
    ):
        for value in secret_meta.values():
            if isinstance(value, str):
                assert value not in combined


async def test_login_security_decision_is_tenant_scoped(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    await _promote_to_admin(tenant_a_headers)
    payload = decode_token(tenant_a_headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        tenant_name = (
            await db.execute(
                select(Tenant.name).where(Tenant.id == uuid.UUID(payload["tenant_id"]))
            )
        ).scalar_one()

    failed_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_name": tenant_name,
            "username": "missing-user",
            "password": "not-stored",
        },
    )
    assert failed_login.status_code == 401

    response = await client.get("/api/v1/audit/", headers=tenant_a_headers)
    login_rows = [
        item for item in response.json()["items"] if item["path"] == "/api/v1/auth/login"
    ]
    assert login_rows
    assert login_rows[0]["tenant_id"] == payload["tenant_id"]
    assert "not-stored" not in str(login_rows[0])
