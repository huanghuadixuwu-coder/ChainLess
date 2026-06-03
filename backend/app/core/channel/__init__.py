"""Channel abstraction for delivering agent results to external platforms (Feishu, etc.)."""

from .base import ChannelBase, ChannelMessage
from .feishu import FeishuChannel

__all__ = ["ChannelBase", "ChannelMessage", "FeishuChannel"]
