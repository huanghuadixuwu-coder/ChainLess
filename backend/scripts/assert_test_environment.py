"""Fail-closed guard for destructive or tenant-creating test flows."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from sqlalchemy import text

from app.api.deps import _async_session_factory
from app.config import settings


@dataclass(frozen=True)
class TestEnvironmentIdentity:
    ok: bool
    app_env: str
    chainless_testing: str
    database_host: str
    database_name: str
    connected_database: str
    connected_user: str
    redis_host: str


def _parse_database_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.replace("postgresql+asyncpg://", "postgresql://", 1))
    database = parsed.path.lstrip("/").split("?", 1)[0]
    return parsed.hostname or "", database


def _parse_redis_url(value: str) -> str:
    parsed = urlsplit(value)
    return parsed.hostname or ""


def _redacted_database_identity() -> dict[str, str]:
    host, database = _parse_database_url(settings.database_url)
    return {"host": host, "database": database}


async def assert_isolated_test_environment() -> TestEnvironmentIdentity:
    """Raise unless the current process is connected to the isolated test stack."""
    failures: list[str] = []
    db_host, db_name = _parse_database_url(settings.database_url)
    redis_host = _parse_redis_url(settings.redis_url)
    chainless_testing = os.environ.get("CHAINLESS_TESTING", "")

    if settings.app_env.lower() != "test":
        failures.append("APP_ENV must be test")
    if chainless_testing != "1":
        failures.append("CHAINLESS_TESTING must be 1")
    if db_host != "db-test":
        failures.append("DATABASE_URL host must be db-test")
    if db_name != "chainless_test":
        failures.append("DATABASE_URL database must be chainless_test")
    if redis_host != "redis-test":
        failures.append("REDIS_URL host must be redis-test")

    connected_database = ""
    connected_user = ""
    try:
        async with _async_session_factory() as db:
            row = (
                await db.execute(
                    text(
                        "select current_database() as database, "
                        "current_user as username"
                    )
                )
            ).mappings().one()
            connected_database = str(row["database"])
            connected_user = str(row["username"])
    except Exception as exc:
        failures.append(f"database identity query failed: {type(exc).__name__}")

    if connected_database and connected_database != "chainless_test":
        failures.append("connected database must be chainless_test")

    if failures:
        redacted = _redacted_database_identity()
        raise RuntimeError(
            "Refusing to run tenant-creating test flow outside isolated test "
            f"environment: {', '.join(failures)}; database={redacted}"
        )

    return TestEnvironmentIdentity(
        ok=True,
        app_env=settings.app_env,
        chainless_testing=chainless_testing,
        database_host=db_host,
        database_name=db_name,
        connected_database=connected_database,
        connected_user=connected_user,
        redis_host=redis_host,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print JSON identity.")
    args = parser.parse_args()

    identity = await assert_isolated_test_environment()
    if args.json:
        print(json.dumps(asdict(identity), sort_keys=True))
    else:
        print("isolated test environment ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
