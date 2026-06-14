#!/usr/bin/env python3
"""Probe live Nginx, admin boundaries, audit, and sandbox execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx
from sqlalchemy import delete

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from app.api.deps import _async_session_factory
from app.config import settings
from app.core.sandbox.manager import SandboxManager
from app.models.tenant import Tenant


def _expect_status(response: httpx.Response, status_code: int, label: str) -> None:
    if response.status_code != status_code:
        raise AssertionError(
            f"{label} returned {response.status_code}, expected {status_code}: {response.text}"
        )


async def _delete_probe_tenant(tenant_name: str) -> None:
    async with _async_session_factory() as db:
        await db.execute(delete(Tenant).where(Tenant.name == tenant_name))
        await db.commit()


async def probe(base_url: str) -> None:
    suffix = int(time.time() * 1000)
    title = f"W10 production boundary probe {suffix}"
    tenant_name = f"w5-boundary-probe-{suffix}"
    member_headers: dict[str, str] = {}
    admin_headers: dict[str, str] = {}
    conversation_id: str | None = None
    auth_boundary: dict[str, int | bool | str] = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        try:
            health = await client.get("/api/v1/health")
            health.raise_for_status()
            assert health.json()["status"] == "ok", health.text
            assert health.headers["x-content-type-options"] == "nosniff"
            assert health.headers["x-frame-options"] == "DENY"

            no_auth_health = await client.get("/api/v1/system/health")
            no_auth_metrics = await client.get("/api/v1/system/metrics")
            _expect_status(no_auth_health, 401, "no-auth detailed health")
            _expect_status(no_auth_metrics, 401, "no-auth system metrics")

            member = await client.post(
                "/api/v1/auth/register",
                json={
                    "tenant_name": tenant_name,
                    "username": "member",
                    "password": "boundary-secret-123",
                },
            )
            member.raise_for_status()
            member_headers = {
                "Authorization": f"Bearer {member.json()['access_token']}"
            }
            member_health = await client.get(
                "/api/v1/system/health", headers=member_headers
            )
            member_metrics = await client.get(
                "/api/v1/system/metrics", headers=member_headers
            )
            member_memory = await client.post(
                "/api/v1/memories/",
                headers=member_headers,
                json={
                    "type": "user",
                    "name": "member-must-not-write",
                    "content": "member writes are forbidden",
                },
            )
            _expect_status(member_health, 403, "member detailed health")
            _expect_status(member_metrics, 403, "member system metrics")
            _expect_status(member_memory, 403, "member memory mutation")

            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "tenant_name": "default",
                    "username": "admin",
                    "password": settings.bootstrap_admin_password,
                },
            )
            login.raise_for_status()
            admin_headers = {
                "Authorization": f"Bearer {login.json()['access_token']}"
            }

            admin_health = await client.get(
                "/api/v1/system/health", headers=admin_headers
            )
            admin_metrics = await client.get(
                "/api/v1/system/metrics", headers=admin_headers
            )
            admin_health.raise_for_status()
            admin_metrics.raise_for_status()
            assert admin_health.json()["status"] == "ok", admin_health.text
            assert "chainless_db_up" in admin_metrics.text
            auth_boundary = {
                "public_health": health.status_code,
                "no_auth_health": no_auth_health.status_code,
                "no_auth_metrics": no_auth_metrics.status_code,
                "member_health": member_health.status_code,
                "member_metrics": member_metrics.status_code,
                "member_memory": member_memory.status_code,
                "admin_health": admin_health.status_code,
                "admin_metrics": admin_metrics.status_code,
                "metrics_has_db": True,
            }

            created = await client.post(
                "/api/v1/conversations/",
                headers=admin_headers,
                json={"title": title},
            )
            created.raise_for_status()
            conversation_id = created.json()["id"]

            audit = await client.get("/api/v1/audit/?limit=100", headers=admin_headers)
            audit.raise_for_status()
            create_rows = [
                item
                for item in audit.json()["items"]
                if item["method"] == "POST" and item["path"] == "/api/v1/conversations/"
            ]
            assert create_rows, audit.text
            assert title not in json.dumps(create_rows, ensure_ascii=False)
        finally:
            if conversation_id and admin_headers:
                deleted = await client.delete(
                    f"/api/v1/conversations/{conversation_id}?purge=true",
                    headers=admin_headers,
                )
                deleted.raise_for_status()
                conversation_id = None
            await _delete_probe_tenant(tenant_name)

    manager = SandboxManager(settings)
    container_id = await manager.allocate()
    output: list[str] = []
    try:
        async for event in manager.execute(container_id, "print(6 * 7)", timeout=10):
            if event["type"] in {"stdout", "stderr"}:
                output.append(event["data"])
            if event["type"] == "error":
                raise RuntimeError(event["data"])
    finally:
        await manager.recycle(container_id)
        sandbox_health = await manager.get_proxy_health()
        await manager.close()

    rendered = "".join(output).strip()
    assert rendered == "42", rendered
    assert sandbox_health["pool_size"] >= 1
    assert sandbox_health["total_containers"] <= settings.sandbox_pool_max
    print(
        json.dumps(
            {
                "ok": True,
                "base_url": base_url,
                "auth_boundary": auth_boundary,
                "audit": "tenant-scoped-and-body-free",
                "sandbox_output": rendered,
                "sandbox_health": sandbox_health,
                "cleanup": "conversation-and-temp-tenant-deleted",
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://nginx")
    args = parser.parse_args()
    asyncio.run(probe(args.base_url.rstrip("/")))


if __name__ == "__main__":
    main()
