"""Delivers outbox rows to Telegram with retries. (ADR 0004)"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.messaging import _repository as repo
from app.modules.messaging._models import OutboxKind, OutboxMessage, OutboxStatus

log = logging.getLogger("outbox")

MAX_ATTEMPTS = 6


class PermanentError(Exception):
    """The message can never be delivered (unknown chat, bot blocked, bad markup)."""


class RetryLater(Exception):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"retry after {seconds}s")
        self.seconds = seconds


class Transport(Protocol):
    async def send(self, chat_id: int, text: str, buttons: list[Any] | None) -> int: ...

    async def edit(
        self, chat_id: int, message_id: int, text: str, buttons: list[Any] | None
    ) -> None: ...


def _markup(buttons: list[Any] | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=b["text"], callback_data=b.get("callback_data"), url=b.get("url")
                )
                for b in row
            ]
            for row in buttons
        ]
    )


def _send_markup(buttons: list[Any] | None) -> InlineKeyboardMarkup | ReplyKeyboardMarkup | None:
    """A reply keyboard when any button asks for the contact, else inline buttons."""
    if buttons and any(b.get("request_contact") for row in buttons for b in row):
        return ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text=b["text"], request_contact=bool(b.get("request_contact")))
                    for b in row
                ]
                for row in buttons
            ],
            resize_keyboard=True,
        )
    return _markup(buttons)


class TelegramTransport:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str, buttons: list[Any] | None) -> int:
        try:
            msg = await self.bot.send_message(chat_id, text, reply_markup=_send_markup(buttons))
        except TelegramRetryAfter as e:
            raise RetryLater(e.retry_after) from e
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as e:
            raise PermanentError(str(e)) from e
        return msg.message_id

    async def edit(
        self, chat_id: int, message_id: int, text: str, buttons: list[Any] | None
    ) -> None:
        try:
            # Telegram removes the inline keyboard when reply_markup is omitted.
            await self.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=_markup(buttons)
            )
        except TelegramRetryAfter as e:
            raise RetryLater(e.retry_after) from e
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
            raise PermanentError(str(e)) from e
        except (TelegramForbiddenError, TelegramNotFound) as e:
            raise PermanentError(str(e)) from e


async def _deliver(session: AsyncSession, transport: Transport, row: OutboxMessage) -> None:
    now = datetime.now(UTC)
    try:
        if row.kind == OutboxKind.SEND:
            row.telegram_message_id = await transport.send(row.chat_id, row.text, row.buttons)
        else:
            target = await repo.get_by_key(session, row.edit_of or "")
            if target is None or target.status == OutboxStatus.FAILED:
                raise PermanentError(f"message {row.edit_of} was never delivered")
            if target.status == OutboxStatus.PENDING or target.telegram_message_id is None:
                row.next_attempt_at = now + timedelta(seconds=1)  # wait for the send
                return
            await transport.edit(row.chat_id, target.telegram_message_id, row.text, row.buttons)
    except RetryLater as e:
        row.next_attempt_at = now + timedelta(seconds=e.seconds)
        return
    except PermanentError as e:
        row.status, row.last_error = OutboxStatus.FAILED, str(e)
        log.warning("outbox %s (%s to %s) failed: %s", row.id, row.key, row.chat_id, e)
        return
    except Exception as e:
        row.attempts += 1
        row.last_error = repr(e)
        if row.attempts >= MAX_ATTEMPTS:
            row.status = OutboxStatus.FAILED
            log.warning("outbox %s (%s) gave up: %r", row.id, row.key, e)
        else:
            row.next_attempt_at = now + timedelta(seconds=2**row.attempts)
        return
    row.status, row.sent_at = OutboxStatus.SENT, now


async def deliver_due(
    sessionmaker: async_sessionmaker[AsyncSession], transport: Transport, limit: int = 20
) -> int:
    """Deliver one batch; returns how many rows were looked at. The batch commits here."""
    async with sessionmaker() as session, session.begin():
        rows: Sequence[OutboxMessage] = await repo.lock_due(session, datetime.now(UTC), limit)
        for row in rows:
            await _deliver(session, transport, row)
            await session.flush()
        return len(rows)


async def run_worker(sessionmaker: async_sessionmaker[AsyncSession], bot: Bot | None) -> None:
    """Forever: deliver due rows. Without a bot, rows stay pending (nothing to send with)."""
    if bot is None:
        log.warning("no Telegram bot: outbox rows stay pending")
        return
    transport = TelegramTransport(bot)
    while True:
        try:
            busy = await deliver_due(sessionmaker, transport)
        except Exception:
            log.exception("outbox worker error")
            busy = 0
        await asyncio.sleep(0.2 if busy else 0.5)
