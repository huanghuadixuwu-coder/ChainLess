"""Feishu interactive card channel — sends formatted messages via Feishu bot webhook."""

import httpx

from .base import ChannelBase, ChannelMessage

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

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, message: ChannelMessage) -> bool:
        """Send an interactive card message to Feishu."""
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
        client = _get_client()
        resp = await client.post(self.webhook_url, json=body)
            return resp.status_code == 200

    async def validate(self) -> bool:
        """Check that the webhook URL looks like a valid Feishu endpoint."""
        return self.webhook_url.startswith("https://open.feishu.cn/")
