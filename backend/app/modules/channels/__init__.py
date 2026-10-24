"""Connects the channels sellers write from to the seller assistant."""

from app.modules.channels._render import plain as render_plain
from app.modules.channels._render import telegram as render_telegram
from app.modules.channels._service import outbox_key, receive
from app.modules.channels._telegram import TELEGRAM
from app.modules.channels._telegram import from_callback as telegram_choice
from app.modules.channels._telegram import from_message as telegram_message

__all__ = [
    "TELEGRAM",
    "outbox_key",
    "receive",
    "render_plain",
    "render_telegram",
    "telegram_choice",
    "telegram_message",
]
