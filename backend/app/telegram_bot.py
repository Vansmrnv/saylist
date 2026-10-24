"""Business-facing Telegram bot. Seller conversation: update -> channels -> assistant -> outbox
(ADR 0007). Job buttons go straight to the jobs contract. Thin: no decisions are made here."""

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from app.core.db import get_sessionmaker
from app.modules import assistant, businesses, channels, jobs

log = logging.getLogger("telegram")
router = Router()

SORRY = "Sorry, something went wrong. Please send that again."


async def _converse(bot: Bot, inbound: assistant.InboundMessage) -> None:
    """Replies are queued in the same transaction and delivered by the outbox worker."""
    try:
        async with get_sessionmaker()() as session, session.begin():
            await channels.receive(session, inbound)
    except Exception:
        log.exception("conversation failed (%s)", inbound.external_id)
        await bot.send_message(int(inbound.external_id), SORRY)  # the outbox is unreachable


@router.message(F.text | F.contact | F.voice | F.audio)
async def seller_message(message: Message, bot: Bot) -> None:
    if message.voice or message.audio or (message.text and not message.text.startswith("/start")):
        await bot.send_chat_action(message.chat.id, "typing")
    inbound = await channels.telegram_message(message, bot)
    if inbound is not None:
        await _converse(bot, inbound)


@router.callback_query(F.data.startswith("ch:") | F.data.startswith("prop:"))
async def seller_choice(callback: CallbackQuery, bot: Bot) -> None:
    inbound = channels.telegram_choice(callback)
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)  # one tap per card
    await callback.answer()
    if inbound is not None:
        await _converse(bot, inbound)


async def _business_id(chat_id: int) -> int | None:
    async with get_sessionmaker()() as session:
        business = await businesses.get_by_chat(session, chat_id)
    return business.id if business else None


@router.callback_query(F.data.regexp(r"^(acc|dec):\d+(:\d+)?$"))
async def offer_button(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    business_id = await _business_id(callback.from_user.id)
    if business_id is None:
        await callback.answer("You're not registered as a business.")
        return
    async with get_sessionmaker()() as session, session.begin():
        if parts[0] == "acc":
            toast = await jobs.accept_offer(session, int(parts[1]), business_id, int(parts[2]))
        else:
            toast = await jobs.decline_offer(session, int(parts[1]), business_id)
    await callback.answer(toast)


@router.callback_query(F.data.regexp(r"^job:\d+:[a-z]+(:\d+)?$"))
async def job_button(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    business_id = await _business_id(callback.from_user.id)
    if business_id is None:
        await callback.answer("You're not registered as a business.")
        return
    try:
        action = jobs.BusinessAction(parts[2])
    except ValueError:
        await callback.answer("Unknown button.")
        return
    minutes = int(parts[3]) if len(parts) > 3 else None
    async with get_sessionmaker()() as session, session.begin():
        toast = await jobs.advance(session, int(parts[1]), business_id, action, minutes)
    await callback.answer(toast)
