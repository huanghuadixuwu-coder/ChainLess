"""Channel SPI base class — all delivery channels must implement this interface."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ChannelMessage(BaseModel):
    """A message to be delivered through a channel."""

    title: str
    content: str


class ChannelBase(ABC):
    """Abstract base for all notification channels."""

    @abstractmethod
    async def send(self, message: ChannelMessage) -> bool:
        """Deliver the message through this channel. Returns True on success."""
        ...

    @abstractmethod
    async def validate(self) -> bool:
        """Check whether this channel is correctly configured. Returns True if valid."""
        ...
