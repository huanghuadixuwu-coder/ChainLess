"""Feishu interactive card channel."""

import base64
import hashlib
import hmac
import logging
import time

import httpx

from .base import ChannelBase, ChannelMessage

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


class FeishuChannel(ChannelBase):
    """Deliver agent results as Feishu interactive cards.

    Expects a Feishu webhook URL in the form:
        https://open.feishu.cn/open-apis/bot/v2/hook/<token>
    """

    def __init__(self, webhook_url: str, signing_secret: str | None = None):
        self.webhook_url = webhook_url
        self.signing_secret = signing_secret

    async def send(self, message: ChannelMessage) -> bool:
        """Send an interactive card message to Feishu with retry."""
        result = await self.send_with_result(message)
        return result["ok"]

    async def send_with_result(self, message: ChannelMessage) -> dict:
        """Send a message and return structured delivery evidence."""
        body = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": message.title},
                },
                "elements": [
                    {"tag": "markdown", "content": message.content},
                ],
            },
        }
        if self.signing_secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{self.signing_secret}".encode("utf-8")
            body["timestamp"] = timestamp
            body["sign"] = base64.b64encode(
                hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
            ).decode("ascii")
        client = _get_client()
        for attempt in range(1, 4):
            try:
                resp = await client.post(self.webhook_url, json=body)
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "attempts": attempt,
                        "status_code": resp.status_code,
                        "error": None,
                    }
            except Exception:
                pass
            logger.warning("Feishu delivery attempt %d failed", attempt)

        return {
            "ok": False,
            "attempts": 3,
            "status_code": None,
            "error": "Feishu delivery failed",
        }

    async def validate(self) -> bool:
        """Check that the webhook URL looks like a valid Feishu endpoint."""
        return self.webhook_url.startswith("https://open.feishu.cn/")
