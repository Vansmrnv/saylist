"""The channel-neutral vocabulary between channel adapters and the assistant (ADR 0007)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class InboundKind(StrEnum):
    START = "start"  # the seller opened the conversation (Telegram /start, a web chat opened)
    TEXT = "text"
    VOICE = "voice"  # already transcribed by the channel: `text` holds the transcript
    CONTACT = "contact"  # the seller shared their phone through the channel's own control
    CHOICE = "choice"  # the seller picked one of the `Choice`s of an earlier reply


class InboundMessage(BaseModel):
    """One thing the seller did, normalized by a channel adapter.

    Identity is `(channel, external_id)` for now; one seller across several channels comes with
    the business entity redesign.
    """

    channel: str  # "telegram", "cli", ...
    external_id: str  # the sender's address in that channel (Telegram chat id, phone number)
    message_id: str  # unique per sender in that channel; a redelivery repeats it
    kind: InboundKind
    text: str | None = None
    choice_value: str | None = None
    phone: str | None = None
    received_at: datetime | None = None


class ReplyKind(StrEnum):
    TEXT = "text"
    CHOICES = "choices"  # text plus options to pick from
    CARD = "card"  # a titled record (e.g. the proposed profile), optionally with options
    ASK_CONTACT = "ask_contact"  # text asking for the phone; channels add their own control


class Choice(BaseModel):
    value: str  # comes back as `InboundMessage.choice_value`; short (Telegram allows 64 bytes)
    label: str


class CardField(BaseModel):
    label: str
    value: str


class Reply(BaseModel):
    """What the assistant says. Plain text only: each channel renders and escapes it."""

    kind: ReplyKind = ReplyKind.TEXT
    text: str = ""  # the message; for a card, the line under the fields
    title: str | None = None
    fields: list[CardField] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
