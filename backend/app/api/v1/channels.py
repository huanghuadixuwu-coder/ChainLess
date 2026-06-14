"""Admin-only, tenant-scoped delivery channel settings API."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error, not_found, validation_error
from app.api.deps import get_db, require_role
from app.api.pagination import paginated_response
from app.core.audit.service import AuditRecord, write_audit_log
from app.core.channel.base import ChannelMessage
from app.core.channel.feishu import FeishuChannel
from app.core.secrets import decrypt_secret, encrypt_secret, secret_metadata
from app.models.channel_configuration import ChannelConfiguration

router = APIRouter(prefix="/channels", tags=["settings"])
Admin = Depends(require_role("admin"))
SUPPORTED_CHANNELS = {"feishu"}
SECRET_FIELDS = {"webhook_url", "secret"}
FEISHU_PUBLIC_FIELDS = {"label"}


class ChannelConfigRequest(BaseModel):
    channel_type: str
    config: Any = Field(default_factory=dict)
    enabled: bool = True


class ChannelTestRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    title: str = "Test Message"
    content: str = "This is a test message from Chainless."


class FeishuConfigRequest(BaseModel):
    webhook_url: str
    secret: str | None = None


class TestMessageRequest(BaseModel):
    webhook_url: str | None = None
    secret: str | None = None
    title: str = "Test Message"
    content: str = "This is a test message from Chainless."


def _tenant_id(user: dict) -> uuid.UUID:
    return uuid.UUID(user["tenant_id"])


def _require_supported(channel_type: str) -> None:
    if channel_type not in SUPPORTED_CHANNELS:
        raise api_error(400, "CHANNEL_NOT_SUPPORTED", f"Unsupported channel_type: {channel_type}")


async def _configuration_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, channel_type: str
) -> ChannelConfiguration:
    row = (
        await db.execute(
            select(ChannelConfiguration).where(
                ChannelConfiguration.tenant_id == tenant_id,
                ChannelConfiguration.channel_type == channel_type,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("CHANNEL_NOT_FOUND", f"Channel '{channel_type}' is not configured")
    return row


def _decrypt_secrets(row: ChannelConfiguration) -> dict[str, str]:
    return json.loads(decrypt_secret(row.encrypted_secrets))


def _serialize(row: ChannelConfiguration) -> dict:
    try:
        public_config, misplaced_secrets = _split_feishu_config(dict(row.public_config or {}))
    except HTTPException as exc:
        raise api_error(
            500,
            "UNSAFE_CHANNEL_CONFIGURATION",
            "Stored channel public configuration requires controlled migration",
        ) from exc
    if misplaced_secrets:
        raise api_error(
            500,
            "UNSAFE_CHANNEL_CONFIGURATION",
            "Stored channel public configuration requires controlled migration",
        )
    secrets = _decrypt_secrets(row)
    return {
        "id": str(row.id),
        "channel_type": row.channel_type,
        "enabled": row.enabled,
        "config": public_config,
        "secrets": {name: secret_metadata(value) for name, value in secrets.items()},
    }


def _split_feishu_config(config: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    allowed_fields = FEISHU_PUBLIC_FIELDS | SECRET_FIELDS
    if any(key not in allowed_fields for key in config):
        raise validation_error("Feishu config contains unsupported fields")
    if any(isinstance(value, (dict, list, tuple, set)) for value in config.values()):
        raise validation_error("Feishu config values must be scalar")

    public_config: dict[str, str] = {}
    if "label" in config:
        if not isinstance(config["label"], str):
            raise validation_error("Feishu label must be a string")
        public_config["label"] = config["label"]

    secrets: dict[str, str] = {}
    for key in SECRET_FIELDS:
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            raise validation_error("Feishu secret fields must be strings")
        if isinstance(value, str) and value.strip():
            secrets[key] = value.strip()
    return public_config, secrets


async def _configure(
    body: ChannelConfigRequest,
    db: AsyncSession,
    user: dict,
) -> dict:
    _require_supported(body.channel_type)
    if not isinstance(body.config, dict):
        raise validation_error("Feishu config must be an object")
    tenant_id = _tenant_id(user)
    existing = (
        await db.execute(
            select(ChannelConfiguration).where(
                ChannelConfiguration.tenant_id == tenant_id,
                ChannelConfiguration.channel_type == body.channel_type,
            )
        )
    ).scalar_one_or_none()
    previous_secrets = _decrypt_secrets(existing) if existing else {}
    public_config, incoming_secrets = _split_feishu_config(body.config)
    secrets = {**previous_secrets, **incoming_secrets}
    if body.channel_type == "feishu" and not secrets.get("webhook_url"):
        raise validation_error("webhook_url is required for Feishu")
    if existing is None:
        existing = ChannelConfiguration(
            tenant_id=tenant_id,
            channel_type=body.channel_type,
            public_config=public_config,
            encrypted_secrets=encrypt_secret(json.dumps(secrets, separators=(",", ":"))),
            enabled=body.enabled,
        )
        db.add(existing)
    else:
        existing.public_config = public_config
        existing.encrypted_secrets = encrypt_secret(json.dumps(secrets, separators=(",", ":")))
        existing.enabled = body.enabled
    await db.commit()
    await db.refresh(existing)
    return _serialize(existing)


@router.get("")
async def list_channels(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    tenant_id = _tenant_id(user)
    total = int(
        (await db.execute(select(func.count()).select_from(ChannelConfiguration).where(ChannelConfiguration.tenant_id == tenant_id))).scalar()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(ChannelConfiguration)
                .where(ChannelConfiguration.tenant_id == tenant_id)
                .order_by(ChannelConfiguration.channel_type)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return paginated_response([_serialize(row) for row in rows], total, limit, offset, request)


@router.get("/{channel_id}")
async def get_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    _require_supported(channel_id)
    return _serialize(await _configuration_or_404(db, _tenant_id(user), channel_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def configure_channel(
    body: ChannelConfigRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    return await _configure(body, db, user)


@router.post("/feishu", status_code=status.HTTP_201_CREATED)
async def configure_feishu(
    body: FeishuConfigRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """Compatibility adapter backed only by the generic DB owner."""
    return await _configure(
        ChannelConfigRequest(
            channel_type="feishu",
            config={"webhook_url": body.webhook_url, "secret": body.secret},
        ),
        db,
        user,
    )


async def _test_channel(
    channel_id: str,
    body: ChannelTestRequest,
    db: AsyncSession,
    user: dict,
) -> dict:
    _require_supported(channel_id)
    tenant_id = _tenant_id(user)
    row = await _configuration_or_404(db, tenant_id, channel_id)
    secrets = _decrypt_secrets(row)
    channel = FeishuChannel(secrets["webhook_url"], signing_secret=secrets.get("secret"))
    result = await channel.send_with_result(ChannelMessage(title=body.title, content=body.content))
    await write_audit_log(
        db,
        AuditRecord(
            tenant_id=tenant_id,
            user_id=uuid.UUID(user["user_id"]),
            action="TEST channel",
            resource_type="channels",
            resource_id=str(row.id),
            method="POST",
            path=f"/api/v1/channels/{channel_id}/test",
            status_code=200 if result["ok"] else 502,
            details={"channel_type": channel_id, "ok": bool(result["ok"])},
        ),
    )
    return {
        "status": "ok" if result["ok"] else "failed",
        "message": "Test message sent successfully" if result["ok"] else "Channel test failed",
        "delivery": {
            "ok": bool(result["ok"]),
            "attempts": result["attempts"],
            "status_code": result["status_code"],
        },
    }


@router.post("/feishu/test")
async def test_feishu(
    body: TestMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    """Compatibility adapter; optional supplied secrets update the generic owner first."""
    if body.webhook_url or body.secret:
        await _configure(
            ChannelConfigRequest(
                channel_type="feishu",
                config={"webhook_url": body.webhook_url, "secret": body.secret},
            ),
            db,
            user,
        )
    return await _test_channel(
        "feishu",
        ChannelTestRequest(title=body.title, content=body.content),
        db,
        user,
    )


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: str,
    body: ChannelTestRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Admin,
):
    return await _test_channel(channel_id, body, db, user)
