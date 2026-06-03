"""Channel configuration API — manage delivery channel settings.

Endpoints:
    POST /channels/feishu        — configure a Feishu webhook
    POST /channels/feishu/test   — send a test message via Feishu
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.channel.feishu import FeishuChannel
from app.core.channel.base import ChannelMessage

router = APIRouter(prefix="/channels", tags=["channels"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FeishuConfigRequest(BaseModel):
    webhook_url: str


class TestMessageRequest(BaseModel):
    webhook_url: str
    title: str = "Test Message"
    content: str = "This is a test message from Chainless."


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/feishu")
async def configure_feishu(
    body: FeishuConfigRequest,
    _: dict = Depends(get_current_user),
):
    """Validate and store a Feishu webhook configuration.

    This endpoint validates the webhook URL and, on success, returns a
    config snippet that the caller can persist.
    """
    channel = FeishuChannel(body.webhook_url)
    is_valid = await channel.validate()
    return {
        "status": "ok" if is_valid else "invalid",
        "webhook_url": body.webhook_url,
        "valid": is_valid,
        "message": "Feishu webhook validated" if is_valid
                   else "Webhook URL should start with https://open.feishu.cn/",
    }


@router.post("/feishu/test")
async def test_feishu(
    body: TestMessageRequest,
    _: dict = Depends(get_current_user),
):
    """Send a test message through a Feishu webhook."""
    channel = FeishuChannel(body.webhook_url)
    msg = ChannelMessage(title=body.title, content=body.content)
    success = await channel.send(msg)
    return {
        "status": "ok" if success else "failed",
        "message": "Test message sent successfully" if success
                   else "Failed to send test message (check webhook URL)",
    }
