#!/usr/bin/env python3
"""Run a fail-closed PostgreSQL backup/restore drill in the isolated test DB."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete

from app.api.deps import _async_session_factory
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_service import hash_password
from scripts.assert_test_environment import assert_isolated_test_environment
from scripts.seed import seed


_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _run(args: list[str], *, env: dict[str, str], stdout=None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        env=env,
        stdout=stdout or subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed "
            f"exit={result.returncode} args={args!r} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return result


def _psql(
    sql: str,
    *,
    database: str,
    env: dict[str, str],
    tuples_only: bool = False,
) -> str:
    args = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        env["DB_USER"],
        "-h",
        env["DB_HOST"],
        "-d",
        database,
    ]
    if tuples_only:
        args.append("-At")
    args.extend(["-c", sql])
    result = _run(args, env=env)
    return result.stdout


def _quote_ident(value: str) -> str:
    if not _DB_NAME_RE.match(value):
        raise ValueError(f"Unsafe database identifier: {value!r}")
    return f'"{value}"'


def _dump_source_database(path: Path, *, env: dict[str, str]) -> int:
    with path.open("w", encoding="utf-8") as handle:
        _run(
            [
                "pg_dump",
                "--format=plain",
                "--no-owner",
                "--no-privileges",
                "-U",
                env["DB_USER"],
                "-h",
                env["DB_HOST"],
                env["DB_NAME"],
            ],
            env=env,
            stdout=handle,
        )
    # Some client images ship a newer pg_dump than the PG16 test server. Keep
    # the drill compatible by removing PG17-only session GUCs from plain SQL.
    text = path.read_text(encoding="utf-8")
    sanitized = "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith("SET transaction_timeout")
    )
    path.write_text(sanitized + "\n", encoding="utf-8")
    return path.stat().st_size


def _restore_dump(path: Path, *, target_db: str, env: dict[str, str]) -> None:
    _run(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            env["DB_USER"],
            "-h",
            env["DB_HOST"],
            "-d",
            target_db,
            "-f",
            str(path),
        ],
        env=env,
    )


def _query_restored_counts(target_db: str, *, env: dict[str, str]) -> dict[str, int | str]:
    sql = """
SELECT
  current_database(),
  (SELECT count(*) FROM tenants WHERE name = 'default'),
  (SELECT count(*) FROM users WHERE username = 'admin'),
  (SELECT count(*) FROM agents WHERE name = 'Chainless Assistant'),
  (SELECT count(*) FROM tenants WHERE name LIKE 'restore-fixture-%'),
  (SELECT count(*) FROM users WHERE username LIKE 'restore-fixture-%');
""".strip()
    output = _psql(sql, database=target_db, env=env, tuples_only=True).strip()
    database, tenants, admins, agents, fixture_tenants, fixture_users = output.split("|")
    return {
        "database": database,
        "default_tenants": int(tenants),
        "admin_users": int(admins),
        "default_agents": int(agents),
        "fixture_tenants": int(fixture_tenants),
        "fixture_users": int(fixture_users),
    }


async def _prepare_source_fixture(name: str) -> None:
    await seed()
    async with _async_session_factory() as db:
        tenant = Tenant(name=name)
        db.add(tenant)
        await db.flush()
        db.add(
            User(
                tenant_id=tenant.id,
                username=name,
                password_hash=hash_password("restore-fixture-password"),
            )
        )
        await db.commit()


async def _delete_source_fixture(name: str) -> None:
    async with _async_session_factory() as db:
        await db.execute(delete(Tenant).where(Tenant.name == name))
        await db.commit()


def run_restore_drill(*, keep_dump: bool = False) -> dict:
    asyncio.run(assert_isolated_test_environment())

    env = {
        **os.environ,
        "PGPASSWORD": os.environ.get("DB_PASSWORD", "chainless_test"),
        "DB_USER": os.environ.get("DB_USER", "chainless"),
        "DB_HOST": os.environ.get("DB_HOST", "db-test"),
        "DB_NAME": os.environ.get("DB_NAME", "chainless_test"),
    }
    if env["DB_HOST"] != "db-test" or env["DB_NAME"] != "chainless_test":
        raise RuntimeError("restore drill requires db-test/chainless_test")

    target_db = f"chainless_restore_drill_{uuid.uuid4().hex[:12]}"
    quoted_target = _quote_ident(target_db)
    backup_path = Path(tempfile.gettempdir()) / f"{target_db}.sql"
    cleanup: dict[str, bool] = {
        "target_database_dropped": False,
        "dump_removed": False,
        "source_fixture_deleted": False,
    }
    fixture_name = f"restore-fixture-{uuid.uuid4().hex[:12]}"

    try:
        asyncio.run(_prepare_source_fixture(fixture_name))
        backup_bytes = _dump_source_database(backup_path, env=env)
        if backup_bytes <= 0:
            raise RuntimeError("restore drill backup dump is empty")

        _psql(f"CREATE DATABASE {quoted_target};", database="postgres", env=env)
        _restore_dump(backup_path, target_db=target_db, env=env)
        counts = _query_restored_counts(target_db, env=env)
        if counts["database"] != target_db:
            raise RuntimeError("restore drill queried the wrong database")
        if (
            counts["default_tenants"] != 1
            or counts["admin_users"] < 1
            or counts["default_agents"] != 1
            or counts["fixture_tenants"] != 1
            or counts["fixture_users"] != 1
        ):
            raise RuntimeError(f"restore drill restored unexpected seed counts: {counts}")

        return {
            "ok": True,
            "source_database": env["DB_NAME"],
            "restored_database": target_db,
            "backup_bytes": backup_bytes,
            "seed_counts": counts,
            "fixture_name": fixture_name,
            "cleanup": cleanup,
        }
    finally:
        try:
            try:
                asyncio.run(_delete_source_fixture(fixture_name))
                cleanup["source_fixture_deleted"] = True
            except Exception:
                cleanup["source_fixture_deleted"] = False
            _psql(
                (
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    f"WHERE datname = '{target_db}' AND pid <> pg_backend_pid();"
                ),
                database="postgres",
                env=env,
            )
            _psql(f"DROP DATABASE IF EXISTS {quoted_target};", database="postgres", env=env)
            cleanup["target_database_dropped"] = True
        finally:
            if backup_path.exists() and not keep_dump:
                backup_path.unlink()
                cleanup["dump_removed"] = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-dump", action="store_true")
    args = parser.parse_args()
    result = run_restore_drill(keep_dump=args.keep_dump)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
