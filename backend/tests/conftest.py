"""Shared isolated test fixtures for backend API contract tests."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CHAINLESS_TESTING", "1")

from app.main import app


def pytest_sessionstart(session: pytest.Session) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if "db-test" not in database_url or "chainless_test" not in database_url:
        raise RuntimeError(
            "Refusing to run backend tests without isolated db-test DATABASE_URL."
        )

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def tenant_a_headers(client: AsyncClient) -> dict[str, str]:
    return await _register_headers(client, "tenant-a")


@pytest_asyncio.fixture
async def tenant_b_headers(client: AsyncClient) -> dict[str, str]:
    return await _register_headers(client, "tenant-b")


async def _register_headers(client: AsyncClient, prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": f"{prefix}-{suffix}",
            "username": f"user-{suffix}",
            "password": "secret123",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
