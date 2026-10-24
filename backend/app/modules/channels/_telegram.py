"""Telegram update -> InboundMessage. Voice is transcribed here, so the assistant sees text."""

import logging

from aiogram import Bot
from aiogram.types import Audio, CallbackQuery, Message, Voice

from app.core import stt
from app.modules.assistant import InboundKind, InboundMessage
from app.modules.channels._render import CHOICE_PREFIX

log = logging.getLogger("channels.telegram")

TELEGRAM = "telegram"
_LEGACY_CARD = {"ok": "confirm", "edit": "change"}  # cards sent before the assistant existed


async def from_message(message: Message, bot: Bot) -> InboundMessage | None:
    """A seller's message, or None if it is nothing the assistant handles (a sticker, a photo).
    A voice note that cannot be transcribed comes back as VOICE with no text."""

    def inbound(
        kind: InboundKind, text: str | None = None, phone: str | None = None
    ) -> InboundMessage:
        return InboundMessage(
            channel=TELEGRAM,
            external_id=str(message.chat.id),
            message_id=str(message.message_id),
            kind=kind,
            text=text,
            phone=phone,
            received_at=message.date,
        )

    if message.contact is not None:
        return inbound(InboundKind.CONTACT, phone=message.contact.phone_number)
    media = message.voice or message.audio
    if media is not None:
        return inbound(InboundKind.VOICE, text=await _transcribe(media, bot))
    if message.text is None:
        return None
    if message.text.startswith("/start"):
        return inbound(InboundKind.START)
    return inbound(InboundKind.TEXT, text=message.text)


def from_callback(callback: CallbackQuery) -> InboundMessage | None:
    """A tap on an assistant choice (`ch:<value>`, or a pre-assistant `prop:ok|edit:<id>`)."""
    data = callback.data or ""
    if data.startswith(CHOICE_PREFIX):
        value = data.removeprefix(CHOICE_PREFIX)
    elif data.startswith("prop:") and data.count(":") == 2:
        _, action, proposal_id = data.split(":")
        if action not in _LEGACY_CARD:
            return None
        value = f"{_LEGACY_CARD[action]}:{proposal_id}"
    else:
        return None
    return InboundMessage(
        channel=TELEGRAM,
        external_id=str(callback.from_user.id),  # private chat: chat id == user id
        message_id=f"cb:{callback.id}",
        kind=InboundKind.CHOICE,
        choice_value=value,
    )


async def _transcribe(media: Voice | Audio, bot: Bot) -> str | None:
    if not stt.available():
        return None
    try:
        downloaded = await bot.download(media)
        return await stt.transcribe(downloaded.read() if downloaded else b"")
    except Exception:
        log.exception("transcription failed")
        return None
