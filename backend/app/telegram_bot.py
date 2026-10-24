"""Business-facing Telegram bot: onboarding by voice or text, profile edits, and the job buttons.
Thin: every decision is made by the businesses and jobs contracts."""

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.core import stt
from app.core.db import get_sessionmaker
from app.modules import businesses, jobs

log = logging.getLogger("telegram")
router = Router()

PHONE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Share phone number", request_contact=True)]],
    resize_keyboard=True,
)


def card_buttons(proposal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Correct", callback_data=f"prop:ok:{proposal_id}"),
                InlineKeyboardButton(text="✏️ Change", callback_data=f"prop:edit:{proposal_id}"),
            ]
        ]
    )


def card_text(profile: businesses.Profile, phone: str | None, header: str) -> str:
    def v(value: str | None) -> str:
        return escape(value or "-")

    return "\n".join(
        [
            header,
            f"👤 Name: {v(profile.name)}",
            f"🛠 Trade: {escape(businesses.trade_label(profile.trade))}",
            f"📍 Area: {v(profile.area)}",
            f"📞 Phone: {v(phone) if phone else 'not shared yet'}",
            f"🕒 Availability: {v(profile.availability_text)}",
            f"💶 Prices: {v(profile.pricing_text)}",
            f"📄 Quoted separately: {v(profile.quoted_separately)}",
        ]
    )


CONFIRM_REPLIES = {
    businesses.ConfirmOutcome.LIVE: "🚀 You're live. Job requests will arrive here.",
    businesses.ConfirmOutcome.UPDATED: "✅ Profile updated.",
    businesses.ConfirmOutcome.NEEDS_BASICS: "Please tell me your business name and area first.",
    businesses.ConfirmOutcome.STALE: "That card is out of date; use the latest one.",
}


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "👋 Hi! I'll bring you jobs from local customers, with the exact address, a booked time "
        "and how to get in, so you don't have to call anyone.\n\n"
        "Send me a <b>voice note</b> (or text) saying:\n"
        "• what you do and your business name\n"
        "• the area you cover\n"
        "• when you're available\n"
        "• what you charge\n\n"
        "Also tap <b>📱 Share phone number</b> below.",
        reply_markup=PHONE_KEYBOARD,
    )


@router.message(Command("profile"))
async def show_profile(message: Message) -> None:
    async with get_sessionmaker()() as session:
        business = await businesses.get_by_chat(session, message.chat.id)
    if business is None or business.trade is None:
        await message.answer("No profile yet. Send me a voice note or text about your business.")
        return
    header = "✅ <b>Your live profile</b>" if business.status == "active" else "📝 <b>Draft</b>"
    await message.answer(card_text(business.profile(), business.phone, header))


@router.message(F.contact)
async def got_contact(message: Message) -> None:
    if message.contact is None:
        return
    phone = message.contact.phone_number
    phone = phone if phone.startswith("+") else "+" + phone
    async with get_sessionmaker()() as session, session.begin():
        outcome = await businesses.set_phone(session, message.chat.id, phone)
    await message.answer(f"📞 Saved your phone: {escape(phone)}")
    if outcome in CONFIRM_REPLIES:
        await message.answer(CONFIRM_REPLIES[outcome])


@router.message(F.voice | F.audio)
async def got_voice(message: Message, bot: Bot) -> None:
    if not stt.available():
        await message.answer("Voice notes aren't set up on this server yet. Please send text.")
        return
    media = message.voice or message.audio
    if media is None:
        return
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        downloaded = await bot.download(media)
        text = await stt.transcribe(downloaded.read() if downloaded else b"")
    except Exception:
        log.exception("transcription failed")
        await message.answer("Sorry, I couldn't hear that. Please try again or send text.")
        return
    await message.answer(f"🎙 I heard: <i>{escape(text)}</i>")
    await describe(message, text)


@router.message(F.text & ~F.text.startswith("/"))
async def got_text(message: Message) -> None:
    await describe(message, message.text or "")


async def describe(message: Message, text: str) -> None:
    """Any voice or text is a description (first time) or an edit (afterwards)."""
    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        async with get_sessionmaker()() as session, session.begin():
            proposal = await businesses.propose(session, message.chat.id, text)
    except Exception:
        log.exception("proposal failed")
        await message.answer("Sorry, something went wrong. Please send that again.")
        return
    header = (
        "✏️ <b>Updated profile (not saved yet)</b>"
        if proposal.business_status == "active"
        else "📝 <b>Your profile (not live yet)</b>"
    )
    card = card_text(proposal.profile, proposal.phone, header)
    if proposal.missing_basics:
        await message.answer(
            f"{card}\n\nAlmost there! Please tell me your {' and '.join(proposal.missing_basics)}."
        )
    else:
        await message.answer(card, reply_markup=card_buttons(proposal.proposal_id))


@router.callback_query(F.data.startswith("prop:"))
async def proposal_button(callback: CallbackQuery, bot: Bot) -> None:
    _, action, raw_id = (callback.data or "").split(":")
    chat_id = callback.from_user.id
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action == "edit":
        await bot.send_message(chat_id, "✏️ Tell me what to change (voice or text).")
        return
    async with get_sessionmaker()() as session, session.begin():
        outcome = await businesses.confirm(session, chat_id, int(raw_id))
    if outcome == businesses.ConfirmOutcome.NEEDS_PHONE:
        await bot.send_message(
            chat_id,
            "One last thing: tap 📱 <b>Share phone number</b>. You go live as soon as it's shared.",
            reply_markup=PHONE_KEYBOARD,
        )
        return
    await bot.send_message(chat_id, CONFIRM_REPLIES[outcome])


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
