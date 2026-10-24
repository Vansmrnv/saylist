"""Telegram bot for businesses: onboarding by voice/text, profile edits, job offers."""
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           Message, ReplyKeyboardMarkup)

import core
import db
import llm
import stt

log = logging.getLogger("business_bot")
router = Router()

# chat_id -> {"profile": dict, "transcript": str}: the card shown but not confirmed yet
pending: dict[int, dict] = {}
# chat_id -> phone shared before the business row exists
pending_phone: dict[int, str] = {}
# chats that pressed [Correct] without a phone; activate as soon as they share it
activate_after_phone: set[int] = set()

PHONE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Share phone number", request_contact=True)]],
    resize_keyboard=True,
)
CARD_BUTTONS = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Correct", callback_data="profile:ok"),
    InlineKeyboardButton(text="✏️ Change", callback_data="profile:change"),
]])


def _profile_of(business: dict) -> dict:
    return {k: business.get(k) for k in db.PROFILE_FIELDS}


def _missing_basics(profile: dict) -> list[str]:
    return [label for key, label in (("name", "your business name"), ("area", "the area you cover"))
            if not profile.get(key)]


def card_text(profile: dict, phone: str | None, status: str) -> str:
    def v(key):
        return escape(profile.get(key) or "-")
    header = {
        "active": "✅ <b>Your live profile</b>",
        "edit": "✏️ <b>Updated profile (not saved yet)</b>",
    }.get(status, "📝 <b>Your profile (not live yet)</b>")
    return "\n".join([
        header,
        f"👤 Name: {v('name')}",
        f"🛠 Trade: {escape(core.trade_label(profile.get('trade')))}",
        f"📍 Area: {v('area')}",
        f"📞 Phone: {escape(phone or 'not shared yet')}",
        f"🕒 Availability: {v('availability_text')}",
        f"💶 Prices: {v('pricing_text')}",
        f"📄 Quoted separately: {v('quoted_separately')}",
    ])


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Hi! I'll put your business in front of local clients.\n\n"
        "Send me a <b>voice note</b> (or text) saying:\n"
        "• what you do and your business name\n"
        "• the area you cover\n"
        "• when you're available\n"
        "• what you charge\n\n"
        "Also tap <b>📱 Share phone number</b> below so clients can call you.",
        reply_markup=PHONE_KEYBOARD,
    )


@router.message(Command("profile"))
async def show_profile(message: Message):
    business = db.get_business_by_chat(message.chat.id)
    if not business:
        await message.answer("You don't have a profile yet. Send me a voice note or text about your business.")
        return
    await message.answer(card_text(_profile_of(business), business["phone"], business["status"]))


@router.message(F.contact)
async def got_contact(message: Message):
    chat_id = message.chat.id
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    business = db.get_business_by_chat(chat_id)
    if business:
        db.update("businesses", business["id"], {"phone": phone, "updated_at": db.utcnow()})
    else:
        pending_phone[chat_id] = phone
    await message.answer(f"📞 Saved your phone: {escape(phone)}")
    if chat_id in activate_after_phone:
        await _activate(message.bot, chat_id)


@router.message(F.voice | F.audio)
async def got_voice(message: Message, bot: Bot):
    if not stt.available():
        await message.answer("Voice notes aren't set up on this server yet. Please send it as text.")
        return
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        media = message.voice or message.audio
        data = (await bot.download(media)).read()
        text = await stt.transcribe(data)
    except Exception:
        log.exception("transcription failed")
        await message.answer("Sorry, I couldn't hear that. Please try again or send text.")
        return
    await message.answer(f"🎙 I heard: <i>{escape(text)}</i>")
    await handle_description(message, text)


@router.message(F.text & ~F.text.startswith("/"))
async def got_text(message: Message):
    await handle_description(message, message.text)


async def handle_description(message: Message, text: str):
    """Any voice/text: new profile if none exists, otherwise an edit."""
    chat_id = message.chat.id
    await message.bot.send_chat_action(chat_id, "typing")
    business = db.get_business_by_chat(chat_id)
    draft = pending.get(chat_id)
    current = draft["profile"] if draft else (_profile_of(business) if business else None)
    try:
        if current:
            profile = (await llm.update_business_profile(current, text)).model_dump()
        else:
            profile = (await llm.extract_business_profile(text)).model_dump()
    except Exception:
        log.exception("profile extraction failed")
        await message.answer("Sorry, something went wrong. Please send that again.")
        return
    transcript = f"{draft['transcript']}\n---\n{text}" if draft else text
    pending[chat_id] = {"profile": profile, "transcript": transcript}

    # New businesses are saved as a draft right away (an active one keeps its live profile until confirmed).
    if not business or business["status"] == "draft":
        db.save_business(chat_id, profile, "draft", phone=pending_phone.pop(chat_id, None), transcript=text)
        business = db.get_business_by_chat(chat_id)

    status = "draft" if business["status"] == "draft" else "edit"
    card = card_text(profile, business["phone"], status)
    missing = _missing_basics(profile)
    if missing:
        await message.answer(f"{card}\n\nAlmost there! Please tell me {' and '.join(missing)}.")
    else:
        await message.answer(card, reply_markup=CARD_BUTTONS)


async def _activate(bot: Bot, chat_id: int) -> None:
    business = db.get_business_by_chat(chat_id)
    draft = pending.pop(chat_id, None)
    profile = draft["profile"] if draft else _profile_of(business)
    transcript = draft["transcript"] if draft and business["status"] == "active" else None
    was_active = business["status"] == "active"
    db.save_business(chat_id, profile, "active", transcript=transcript)
    activate_after_phone.discard(chat_id)
    log.info("business %s is live", business["id"])
    await bot.send_message(chat_id, "✅ Profile updated." if was_active else "🚀 You're live. Job requests will arrive here.")


@router.callback_query(F.data == "profile:ok")
async def confirm_profile(callback: CallbackQuery, bot: Bot):
    chat_id = callback.message.chat.id
    business = db.get_business_by_chat(chat_id)
    draft = pending.get(chat_id)
    if not business or (not draft and business["status"] == "active"):
        await callback.answer("Nothing to save.")
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    if _missing_basics(draft["profile"] if draft else _profile_of(business)):
        await callback.answer()
        await bot.send_message(chat_id, "Please tell me your business name and area first.")
        return
    await callback.answer()
    if not business["phone"]:
        pending.setdefault(chat_id, {"profile": _profile_of(business), "transcript": ""})
        activate_after_phone.add(chat_id)
        await bot.send_message(chat_id, "One last thing: tap 📱 <b>Share phone number</b> so clients can reach you.",
                               reply_markup=PHONE_KEYBOARD)
        return
    await _activate(bot, chat_id)


@router.callback_query(F.data == "profile:change")
async def change_profile(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer("✏️ Tell me what to change (voice or text).")


@router.callback_query(F.data.startswith("accept:"))
async def accept_offer(callback: CallbackQuery):
    result = await core.accept(int(callback.data.split(":")[1]))
    await callback.answer(result)


@router.callback_query(F.data.startswith("decline:"))
async def decline_offer(callback: CallbackQuery):
    result = await core.decline(int(callback.data.split(":")[1]))
    await callback.answer(result)
