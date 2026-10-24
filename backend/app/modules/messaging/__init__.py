"""Delivers outbound Telegram messages reliably through an outbox. (ADR 0004)"""

from app.modules.messaging import _models  # noqa: F401  (registers the tables)
from app.modules.messaging._schemas import Button, OutboxView
from app.modules.messaging._service import edit, list_recent, send
from app.modules.messaging._worker import (
    PermanentError,
    RetryLater,
    TelegramTransport,
    Transport,
    deliver_due,
    run_worker,
)

__all__ = [
    "Button",
    "OutboxView",
    "PermanentError",
    "RetryLater",
    "TelegramTransport",
    "Transport",
    "deliver_due",
    "edit",
    "list_recent",
    "run_worker",
    "send",
]
