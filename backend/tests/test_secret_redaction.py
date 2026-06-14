"""Encrypted-at-rest and write-only secret settings contracts."""

from __future__ import annotations

import json
import uuid
import logging
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.api.deps import _async_session_factory
from app.core.llm.gateway import LLMGateway
from app.core.channel.feishu import FeishuChannel
from app.core.channel.base import ChannelMessage
from app.core.secrets import decrypt_secret, encrypt_secret
from app.models.audit_log import AuditLog
from app.models.channel_configuration import ChannelConfiguration
from app.models.llm_provider import LLMProvider
from app.models.user import User
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


async def _promote(headers: dict[str, str]) -> dict:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    async with _async_session_factory() as db:
        await db.execute(
            update(User)
            .where(User.id == uuid.UUID(payload["user_id"]))
            .values(role="admin")
        )
        await db.commit()
    return payload


async def test_provider_secret_is_encrypted_masked_preserved_and_runtime_default(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = await _promote(tenant_a_headers)
    secret = f"provider-secret-{uuid.uuid4().hex}"
    created = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "runtime-provider",
            "api_base": "https://provider.example/v1",
            "api_key": secret,
            "model": "runtime-model",
            "is_default": True,
        },
    )
    assert created.status_code == 201, created.text
    assert secret not in created.text
    assert created.json()["api_key"]["mask"] == "********"

    updated = await client.put(
        "/api/v1/llm-providers/runtime-provider",
        headers=tenant_a_headers,
        json={"api_key": "", "model": "runtime-model-v2"},
    )
    listed = await client.get("/api/v1/llm-providers/", headers=tenant_a_headers)
    assert updated.status_code == 200, updated.text
    assert secret not in updated.text + listed.text

    selected_secret = f"selected-secret-{uuid.uuid4().hex}"
    second = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": "selected-provider",
            "api_base": "https://selected.example/v1",
            "api_key": selected_secret,
            "model": "selected-model",
        },
    )
    selected = await client.post(
        "/api/v1/llm-providers/selected-provider/default",
        headers=tenant_a_headers,
    )
    assert second.status_code == 201 and selected.status_code == 200
    assert selected_secret not in second.text + selected.text

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(LLMProvider).where(
                    LLMProvider.tenant_id == uuid.UUID(identity["tenant_id"]),
                    LLMProvider.name == "runtime-provider",
                )
            )
        ).scalar_one()
        assert row.encrypted_api_key != secret
        assert secret not in row.encrypted_api_key
        assert decrypt_secret(row.encrypted_api_key) == secret

    captured: dict = {}

    class Response:
        def __aiter__(self):
            async def values():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="runtime-ok", tool_calls=None))]
                )
            return values()

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("app.core.llm.gateway.litellm.acompletion", fake_completion)
    output = [
        event
        async for event in LLMGateway().chat_stream(
            "default",
            [{"role": "user", "content": "test"}],
            tenant_id=identity["tenant_id"],
        )
    ]
    assert output == [{"type": "text", "content": "runtime-ok"}]
    assert captured["api_key"] == selected_secret
    assert captured["model"] == "openai/selected-model"

    deleted = await client.delete(
        "/api/v1/llm-providers/selected-provider", headers=tenant_a_headers
    )
    fallback = await LLMGateway().get_config(identity["tenant_id"], "default")
    assert deleted.status_code == 204
    assert fallback["name"] == "runtime-provider"
    assert fallback["api_key"] == secret


async def test_channel_secrets_are_encrypted_masked_preserved_and_test_redacted(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = await _promote(tenant_a_headers)
    webhook = f"https://open.feishu.cn/{uuid.uuid4().hex}"
    signing_secret = f"sign-{uuid.uuid4().hex}"
    created = await client.post(
        "/api/v1/channels",
        headers=tenant_a_headers,
        json={
            "channel_type": "feishu",
            "config": {"webhook_url": webhook, "secret": signing_secret, "label": "ops"},
        },
    )
    assert created.status_code == 201, created.text
    assert webhook not in created.text
    assert signing_secret not in created.text
    assert created.json()["config"] == {"label": "ops"}

    preserved = await client.post(
        "/api/v1/channels",
        headers=tenant_a_headers,
        json={
            "channel_type": "feishu",
            "config": {"webhook_url": "", "secret": "", "label": "updated"},
        },
    )
    assert preserved.status_code == 201
    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(ChannelConfiguration).where(
                    ChannelConfiguration.tenant_id == uuid.UUID(identity["tenant_id"])
                )
            )
        ).scalar_one()
        assert webhook not in row.encrypted_secrets
        assert signing_secret not in row.encrypted_secrets
        plaintext = decrypt_secret(row.encrypted_secrets)
        assert webhook in plaintext and signing_secret in plaintext

    async def fake_send(self, message):
        assert self.signing_secret == signing_secret
        return {"ok": False, "attempts": 1, "status_code": None, "error": webhook}

    monkeypatch.setattr("app.api.v1.channels.FeishuChannel.send_with_result", fake_send)
    tested = await client.post(
        "/api/v1/channels/feishu/test",
        headers=tenant_a_headers,
        json={"title": "safe", "content": "safe"},
    )
    assert tested.status_code == 200
    assert webhook not in tested.text and signing_secret not in tested.text

    async with _async_session_factory() as db:
        audits = list(
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.tenant_id == uuid.UUID(identity["tenant_id"]))
                )
            ).scalars()
        )
    audit_text = str([row.details for row in audits])
    assert webhook not in audit_text and signing_secret not in audit_text


async def test_feishu_signing_secret_adds_deterministic_signature_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signing_secret = "feishu-signing-secret"
    captured: dict = {}

    class SuccessfulClient:
        async def post(self, url, json):
            captured["url"] = url
            captured["body"] = json
            return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr("app.core.channel.feishu._get_client", lambda: SuccessfulClient())
    monkeypatch.setattr("app.core.channel.feishu.time.time", lambda: 1_700_000_000)

    result = await FeishuChannel(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        signing_secret=signing_secret,
    ).send_with_result(ChannelMessage(title="signed", content="payload"))

    assert result["ok"] is True
    assert captured["body"]["timestamp"] == "1700000000"
    assert captured["body"]["sign"] == "NgRjKpbVvglmhYtghJqSGy1Bn9RBAcQV0XePujxQEAM="
    assert signing_secret not in json.dumps(captured["body"])


async def test_feishu_without_signing_secret_preserves_unsigned_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class SuccessfulClient:
        async def post(self, url, json):
            captured["body"] = json
            return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr("app.core.channel.feishu._get_client", lambda: SuccessfulClient())

    result = await FeishuChannel(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    ).send_with_result(ChannelMessage(title="unsigned", content="payload"))

    assert result["ok"] is True
    assert "timestamp" not in captured["body"]
    assert "sign" not in captured["body"]


async def test_feishu_generic_config_rejects_unknown_nested_and_non_scalar_public_values(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = await _promote(tenant_a_headers)
    webhook = f"https://open.feishu.cn/{uuid.uuid4().hex}"
    secret = f"nested-secret-{uuid.uuid4().hex}"

    for config in (
        {"webhook_url": webhook, "unknown": "value"},
        {"webhook_url": webhook, "meta": {"webhook_url": secret}},
        {"webhook_url": webhook, "label": [secret]},
        {"webhook_url": {"value": secret}},
        [secret],
        secret,
    ):
        response = await client.post(
            "/api/v1/channels",
            headers=tenant_a_headers,
            json={"channel_type": "feishu", "config": config},
        )
        assert response.status_code == 422
        assert webhook not in response.text
        assert secret not in response.text

    async with _async_session_factory() as db:
        row = (
            await db.execute(
                select(ChannelConfiguration).where(
                    ChannelConfiguration.tenant_id == uuid.UUID(identity["tenant_id"])
                )
            )
        ).scalar_one_or_none()
    assert row is None


async def test_historical_unsafe_feishu_public_config_is_never_returned(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
) -> None:
    identity = await _promote(tenant_a_headers)
    secret = f"historical-public-secret-{uuid.uuid4().hex}"
    async with _async_session_factory() as db:
        db.add(
            ChannelConfiguration(
                tenant_id=uuid.UUID(identity["tenant_id"]),
                channel_type="feishu",
                public_config={"meta": {"webhook_url": secret}},
                encrypted_secrets=encrypt_secret(
                    json.dumps({"webhook_url": "https://open.feishu.cn/safe"})
                ),
                enabled=True,
            )
        )
        await db.commit()

    response = await client.get("/api/v1/channels/feishu", headers=tenant_a_headers)

    assert response.status_code == 500
    assert secret not in response.text


async def test_validation_error_and_provider_test_never_echo_secret(
    client: AsyncClient,
    tenant_a_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = await _promote(tenant_a_headers)
    secret = f"validation-secret-{uuid.uuid4().hex}"
    invalid = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={"name": "x", "api_base": "https://example.test", "api_key": {"value": secret}, "model": "m"},
    )
    assert invalid.status_code == 422
    assert secret not in invalid.text

    provider_name = f"failing-{secret}"
    created = await client.post(
        "/api/v1/llm-providers/",
        headers=tenant_a_headers,
        json={
            "name": provider_name,
            "api_base": "https://provider.example/v1",
            "api_key": secret,
            "model": "model",
        },
    )
    assert created.status_code == 201

    class FailingGateway:
        async def chat_stream(self, *args, **kwargs):
            raise RuntimeError(secret)
            yield

    monkeypatch.setattr("app.api.v1.llm_providers.app_state.llm_gateway", FailingGateway())
    tested = await client.post(
        f"/api/v1/llm-providers/{provider_name}/test", headers=tenant_a_headers
    )
    assert tested.status_code == 502
    assert secret not in tested.text

    async with _async_session_factory() as db:
        audits = list(
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.tenant_id == uuid.UUID(identity["tenant_id"]))
                )
            ).scalars()
        )
    audit_text = str(
        [
            {
                "path": row.path,
                "resource_id": row.resource_id,
                "details": row.details,
            }
            for row in audits
        ]
    )
    assert secret not in audit_text
    assert provider_name not in audit_text


async def test_channel_failures_do_not_write_secret_to_logs(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"https://open.feishu.cn/log-secret-{uuid.uuid4().hex}"

    class FailingClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError(secret)

    monkeypatch.setattr("app.core.channel.feishu._get_client", lambda: FailingClient())
    caplog.set_level(logging.WARNING)
    result = await FeishuChannel(secret).send_with_result(
        ChannelMessage(title="safe", content="safe")
    )
    assert result["error"] == "Feishu delivery failed"
    assert secret not in caplog.text
    assert secret not in str(result)

    from app.main import app

    route = f"/__test__/secret-error-{uuid.uuid4().hex}"

    async def fail():
        raise RuntimeError(secret)

    app.add_api_route(route, fail, methods=["GET"])
    response = await client.get(route)
    assert response.status_code == 500
    assert secret not in response.text
    assert secret not in caplog.text
